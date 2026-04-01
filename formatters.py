"""
플랫폼별 콘텐츠 포맷터
각 플랫폼에 맞는 규칙(이미지 위치, 텍스트 제한, HTML 스타일 등)으로 변환
"""

import html as html_lib
import re


_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.?\s*[가-힣]+요일$")
_URL_RE = re.compile(r"https?://[^\s<>\"]+")

# 팁 섹션 헤더 패턴
_TIP_HEADERS = {
    "티끌 마케팅 Tips", "📌 티끌 마케팅 Tips", "오늘의 티끌 마케팅 Tips", "티끌마케팅 Tips",
    "티끌 마케팅 팁", "📌 티끌 마케팅 팁", "오늘의 티끌 마케팅 팁", "티끌마케팅 팁",
}

# 발행 후 제거할 고정 문구 (팁 헤더는 포함하지 않음 — _extract_tips_and_closing이 처리)
_CLOSING_EXCLUDE = {
    "오늘의 티끌 알맹이는 여기까지!",
    "내일도, 티끌 모아 실력.",
    "WK마케팅그룹",
    "오늘의 티끌",
}

# 네이버 블로그 기본 태그
NAVER_DEFAULT_TAGS = ["마케팅전략", "브랜딩", "소비자인사이트", "마케팅인사이트", "마케팅칼럼", "티끌뉴스"]

# 본문 키워드 → 자동 태그 매핑
_KEYWORD_TAG_MAP = {
    "뉴스레터": "뉴스레터",
    "이메일": "이메일마케팅",
    "오픈율": "이메일마케팅",
    "클릭률": "이메일마케팅",
    "CTA": "CTA전략",
    "구독": "구독마케팅",
    "SNS": "SNS마케팅",
    "인스타그램": "인스타그램마케팅",
    "유튜브": "유튜브마케팅",
    "콘텐츠": "콘텐츠마케팅",
    "광고": "광고마케팅",
    "퍼포먼스": "퍼포먼스마케팅",
    "데이터": "데이터드리븐",
    "AI": "AI마케팅",
    "챗GPT": "AI마케팅",
    "트렌드": "마케팅트렌드",
    "브랜드": "브랜드마케팅",
    "소비자": "소비자행동",
    "고객경험": "고객경험",
    "MZ": "MZ세대마케팅",
    "2030": "MZ세대마케팅",
    "건강": "헬스케어마케팅",
    "식품": "식품마케팅",
    "쇼핑": "쇼핑트렌드",
    "복리": "자기계발",
    "습관": "습관형성",
    "생산성": "생산성",
    "스타트업": "스타트업",
    "커머스": "이커머스",
    "디지털": "디지털마케팅",
}


def extract_content_tags(title: str, text: str, max_extra: int = 4) -> list[str]:
    """제목+본문에서 키워드를 분석해 관련 태그 자동 추출"""
    combined = (title + " " + text).lower()
    extra = []
    seen = set()
    for keyword, tag in _KEYWORD_TAG_MAP.items():
        if keyword.lower() in combined and tag not in seen:
            extra.append(tag)
            seen.add(tag)
        if len(extra) >= max_extra:
            break
    return extra


def _html_to_paragraphs(html_content: str) -> list[str]:
    """HTML 본문을 문단 리스트로 정리"""
    if not html_content:
        return []

    text = html_content

    # figure(이미지+캡션) 블록 전체 제거 — 캡션 텍스트가 본문에 섞이지 않도록
    text = re.sub(r"<figure[^>]*>.*?</figure\s*>", "", text, flags=re.I | re.DOTALL)

    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</div\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</li\s*>", "\n\n", text, flags=re.I)

    # 태그 제거
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)

    text = text.replace("\r", "")
    text = re.sub(r"\n{3,}", "\n\n", text)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return paragraphs


def _join_paragraphs_as_html(paragraphs: list[str]) -> str:
    """문단 리스트를 템플릿용 HTML로 합침"""
    if not paragraphs:
        return ""
    return "".join(f"<p>{p}</p>" for p in paragraphs if p.strip())


def _extract_date(paragraphs: list[str]) -> tuple[str, list[str]]:
    """첫 문단이 날짜면 분리"""
    if paragraphs and _DATE_RE.match(paragraphs[0].strip()):
        return paragraphs[0].strip(), paragraphs[1:]
    return "", paragraphs


