#!/bin/bash
# 새 Mac에서 노션 토큰 자동 갱신 설치 스크립트
# 터미널에서 실행: bash setup_on_new_mac.sh

set -e

SCRIPT_DIR="$HOME/notion-token-refresher"
PLIST_PATH="$HOME/Library/LaunchAgents/com.wkmg.notion-token-refresher.plist"
GCLOUD_DIR="$HOME/google-cloud-sdk"

echo "======================================"
echo "  노션 발행 토큰 자동 갱신 설치"
echo "  (Google Cloud VM 연동)"
echo "======================================"

# 1. 디렉토리 생성
mkdir -p "$SCRIPT_DIR"

# 2. pycookiecheat 설치
echo ""
echo "📦 pycookiecheat 설치 중..."
pip3 install pycookiecheat --break-system-packages 2>/dev/null || pip3 install pycookiecheat

# 3. gcloud CLI 설치
if [ ! -f "$GCLOUD_DIR/bin/gcloud" ]; then
    echo ""
    echo "📦 Google Cloud SDK 설치 중..."
    cd /tmp
    curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-darwin-arm.tar.gz
    tar -xzf google-cloud-cli-darwin-arm.tar.gz -C "$HOME/"
    rm google-cloud-cli-darwin-arm.tar.gz
    echo "✅ gcloud SDK 설치 완료"
fi

GCLOUD_BIN="$GCLOUD_DIR/bin/gcloud"
PYTHON3_PATH=$(which python3)
echo "✅ gcloud CLI: $($GCLOUD_BIN --version 2>&1 | head -1)"

# 4. gcloud 로그인 (처음만)
echo ""
echo "🔐 Google Cloud 로그인..."
CLOUDSDK_PYTHON="$PYTHON3_PATH" $GCLOUD_BIN auth login --project=tk-automation-260328

# 5. SSH 키 생성 및 VM 접속 테스트
echo ""
echo "🔑 VM SSH 연결 테스트..."
CLOUDSDK_PYTHON="$PYTHON3_PATH" $GCLOUD_BIN compute ssh notion-worker \
    --zone=asia-northeast3-a \
    --project=tk-automation-260328 \
    --command="echo '✅ VM SSH 연결 성공'"

