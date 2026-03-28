"""
티끌레터 HTML 템플릿 엔진
========================
원본 이메일(3298304) HTML 구조를 기반으로,
노션 콘텐츠를 삽입한 완성 HTML을 생성합니다.

블록 구조 (총 13개):
  [0]  🖼️ 헤더 배너 (고정)
  [1]  ── 구분선 (고정)
  [2]  📝 날짜 (가변)
  [3]  🖼️ 뉴스 이미지 1 (가변)
  [4]  📝 본문 단락 1 + 원문링크 (가변)
  [5]  🖼️ 중간 이미지 (가변)
  [6]  📝 본문 단락 2 (가변)
  [7]  ── 구분선 (고정)
  [8]  🖼️ 액션 배너 (고정)
  [9]  📝 실천 포인트 bullet x3 (가변)
  [10] ── 구분선 (고정)
  [11] 📝 마무리 인사 (고정, bg:#F1F3F5)
  [12] 📝 푸터 - 회사정보 + 수신거부 (고정)
"""
import os
import re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# ── 블록 생성 함수들 ──────────────────────────────────────

# 스티비 공통 텍스트 스타일
_FONT_FAMILY = (
    "AppleSDGothic, apple sd gothic neo, noto sans korean, "
    "noto sans korean regular, noto sans cjk kr, noto sans cjk, "
    "nanum gothic, malgun gothic, dotum, arial, helvetica, MS Gothic, sans-serif!important"
)


def _wrap_block(inner_html: str, bg_color: str = "") -> str:
    """stb-block-outer 래퍼"""
    bg = f"background:{bg_color};" if bg_color else ""
    return (
        f'<div class="stb-block-outer"><table class="stb-block stb-cols-1" border="0" '
        f'cellpadding="0" cellspacing="0" style="overflow:hidden;margin:0px auto;padding:0px;'
        f'width:100%;max-width:630px;clear:both;{bg}line-height:1.7;border-width:0px;border: 0px;'
        f'font-size:14px;border:0;box-sizing:border-box;" width="100%">'
        f'<tbody><tr><td><table class="stb-cell-wrap" border="0" cellpadding="0" cellspacing="0" '
        f'width="100%"><tbody><tr><td style="text-align:center;font-size:0;">'
        f'{inner_html}'
        f'</td></tr></tbody></table></td></tr></tbody></table></div>'
    )


def _make_text_block(html_content: str, padding: str = "15px 15px 15px 15px",
                     font_size: str = "16px", text_align: str = "left",
                     color: str = "#000000") -> str:
    """텍스트 블록 생성"""
    inner = (
        f'<div class="stb-left-cell" style="max-width:630px;width:100%!important;margin:0;'
        f'vertical-align:top;border-collapse:collapse;box-sizing:border-box;font-size:unset;'
        f'display:inline-block;">'
        f'<div class="stb-text-box" style="text-align:{text_align};margin:0px;line-height:1.7;'
        f'word-break:break-word;font-size:{font_size};font-family:{_FONT_FAMILY};'
        f'color:{color};clear:both;border:0;">'
        f'<table class="stb-text-box-inner" border="0" cellpadding="0" cellspacing="0" '
        f'style="width:100%;"><tbody><tr>'
        f'<td style="padding:{padding};font-size:{font_size};line-height:1.7;'
        f'word-break:break-word;color:{color};border:0;font-family:{_FONT_FAMILY};width:100%;">'
        f'{html_content}'
        f'</td></tr></tbody></table></div></div>'
    )
    return inner


def _make_image_block(src: str, width: int = 600,
                      padding: str = "5px 15px 5px 15px") -> str:
    """이미지 블록 생성"""
    inner = (
        f'<div class="stb-left-cell" style="max-width:630px;width:100%!important;margin:0;'
        f'vertical-align:top;border-collapse:collapse;box-sizing:border-box;font-size:unset;'
        f'display:inline-block;">'
        f'<div class="stb-image-box" style="text-align:center;margin:0px;width:100%;'
        f'box-sizing:border-box;clear:both;">'
        f'<table border="0" cellpadding="0" cellspacing="0" style="width:100%;" align="center">'
        f'<tbody><tr><td style="padding:{padding};text-align:center;font-size:0;border:0;'
        f'line-height:0;width:100%;box-sizing:border-box;">'
        f'<img src="{src}" style="width:100%;display:inline;vertical-align:bottom;'
        f'text-align:center;max-width:100%;height:auto;border:0;" width="{width}" '
        f'class="stb-center"></td></tr></tbody></table></div></div>'
    )
    return inner