def _extract_source_link(
    html_content: str,
    paragraphs: list[str],
    source_link_url: str = "",
) -> tuple[str, list[str]]:
    """원문 링크 추출"""
    if source_link_url:
        cleaned = [
            p for p in paragraphs
            if "관련기사 전문보기" not in p and not _URL_RE.fullmatch(p.strip())
        ]
        return source_link_url.strip(), cleaned

    hrefs = re.findall(r'href=[\'"]([^\'"]+)[\'"]', html_content or "", flags=re.I)
    for href in hrefs:
        if href.startswith("http"):
            cleaned = []
            for p in paragraphs:
                if "관련기사 전문보기" in p:
                    continue
                if href in p:
                    continue
                cleaned.append(p)
            return href.strip(), cleaned

    cleaned = []
    found_url = ""
    for p in paragraphs:
        url_match = _URL_RE.search(p)
        if url_match and not found_url:
            found_url = url_match.group(0).strip()
            if "관련기사 전문보기" in p or p.strip() == found_url:
                continue
            p = p.replace(found_url, "").strip()
            if p:
                cleaned.append(p)
            continue
        if "관련기사 전문보기" in p:
            continue
        cleaned.append(p)

    return found_url, cleaned


def _parse_tip(text: str) -> dict | None:
    """팁 텍스트를 {title, desc}로 파싱.
    지원 형식:
      1) 제목: 설명  (콜론 구분)
      2) 첫문장. 나머지.  (온점+공백 구분)
      3) 단일 문장  (전체 = title)
    """
    text = text.strip()
    if not text:
        return None

    # 1) 콜론 구분
    m = re.match(r"^(.+?)\s*:\s*(.+)$", text, re.DOTALL)
    if m:
        return {"title": m.group(1).strip(), "desc": m.group(2).strip()}

    # 2) 온점+공백 구분 (첫 문장 = title, 나머지 = desc)
    m2 = re.search(r"^(.+?[.!?])\s+(.+)$", text, re.DOTALL)
    if m2:
        title = m2.group(1).strip().rstrip(".")
        desc = m2.group(2).strip()
        return {"title": title, "desc": desc}

    # 3) 단일 문장
    return {"title": text, "desc": ""}


def _extract_tips_and_closing(paragraphs: list[str]) -> tuple[list[dict], str, list[str]]:
    """
    팁 섹션 추출.

    우선순위:
    1) "티끌 마케팅 Tips" 같은 섹션 헤더 발견 시 → 이후 모든 항목이 팁
    2) 없으면 하단에서 "제목: 설명" 형식으로 스캔 (기존 로직)
    """
    # 1) 섹션 헤더 기반
    header_idx = -1
    for i, p in enumerate(paragraphs):
        clean = p.strip().lstrip("📌# *").strip()
        if clean in _TIP_HEADERS or re.sub(r"\s", "", clean) in {"티끌마케팅Tips", "티끌마케팅Tip", "티끌마케팅팁"}:
            header_idx = i
            break

    if header_idx != -1:
        tip_paragraphs = paragraphs[header_idx + 1:]
        remaining = paragraphs[:header_idx]
        tips = [_parse_tip(p) for p in tip_paragraphs if p.strip()]
        tips = [t for t in tips if t]
        return tips, "", remaining

    # 2) 하단 스캔 (콜론 형식 fallback)
    tips = []
    idx = len(paragraphs) - 1
    while idx >= 0 and len(tips) < 3:
        p = paragraphs[idx].strip()
        m = re.match(r"^(.+?)\s*:\s*(.+)$", p)
        if not m:
            break
        tips.append({"title": m.group(1).strip(), "desc": m.group(2).strip()})
        idx -= 1

    tips.reverse()

    if not tips:
        return [], "", paragraphs

    closing_text = ""
    if idx >= 0:
        closing_text = paragraphs[idx].strip()
        idx -= 1

    remaining = paragraphs[:idx + 1]
    return tips, closing_text, remaining


def _split_body_1_and_body_2(paragraphs: list[str]) -> tuple[list[str], list[str]]:
    if not paragraphs:
        return [], []
    if len(paragraphs) == 1:
        return paragraphs, []
    if len(paragraphs) == 2:
        return [paragraphs[0]], [paragraphs[1]]
    return paragraphs[:2], paragraphs[2:]