# 6. refresh_tokens.py 생성
echo ""
echo "📝 refresh_tokens.py 생성 중..."
cat > "$SCRIPT_DIR/refresh_tokens.py" << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""
노션 발행 시스템 토큰 자동 갱신 스크립트
- Chrome에서 네이버 쿠키 + 스티비 토큰 추출
- Google Cloud VM의 .env 파일에 SSH로 업데이트
- notion-worker 서비스 자동 재시작
"""
import json, os, subprocess, sys
from pathlib import Path
from datetime import datetime

# Google Cloud VM 설정
GCE_INSTANCE = "notion-worker"
GCE_ZONE = "asia-northeast3-a"
GCE_PROJECT = "tk-automation-260328"
GCE_ENV_FILE = "/home/kimbongsoo/notion-publisher/.env"
GCLOUD_BIN = str(Path.home() / "google-cloud-sdk/bin/gcloud")
PYTHON3_PATH = "/opt/homebrew/bin/python3"

LOG_FILE = Path(__file__).parent / "refresh.log"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def get_naver_cookie():
    """Chrome에서 네이버 NID_SES 쿠키 추출"""
    try:
        from pycookiecheat import chrome_cookies
    except ImportError:
        log("❌ pycookiecheat 미설치: pip3 install pycookiecheat")
        return None
    base = Path.home() / "Library/Application Support/Google/Chrome"
    for name in ["Default"] + [f"Profile {i}" for i in range(1, 20)]:
        cookie_file = base / name / "Cookies"
        if not cookie_file.exists():
            continue
        try:
            cookies = chrome_cookies("https://naver.com", cookie_file=str(cookie_file))
            nid_ses = cookies.get("NID_SES", "")
            if nid_ses:
                log(f"✅ 네이버 NID_SES 추출 완료 (프로필: {name})")
                return nid_ses
        except Exception:
            continue
    log("❌ 네이버 NID_SES 없음 (Chrome에서 naver.com 로그인 필요)")
    return None

def get_stibee_token():
    """Chrome localStorage에서 스티비 토큰 추출"""
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
            set stibeeTab to make new tab at end of tabs of front window
            set URL of stibeeTab to "https://stibee.com/dashboard"
            delay 4
        end if
        execute stibeeTab javascript "localStorage.getItem('satellizer_token') || localStorage.getItem('accessToken') || ''"
    end tell
    '''
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
        token = result.stdout.strip()
        if token and len(token) > 20:
            log("✅ 스티비 토큰 추출 완료")
            return token
        log("❌ 스티비 토큰 없음 (Chrome > 보기 > 개발자 > Apple Events 자바스크립트 허용 필요)")
        return None
    except Exception as e:
        log(f"❌ 스티비 토큰 오류: {e}")
        return None

def gce_ssh(command):
    """Google Cloud VM에 SSH 명령 실행"""
    return subprocess.run(
        [GCLOUD_BIN, "compute", "ssh", GCE_INSTANCE,
         f"--zone={GCE_ZONE}", f"--project={GCE_PROJECT}",
         f"--command={command}"],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "CLOUDSDK_PYTHON": PYTHON3_PATH}
    )

def update_gce_env(key, value):
    """Google Cloud VM의 .env 파일에서 해당 키를 업데이트"""
    cmd = f"grep -q '^{key}=' {GCE_ENV_FILE} && sed -i 's|^{key}=.*|{key}={value}|' {GCE_ENV_FILE} || echo '{key}={value}' >> {GCE_ENV_FILE}"
    try:
        result = gce_ssh(cmd)
        if result.returncode == 0:
            log(f"✅ GCE {key} 업데이트 완료")
            return True
        log(f"❌ GCE {key} 업데이트 실패: {result.stderr.strip()[:100]}")
        return False
    except Exception as e:
        log(f"❌ GCE 업데이트 오류: {e}")
        return False

def restart_gce_service():
    """Google Cloud VM의 notion-worker 서비스 재시작"""
    try:
        result = gce_ssh("sudo systemctl restart notion-worker")
        if result.returncode == 0:
            log("✅ notion-worker 서비스 재시작 완료")
            return True
        log(f"❌ 서비스 재시작 실패: {result.stderr.strip()[:100]}")
        return False
    except Exception as e:
        log(f"❌ 서비스 재시작 오류: {e}")
        return False

def main():
    log("=" * 40)
    log("토큰 자동 갱신 시작 (Google Cloud VM)")
    updated = 0

    nid_ses = get_naver_cookie()
    if nid_ses and update_gce_env("NAVER_NID_SES", nid_ses):
        updated += 1

    token = get_stibee_token()
    if token and update_gce_env("STIBEE_ACCESS_TOKEN", token):
        updated += 1

    if updated > 0:
        restart_gce_service()

    log(f"완료: {updated}/2 업데이트")
    log("=" * 40)

if __name__ == "__main__":
    main()
PYTHON_SCRIPT

# 7. launchd plist 생성 (Mac 시작 시 + 매주 월요일 9시)
echo ""
echo "⏰ launchd 등록 중..."

# 기존 등록 해제 (있을 경우)
launchctl unload "$PLIST_PATH" 2>/dev/null || true

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wkmg.notion-token-refresher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$SCRIPT_DIR/refresh_tokens.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key><integer>1</integer>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/launchd.log</string>
</dict>
</plist>
PLIST

launchctl load "$PLIST_PATH"

# 8. 즉시 테스트 실행
echo ""
echo "🧪 테스트 실행..."
python3 "$SCRIPT_DIR/refresh_tokens.py"

echo ""
echo "======================================"
echo "✅ 설치 완료!"
echo "   - Mac 켤 때마다 자동 실행"
echo "   - 매주 월요일 오전 9시 자동 실행"
echo "   - 로그: $SCRIPT_DIR/refresh.log"
echo "======================================"
echo ""
echo "⚠️  사전 조건:"
echo "   1. Chrome에서 naver.com 로그인 (로그인 상태 유지 체크)"
echo "   2. Chrome에서 stibee.com 로그인"
echo "   3. Chrome > 보기 > 개발자 > Apple Events의 자바스크립트 허용"
