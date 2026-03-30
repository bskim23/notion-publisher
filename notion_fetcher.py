"""
노션 API 연동 모듈
- 발행 대상 페이지 조회
- 페이지 콘텐츠(블록) 파싱
- 발행 결과 속성 업데이트
"""
from __future__ import annotations

import html
import requests
import urllib.request
import tempfile
from datetime import datetime
from typing import Any

from config import (
    NOTION_TOKEN,
    STATUS_PROPERTY,
    TITLE_PROPERTY,
    MODE_PROPERTY,
    CHANNELS_PROPERTY,
    NAVER_URL_PROPERTY,
    IMWEB_URL_PROPERTY,
    FACEBOOK_URL_PROPERTY,
    STIBEE_CAMPAIGN_ID_PROPERTY,
    RESERVED_AT_PROPERTY,
    ERROR_LOG_PROPERTY,
    TEST_CONFIRMED_PROPERTY,
    FB_QUOTE_PROPERTY,
    TAGS_PROPERTY,
)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _query_database(database_id: str, payload: dict) -> list[dict]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    res = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    res.raise_for_status()
    return res.json().get("results", [])


def get_pages_by_status(database_id: str, status: str) -> list[dict]:
    return _query_database(
        database_id,
        {
            "filter": {
                "property": STATUS_PROPERTY,
                "select": {"equals": status},
            }
        },
    )


def get_pending_pages(database_id: str) -> list[dict]:
    """이전 호환성 유지용: 테스트요청/실발행요청은 main.py에서 개별 조회."""
    return get_pages_by_status(database_id, status="발행요청")



def get_page(page_id: str) -> dict:
    url = f"https://api.notion.com/v1/pages/{page_id}"
    res = requests.get(url, headers=HEADERS, timeout=30)
    res.raise_for_status()
    return res.json()



def get_page_title(page: dict) -> str:
    props = page.get("properties", {})
    if TITLE_PROPERTY in props and props[TITLE_PROPERTY].get("type") == "title":
        texts = props[TITLE_PROPERTY].get("title", [])
        title = "".join(t.get("plain_text", "") for t in texts).strip()
        if title:
            return title

    for _, val in props.items():
        if val.get("type") == "title":
            texts = val.get("title", [])
            return "".join(t.get("plain_text", "") for t in texts).strip() or "제목 없음"

    return "제목 없음"



def get_select_value(page: dict, prop_name: str) -> str | None:
    prop = page.get("properties", {}).get(prop_name, {})
    if prop.get("type") == "select":
        select = prop.get("select")
        return select.get("name") if select else None
    return None



def get_multi_select_values(page: dict, prop_name: str) -> list[str]:
    prop = page.get("properties", {}).get(prop_name, {})
    if prop.get("type") == "multi_select":
        return [item.get("name") for item in prop.get("multi_select", []) if item.get("name")]
    return []



def get_checkbox_value(page: dict, prop_name: str) -> bool:
    prop = page.get("properties", {}).get(prop_name, {})
    if prop.get("type") == "checkbox":
        return bool(prop.get("checkbox"))
    return False



def get_rich_text_value(page: dict, prop_name: str) -> str:
    """Rich Text 속성의 plain_text 값을 반환합니다."""
    prop = page.get("properties", {}).get(prop_name, {})
    if prop.get("type") == "rich_text":
        texts = prop.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in texts).strip()
    return ""


def get_fb_quote(page: dict) -> str:
    """페이스북 인용구(fb_quote) 속성값을 반환합니다."""
    return get_rich_text_value(page, FB_QUOTE_PROPERTY)


def get_page_tags(page: dict) -> list[str] | None:
    """태그 속성(Multi-select) 값을 반환합니다. 비어있으면 None."""
    tags = get_multi_select_values(page, TAGS_PROPERTY)
    return tags if tags else None


def get_page_mode(page: dict) -> str | None:
    return get_select_value(page, MODE_PROPERTY)



def get_page_channels(page: dict) -> list[str]:
    return get_multi_select_values(page, CHANNELS_PROPERTY)



def get_page_blocks(page_id: str) -> list:
    all_blocks = []
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    cursor = None

    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor

        res = requests.get(url, headers=HEADERS, params=params, timeout=30)
        res.raise_for_status()
        data = res.json()

        for block in data.get("results", []):
            all_blocks.append(block)
            if block.get("has_children"):
                children = get_page_blocks(block["id"])
                all_blocks.extend(children)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return all_blocks



def _rich_text_to_plain(rich_texts: list) -> str:
    return "".join(t.get("plain_text", "") for t in rich_texts)



def _rich_text_to_html(rich_texts: list) -> str:
    result = ""
    for t in rich_texts:
        text = html.escape(t.get("plain_text", ""))
        annotations = t.get("annotations", {})
        href = t.get("href")

        if href:
            text = f'<a href="{html.escape(href, quote=True)}">{text}</a>'
        if annotations.get("bold"):
            text = f"<strong>{text}</strong>"
        if annotations.get("italic"):
            text = f"<em>{text}</em>"
        if annotations.get("strikethrough"):
            text = f"<del>{text}</del>"
        if annotations.get("code"):
            text = f"<code>{text}</code>"
        result += text
    return result



def _get_image_url(block: dict) -> str | None:
    img = block.get("image", {})
    if img.get("type") == "external":
        return img["external"].get("url")
    if img.get("type") == "file":
        return img["file"].get("url")
    return None



