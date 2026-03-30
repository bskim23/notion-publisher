"""
노션 → 채널 발행 오케스트레이터

주요 변경점
- 폴링 중심 구조를 유지하되, 페이지 1건 직접 실행(--page-id) 지원
- 테스트요청 / 실발행요청 상태 분리
- 스티비 + 네이버 선행 실행, 페이스북은 네이버 URL 의존
- 채널별 결과를 노션 속성에 기록
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import schedule

from config import (
    NOTION_DATABASE_ID,
    POLLING_INTERVAL,
    STATUS_TEST_REQUEST,
    STATUS_PROD_REQUEST,
    STATUS_PROCESSING,
    STATUS_TEST_DONE,
    STATUS_DONE,
    STATUS_PARTIAL,
    STATUS_FAILED,
    MODE_TEST,
    MODE_PROD,
    CHANNELS_PROPERTY,
    NAVER_URL_PROPERTY,
    IMWEB_URL_PROPERTY,
    FACEBOOK_URL_PROPERTY,
    STIBEE_CAMPAIGN_ID_PROPERTY,
    RESERVED_AT_PROPERTY,
    ERROR_LOG_PROPERTY,
    STIBEE_SENDER_NAME,
    STIBEE_TEST_ADDRESS_BOOK_ID,
    STIBEE_PROD_ADDRESS_BOOK_ID,
    STIBEE_PROD_SEND_HOUR,
    STIBEE_PROD_SEND_MINUTE,
    FACEBOOK_PAGE_ID,
    FACEBOOK_ACCESS_TOKEN,
    FACEBOOK_TEST_PAGE_ID,
    FACEBOOK_TEST_ACCESS_TOKEN,
    validate_config,
)
from notion_fetcher import (
    get_pages_by_status,
    get_page,
    get_page_title,
    get_page_mode,
    get_page_channels,
    get_fb_quote,
    get_page_tags,
    get_page_blocks,
    blocks_to_html,
    blocks_to_plain_text,
    get_image_urls,
    update_page_properties,
    update_page_status,
)
from formatters import format_for_naver_blog, format_for_imweb, format_for_stibee
from publishers.naver_blog import post_to_naver_blog
from publishers.imweb_publisher import post_to_imweb
from publishers.facebook_publisher import post_to_facebook
from publishers.stibee_publisher import post_to_stibee

KST = timezone(timedelta(hours=9))
CHANNEL_NAME_MAP = {
    "네이버블로그": "naver",
    "아임웹": "imweb",
    "페이스북": "facebook",
    "스티비": "stibee",
}

DEFAULT_CHANNELS = {"naver": True, "imweb": True, "facebook": True, "stibee": True}


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")




# 한국 공휴일 (매년 초 업데이트 필요)
KR_HOLIDAYS = {
    # 2026년
    "2026-01-01", "2026-01-27", "2026-01-28", "2026-01-29",  # 신정, 설날
    "2026-03-01",  # 삼일절
    "2026-03-02",  # 설날 대체공휴일 (일→월)
    "2026-05-05", "2026-05-24",  # 어린이날, 부처님오신날
    "2026-06-06",  # 현충일
    "2026-08-15",  # 광복절
    "2026-08-17",  # 광복절 대체공휴일
    "2026-09-24", "2026-09-25", "2026-09-26",  # 추석
    "2026-10-03", "2026-10-09",  # 개천절, 한글날
    "2026-12-25",  # 성탄절
    # 2027년
    "2027-01-01",  # 신정
    "2027-02-15", "2027-02-16", "2027-02-17",  # 설날
    "2027-03-01",  # 삼일절
    "2027-05-05", "2027-05-13",  # 어린이날, 부처님오신날
    "2027-06-06",  # 현충일
    "2027-06-07",  # 현충일 대체공휴일 (일→월)
    "2027-08-15",  # 광복절
    "2027-08-16",  # 광복절 대체공휴일 (일→월)
    "2027-10-03", "2027-10-04", "2027-10-05", "2027-10-06",  # 추석+개천절
    "2027-10-09",  # 한글날
    "2027-10-11",  # 한글날 대체공휴일 (토→월)
    "2027-12-25",  # 성탄절
}


def _is_holiday(d: datetime) -> bool:
    """토/일 또는 공휴일이면 True"""
    if d.weekday() >= 5:
        return True
    return d.strftime("%Y-%m-%d") in KR_HOLIDAYS


def _next_send_time(now: datetime | None = None, skip_holidays: bool = False) -> datetime:
    """익일 오전 8:30 발송 시각 계산. skip_holidays=True면 토/일/공휴일 건너뜀."""
    now = now or datetime.now(KST)
    target = (now + timedelta(days=1)).replace(
        hour=STIBEE_PROD_SEND_HOUR, minute=STIBEE_PROD_SEND_MINUTE, second=0, microsecond=0,
    )
    if skip_holidays:
        while _is_holiday(target):
            target += timedelta(days=1)
    return target



def _infer_mode(page: dict, mode_override: str | None = None) -> str:
    if mode_override:
        return mode_override
    mode = get_page_mode(page)
    if mode in (MODE_TEST, MODE_PROD):
        return mode
    status = page.get("properties", {}).get("발행 상태", {}).get("select", {})
    status_name = status.get("name") if status else None
    if status_name == STATUS_TEST_REQUEST:
        return MODE_TEST
    if status_name == STATUS_PROD_REQUEST:
        return MODE_PROD
    return MODE_PROD



def _resolve_channels(page: dict) -> dict[str, bool]:
    selected = get_page_channels(page)
    if not selected:
        return DEFAULT_CHANNELS.copy()

    resolved = {k: False for k in DEFAULT_CHANNELS}
    for item in selected:
        key = CHANNEL_NAME_MAP.get(item)
        if key:
            resolved[key] = True
    return resolved



def _build_stibee_payload(title: str, html_content: str, image_urls: list[str], mode: str) -> dict:
    payload = format_for_stibee(title, html_content, image_urls, sender_name=STIBEE_SENDER_NAME)
    if mode == MODE_TEST:
        payload["address_book_id"] = STIBEE_TEST_ADDRESS_BOOK_ID
        payload["reserved_time"] = _next_send_time(skip_holidays=False)
    else:
        payload["address_book_id"] = STIBEE_PROD_ADDRESS_BOOK_ID
        payload["reserved_time"] = _next_send_time(skip_holidays=True)
    return payload



def _normalize_result(result, *, url_key: str = "url") -> dict:
    if isinstance(result, dict):
        normalized = {"success": bool(result.get("success"))}
        normalized.update(result)
        normalized.setdefault(url_key, result.get(url_key))
        normalized.setdefault("error", None)
        return normalized
    if isinstance(result, bool):
        return {"success": result, url_key: None, "error": None if result else "채널 발행 실패"}
    return {"success": False, url_key: None, "error": "알 수 없는 반환값"}



def _build_facebook_target(mode: str) -> tuple[str | None, str | None]:
    if mode == MODE_TEST:
        return FACEBOOK_TEST_PAGE_ID or FACEBOOK_PAGE_ID, FACEBOOK_TEST_ACCESS_TOKEN or FACEBOOK_ACCESS_TOKEN
    return FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN



def _update_notion_results(page_id: str, mode: str, results: dict):
    updates = {}
    errors = []

    naver = results.get("naver") or {}
    if naver.get("url"):
        updates[NAVER_URL_PROPERTY] = naver["url"]
    if naver.get("error"):
        errors.append(f"네이버: {naver['error']}")

    imweb = results.get("imweb") or {}
    if imweb.get("url"):
        updates[IMWEB_URL_PROPERTY] = imweb["url"]
    if imweb.get("error"):
        errors.append(f"아임웹: {imweb['error']}")

    stibee = results.get("stibee") or {}
    if stibee.get("campaign_id"):
        updates[STIBEE_CAMPAIGN_ID_PROPERTY] = stibee["campaign_id"]
    if stibee.get("reserved_time"):
        updates[RESERVED_AT_PROPERTY] = stibee["reserved_time"]
    if stibee.get("error"):
        errors.append(f"스티비: {stibee['error']}")

    facebook = results.get("facebook") or {}
    if facebook.get("url"):
        updates[FACEBOOK_URL_PROPERTY] = facebook["url"]
    if facebook.get("error"):
        errors.append(f"페이스북: {facebook['error']}")

    successes = [r.get("success") for r in results.values() if r is not None]
    if successes and all(successes):
        final_status = STATUS_TEST_DONE if mode == MODE_TEST else STATUS_DONE
    elif any(successes):
        final_status = STATUS_PARTIAL
    else:
        final_status = STATUS_FAILED

    updates["발행 상태"] = final_status
    updates[ERROR_LOG_PROPERTY] = "\n".join(errors) if errors else ""
    update_page_properties(page_id, updates)
    return final_status



def process_page(page: dict, mode_override: str | None = None) -> dict:
    page_id = page["id"]
    title = get_page_title(page)
    fb_quote = get_fb_quote(page)
    notion_tags = get_page_tags(page)
    mode = _infer_mode(page, mode_override)
    channels = _resolve_channels(page)

    _log(f"📄 처리 시작: «{title}» | 모드: {mode}")
    update_page_status(page_id, STATUS_PROCESSING)

    blocks = get_page_blocks(page_id)
    html_content = blocks_to_html(blocks)
    plain_content = blocks_to_plain_text(blocks)
    image_urls = get_image_urls(blocks)
    _log(f"   콘텐츠 파싱 완료 | 이미지 {len(image_urls)}장")

    naver_payload = format_for_naver_blog(title, html_content, image_urls, tags=notion_tags)
    imweb_payload = format_for_imweb(title, html_content, image_urls)
    stibee_payload = _build_stibee_payload(title, html_content, image_urls, mode)

    results = {"naver": None, "stibee": None, "facebook": None, "imweb": None}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {}
        if channels["naver"]:
            _log("  📝 네이버 블로그 실행")
            future_map["naver"] = executor.submit(post_to_naver_blog, naver_payload)
        if channels["stibee"]:
            _log("  📧 스티비 실행")
            future_map["stibee"] = executor.submit(post_to_stibee, stibee_payload)

        for name, future in future_map.items():
            results[name] = _normalize_result(future.result())

    naver_url = (results.get("naver") or {}).get("url")

    if channels["facebook"]:
        fb_page_id, fb_token = _build_facebook_target(mode)
        fb_result = _normalize_result(
            post_to_facebook(title=title, naver_blog_url=naver_url or "", fb_quote=fb_quote, page_id=fb_page_id, access_token=fb_token),
            url_key="post_id",
        )
        # post_id (예: "179944182094039_1234567890") → 페이스북 URL 변환
        post_id = fb_result.get("post_id")
        if post_id:
            fb_result["url"] = f"https://www.facebook.com/{post_id}"
        results["facebook"] = fb_result
    if channels["imweb"]:
        _log("  🌐 아임웹 실행")
        results["imweb"] = _normalize_result(post_to_imweb(imweb_payload))

    final_status = _update_notion_results(page_id, mode, results)

    icon = lambda ok: "✅" if ok else "❌"
    _log(f"   최종 상태: {final_status}")
    for channel in ("naver", "stibee", "facebook", "imweb"):
        result = results.get(channel)
        if result is None:
            continue
        _log(f"   {channel:<8} {icon(result.get('success', False))}")

    return {"page_id": page_id, "title": title, "mode": mode, "status": final_status, "results": results}



def check_and_publish():
    _log("🔍 발행 대상 확인 중...")
    targets = []
    try:
        targets.extend(get_pages_by_status(NOTION_DATABASE_ID, STATUS_TEST_REQUEST))
        targets.extend(get_pages_by_status(NOTION_DATABASE_ID, STATUS_PROD_REQUEST))
    except Exception as e:
        _log(f"❌ 노션 API 오류: {e}")
        return

    if not targets:
        _log("   대기 중인 글 없음")
        return

    _log(f"   📋 {len(targets)}개 발견")
    for page in targets:
        try:
            process_page(page)
        except Exception as e:
            page_id = page.get("id")
            _log(f"❌ 페이지 처리 오류: {e}")
            if page_id:
                update_page_properties(page_id, {"발행 상태": STATUS_FAILED, ERROR_LOG_PROPERTY: str(e)})



def run_once(page_id: str | None = None, mode: str | None = None):
    _log("🚀 단회 실행 모드")
    if page_id:
        page = get_page(page_id)
        process_page(page, mode_override=mode)
    else:
        check_and_publish()
    _log("완료. 종료합니다.")



def _get_poll_interval() -> int | None:
    """현재 KST 시각에 따라 폴링 간격(초) 반환. None이면 중지 시간대."""
    hour = datetime.now(KST).hour
    if 10 <= hour < 19:
        return 60        # 오전 10시 ~ 오후 7시: 1분
    elif 19 <= hour < 22:
        return 600       # 오후 7시 ~ 오후 10시: 10분
    else:
        return None       # 오후 10시 ~ 오전 10시: 중지


def run_polling():
    _log("🚀 발행 시스템 시작")
    _log(f"   10:00~19:00 → 1분 | 19:00~22:00 → 10분 | 22:00~10:00 → 중지")
    _log(f"   트리거 상태: {STATUS_TEST_REQUEST}, {STATUS_PROD_REQUEST}")
    _log("   종료: Ctrl+C\n")

    while True:
        interval = _get_poll_interval()
        if interval is None:
            now = datetime.now(KST)
            # 다음 오전 10시까지 대기
            wake = now.replace(hour=10, minute=0, second=0, microsecond=0)
            if now.hour >= 22:
                wake += timedelta(days=1)
            sleep_sec = (wake - now).total_seconds()
            _log(f"😴 야간 중지 (다음 기동: {wake.strftime('%m/%d %H:%M')} KST)")
            time.sleep(max(sleep_sec, 60))
            continue

        check_and_publish()
        time.sleep(interval)



def run_test():
    _log("연결 테스트는 추후 갱신 필요")



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--page-id", help="노션 페이지 ID 1건만 실행")
    parser.add_argument("--mode", choices=["test", "prod"], help="페이지 실행 모드 강제 지정")
    args = parser.parse_args()

    if not validate_config():
        return

    mode_override = None
    if args.mode == "test":
        mode_override = MODE_TEST
    elif args.mode == "prod":
        mode_override = MODE_PROD

    if args.test:
        run_test()
    elif args.once or args.page_id:
        run_once(page_id=args.page_id, mode=mode_override)
    else:
        run_polling()


if __name__ == "__main__":
    main()
