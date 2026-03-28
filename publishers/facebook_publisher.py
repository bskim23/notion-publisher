"""페이스북 링크 공유 게시 모듈"""
from __future__ import annotations

import requests

from config import FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN

GRAPH_BASE = "https://graph.facebook.com/v19.0"


def post_to_facebook(
    title: str,
    naver_blog_url: str,
    message: str | None = None,
    fb_quote: str | None = None,
    page_id: str | None = None,
    access_token: str | None = None,
) -> dict:
    """
    네이버 블로그 URL을 페이스북 페이지에 링크 공유합니다.
    fb_quote가 있으면 인용구 + URL 형태, 없으면 제목 + URL fallback.
    반환값: {success, post_id, error}
    """
    target_page_id = page_id or FACEBOOK_PAGE_ID
    token = access_token or FACEBOOK_ACCESS_TOKEN

    if not target_page_id or not token:
        msg = "페이스북 Page ID / Access Token이 설정되지 않았습니다"
        print(f"  ❌ {msg}")
        return {"success": False, "post_id": None, "error": msg}

    if not naver_blog_url:
        msg = "네이버 블로그 URL이 없어 페이스북 링크 공유를 건너뜁니다"
        print(f"  ❌ {msg}")
        return {"success": False, "post_id": None, "error": msg}

    if message:
        post_message = message
    elif fb_quote:
        post_message = f"\"{fb_quote}\"\n\n{naver_blog_url}"
    else:
        post_message = f"오늘의 티끌레터: {title}\n\n{naver_blog_url}"

    try:
        res = requests.post(
            f"{GRAPH_BASE}/{target_page_id}/feed",
            params={
                "link": naver_blog_url,
                "message": post_message,
                "access_token": token,
            },
            timeout=20,
        )
        data = res.json()
        if "id" in data:
            print(f"  ✅ 페이스북 링크 공유 완료 (포스트 ID: {data['id']})")
            return {"success": True, "post_id": data["id"], "error": None}

        err = data.get("error", {})
        msg = err.get("message", res.text)
        print(f"  ❌ 페이스북 링크 공유 실패: {msg}")
        return {"success": False, "post_id": None, "error": msg}
    except Exception as e:
        print(f"  ❌ 페이스북 링크 공유 오류: {e}")
        return {"success": False, "post_id": None, "error": str(e)}
