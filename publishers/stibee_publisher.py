"""
스티비(Stibee) 뉴스레터 발송 모듈 — 내부 API 사용
=================================================
공식 API(api.stibee.com/v1)는 구독자 관리만 가능하므로,
이메일 생성/발송은 내부 API(stibee.com/api/v1.0)를 사용합니다.

전제 조건:
  - Chrome에 stibee.com 로그인 상태
  - 세션 파일이 존재: ~/.stibee_session.json
  - 세션 만료 시 Claude in Chrome으로 재발급 가능

플로우:
  1. 세션 파일에서 토큰 로드 및 유효성 검증
  2. 기존 이메일 복사(copy) → 새 이메일 ID 생성
  3. Step 1~4 설정 (수신자, A/B, 제목/발신자, HTML 본문)
  4. reserve (즉시발송 = 현재시간+1분)

검증된 API 사양 (2026-03-25):
  - 인증 헤더: accessToken (NOT Authorization: Bearer)
  - step3 발신자명: senderNameA (NOT senderName)
  - step3 발신자이메일: 검증된 이메일만 가능 (wkmg@wkmg.co.kr)
  - step4 HTML: form-encoded, param name = "html"
  - reserve: form-encoded, param name = "reservedTime", format = "YYYY-MM-DD HH:MM"
  - copy 응답: 정수(새 이메일 ID) 직접 반환
"""
import json
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from config import (
    STIBEE_ADDRESS_BOOK_ID,
    STIBEE_SENDER_EMAIL,
    STIBEE_SENDER_NAME,
)

# ── 상수 ────────────────────────────────────────────────────
STIBEE_INTERNAL_BASE = "https://stibee.com/api/v1.0"

# 소스 이메일: 티끌레터 템플릿이 적용된 최근 발송 이메일
SOURCE_EMAIL_ID = 3298304  # "여백도 전략이 된다"

# KST 타임존
KST = timezone(timedelta(hours=9))

# 세션 파일 경로 (재부팅 후에도 유지)
SESSION_FILE = Path(os.getenv("STIBEE_SESSION_FILE", str(Path.home() / ".stibee_session.json")))


# ── 세션 관리 ──────────────────────────────────────────────

def _get_stibee_token_from_chrome() -> str:
    """Chrome Local Storage LevelDB에서 stibee satellizer_token 직접 읽기"""
    import glob
    import re
    from pathlib import Path

    chrome_dir = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    if not chrome_dir.exists():
        return ""

    for profile_dir in sorted(chrome_dir.iterdir()):
        ls_dir = profile_dir / "Local Storage" / "leveldb"
        if not ls_dir.exists():
            continue
        files = sorted(
            glob.glob(str(ls_dir / "*.ldb")) + glob.glob(str(ls_dir / "*.log")),
            key=os.path.getmtime, reverse=True,
        )
        for f in files:
            try:
                # FDA 제한 우회: 임시 복사본에서 읽기
                import shutil, tempfile, subprocess as _sp
                tmp_f = os.path.join(tempfile.gettempdir(), os.path.basename(f))
                cp_r = _sp.run(["cp", f, tmp_f], capture_output=True, timeout=5)
                if cp_r.returncode != 0:
                    shutil.copy2(f, tmp_f)
                with open(tmp_f, "rb") as fh:
                    data = fh.read()
                os.unlink(tmp_f)
                if b"stibee.com" not in data or b"satellizer_token" not in data:
                    continue
                match = re.search(rb"ephemeral[0-9a-f]{100,200}", data)
                if match:
                    token = match.group().decode("ascii")
                    print(f"  ✅ 스티비 토큰 로드 (Chrome/{profile_dir.name})")
                    return token
            except Exception:
                continue
    return ""