# ── 공통 필터 ────────────────────────────────────────────────

def _filter_fixed(paragraphs: list[str]) -> list[str]:
    return [
        p for p in paragraphs
        if p.strip() not in _CLOSING_EXCLUDE
        and "수신거부" not in p
        and "Unsubscribe" not in p
    ]


# ── 플랫폼별 포맷터 ──────────────────────────────────────────

def format_for_naver_blog(
    title: str,
    html_content: str,
    image_urls: list,
    category: str = "티끌레터™",
    source_link_url: str = "",
    tags: list | None = None,
) -> dict:
    """
    네이버 블로그용 포맷 — 티끌레터 레이아웃 재현
    sections: [{"type": "html"|"image", "content"|"url": ...}, ...]
    순서: 헤더배너 → 날짜+본문1 → 기사이미지 → 본문2 → 액션배너 → 팁 → 마무리
    """
    from publishers.tikkeul_template import HEADER_BANNER_SRC, ACTION_BANNER_SRC, FOOTER_BANNER_LOCAL, HEADER_BANNER_LOCAL, ACTION_BANNER_LOCAL

    paragraphs = _html_to_paragraphs(html_content)
    paragraphs = _filter_fixed(paragraphs)

    date_str, paragraphs = _extract_date(paragraphs)
    source_url, paragraphs = _extract_source_link(html_content, paragraphs, source_link_url)
    tips, closing_text, paragraphs = _extract_tips_and_closing(paragraphs)
    body_1_ps, body_2_ps = _split_body_1_and_body_2(paragraphs)
    if closing_text:
        body_2_ps.append(closing_text)

    SUBSCRIBE_URL = "https://page.stibee.com/subscriptions/466923"

    # ── SE3 호환 HTML 빌더 ─────────────────────────────────
    # 허용: <strong>, <a>, <hr>, <p style="text-align:...">
    # 날짜만 가운데 정렬, 이후 단락은 명시적으로 left 지정해 블리드 방지

    def _p(text, align="left"):
        return f'<p style="text-align:{align};">{text}</p>'
    def _bold(text): return f'<strong>{text}</strong>'

    sections = []

    # [0] 기사 대표 이미지 (첫 번째 이미지 = 자동 대표 선택)
    if image_urls:
        sections.append({"type": "image", "url": image_urls[0]})

    # [1] 본문1(왼쪽) — 날짜 제거됨
    part1_lines = []
    if False:  # 날짜 블록 사용 안 함
        pass
    for p in body_1_ps:
        part1_lines.append(_p(p))          # align=left 기본
    if source_url:
        part1_lines.append(
            _p(f'<a href="{source_url}" target="_blank">👉 관련기사 전문보기</a>')
        )
    if part1_lines:
        sections.append({"type": "html", "content": "\n".join(part1_lines)})

    # [2] 헤더 배너 (로컬 파일)
    sections.append({"type": "local_file", "path": HEADER_BANNER_LOCAL})

    # [3] 본문2 (헤더 배너 직후 → 여백 없이 바로 이어붙임)
    if body_2_ps:
        sections.append({"type": "html", "content": "\n".join(_p(p) for p in body_2_ps), "leading_newline": False})

    # [4] 액션 배너 (Tips 헤더 이미지) + 팁 (블릿 포인트, 팁 사이 한 줄)
    if tips:
        sections.append({"type": "local_file", "path": ACTION_BANNER_LOCAL})
        tip_parts = []
        for tip in tips:
            t = tip.get("title", "")
            d = tip.get("desc", "")
            if t and d:
                tip_parts.append(f"• {_bold(t)}: {d}")
            elif t:
                tip_parts.append(f"• {t}")
        if tip_parts:
            # <br>로 연결 → 팁 사이 한 줄만 띄움, 과도한 단락 간격 없음
            tips_html = "<br>\n".join(tip_parts)
            # leading_newline=False: 액션배너 이미지 직후라 Enter 불필요
            # 끝에 <p>&nbsp;</p> 추가 → 푸터 이미지와 2줄 간격
            sections.append({
                "type": "html",
                "content": f"<p>{tips_html}</p><p>&nbsp;</p>",
                "leading_newline": False,
            })

    # [5] 푸터: 구독 배너 이미지(로컬 파일)
    sections.append({
        "type": "local_file",
        "path": FOOTER_BANNER_LOCAL,
    })
    # [6] 구독 신청 하이퍼링크 (푸터 이미지 하단)
    sections.append({
        "type": "html",
        "content": _p(
            f'<a href="{SUBSCRIBE_URL}" target="_blank">'
            f'👉 티끌레터™ 구독 신청하기</a>',
            align="center",
        ),
    })

    # ── plain text (태그 추출용) ───────────────────────────
    text_parts = []
    if date_str:
        text_parts.append(date_str)
    text_parts.extend(body_1_ps)
    text_parts.extend(body_2_ps)
    if tips:
        for i, tip in enumerate(tips, 1):
            t, d = tip.get("title", ""), tip.get("desc", "")
            text_parts.append(f"{i}. {t} {d}".strip())
    text = "\n\n".join(p for p in text_parts if p.strip())

    # 기본 태그 + 본문 키워드 자동 태그 합산 (중복 제거)
    if tags is None:
        extra = extract_content_tags(title, text, max_extra=4)
        all_tags = list(dict.fromkeys(NAVER_DEFAULT_TAGS + extra))
    else:
        all_tags = tags

    return {
        "title": title,
        "sections": sections,
        "text": text,          # 하위 호환 (html_body 미사용)
        "html_body": "",       # 하위 호환
        "image_urls": image_urls,
        "category": category,
        "tags": all_tags,
    }


