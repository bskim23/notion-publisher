# 노션 DB 설정 가이드

## 1단계: 노션 데이터베이스 속성 설정

아래 속성을 노션 DB에 추가해주세요.

| 속성 이름   | 타입    | 옵션 값                                              |
|------------|---------|-----------------------------------------------------|
| 이름       | 제목    | (기본값)                                            |
| 발행 상태  | 선택    | 작성중 / **발행요청** / 처리중 / 발행완료 / 일부실패 |
| 발행일시   | 날짜    | 자동 기록용                                         |

> **"발행요청"** 이 트리거입니다.
> 글을 다 쓴 후 발행 상태를 **발행요청** 으로 바꾸면 자동으로 발행됩니다.

---

## 2단계: 노션 인테그레이션 생성

1. https://www.notion.so/my-integrations 접속
2. **"새 인테그레이션"** 클릭
3. 이름: `자동발행봇`
4. 권한: **콘텐츠 읽기 / 콘텐츠 업데이트** 체크
5. **토큰(secret_xxx...)** 복사 → `.env`의 `NOTION_TOKEN`에 입력

## 3단계: DB에 인테그레이션 연결

1. 노션 데이터베이스 페이지 열기
2. 우측 상단 **⋯** → **연결** → 생성한 인테그레이션 추가

## 4단계: 데이터베이스 ID 확인

노션 DB URL에서 ID를 복사합니다.

```
https://www.notion.so/내_워크스페이스/[이 부분이 DB ID]?v=...
```

---

## 페이스북 액세스 토큰 발급 방법

1. https://developers.facebook.com/tools/explorer/ 접속
2. 앱 선택 (없으면 새로 생성)
3. **Generate Access Token** 클릭
4. 권한 추가: `pages_manage_posts`, `pages_read_engagement`
5. 페이지 액세스 토큰으로 교환
6. 장기 토큰 발급 (기본 단기 토큰은 1~2시간 만료)

> 💡 장기 토큰 발급:
> `GET https://graph.facebook.com/v18.0/oauth/access_token?grant_type=fb_exchange_token&client_id={APP_ID}&client_secret={APP_SECRET}&fb_exchange_token={SHORT_TOKEN}`

---

## 스티비 API 키 발급

1. 스티비 로그인 → **설정** (우측 상단)
2. **API 키** 탭 → 새 키 생성
3. 주소록 ID: 스티비 → 주소록 → 해당 주소록 클릭 → URL의 숫자

---

## 실행 방법

```bash
# 1. 설치
pip install -r requirements.txt
playwright install chromium

# 2. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 API 키 입력

# 3. 연결 테스트
python main.py --test

# 4-A. 자동 실행 (60초마다 노션 감지)
python main.py

# 4-B. 수동 1회 실행
python main.py --once
```
