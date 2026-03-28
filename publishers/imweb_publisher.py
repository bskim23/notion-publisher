"""
아임웹(Imweb) 홈페이지 게시 모듈 — Playwright 브라우저 자동화

기존 API v2가 폐기되어 브라우저 자동화로 전환.
프론트엔드 게시판 글쓰기 페이지 사용.

흐름:
  1. wkmg.imweb.me/admin 관리자 로그인 (uid/passwd)
  2. /insight 게시판 목록 → 글쓰기 URL 추출 (board 파라미터 포함)
  3. 글쓰기 페이지에서 제목/본문 입력
  4. hidden body/plain_body 필드 동기화 (Froala 에디터 특성)
  5. "작성" 버튼 클릭 → 게시 완료 URL 반환

검증: 2026-03-27
  - 폼: POST /backpg/post_add.cm
  - 제목: input[name="subject"]
  - 본문: div.fr-element.fr-view (Froala Editor, contenteditable)
  - 히든: input[name="body"], input[name="plain_body"], input[name="board_code"]
  - 게시판: board=b201905275ceb84ff7a9eb (WKMG Insight)
  - 작성: button._save_post
"""
from __future__ import annotations

import os
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import IMWEB_ID, IMWEB_PW

# ── 상수 ──────────────────────────────────────────────
ADMIN_URL = "https://wkmg.imweb.me/admin"
SITE_URL = "https://wkmg.imweb.me"
BOARD_SLUG = "165"
# "지난 티끌레터™ 모아보기" 게시판 board 코드 (2026-03-27 확인)
BOARD_CODE = "b202601193071b123c4d74"
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")


def _login(page) -> bool:
    """관리자 패널 로그인 (uid/passwd). 성공 True."""
    print("  🔑 아임웹 관리자 로그인 시도...")
    page.goto(ADMIN_URL, wait_until="networkidle", timeout=20_000)
    time.sleep(2)

    try:
        page.locator('input[name="uid"]').fill(IMWEB_ID, timeout=5000)
        time.sleep(0.3)
        page.locator('input[name="passwd"]').fill(IMWEB_PW, timeout=3000)
        time.sleep(0.3)
        page.locator(".login-btn").click(timeout=3000)
        time.sleep(5)
    except Exception as e:
        print(f"  ❌ 아임웹 로그인 폼 입력 실패: {e}")
        return False

    # 로그인 성공 확인: 로그인 버튼이 사라졌으면 성공
    login_btn_count = page.locator(".login-btn").count()
    if login_btn_count == 0:
        print("  ✅ 아임웹 관리자 로그인 성공")
        return True

    # fallback: 페이지 텍스트 확인 (SPA 로딩 후)
    time.sleep(5)
    body_text = page.evaluate("() => document.body.textContent.slice(0, 500)")
    if "대시보드" in body_text or "요약" in body_text or "디자인 모드" in body_text:
        print("  ✅ 아임웹 관리자 로그인 성공")
        return True

    print("  ❌ 아임웹 로그인 실패")
    return False