def _get_stibee_session() -> dict | None:
    """
    스티비 세션 획득 (우선순위):
    1. Chrome localStorage에서 직접 읽기 (macOS, stibee.com 탭 필요)
    2. 세션 파일 (~/.stibee_session.json)
    3. 환경변수 STIBEE_ACCESS_TOKEN
    """
    token = ""
    cookies = {}

    # 1. Chrome localStorage 직접 읽기
    chrome_token = _get_stibee_token_from_chrome()
    if chrome_token:
        token = chrome_token
        print("  ✅ 스티비 토큰 로드 (Chrome localStorage)")

    # 2. 세션 파일
    if not token or len(token) < 20:
        if SESSION_FILE.exists():
            try:
                data = json.loads(SESSION_FILE.read_text())
                token = data.get("token", "")
                cookies = data.get("cookies", {})
            except Exception:
                pass

    # 3. 환경변수 fallback
    if not token or len(token) < 20:
        token = os.getenv("STIBEE_ACCESS_TOKEN", "")
        cookies = {}

    if not token or len(token) < 20:
        print("  ❌ 스티비 토큰 없음")
        print("     → Chrome에서 stibee.com 로그인 후 DevTools > Application > Local Storage > accessToken")
        print("     → .env 파일에 STIBEE_ACCESS_TOKEN을 설정하세요")
        return None

    # 유효성 검증
    r = requests.get(
        f"{STIBEE_INTERNAL_BASE}/accounts/me/role",
        headers={"accessToken": token, "Accept": "application/json"},
        cookies=cookies, timeout=10,
    )
    if r.status_code == 200:
        print("  ✅ 스티비 세션 유효")
        return {"token": token, "cookies": cookies}

    print(f"  ❌ 스티비 토큰 만료 (HTTP {r.status_code})")
    print("     → STIBEE_ACCESS_TOKEN을 새 값으로 업데이트하세요")
    return None


# ── 헤더 빌더 ──────────────────────────────────────────────

def _build_headers(session: dict) -> dict:
    """내부 API JSON 호출용 헤더"""
    return {
        "accessToken": session["token"],
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }


def _build_form_headers(session: dict) -> dict:
    """form-encoded 요청용 헤더"""
    return {
        "accessToken": session["token"],
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }


# ── 내부 API 호출 ───────────────────────────────────────────

def _copy_email(headers: dict, cookies: dict, source_id: int) -> int | None:
    """기존 이메일을 복사하여 새 이메일 ID를 반환합니다."""
    res = requests.post(
        f"{STIBEE_INTERNAL_BASE}/emails/{source_id}/copy",
        headers=headers, cookies=cookies, timeout=15,
    )
    if res.status_code == 200:
        new_id = res.json()  # 정수 직접 반환
        print(f"    이메일 복사 완료 (원본: {source_id} → 새 ID: {new_id})")
        return int(new_id)
    else:
        print(f"  ❌ 이메일 복사 실패: HTTP {res.status_code} {res.text[:200]}")
        return None


def _setup_step1(headers: dict, cookies: dict, email_id: int, address_book_id: int) -> bool:
    """Step 1: 수신자 설정"""
    payload = {
        "listId": address_book_id,
        "listGroupIds": [],
        "listSegmentIds": [],
        "groupSegmentCondition": "or",
    }
    res = requests.put(
        f"{STIBEE_INTERNAL_BASE}/emails/{email_id}/step1",
        headers=headers, cookies=cookies, json=payload, timeout=15,
    )
    if res.status_code == 200:
        print(f"    Step 1 완료: 수신자 → 주소록 {address_book_id}")
        return True
    print(f"  ❌ Step 1 실패: HTTP {res.status_code} {res.text[:100]}")
    return False


def _setup_step2(headers: dict, cookies: dict, email_id: int) -> bool:
    """Step 2: A/B 테스트 비활성화"""
    res = requests.put(
        f"{STIBEE_INTERNAL_BASE}/emails/{email_id}/step2",
        headers=headers, cookies=cookies, json={"isAb": False}, timeout=15,
    )
    if res.status_code == 200:
        print("    Step 2 완료: A/B 비활성")
        return True
    print(f"  ❌ Step 2 실패: HTTP {res.status_code}")
    return False


def _setup_step3(headers: dict, cookies: dict, email_id: int, subject: str,
                 sender_name: str = None, sender_email: str = None) -> bool:
    """Step 3: 제목, 발신자 설정 (senderNameA, senderEmail)"""
    payload = {
        "subjectA": subject,
        "senderNameA": sender_name or STIBEE_SENDER_NAME or "티끌레터",
        "senderEmail": sender_email or STIBEE_SENDER_EMAIL or "wkmg@wkmg.co.kr",
    }
    res = requests.put(
        f"{STIBEE_INTERNAL_BASE}/emails/{email_id}/step3",
        headers=headers, cookies=cookies, json=payload, timeout=15,
    )
    if res.status_code == 200:
        print(f"    Step 3 완료: 제목 → «{subject[:40]}»")
        return True
    print(f"  ❌ Step 3 실패: HTTP {res.status_code} {res.text[:200]}")
    return False