def blocks_to_html(blocks: list) -> str:
    parts = []
    in_ul = False
    in_ol = False

    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        rich = data.get("rich_text", [])

        if in_ul and btype != "bulleted_list_item":
            parts.append("</ul>")
            in_ul = False
        if in_ol and btype != "numbered_list_item":
            parts.append("</ol>")
            in_ol = False

        if btype == "paragraph":
            text = _rich_text_to_html(rich)
            parts.append(f"<p>{text}</p>" if text.strip() else "<br>")
        elif btype == "heading_1":
            parts.append(f"<h1>{_rich_text_to_html(rich)}</h1>")
        elif btype == "heading_2":
            parts.append(f"<h2>{_rich_text_to_html(rich)}</h2>")
        elif btype == "heading_3":
            parts.append(f"<h3>{_rich_text_to_html(rich)}</h3>")
        elif btype == "bulleted_list_item":
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            parts.append(f"  <li>{_rich_text_to_html(rich)}</li>")
        elif btype == "numbered_list_item":
            if not in_ol:
                parts.append("<ol>")
                in_ol = True
            parts.append(f"  <li>{_rich_text_to_html(rich)}</li>")
        elif btype == "quote":
            parts.append(f"<blockquote>{_rich_text_to_html(rich)}</blockquote>")
        elif btype == "divider":
            parts.append("<hr>")
        elif btype == "image":
            url = _get_image_url(block)
            caption = html.escape(_rich_text_to_plain(data.get("caption", [])))
            if url:
                alt = caption or "이미지"
                parts.append(
                    f'<figure><img src="{html.escape(url, quote=True)}" alt="{alt}" style="max-width:100%;">'
                    f"<figcaption>{caption}</figcaption></figure>"
                )
        elif btype == "code":
            code_text = html.escape(_rich_text_to_plain(rich))
            lang = data.get("language", "")
            parts.append(f'<pre><code class="{html.escape(lang, quote=True)}">{code_text}</code></pre>')
        elif btype == "callout":
            emoji = data.get("icon", {}).get("emoji", "💡")
            parts.append(f'<div class="callout">{html.escape(emoji)} {_rich_text_to_html(rich)}</div>')

    if in_ul:
        parts.append("</ul>")
    if in_ol:
        parts.append("</ol>")

    return "\n".join(parts)



def blocks_to_plain_text(blocks: list) -> str:
    parts = []
    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        rich = data.get("rich_text", [])
        text = _rich_text_to_plain(rich)

        if btype == "paragraph":
            if text.strip():
                parts.append(text)
        elif btype in ("heading_1", "heading_2", "heading_3"):
            if text.strip():
                parts.append(f"\n【 {text} 】")
        elif btype == "bulleted_list_item":
            parts.append(f"• {text}")
        elif btype == "numbered_list_item":
            parts.append(f"- {text}")
        elif btype == "quote":
            parts.append(f'"{text}"')
        elif btype == "divider":
            parts.append("─" * 20)
        elif btype == "callout":
            emoji = data.get("icon", {}).get("emoji", "💡")
            parts.append(f"{emoji} {text}")
    return "\n\n".join(p for p in parts if p)



def get_image_urls(blocks: list) -> list[str]:
    urls = []
    for block in blocks:
        if block.get("type") == "image":
            url = _get_image_url(block)
            if url:
                urls.append(url)
    return urls



def download_images(image_urls: list) -> list[str]:
    local_paths = []
    for url in image_urls:
        try:
            suffix = ".jpg" if "jpg" in url.lower() else ".png"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            urllib.request.urlretrieve(url, tmp.name)
            local_paths.append(tmp.name)
        except Exception as e:
            print(f"  ⚠️ 이미지 다운로드 실패: {url} → {e}")
    return local_paths



def update_page_properties(page_id: str, properties: dict[str, Any]) -> bool:
    payload_props: dict[str, Any] = {}

    for name, value in properties.items():
        if value is None:
            continue

        if name in {STATUS_PROPERTY, MODE_PROPERTY}:
            payload_props[name] = {"select": {"name": value}}
        elif name in {NAVER_URL_PROPERTY, IMWEB_URL_PROPERTY, FACEBOOK_URL_PROPERTY}:
            payload_props[name] = {"url": value}
        elif name == STIBEE_CAMPAIGN_ID_PROPERTY:
            payload_props[name] = {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
        elif name == ERROR_LOG_PROPERTY:
            payload_props[name] = {"rich_text": [{"type": "text", "text": {"content": str(value)[:2000]}}]}
        elif name == RESERVED_AT_PROPERTY:
            if isinstance(value, datetime):
                payload_props[name] = {"date": {"start": value.isoformat()}}
            else:
                payload_props[name] = {"date": {"start": str(value)}}
        elif name == TEST_CONFIRMED_PROPERTY:
            payload_props[name] = {"checkbox": bool(value)}
        else:
            raise ValueError(f"지원하지 않는 노션 속성 업데이트: {name}")

    url = f"https://api.notion.com/v1/pages/{page_id}"
    res = requests.patch(url, headers=HEADERS, json={"properties": payload_props}, timeout=30)
    return res.status_code == 200



def update_page_status(page_id: str, status: str) -> bool:
    return update_page_properties(page_id, {STATUS_PROPERTY: status})
