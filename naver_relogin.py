#!/usr/bin/env python3
"""
네이버 자동 재로그인 스크립트
미니(OpenClaw)가 "네이버 재로그인" 지시 시 실행

실행: python3 naver_relogin.py
"""
import os
import sys
import json
import time
import sqlite3
import shutil
import tempfile
import requests
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(PROJECT_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

NAVER_ID = os.getenv("NAVER_ID", "")
NAVER_PW = os.getenv("NAVER_PW", "")
CHAT_ID = "8677699069"
CHROME_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"

# Telegram bot token
_tg_config = Path.home() / ".claude-tg-bridge" / "config.json"
with open(_tg_config) as f:
    BOT_TOKEN = json.load(f)["bot_token"]


def _send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as e:
        print(f"  텔레그램 전송 실패: {e}")


def _send_telegram_photo(path: str, caption: str):
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"photo": f},
                timeout=15,
            )
    except Exception as e:
        print(f"  텔레그램 사진 전송 실패: {e}")


def _find_best_profile() -> str:
    """NID_SES 쿠키가 있거나 가장 최근 활동한 Chrome 프로필 반환"""
    profiles = sorted(
        [p.name for p in CHROME_DIR.iterdir() if p.is_dir() and p.name.startswith("Profile")]
    )
    for profile in profiles:
        cookie_path = CHROME_DIR / profile / "Cookies"
        if not cookie_path.exists():
            continue
        tmp = Path("/tmp/_tikkeul_naver_profile.db")
        try:
            shutil.copy2(cookie_path, tmp)
            conn = sqlite3.connect(str(tmp))
            row = conn.execute(
                "SELECT 1 FROM cookies WHERE host_key LIKE '%naver.com' AND name='NID_SES' LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                return profile
        except Exception:
            continue
    return "Profile 7"  # 기존 네이버 발행용 프로필


def run():
    if not NAVER_ID or not NAVER_PW:
        print("❌ NAVER_ID/NAVER_PW 환경변수 없음")
        return

    from playwright.sync_api import sync_playwright

    profile = _find_best_profile()
    profile_path = str(CHROME_DIR / profile)
    print(f"  Chrome 프로필: {profile} ({profile_path})")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        page = ctx.new_page()

        print("  네이버 로그인 페이지 접속...")
        page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded", timeout=20000)
        time.sleep(1.5)

        # 이미 로그인된 경우
        if "nidlogin" not in page.url:
            print("✅ 이미 로그인 상태 — 쿠키 갱신 완료")
            _send_telegram("✅ 네이버 이미 로그인 상태 — 쿠키 갱신 완료")
            ctx.close()
            return

        # ID / PW 입력
        print("  ID/PW 입력 중...")
        try:
            page.fill("#id", NAVER_ID)
            time.sleep(0.5)
            page.fill("#pw", NAVER_PW)
            time.sleep(0.5)
            page.click(".btn_login")
            time.sleep(3)
        except Exception as e:
            print(f"  ⚠️ 로그인 입력 실패: {e}")

        current_url = page.url
        print(f"  로그인 후 URL: {current_url}")

        # 로그인 성공 확인
        if "nidlogin" not in current_url:
            print("✅ 네이버 로그인 완료")
            _send_telegram("✅ 네이버 로그인 완료 — 세션 갱신됨")
            ctx.close()
            return

        # CAPTCHA 또는 추가 인증 필요
        print("  ⚠️ 추가 인증 필요 — 스크린샷 캡처 중...")
        ss_path = tempfile.mktemp(suffix=".png")
        page.screenshot(path=ss_path)

        _send_telegram_photo(
            ss_path,
            "🔐 네이버 로그인 추가 인증 발생\n"
            "Mac 화면에서 직접 해결 후\n"
            "텔레그램으로 '완료' 전송해 주세요"
        )
        print("  스크린샷 텔레그램 전송 완료")
        print("  브라우저 열어둔 채 대기 중... (최대 10분)")

        # 사용자가 직접 해결할 때까지 폴링
        for i in range(10):
            time.sleep(60)
            try:
                current_url = page.url
            except Exception:
                break
            if "nidlogin" not in current_url:
                print("✅ 네이버 로그인 완료 (사용자 직접 해결)")
                _send_telegram("✅ 네이버 로그인 완료 — 감사합니다")
                ctx.close()
                return
            print(f"  대기 중... ({i + 1}/10분)")

        print("❌ 10분 내 로그인 미완료")
        _send_telegram("❌ 네이버 로그인 타임아웃 (10분 초과) — 수동 처리 필요")
        ctx.close()


if __name__ == "__main__":
    run()