def _make_divider_block() -> str:
    """구분선 블록"""
    inner = (
        '<table border="0" cellpadding="0" cellspacing="0" style="mso-table-lspace: 0pt; '
        'mso-table-rspace: 0pt;" align="left" width="100%"><tbody><tr>'
        '<td style="padding:15px 15px 15px 15px;border:0;">'
        '<table class="stb-partition" style="width:100%;height: 0;background: none;padding: 0px;'
        'border-top-width:1px;border-top-style:dashed;border-top-color:#999999;margin:0 0;'
        'border-collapse:separate;"></table></td></tr></tbody></table>'
    )
    return inner


# ── 고정 블록 (원본에서 추출) ──────────────────────────────

# 블록 0: 헤더 배너 이미지 (매호 동일)
HEADER_BANNER_SRC = "https://img2.stibee.com/16538_3197287_1768977951595362040.jpg"

# 블록 8: 액션 배너 이미지 (매호 동일)
ACTION_BANNER_SRC = "https://img2.stibee.com/16538_3195206_1768895808348307541.jpg"

# 푸터 구독 배너 이미지 (로컬 파일 - 하드코딩)
FOOTER_BANNER_LOCAL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "footer_banner.jpg"
)

# 블록 11: 마무리 인사
CLOSING_HTML = (
    '<div style="text-align: center;">'
    '<span class="link-edited stb-bold" style="font-weight: bold;">오늘의 티끌 알맹이는 여기까지!</span>'
    '<br><span><span class="hljs-variable">내일도, 티끌 모아 실력.</span></span></div>'
)

# 블록 12: 푸터 (수신거부 포함) - 별도 구조
FOOTER_HTML = (
    '<div class="stb-block-outer"><table class="stb-block stb-cols-1" border="0" cellpadding="0" '
    'cellspacing="0" style="overflow:hidden;margin:0px auto;padding:0px;width:100%;max-width:630px;'
    'clear:both;line-height:1.7;border-width:0px;border: 0px;font-size:14px;border:0;'
    'box-sizing:border-box;" width="100%"><tbody><tr><td><table class="stb-cell-wrap" border="0" '
    'cellpadding="0" cellspacing="0" width="100%"><tbody><tr><td style="text-align:center;font-size:0;">'
    '<table class="stb-cell" border="0" cellpadding="0" cellspacing="0" style="max-width:630px;'
    'width:100%!important;margin:0;vertical-align:top;border-collapse:collapse;box-sizing:border-box;'
    'font-size:unset;" align="left" width="100%"><tbody><tr>'
    '<td class="stb-text-box" style="padding:0 0;text-align:center;margin:0px;line-height:1.7;'
    'word-break:break-word;font-size:12px;font-family:' + _FONT_FAMILY + ';color:#747579;border:0;">'
    '<table border="0" cellpadding="0" cellspacing="0" style="width:100%;"><tbody><tr>'
    '<td style="padding:15px 15px 15px 15px;font-family:' + _FONT_FAMILY + ';'
    'line-height:1.7;word-break:break-word;border:0;width:100%;text-align:center;">'
    '<div><span class="stb-fore-colored" style="color: #747579;">WK마케팅그룹</span></div>'
    '<div><span style="color: #747579;" class="stb-fore-colored"><span style="font-size: 12px;">'
    '<a href="mailto:wkmg@wkmg.co.kr" class="stb-mailto stb-fore-colored" '
    'style="color: rgb(116, 117, 121); padding: 0px; text-align: left; line-height: 1.7; '
    'font-weight: normal; text-decoration: underline;" target="_blank">wkmg@wkmg.co.kr</a>'
    '&nbsp;</span> &nbsp;02-571-7752</span></div>'
    '<div><span style="color: #747579;" class="stb-fore-colored">'
    '서울시 서초구 논현로 79 윈드스톤빌딩 1510호</span><br>'
    '<span class="stb-fore-colored" style="color: #747579;">'
    '<a href="$%unsubscribe%$" class="stb-fore-colored stb-underline" '
    'style="text-decoration: underline; color: rgb(116, 117, 121); font-weight: normal;" '
    'target="_blank"><span style="font-weight: normal; font-style: normal;">수신거부</span></a>'
    '&nbsp;<a href="$%unsubscribe%$" class="stb-fore-colored stb-underline" '
    'style="text-decoration: underline; color: rgb(116, 117, 121); font-weight: normal;" '
    'target="_blank"><span style="font-weight: normal; font-style: normal;">Unsubscribe</span></a>'
    '</span></div></td></tr></tbody></table></td></tr></tbody></table>'
    '</td></tr></tbody></table></td></tr></tbody></table></div>'
)