def _setup_step4_html(form_headers: dict, cookies: dict, email_id: int, html: str) -> bool:
    """Step 4: HTML 본문 설정 (form-encoded, param: html)"""
    res = requests.put(
        f"{STIBEE_INTERNAL_BASE}/editor/{email_id}/contents/html",
        headers=form_headers, cookies=cookies,
        data=urllib.parse.urlencode({"html": html}),
        timeout=30,
    )
    if res.status_code == 200:
        print(f"    Step 4 완료: HTML ({len(html):,}자)")
        return True
    print(f"  ❌ Step 4 실패: HTTP {res.status_code} {res.text[:200]}")
    return False


def _reserve_send(form_headers: dict, cookies: dict, email_id: int, reserved_time: datetime | None = None) -> tuple[bool, str | None]:
    """발송 예약. reserved_time이 없으면 현재 KST + 1분으로 예약합니다."""
    send_time = reserved_time or (datetime.now(KST) + timedelta(minutes=1))
    time_str = send_time.strftime("%Y-%m-%d %H:%M")

    res = requests.post(
        f"{STIBEE_INTERNAL_BASE}/emails/{email_id}/reserve",
        headers=form_headers, cookies=cookies,
        data=urllib.parse.urlencode({"reservedTime": time_str}),
        timeout=15,
    )
    if res.status_code == 200:
        print(f"    발송 예약: {time_str} KST")
        # 노션 date 필드용 ISO 형식 (KST 타임존 포함)
        iso_str = send_time.strftime("%Y-%m-%dT%H:%M:%S+09:00")
        return True, iso_str
    print(f"  ❌ 예약 실패: HTTP {res.status_code} {res.text[:200]}")
    return False, None


# ── 퍼블릭 함수 ────────────────────────────────────────────

def post_to_stibee(payload: dict) -> dict:
    """
    스티비로 뉴스레터 발송

    payload: format_for_stibee() 반환값
      - subject (str): 이메일 제목
      - html (str): HTML 본문
      - sender_name (str, optional): 발신자명
      - sender_email (str, optional): 발신자 이메일 (검증된 것만)
      - address_book_id (int, optional): 주소록 ID

    전체 플로우:
      1. 세션 획득 (파일 캐시만 사용)
      2. 소스 이메일 복사 → 새 이메일 생성
      3. Step 1~4 설정
      4. reserve (즉시발송)
    """
    subject = payload["subject"]
    html = payload["html"]
    sender_name = payload.get("sender_name")
    sender_email = payload.get("sender_email")
    address_book_id = int(payload.get("address_book_id", STIBEE_ADDRESS_BOOK_ID or 438426))
    source_id = int(payload.get("source_email_id", SOURCE_EMAIL_ID))

    try:
        # ── 1. 세션 획득 ─────────────────────────────────
        session = _get_stibee_session()
        if not session:
            print("  ❌ 스티비 세션 획득 실패")
            return {"success": False, "campaign_id": None, "reserved_time": None, "error": "스티비 세션 획득 실패"}

        headers = _build_headers(session)
        form_headers = _build_form_headers(session)
        cookies = session["cookies"]

        # ── 2. 이메일 복사 ───────────────────────────────
        new_email_id = _copy_email(headers, cookies, source_id)
        if not new_email_id:
            return {"success": False, "campaign_id": None, "reserved_time": None, "error": "이메일 복사 실패"}

        # ── 3. Step 1~4 ────────────────────────────────
        if not _setup_step1(headers, cookies, new_email_id, address_book_id):
            return {"success": False, "campaign_id": new_email_id, "reserved_time": None, "error": "step1 실패"}

        if not _setup_step2(headers, cookies, new_email_id):
            return {"success": False, "campaign_id": new_email_id, "reserved_time": None, "error": "step2 실패"}

        if not _setup_step3(headers, cookies, new_email_id, subject, sender_name, sender_email):
            return {"success": False, "campaign_id": new_email_id, "reserved_time": None, "error": "step3 실패"}

        if not _setup_step4_html(form_headers, cookies, new_email_id, html):
            return {"success": False, "campaign_id": new_email_id, "reserved_time": None, "error": "step4 실패"}

        # ── 4. 발송 ─────────────────────────────────────
        reserved_time = payload.get("reserved_time")
        ok, reserved_time_str = _reserve_send(form_headers, cookies, new_email_id, reserved_time)
        if not ok:
            return {"success": False, "campaign_id": new_email_id, "reserved_time": None, "error": "reserve 실패"}

        print(f"  ✅ 스티비 뉴스레터 발송 완료 (ID: {new_email_id})")
        return {"success": True, "campaign_id": str(new_email_id), "reserved_time": reserved_time_str, "error": None}

    except Exception as e:
        print(f"  ❌ 스티비 발송 오류: {e}")
        return {"success": False, "campaign_id": None, "reserved_time": None, "error": str(e)}