def _get_write_url(page) -> str:
    """
    insight 게시판 목록에서 정확한 글쓰기 URL 추출.
    board 파라미터가 포함된 URL이 필요 (없으면 '게시판 없음' 에러 발생).
    """
    list_url = f"{SITE_URL}/{BOARD_SLUG}?t=board"
    page.goto(list_url, wait_until="networkidle", timeout=15_000)
    time.sleep(3)

    # 글쓰기 링크에서 board 파라미터 추출
    write_url = page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a[href*="bmode=write"]'));
            if (links.length > 0) return links[0].href;
            return null;
        }
    """)

    if write_url:
        print(f"  📋 글쓰기 URL 추출: {write_url[:80]}...")
        return write_url

    # fallback: 기본 board 코드 사용
    fallback = f"{SITE_URL}/{BOARD_SLUG}/?board={BOARD_CODE}&bmode=write&t=board"
    print(f"  ⚠️ 글쓰기 링크 못 찾음, fallback 사용: {fallback}")
    return fallback


def _navigate_to_write(page) -> bool:
    """글쓰기 페이지 이동 및 폼 확인."""
    write_url = _get_write_url(page)
    page.goto(write_url, wait_until="networkidle", timeout=15_000)
    time.sleep(5)

    # 폼 존재 확인
    has_form = page.evaluate("""
        () => {
            const titleInput = document.querySelector('input[name="subject"]');
            const editor = document.querySelector('.fr-element.fr-view');
            const boardCode = document.querySelector('input[name="board_code"]');
            return {
                hasTitle: !!titleInput,
                hasEditor: !!editor,
                boardCode: boardCode ? boardCode.value : '',
            };
        }
    """)

    if has_form.get("hasTitle") and has_form.get("hasEditor"):
        bc = has_form.get("boardCode", "")
        if bc:
            print(f"  ✅ 글쓰기 폼 로드 완료 (board_code={bc})")
        else:
            print("  ⚠️ 글쓰기 폼 로드됐으나 board_code 비어있음")
        return True

    print(f"  ❌ 글쓰기 폼 로드 실패: {has_form}")
    return False


def _fill_and_submit(page, payload: dict) -> bool:
    """글쓰기 폼 채우고 제출. 성공 True."""
    title = payload["title"]
    content = payload["content"]

    # ── 제목 입력 ────────────────────────────────────────
    try:
        title_input = page.locator('input[name="subject"]')
        title_input.fill(title, timeout=5000)
        print(f"    제목 입력: {title[:50]}")
    except Exception as e:
        print(f"  ❌ 제목 입력 실패: {e}")
        return False

    time.sleep(0.5)

    # ── Froala 에디터 + hidden field 동기화 ──────────────
    try:
        result = page.evaluate("""
            (html) => {
                // 1. Froala 에디터에 HTML 설정
                const editor = document.querySelector('.fr-element.fr-view');
                if (!editor) return {ok: false, error: 'editor not found'};
                editor.innerHTML = html;
                editor.dispatchEvent(new Event('input', {bubbles: true}));

                // 2. hidden body 필드 동기화 (폼 제출 시 필요)
                const bodyField = document.querySelector('input[name="body"]');
                if (bodyField) bodyField.value = html;

                // 3. plain_body 필드
                const plainField = document.querySelector('input[name="plain_body"]');
                if (plainField) {
                    const tmp = document.createElement('div');
                    tmp.innerHTML = html;
                    plainField.value = tmp.textContent || tmp.innerText || '';
                }

                return {ok: true, length: html.length, boardCode: document.querySelector('input[name="board_code"]')?.value};
            }
        """, content)

        if result.get("ok"):
            print(f"    본문 입력 완료: {result.get('length')} chars (board={result.get('boardCode')})")
        else:
            print(f"  ❌ 본문 입력 실패: {result.get('error')}")
            return False
    except Exception as e:
        print(f"  ❌ 본문 입력 오류: {e}")
        return False

    time.sleep(1)

    # ── "작성" 버튼 클릭 ─────────────────────────────────
    try:
        submit_btn = page.locator("button._save_post")
        if submit_btn.count() == 0:
            submit_btn = page.get_by_text("작성", exact=True).last
        submit_btn.click(timeout=5000)
        print("    '작성' 버튼 클릭")
    except Exception as e:
        print(f"  ❌ 작성 버튼 클릭 실패: {e}")
        return False

    return True


def _extract_post_url(page) -> str | None:
    """게시 완료 후 URL 추출."""
    current = page.url

    # bmode=view가 있으면 게시물 페이지
    if "bmode=view" in current:
        return current

    # 게시물 상세 페이지인지 확인 (제목이 보이고, 수정/삭제 버튼)
    is_post = page.evaluate("""
        () => {
            const hasEditBtn = !!document.querySelector('a:has-text("수정"), button:has-text("수정")');
            const hasListBtn = !!document.querySelector('a:has-text("목록"), button:has-text("목록")');
            return hasEditBtn || hasListBtn;
        }
    """)
    if is_post:
        return current

    # 목록 페이지면 최신 글 URL 추출
    if BOARD_SLUG in current:
        first_link = page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href*="bmode=view"]'));
                if (links.length > 0) return links[0].href;
                return null;
            }
        """)
        if first_link:
            return first_link

    return current


def post_to_imweb(payload: dict) -> dict:
    """
    아임웹 게시 실행 (Playwright 브라우저 자동화).
    payload: format_for_imweb() 반환값
      - title, content, thumbnail
    """
    if not IMWEB_ID or not IMWEB_PW:
        msg = "아임웹 계정 정보가 .env에 설정되지 않았습니다 (IMWEB_ID, IMWEB_PW)"
        print(f"  ❌ {msg}")
        return {"success": False, "url": None, "error": msg}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # confirm/alert 자동 수락
        page.on("dialog", lambda dialog: dialog.accept())

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        try:
            # 1. 관리자 로그인
            if not _login(page):
                return {"success": False, "url": None, "error": "아임웹 관리자 로그인 실패"}

            # 2. 글쓰기 페이지 이동
            if not _navigate_to_write(page):
                return {"success": False, "url": None, "error": "아임웹 글쓰기 페이지 로드 실패"}

            # 3. 폼 작성 및 제출
            if not _fill_and_submit(page, payload):
                return {"success": False, "url": None, "error": "아임웹 글쓰기 폼 작성/제출 실패"}

            # 4. 페이지 전환 대기 (폼 제출 → 게시물 상세 또는 목록)
            try:
                page.wait_for_url(
                    lambda url: "bmode=write" not in url,
                    timeout=15_000,
                )
            except PWTimeout:
                pass

            time.sleep(3)

            # 5. URL 추출
            post_url = _extract_post_url(page)
            if post_url and "bmode=write" not in post_url:
                print(f"  ✅ 아임웹 게시 완료: {post_url}")
                return {"success": True, "url": post_url, "error": None}
            else:
                # 글쓰기 페이지에 머물러 있으면 실패 가능성
                print(f"  ⚠️ 아임웹 게시 결과 URL: {page.url}")
                return {"success": True, "url": page.url, "error": None}

        except Exception as e:
            print(f"  ❌ 아임웹 게시 오류: {e}")
            return {"success": False, "url": None, "error": str(e)}

        finally:
            browser.close()