# ── HTML 래퍼 (head + body 시작/끝) ───────────────────────

HTML_HEAD = (
    '<!DOCTYPE html><html><head>'
    '<meta content="width=device-width, initial-scale=1, maximum-scale=1" name="viewport">'
    '<meta charset="UTF-8">'
    '<style>'
    '@media only screen and (max-width:640px) {'
    '.stb-container {}.stb-left-cell,.stb-right-cell {max-width: 100% !important;'
    'width: 100% !important;box-sizing: border-box;}'
    '.stb-image-box td {text-align: center;}'
    '.stb-image-box td img {width: 100%;}'
    '.stb-block {width: 100%!important;}'
    'table.stb-cell {width: 100%!important;}'
    '.stb-cell td,.stb-left-cell td,.stb-right-cell td {width: 100%!important;}'
    'img.stb-justify {width: 100%!important;}'
    '}'
    '.stb-left-cell p,.stb-right-cell p {margin: 0!important;}'
    '</style></head>'
    '<body style="width:100%;margin:0px;">'
    '<div class="stb-container-full" style="width:100%;padding:40px 0;margin:0px auto;display:block;">'
    '<table class="stb-container stb-option-normal" cellpadding="0" cellspacing="0" border="0" '
    'align="center" style="margin:0px auto;width:94%;max-width:630px;background:#ffffff;'
    'border-style:none;box-sizing:border-box;">'
    '<tbody><tr style="margin: 0;padding:0;">'
    '<td style="width:100%;max-width:630px;margin:0 auto;position:relative;border-spacing:0;'
    'border:0;clear:both;border-collapse:separate;padding:0;overflow:hidden;background:#ffffff;">'
)

HTML_TAIL = (
    '</td></tr></tbody></table></div></body></html>'
)


# ── 메인 함수 ────────────────────────────────────────────

