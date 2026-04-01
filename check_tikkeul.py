#!/usr/bin/env python3
"""
티끌 자동화 사전 점검 스크립트
미니(OpenClaw)가 "티끌 가능?" 명령 시 실행

실행: python3 check_tikkeul.py
"""
import os
import sys
import subprocess
import sqlite3
import shutil
import requests
import io
import contextlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
WORKER_LOG = PROJECT_DIR / "worker.log"
ASSETS_DIR = PROJECT_DIR / "assets"
CHROME_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
KST = timezone(timedelta(hours=9))

# .env 로드
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(PROJECT_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

results = []
issues = []


def ok(label, detail=""):
    msg = f"✅ {label}" + (f": {detail}" if detail else "")
    results.append(msg)


def fail(label, detail=""):
    msg = f"❌ {label}" + (f": {detail}" if detail else "")
    results.append(msg)
    issues.append(label)


def warn(label, detail=""):
    msg = f"⚠️ {label}" + (f": {detail}" if detail else "")
    results.append(msg)


now_kst = datetime.now(KST)
hour = now_kst.hour


# ① 워커 실행 여부
try:
    out = subprocess.check_output(["launchctl", "list"], text=True)
    lines = [l for l in out.splitlines() if "notion-publisher" in l]
    if lines:
        parts = lines[0].split()
        pid = parts[0]
        if pid != "-":
            ok("워커", f"실행 중 (PID {pid})")
        else:
            fail("워커", f"중지됨 (마지막 종료코드: {parts[1]})")
    else:
        fail("워커", "서비스 없음 (launchctl에 미등록)")
except Exception as e:
    fail("워커", str(e))


# ② 워커 활성 여부
is_active_time = 10 <= hour < 22
if WORKER_LOG.exists():
    mtime = datetime.fromtimestamp(WORKER_LOG.stat().st_mtime, tz=KST)
    elapsed_min = int((now_kst - mtime).total_seconds() / 60)
    if is_active_time and elapsed_min > 10:
        fail("워커 활성", f"{elapsed_min}분째 갱신 없음 (hanging 의심)")
    elif elapsed_min == 0:
        ok("워커 활성", "방금 업데이트")
    else:
        ok("워커 활성", f"{elapsed_min}분 전 업데이트")
else:
    fail("워커 활성", "로그 파일 없음")


# ③ 네이버 쿠키 만료 확인
def _check_naver_cookie_expiry():
    CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
    profiles = []
    if CHROME_DIR.exists():
        profiles = sorted(
            [p.name for p in CHROME_DIR.iterdir() if p.is_dir() and p.name.startswith("Profile")]
        ) + ["Default"]

    for profile in profiles:
        cookie_path = CHROME_DIR / profile / "Cookies"
        if not cookie_path.exists():
            continue

        # pycookiecheat로 존재 여부 확인 (WAL/암호화 처리 포함)
        try:
            from pycookiecheat import chrome_cookies
            raw = chrome_cookies("https://naver.com", cookie_file=str(cookie_path))
            if not raw.get("NID_SES"):
                continue
        except Exception:
            continue

        # SQLite에서 만료일 조회 (WAL 포함하여 복사)
        tmp = Path("/tmp/_tikkeul_naver_check.db")
        try:
            shutil.copy2(cookie_path, tmp)
            for ext in ["-wal", "-shm"]:
                src = cookie_path.parent / f"Cookies{ext}"
                if src.exists():
                    shutil.copy2(src, Path(f"/tmp/_tikkeul_naver_check.db{ext}"))
            conn = sqlite3.connect(str(tmp))
            row = conn.execute(
                "SELECT expires_utc FROM cookies "
                "WHERE host_key LIKE '%naver.com' AND name='NID_SES' LIMIT 1"
            ).fetchone()
            conn.close()
            if row and row[0]:
                expires = CHROME_EPOCH + timedelta(microseconds=row[0])
                expires_kst = expires.astimezone(KST)
                if expires_kst < now_kst:
                    return False, f"만료됨 ({expires_kst.strftime('%Y-%m-%d')})"
                return True, f"유효 (만료: {expires_kst.strftime('%Y-%m-%d')})"
            # 만료일 읽기 실패해도 쿠키 존재는 확인됨
            return True, "유효 (만료일 미확인)"
        except Exception:
            return True, "유효 (만료일 미확인)"

    return False, "NID_SES 쿠키 없음 — Chrome에서 네이버 로그인 필요"

try:
    valid, detail = _check_naver_cookie_expiry()
    if valid:
        ok("네이버 쿠키", detail)
    else:
        fail("네이버 쿠키", detail)
except Exception as e:
    fail("네이버 쿠키", str(e))


# ④ 스티비 세션
try:
    from publishers.stibee_publisher import _get_stibee_session
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        session = _get_stibee_session()
    if session:
        ok("스티비 세션", "유효")
    else:
        fail("스티비 세션", "인증 실패 — Chrome에서 stibee.com 로그인 필요")
except Exception as e:
    fail("스티비 세션", str(e))


# ⑤ Notion 연결
try:
    from config import NOTION_TOKEN, NOTION_DATABASE_ID
    res = requests.get(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
        },
        timeout=10,
    )
    if res.status_code == 200:
        ok("Notion 연결", "정상")
    else:
        fail("Notion 연결", f"HTTP {res.status_code}")
except requests.exceptions.Timeout:
    fail("Notion 연결", "타임아웃 (10초 초과)")
except Exception as e:
    fail("Notion 연결", str(e))


# ⑥ 에셋 파일
asset_files = ["header_banner.jpg", "action_banner.jpg", "footer_banner.jpg"]
missing = [f for f in asset_files if not (ASSETS_DIR / f).exists()]
if missing:
    fail("에셋 파일", f"누락: {', '.join(missing)}")
else:
    ok("에셋 파일", "3개 정상")


# ⑦ 현재 폴링 주기
if 10 <= hour < 19:
    polling_msg = "1분 폴링 중"
elif 19 <= hour < 22:
    polling_msg = "10분 폴링 중 — 즉시 실행이 필요하면 '1회 실행' 요청"
else:
    polling_msg = f"야간 중지 중 — 즉시 실행이 필요하면 '1회 실행' 요청"
results.append(f"🕐 폴링: {polling_msg}")


# 최종 출력
print("\n".join(results))
if issues:
    print(f"\n→ 문제: {', '.join(issues)}")
else:
    print("\n→ 준비됐습니다 ✅")
