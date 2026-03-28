#!/usr/bin/env python3
"""
노션 발행 시스템 토큰 자동 갱신 스크립트
- 네이버 NID_SES 쿠키: Chrome에서 추출
- 스티비 accessToken: Chrome localStorage에서 추출
- Google Cloud VM의 .env 파일에 SSH로 자동 업데이트

실행: python3 refresh_tokens.py
launchd로 주 1회 자동 실행 설정 가���
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Google Cloud VM 설정
GCE_INSTANCE = "notion-worker"
GCE_ZONE = "asia-northeast3-a"
GCE_PROJECT = "tk-automation-260328"
GCE_ENV_FILE = "/home/kimbongsoo/notion-publisher/.env"
GCLOUD_BIN = "/Users/kimbongsoo/google-cloud-sdk/bin/gcloud"

LOG_FILE = Path(__file__).parent / "refresh.log"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_naver_cookies() -> tuple[str | None, str | None]:
    """Chrome에서 네이버 전체 쿠키를 JSON으로 추출 (NID_SES도 별도 반환)"""
    try:
        from pycookiecheat import chrome_cookies
    except ImportError:
        log("❌ pycookiecheat 미설치: pip3 install pycookiecheat")
        return None, None

    base = Path.home() / "Library/Application Support/Google/Chrome"
    profiles = ["Default"] + [f"Profile {i}" for i in range(1, 20)]

    for name in profiles:
        cookie_file = base / name / "Cookies"
        if not cookie_file.exists():
            continue
        try:
            cookies = chrome_cookies("https://naver.com", cookie_file=str(cookie_file))
            nid_ses = cookies.get("NID_SES", "")
            if nid_ses:
                # Playwright 형식으로 변환
                playwright_cookies = [
                    {"name": k, "value": v, "domain": ".naver.com", "path": "/"}
                    for k, v in cookies.items() if v
                ]
                import json
                cookies_json = json.dumps(playwright_cookies)
                log(f"✅ 네이버 쿠키 {len(playwright_cookies)}개 추출 완료 (프로필: {name})")
                return nid_ses, cookies_json
        except Exception:
            continue

    log("❌ 네이버 쿠키 없음 (Chrome에서 naver.com 로그인 필요)")
    return None, None


def get_stibee_token() -> str | None:
    """Chrome localStorage에서 스티비 accessToken 추출"""
    script = '''
    tell application "Google Chrome"
        set stibeeTab to null
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "stibee.com" then
                    set stibeeTab to t
                    exit repeat
                end if
            end repeat
            if stibeeTab is not null then exit repeat
        end repeat

        if stibeeTab is null then
            -- stibee.com 탭 없으면 백그라운드로 열기
            set stibeeTab to make new tab at end of tabs of front window
            set URL of stibeeTab to "https://stibee.com/dashboard"
            delay 3
        end if

        set result to execute stibeeTab javascript "localStorage.getItem('satellizer_token') || localStorage.getItem('accessToken') || ''"
        return result
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15
        )
        token = result.stdout.strip()
        if token and len(token) > 20:
            log(f"✅ 스티비 토큰 추출 완료 ({token[:20]}...)")
            return token
        log("❌ 스티비 토큰 없음 (Chrome에서 stibee.com 로그인 필요, Apple Events 허용 필요)")
        return None
    except Exception as e:
        log(f"❌ 스티비 토큰 추출 오류: {e}")
        return None


def update_gce_env(key: str, value: str) -> bool:
    """Google Cloud VM의 .env 파일에서 해당 키를 업데이트"""
    # .env에서 해당 키 라인을 교체 (없으면 추가)
    cmd = f"grep -q '^{key}=' {GCE_ENV_FILE} && sed -i 's|^{key}=.*|{key}={value}|' {GCE_ENV_FILE} || echo '{key}={value}' >> {GCE_ENV_FILE}"
    try:
        result = subprocess.run(
            [GCLOUD_BIN, "compute", "ssh", GCE_INSTANCE,
             f"--zone={GCE_ZONE}", f"--project={GCE_PROJECT}",
             f"--command={cmd}"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "CLOUDSDK_PYTHON": "/opt/homebrew/bin/python3"}
        )
        if result.returncode == 0:
            log(f"✅ GCE {key} 업데이트 완료")
            return True
        else:
            log(f"❌ GCE {key} 업데이트 실패: {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        log(f"❌ gcloud CLI 없음: {GCLOUD_BIN}")
        return False
    except Exception as e:
        log(f"❌ GCE 업데이트 오류: {e}")
        return False


def restart_gce_service() -> bool:
    """Google Cloud VM의 notion-worker 서비스 재시작"""
    try:
        result = subprocess.run(
            [GCLOUD_BIN, "compute", "ssh", GCE_INSTANCE,
             f"--zone={GCE_ZONE}", f"--project={GCE_PROJECT}",
             "--command=sudo systemctl restart notion-worker"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "CLOUDSDK_PYTHON": "/opt/homebrew/bin/python3"}
        )
        if result.returncode == 0:
            log("✅ notion-worker 서비스 재시작 완료")
            return True
        else:
            log(f"❌ 서비스 재시작 실패: {result.stderr.strip()}")
            return False
    except Exception as e:
        log(f"❌ 서비스 재시작 오류: {e}")
        return False


def main():
    log("=" * 50)
    log("토큰 자동 갱신 시작 (Google Cloud VM)")

    updated = 0

    # 네이버 쿠키 (전체 JSON + NID_SES 개별)
    nid_ses, cookies_json = get_naver_cookies()
    if nid_ses:
        if update_gce_env("NAVER_NID_SES", nid_ses):
            updated += 1

    # 스티비 토큰
    stibee_token = get_stibee_token()
    if stibee_token:
        if update_gce_env("STIBEE_ACCESS_TOKEN", stibee_token):
            updated += 1

    # 업데이트 있으면 서비스 재시작
    if updated > 0:
        restart_gce_service()

    log(f"완료: {updated}/2 업데이트")
    log("=" * 50)
    return 0 if updated > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