def format_for_imweb(
    title: str,
    html_content: str,
    image_urls: list,
    source_link_url: str = "",
) -> dict:
    """
    아임웹 '지난 티끌레터™ 모아보기' 게시판 포맷.
    실제 게시물 HTML 구조 (Froala 에디터) 그대로 재현:
      날짜 → 헤더배너 → 본문1 → 원문링크 → 기사이미지 → 본문2
      → 액션배너 → 팁(ul/li) → 빈줄

    모든 텍스트: <span style="font-size:22px;"> 래핑
    빈 줄: <p><span style="font-size:22px;"><br></span></p>
    이미지: fr-fic fr-dii 클래스
    """
    # CDN 고정 이미지 (이미 업로드된 배너)
    IMWEB_HEADER_BANNER = "https://cdn.imweb.me/upload/S201801305a701243df109/a7481c0ea1b6e.png"
    IMWEB_ACTION_BANNER = "https://cdn.imweb.me/upload/S201801305a701243df109/dc92c5b343840.png"

    _SZ = 'style="font-size:22px;"'  # 반복 축약
    _BR = f'<p><span {_SZ}><br></span></p>'  # 빈 줄

    def _span(text: str) -> str:
        return f'<span {_SZ}>{text}</span>'

    def _p(text: str, align: str = "") -> str:
        style = f'style="text-align:{align};"' if align else ""
        return f"<p {style}>{_span(text)}</p>"

    def _img(src: str, alt: str = "") -> str:
        return (
            f'<img src="{src}" alt="{alt}" '
            f'style="border:0px solid rgb(229,231,235);height:auto;left:auto;padding:0px 1px;" '
            f'class="fr-fic fr-dii _img_light_gallery cursor_pointer" '
            f'data-src="{src}">'
        )

    paragraphs = _html_to_paragraphs(html_content)
    paragraphs = _filter_fixed(paragraphs)

    date_str, paragraphs = _extract_date(paragraphs)
    source_url, paragraphs = _extract_source_link(html_content, paragraphs, source_link_url)
    tips, closing_text, paragraphs = _extract_tips_and_closing(paragraphs)
    body_1_ps, body_2_ps = _split_body_1_and_body_2(paragraphs)
    if closing_text:
        body_2_ps.append(closing_text)

    parts: list[str] = []

    # ── 날짜 (중앙 정렬) — 없으면 오늘 날짜 자동 생성 ──
    if not date_str:
        from datetime import datetime, timedelta, timezone
        _KST = timezone(timedelta(hours=9))
        _WD = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
        now = datetime.now(_KST)
        date_str = f"{now.strftime('%Y.%m.%d.')} {_WD[now.weekday()]}"
    parts.append(_p(date_str, align="center"))

    # ── 헤더 배너 이미지 ──
    parts.append(f"<p>{_span(_img(IMWEB_HEADER_BANNER))}</p>")

    # ── 본문 1 ──
    for p in body_1_ps:
        parts.append(f"<p>{_span(p)}</p>")

    # ── 빈 줄 + 원문 링크 ──
    if source_url:
        parts.append(_BR)
        link_html = f'<a href="{source_url}">👉 관련기사 전문보기</a>'
        parts.append(f"<p>{_span(link_html)}</p>")

    # ── 기사 고유 이미지 ──
    if image_urls:
        img_html = "<br>" + _img(image_urls[0], title)
        parts.append(f"<p>{_span(img_html)}</p>")

    # ── 빈 줄 ──
    parts.append(_BR)

    # ── 본문 2 ──
    for p in body_2_ps:
        parts.append(f"<p>{_span(p)}</p>")
        parts.append(_BR)

    # ── 액션 배너 이미지 ──
    parts.append(f"<p>{_span(_img(IMWEB_ACTION_BANNER))}</p>")

    # ── 팁 (ul > li, 볼드 제목) ──
    _UL_STYLE = (
        'style="color:rgb(0,0,0);font-size:16px;padding:0px;margin:0px 0px 0px 30px;"'
    )
    if tips:
        for i, tip in enumerate(tips):
            t = tip.get("title", "")
            d = tip.get("desc", "")
            if t and d:
                li_content = f"<strong>{t}</strong><br>{d}"
            elif t:
                li_content = f"<strong>{t}</strong>"
            else:
                li_content = d
            parts.append(
                f'<ul {_UL_STYLE}>'
                f'<li style="margin-left:15px;">{_span(li_content)}</li>'
                f'</ul>'
            )
            if i < len(tips) - 1:
                parts.append(_BR)

    content = "".join(parts)

    return {
        "title": title,
        "content": content,
        "thumbnail": image_urls[0] if image_urls else None,
    }


