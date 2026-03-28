"""
설정 파일 - 환경변수에서 API 키와 노션/발행 상태 상수를 로드합니다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── 노션 ──────────────────────────────────
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")

# ── 네이버 블로그 (브라우저 자동화) ──────────
NAVER_ID = os.getenv("NAVER_ID", "")
NAVER_PW = os.getenv("NAVER_PW", "")
NAVER_BLOG_ID = os.getenv("NAVER_BLOG_ID", "")

# ── 아임웹 (브라우저 자동화) ────────────────
IMWEB_API_KEY = os.getenv("IMWEB_API_KEY", "")
IMWEB_API_SECRET = os.getenv("IMWEB_API_SECRET", "")
IMWEB_BOARD_CODE = os.getenv("IMWEB_BOARD_CODE", "")
IMWEB_ID = os.getenv("IMWEB_ID", "")
IMWEB_PW = os.getenv("IMWEB_PW", "")

# ── 페이스북 ───────────────────────────────
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
FACEBOOK_TEST_PAGE_ID = os.getenv("FACEBOOK_TEST_PAGE_ID", "")
FACEBOOK_TEST_ACCESS_TOKEN = os.getenv("FACEBOOK_TEST_ACCESS_TOKEN", "")

# ── 스티비 ────────────────────────────────
STIBEE_API_KEY = os.getenv("STIBEE_API_KEY", "")
STIBEE_ADDRESS_BOOK_ID = os.getenv("STIBEE_ADDRESS_BOOK_ID", "")
STIBEE_TEST_ADDRESS_BOOK_ID = os.getenv("STIBEE_TEST_ADDRESS_BOOK_ID", STIBEE_ADDRESS_BOOK_ID)
STIBEE_PROD_ADDRESS_BOOK_ID = os.getenv("STIBEE_PROD_ADDRESS_BOOK_ID", STIBEE_ADDRESS_BOOK_ID)
STIBEE_SENDER_EMAIL = os.getenv("STIBEE_SENDER_EMAIL", "")
STIBEE_SENDER_NAME = os.getenv("STIBEE_SENDER_NAME", "")
STIBEE_LOGIN_EMAIL = os.getenv("STIBEE_LOGIN_EMAIL", "")
STIBEE_LOGIN_PASSWORD = os.getenv("STIBEE_LOGIN_PASSWORD", "")

# ── 시스템 설정 ────────────────────────────
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL", "60"))
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")

# 노션 속성명
STATUS_PROPERTY = "발행 상태"
MODE_PROPERTY = "발행모드"
CHANNELS_PROPERTY = "발행채널"
NAVER_URL_PROPERTY = "네이버URL"
IMWEB_URL_PROPERTY = "아임웹URL"
STIBEE_CAMPAIGN_ID_PROPERTY = "스티비캠페인ID"
RESERVED_AT_PROPERTY = "예약발송시각"
ERROR_LOG_PROPERTY = "에러로그"
REVIEWER_PROPERTY = "검수자"
TEST_CONFIRMED_PROPERTY = "테스트확인"
FB_QUOTE_PROPERTY = "fb_quote"

# 노션 발행 상태
STATUS_DRAFT = "작성중"
STATUS_REVIEWED = "검수완료"
STATUS_TEST_REQUEST = "테스트요청"
STATUS_TEST_DONE = "테스트완료"
STATUS_PROD_REQUEST = "실발행요청"
STATUS_PROCESSING = "처리중"
STATUS_DONE = "발행완료"
STATUS_PARTIAL = "일부실패"
STATUS_FAILED = "발행실패"

# 모드
MODE_TEST = "테스트"
MODE_PROD = "실발행"

# 제목 필드명
TITLE_PROPERTY = "제목"

# 스티비 예약 발송 기본 시각
STIBEE_PROD_SEND_HOUR = int(os.getenv("STIBEE_PROD_SEND_HOUR", "8"))
STIBEE_PROD_SEND_MINUTE = int(os.getenv("STIBEE_PROD_SEND_MINUTE", "30"))


def validate_config() -> bool:
    """필수 환경변수가 설정됐는지 확인"""
    missing = []
    if not NOTION_TOKEN:
        missing.append("NOTION_TOKEN")
    if not NOTION_DATABASE_ID:
        missing.append("NOTION_DATABASE_ID")

    if missing:
        print("❌ 다음 환경변수가 .env 파일에 없습니다:")
        for m in missing:
            print(f"   - {m}")
        return False
    return True