def build_tikkeul_html(
    date_str: str = None,
    news_image_url: str = "",
    body_paragraph_1: str = "",
    source_link_url: str = "",
    source_link_text: str = "👉 원문기사 전체보기",
    middle_image_url: str = "",
    body_paragraph_2: str = "",
    action_points: list[dict] = None,
    preheader: str = "매일 아침 작지만 가치있는 인사이트를. 티끌레터™",
) -> str:
    """
    티끌레터 HTML을 조립합니다.

    Args:
        date_str: 날짜 문자열 (예: "2026.03.25. 수요일"). None이면 오늘 날짜 자동
        news_image_url: 뉴스 대표 이미지 URL
        body_paragraph_1: 도입부 본문 (HTML 가능)
        source_link_url: 원문기사 링크 URL
        source_link_text: 원문기사 링크 텍스트
        middle_image_url: 중간 삽입 이미지 URL
        body_paragraph_2: 분석/해설 본문 (HTML 가능)
        action_points: 실천 포인트 리스트 [{"title": "제목", "desc": "설명"}, ...]
        preheader: 프리헤더 텍스트

    Returns:
        완성된 HTML 문자열
    """
    # 날짜 자동 생성
    if not date_str:
        weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
        now = datetime.now(KST)
        date_str = f"{now.strftime('%Y.%m.%d.')} {weekdays[now.weekday()]}"

    blocks = []

    # 프리헤더 (숨김 텍스트)
    preheader_html = (
        f'<div style="height:0px;max-height:0px;border-width:0px;border: 0px;border-color:initial;'
        f'border-image:initial;visibility:hidden;line-height:0px;font-size:0px;overflow:hidden;'
        f'display:none;">{preheader}</div>'
    )

    # [0] 헤더 배너 (고정)
    blocks.append(_wrap_block(_make_image_block(
        HEADER_BANNER_SRC, width=630, padding="0px 0px 0px 0px"
    )))

    # [1] 구분선 (고정)
    blocks.append(_wrap_block(_make_divider_block()))

    # [2] 날짜 (가변)
    date_html = (
        f'<div style="text-align: center;">'
        f'<span style="text-decoration: underline; font-size: 12px;" class="stb-underline">'
        f'<span style="font-weight: bold;" class="stb-bold">{date_str}</span></span></div>'
    )
    blocks.append(_wrap_block(_make_text_block(date_html, text_align="center")))

    # [3] 뉴스 이미지 (가변)
    if news_image_url:
        blocks.append(_wrap_block(_make_image_block(news_image_url)))

    # [4] 본문 단락 1 + 원문 링크 (가변)
    body1_content = f'<div><span>{body_paragraph_1}</span></div>'
    if source_link_url:
        body1_content += (
            f'<div><p><br></p></div>'
            f'<div><div><div><a href="{source_link_url}" class="stb-underline" '
            f'style="font-weight: normal; font-style: normal; text-decoration: underline; '
            f'color: #ff5252;" target="_blank"><span class="stb-underline">{source_link_text}</span>'
            f'</a></div></div></div>'
        )
    blocks.append(_wrap_block(_make_text_block(body1_content)))

    # [5] 중간 이미지 (가변)
    if middle_image_url:
        blocks.append(_wrap_block(_make_image_block(
            middle_image_url, padding="15px 15px 15px 15px"
        )))

    # [6] 본문 단락 2 (가변)
    # 단락 분리: \n\n → <div><br></div>
    paragraphs = body_paragraph_2.split("\n\n") if "\n\n" in body_paragraph_2 else [body_paragraph_2]
    body2_html = ""
    for j, para in enumerate(paragraphs):
        body2_html += f"<div>{para}</div>"
        if j < len(paragraphs) - 1:
            body2_html += "<div><br></div>"
    blocks.append(_wrap_block(_make_text_block(body2_html)))

    # [7] 구분선 (고정)
    blocks.append(_wrap_block(_make_divider_block()))

    # [8] 액션 배너 (고정)
    blocks.append(_wrap_block(_make_image_block(
        ACTION_BANNER_SRC, padding="15px 15px 25px 15px"
    )))

    # [9] 실천 포인트 (가변)
    if action_points:
        bullets_html = ""
        for k, ap in enumerate(action_points):
            title = ap.get("title", "")
            desc = ap.get("desc", "")
            if title and desc:
                content_html = (
                    f'<span class="stb-bold" style="font-weight: bold;">{title}</span>'
                    f': {desc}'
                )
            elif title:
                content_html = f'<span class="stb-bold" style="font-weight: bold;">{title}</span>'
            else:
                content_html = desc
            bullets_html += (
                f'<ul style="padding: 0px; margin: 0px 0px 0px 30px;">'
                f'<li><p>{content_html}</p></li></ul>'
            )
            if k < len(action_points) - 1:
                bullets_html += '<div><br></div>'
        blocks.append(_wrap_block(_make_text_block(bullets_html)))

    # [10] 구분선 (고정)
    blocks.append(_wrap_block(_make_divider_block()))

    # [11] 마무리 인사 (고정, 배경색)
    blocks.append(_wrap_block(
        _make_text_block(CLOSING_HTML, padding="25px 15px 25px 15px", text_align="center"),
        bg_color="#F1F3F5"
    ))

    # [12] 푸터 (고정 - 별도 구조)
    blocks.append(FOOTER_HTML)

    # 조립
    return HTML_HEAD + preheader_html + "".join(blocks) + HTML_TAIL