def format_for_facebook(title: str, plain_text: str, image_urls: list, page_url: str = "") -> dict:
    """
    페이스북 페이지 포스트용 포맷
    - 네이버 블로그 URL을 링크로 첨부
    """
    MAX_CHARS = 1800
    body = plain_text
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + "...\n\n▶ 전체 내용 보기: " + page_url

    message = f"{title}\n\n{body}"
    if page_url and len(plain_text) <= MAX_CHARS:
        message += f"\n\n▶ 더 보기: {page_url}"

    return {
        "message": message,
        "image_urls": image_urls[:4],
    }


def format_for_stibee(
    title: str,
    html_content: str,
    image_urls: list,
    sender_name: str = "",
    source_link_url: str = "",
    action_points: list = None,
) -> dict:
    """
    스티비 뉴스레터용 포맷 — 티끌레터 템플릿 사용
    """
    from publishers.tikkeul_template import build_tikkeul_html

    paragraphs = _html_to_paragraphs(html_content)
    paragraphs = _filter_fixed(paragraphs)

    date_str, paragraphs = _extract_date(paragraphs)

    extracted_source_link_url, paragraphs = _extract_source_link(
        html_content=html_content,
        paragraphs=paragraphs,
        source_link_url=source_link_url,
    )

    tips, closing_text, paragraphs = _extract_tips_and_closing(paragraphs)

    # action_points 명시적으로 들어오면 우선 사용
    if action_points:
        normalized = []
        for ap in action_points:
            normalized.append({
                "title": ap.get("title", "").strip(),
                "desc": ap.get("desc", ap.get("body", "")).strip(),
            })
        tips = normalized

    body_1_paragraphs, body_2_paragraphs = _split_body_1_and_body_2(paragraphs)

    if closing_text:
        body_2_paragraphs.append(closing_text)

    body_1_html = _join_paragraphs_as_html(body_1_paragraphs)
    body_2_html = _join_paragraphs_as_html(body_2_paragraphs)

    hero_image_url = image_urls[0] if image_urls else ""

    html = build_tikkeul_html(
        date_str=None,  # 날짜 사용 안 함
        news_image_url="",
        body_paragraph_1=body_1_html,
        source_link_url=extracted_source_link_url,
        source_link_text="👉 관련기사 전문보기",
        middle_image_url=hero_image_url,
        body_paragraph_2=body_2_html,
        action_points=tips or [],
    )

    return {
        "subject": title,
        "html": html,
    }
