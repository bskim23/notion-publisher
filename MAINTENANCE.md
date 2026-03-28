# 노션 자동 발행 시스템 — 유지보수 & 사용자 매뉴얼

## 1. 시스템 개요

노션 DB에서 상태를 변경하면 4개 채널에 자동 발행하는 시스템.

```
노션 (상태 변경) → Mac Mini (워커) → 네이버블로그 / 스티비 / 아임웹 / 페이스북
```

**실행 위치 (Mac Mini)**: `~/Library/Mobile Documents/com~apple~CloudDocs/Code/notion-publisher-deploy/`
**실행 방식**: 수동 실행 (`source venv/bin/activate && python3 main.py`)
**GitHub**: `github.com/bskim23/notion-publisher`

---

## 2. 사용자 매뉴얼

### 발행 방법

1. 노션 DB에서 글 작성
2. `발행채널` 선택 (네이버블로그, 스티비, 아임웹, 페이스북)
3. `발행 상태`를 **테스트요청** 또는 **실발행요청**으로 변경
4. 워커가 자동 감지하여 발행 처리

### 테스트요청 vs 실발행요청

| 항목 | 테스트요청 | 실발행요청 |
|------|-----------|-----------|
| 네이버 | 동일 (실제 발행) | 동일 |
| 아임웹 | 동일 (실제 발행) | 동일 |
| 스티비 | kBS에게 익일 08:30 발송 | 전체 구독자에게 다음 근무일 08:30 발송 |
| 페이스북 | Wktest 페이지 | WK 마케팅그룹 페이지 |

> 스티비 실발행은 토/일/공휴일을 건너뛰고 다음 근무일에 발송됩니다.

### 발행 상태 흐름

```
테스트요청 → 처리중 → 테스트완료 (또는 일부실패/발행실패)
실발행요청 → 처리중 → 발행완료 (또는 일부실패/발행실패)
```

### 노션 DB 속성

| 속성명 | 용도 | 자동/수동 |
|--------|------|----------|
| 제목 | 글 제목 | 수동 입력 |
| 발행 상태 | 트리거 & 결과 | 수동 → 자동 |
| 발행모드 | 테스트/실발행 | 자동 (상태에서 추론) |
| 발행채널 | 대상 채널 선택 | 수동 (미선택 시 전체) |
| 네이버URL | 발행된 블로그 URL | 자동 |
| 아임웹URL | 발행된 아임웹 URL | 자동 |
| 스티비캠페인ID | 스티비 이메일 ID | 자동 |
| 예약발송시각 | 스티비 예약 시각 | 자동 |
| 에러로그 | 실패 시 원인 | 자동 |
| fb_quote | 페이스북 인용문 (선택) | 수동 |

### 워커 폴링 스케줄

| 시간대 | 간격 |
|--------|------|
| 오전 10시 ~ 오후 6시 | 10분 |
| 오후 6시 ~ 오후 10시 | 1시간 |
| 오후 10시 ~ 오전 10시 | 중지 (자동 대기) |

### 수동 실행

```bash
# 한 번만 확인하고 종료
python3 main.py --once

# 특정 페이지만 처리
python3 main.py --page-id <노션페이지ID>

# 모드 강제 지정
python3 main.py --page-id <ID> --mode test
```

---

## 3. 아키텍처 (Claude 참고용)

### 파일 구조

```
notion-publisher-deploy/
├── main.py                  # 오케스트레이터 (폴링, 채널 분기, 노션 결과 기록)
├── config.py                # 환경변수 로드, 상수 정의
├── notion_fetcher.py        # 노션 API (페이지 조회, 블록→HTML 변환, 속성 업데이트)
├── formatters.py            # 채널별 콘텐츠 포맷터 (HTML 파싱, 섹션 분리, 태그 생성)
├── requirements.txt         # 의존성: requests, playwright, pycookiecheat, schedule
├── .env                     # 환경변수 (토큰, 비밀번호 등)
├── assets/                  # 정적 에셋 (푸터 배너 이미지 등)
└── publishers/
    ├── naver_blog.py        # 네이버 블로그 (Playwright + Chrome 쿠키)
    ├── stibee_publisher.py  # 스티비 뉴스레터 (내부 API + Chrome LevelDB 토큰)
    ├── imweb_publisher.py   # 아임웹 (Playwright + ID/PW 로그인)
    ├── facebook_publisher.py # 페이스북 (Graph API, 무기한 Page Token)
    └── tikkeul_template.py  # 스티비 HTML 이메일 템플릿 + 배너/링크 상수
```

### 실행 흐름

```
main.py: check_and_publish()
  → notion_fetcher: get_pages_by_status("테스트요청" | "실발행요청")
  → 페이지별 process_page():
      1. notion_fetcher: get_page_blocks() → blocks_to_html()
      2. formatters: format_for_naver/imweb/stibee()
      3. 병렬실행: naver_blog + stibee (ThreadPoolExecutor)
      4. 순차실행: facebook (네이버 URL 필요) → imweb
      5. notion_fetcher: update_page_properties() (결과 기록)
```

### 채널별 인증 방식

| 채널 | 인증 | 토큰 위치 | 만료 |
|------|------|----------|------|
| 네이버 | Chrome 쿠키 (pycookiecheat) | Mac Mini Chrome | 로그아웃 시 |
| 스티비 | Chrome LevelDB (satellizer_token) | Mac Mini Chrome | 로그아웃 시 |
| 아임웹 | ID/PW 로그인 (Playwright) | .env | 비밀번호 변경 시 |
| 페이스북 | Page Access Token | .env | 무기한 |

### 네이버 블로그 — 섹션 삽입 순서 (티끌레터 레이아웃)

```
[0] 기사 대표 이미지   ← 첫 번째 이미지 = 자동으로 대표 이미지 선택
[1] 날짜 + 구분선 + 본문 전반부 + 원문기사 링크
[2] 헤더 배너
[3] 본문 후반부
[4] 액션 배너
[5] 팁 (블릿 포인트)
[6] 푸터 배너 (로컬 파일)
[7] 구독 신청 하이퍼링크
```

> **대표 이미지 원리**: 네이버 SE3에서 첫 번째로 삽입된 이미지가 자동으로 대표(썸네일)가 됨.
> 기사 고유 이미지를 맨 앞에 삽입하여 대표 이미지로 자동 선택되게 함.
> (이전에는 헤더 배너가 0번이었으나 대표 이미지 문제로 순서 변경함)

### 네이버 블로그 — 발행 패널 흐름

```
1. [data-click-area="tpb.publish"] 클릭 → 발행 패널 열기 (4초 대기)
2. _ensure_panel_open()   ← 패널 닫힘 감지 시 재오픈
3. _select_category()     ← Plan A~D fallback 구조
4. _ensure_panel_open()   ← 카테고리 선택 후 패널 닫힘 대비
5. _input_tags()          ← JS 우선, Playwright fallback
6. 최종 발행 버튼 클릭     ← 후보 A~H 순서대로 시도
```

#### 카테고리 선택 (Plan A~D)

| 플랜 | 방법 | 비고 |
|------|------|------|
| A | `[data-click-area="tpb*i.category"]` 클릭 → visible li에서 `endsWith(카테고리명)` | li 텍스트가 `'하위 카테고리티끌레터™'` 형태 |
| B | JS: `data-category-no` 속성으로 탐색 | categoryNo=63 (티끌레터™) |
| C | JS: `<select>` option value 직접 설정 | |
| D | JS: visible li/option에서 endsWith 매칭 (SE 에디터 내부 요소 제외) | |

#### 태그 입력

| 전략 | 방법 |
|------|------|
| JS (우선) | `input[placeholder*="태그"]` 또는 `className.includes('tag')` 탐색 → nativeValueSetter + Enter 키 |
| Playwright (fallback) | `input[placeholder*="태그"]`, `[class*="tag"] input` 등으로 locator → fill + Enter |

> 태그 input의 CSS module 클래스: `tag_input__rvUB5` (해시 변경 가능)
> 발행 패널이 닫혀 있으면 태그 input이 invisible → `_ensure_panel_open()` 필수

#### 최종 발행 버튼 (후보 순서)

| 후보 | 셀렉터 | 비고 |
|------|--------|------|
| A | `[data-click-area="tpb*i.publish"]` | 확인된 최종 발행 버튼 |
| B | `[data-click-area]` (exclusion 제외) + "발행" 텍스트 | |
| G | `button[class*="btn_publish"]` 등 클래스명 | |
| H | JS: visible 버튼 중 text === "발행" | |

> **주의**: `tpb*t.schedule`은 "예약 발행" 버튼이므로 반드시 제외 (EXCLUDED_DCA).
> `tpb.publish`는 패널 열기 버튼이므로 최종 발행과 혼동 금지.

#### _ensure_panel_open()

카테고리 선택이나 썸네일 클릭 후 발행 패널이 닫히는 현상 대응.
EXCLUDED_DCA(`tpb.publish`, `tpb*t.schedule`)를 제외한 `data-click-area` 버튼 중 "발행" 텍스트가 있고 visible한 것이 있으면 패널 열림으로 판단. 없으면 `tpb.publish` 재클릭.

### 핵심 API 사양

**스티비 (내부 API — stibee.com/api/v1.0)**
- 인증 헤더: `accessToken` (NOT `Authorization: Bearer`)
- step3 발신자명: `senderNameA` (NOT `senderName`)
- step4 HTML: form-encoded, param `html`
- reserve: form-encoded, param `reservedTime`, format `YYYY-MM-DD HH:MM`
- copy 응답: 정수 직접 반환 (JSON 객체 아님)

**네이버 SE3 에디터**
- HTML 삽입: ClipboardEvent paste 시뮬레이션 (DataTransfer)
- execCommand('insertHTML')은 SE3에서 무시됨
- AppKit/NSPasteboard는 headless에서 작동 안 함
- 제목: `.se-title-text`, 발행 패널 열기: `[data-click-area="tpb.publish"]`
- 최종 발행: `[data-click-area="tpb*i.publish"]`
- 카테고리 드롭다운: `[data-click-area="tpb*i.category"]`
- CSS module 해시 클래스: `tag_input__rvUB5`, `layer_content_set_publish__KDvaV` 등 (변경 가능)
- 이미지 컴포넌트: `.se-component.se-image`

---

## 4. 트러블슈팅

### 네이버: 텍스트 없이 발행됨

**원인**: HTML 삽입 실패. SE3 에디터가 paste를 무시했거나, 포커스가 본문이 아닌 곳에 있음.
**확인**: 터미널 로그에서 `HTML paste 이벤트 발송` 후 `본문 확인: X자 삽입됨` 확인.
**조치**:
- `_paste_html_to_editor()` 의 3단계 전략 확인 (paste event → clipboard API → plain text)
- `_focus_body()` 가 본문 영역을 제대로 찾고 있는지 확인
- SE3 DOM 구조가 변경되었을 수 있음 → 셀렉터 업데이트 필요

### 네이버: 로그인 실패 / 쿠키 만료

**원인**: Mac Mini Chrome에서 네이버 로그아웃됨.
**조치**: Mac Mini Chrome에서 naver.com 로그인. 자동으로 pycookiecheat가 쿠키를 읽음.
**확인**: `_get_naver_cookies()` → `✅ 네이버 쿠키 발견 (Chrome/Profile X)` 출력 확인.

### 네이버: 카테고리 선택 실패 (엉뚱한 카테고리에 발행)

**원인**: Plan A~D 모두 실패했거나, SE3 에디터 본문의 "티끌레터™" 텍스트를 클릭함.
**확인**: 로그에서 `카테고리 선택 완료 (text): 티끌레터™` 확인.
**조치**:
- `[data-click-area="tpb*i.category"]` 셀렉터가 유효한지 확인
- li 텍스트가 `하위 카테고리티끌레터™` 형태이므로 exact match 아닌 endsWith 사용 확인
- `NAVER_CATEGORY_NO` 환경변수 (기본값 63) 확인

### 네이버: 태그 입력 실패

**원인**: 발행 패널이 닫혀 있어 태그 input이 invisible하거나, CSS module 해시 클래스 변경.
**확인**: 로그에서 `태그 입력 완료` 또는 `⚠️ JS 태그 입력 실패` 확인.
**조치**:
- `_ensure_panel_open()` 이 태그 입력 전에 호출되는지 확인
- 사용 가능한 input 로그에서 `tag` 포함 input 존재 여부 확인
- CSS module 해시가 변경됐으면 셀렉터 업데이트

### 네이버: 잘못된 발행 버튼 클릭 (예약 발행)

**원인**: 발행 패널이 닫힌 상태에서 `tpb*t.schedule` ("예약 발행 N건") 버튼을 최종 발행으로 인식.
**확인**: 로그에서 `최종 발행 클릭 (A: tpb*i.publish)` 확인. 다른 후보가 클릭됐으면 문제.
**조치**:
- `_ensure_panel_open()` 이 최종 발행 전에 패널 열림을 보장하는지 확인
- `EXCLUDED_DCA`에 `tpb*t.schedule` 포함 확인

### 네이버: 대표 이미지가 헤더 배너로 설정됨

**원인**: 첫 번째 삽입 이미지가 자동으로 대표가 되므로, 헤더 배너가 먼저 삽입되면 대표로 선택됨.
**조치**: `formatters.py`의 `format_for_naver_blog()` 섹션 순서에서 기사 이미지가 [0]번인지 확인.
현재 순서: `기사 이미지[0] → 본문1[1] → 헤더 배너[2] → ...`

### 스티비: 세션 획득 실패

**원인**: Chrome에서 stibee.com 로그아웃됨 또는 LevelDB에서 토큰을 못 찾음.
**조치**: Mac Mini Chrome에서 stibee.com 로그인.
**확인**: `_get_stibee_token_from_chrome()` → `✅ 스티비 토큰 로드` 출력 확인.
**fallback**: `.env`에 `STIBEE_ACCESS_TOKEN=<토큰>` 직접 설정.

### 스티비: 토큰은 있는데 API 실패

**원인**: 토큰 만료 (stibee.com 재로그인 필요) 또는 API 사양 변경.
**확인**: `_get_stibee_session()` 에서 `/accounts/me/role` 검증 결과 확인.
**조치**: Chrome에서 stibee.com 재로그인.

### 페이스북: 토큰 만료

**현재 토큰**: 무기한 Page Access Token (만료 안 됨).
**만약 에러 발생 시**: Meta 개발자 콘솔에서 재발급.
1. Graph API Explorer에서 short-lived token 발급
2. Long-lived user token 교환: `GET /oauth/access_token?grant_type=fb_exchange_token&client_id={앱ID}&client_secret={앱시크릿}&fb_exchange_token={토큰}`
3. Page token 발급: `GET /me/accounts?access_token={long_lived_token}`
4. `.env`의 `FACEBOOK_ACCESS_TOKEN` 업데이트

### 아임웹: 로그인 실패

**원인**: 비밀번호 변경 또는 UI 변경.
**조치**: `.env`의 `IMWEB_ID`, `IMWEB_PW` 확인.

### 워커: ModuleNotFoundError

**원인**: venv가 깨짐 (경로 이동 후 등).
**조치**:
```bash
cd ~/Library/Mobile\ Documents/com\~apple\~CloudDocs/Code/notion-publisher-deploy
rm -rf venv
python3.13 -m venv venv       # 반드시 python3.13 (python3은 3.9이므로 문법 에러 발생)
source venv/bin/activate
pip install greenlet==3.1.1   # 먼저 설치 (빌드 실패 방지)
pip install requests==2.31.0 python-dotenv==1.0.1 schedule==1.2.1
pip install --no-deps playwright==1.49.1 pyee==12.0.0
pip install cryptography
playwright install chromium
```
> **주의**: `pip install -r requirements.txt`는 greenlet 빌드 실패 발생.
> 위 순서대로 개별 설치해야 함. `python3`은 3.9이므로 반드시 `python3.13` 사용.

### 워커: "지원하지 않는 노션 속성 업데이트"

**원인**: `update_page_properties()`에 등록되지 않은 속성명.
**조치**: `notion_fetcher.py`의 `update_page_properties()` 함수에 해당 속성 처리 추가.

### 예약발송시각이 이상한 시간으로 표시

**원인**: 타임존 누락. 노션 date 필드는 타임존 없으면 UTC로 해석.
**확인**: ISO 형식에 `+09:00`이 포함되어 있는지 확인 (예: `2026-03-29T08:30:00+09:00`).

---

## 5. 연례 유지보수

### 공휴일 업데이트 (매년 초)

`main.py`의 `KR_HOLIDAYS` 딕셔너리에 새해 공휴일 추가.
현재 2026~2027년까지 입력됨. 대체공휴일 포함 필수.

### Chrome 프로필 변경 시

네이버/스티비 쿠키는 Chrome 프로필에서 자동 탐색하므로 별도 설정 불필요.
단, Chrome 자체를 삭제/재설치하면 재로그인 필요.

### 네이버 SE3 에디터 업데이트 시

CSS module 해시 클래스명(`tag_input__xxxxx`, `layer_content_set_publish__xxxxx` 등)이 변경될 수 있음.
`data-click-area` 속성 기반 셀렉터(`tpb.publish`, `tpb*i.publish`, `tpb*i.category`)는 비교적 안정적.
에디터 업데이트 후 발행 실패 시 DevTools로 셀렉터 확인 필요.

---

## 6. 환경변수 (.env)

```
# 필수
NOTION_TOKEN=secret_xxx
NOTION_DATABASE_ID=xxx-xxx-xxx

# 네이버 (쿠키는 Chrome에서 자동 추출, BLOG_ID만 필수)
NAVER_BLOG_ID=wkmarketing
NAVER_CATEGORY_NO=63              # 티끌레터™ 카테고리 번호 (기본값 63)

# 아임웹
IMWEB_ID=xxx
IMWEB_PW=xxx

# 페이스북
FACEBOOK_PAGE_ID=179944182094039
FACEBOOK_ACCESS_TOKEN=EAAVLZA...
FACEBOOK_TEST_PAGE_ID=1083295568194960
FACEBOOK_TEST_ACCESS_TOKEN=EAAVLZA...

# 스티비 (토큰은 Chrome에서 자동 추출)
STIBEE_ADDRESS_BOOK_ID=438426
STIBEE_TEST_ADDRESS_BOOK_ID=438426
STIBEE_PROD_ADDRESS_BOOK_ID=471503
STIBEE_SENDER_EMAIL=wkmg@wkmg.co.kr
STIBEE_SENDER_NAME=티끌레터

# 시스템
HEADLESS=true
```

---

## 7. Mac Mini 관리

### 필수 조건
- Chrome에 **네이버**, **스티비** 로그인 유지
- Chrome 쿠키 삭제 금지
- Terminal에 **전체 디스크 접근 권한** 부여 (시스템 환경설정 → 개인 정보 보호 → 전체 디스크 접근 권한)

### 재부팅 후

launchd 미설정 상태이므로 수동 시작 필요:
```bash
cd ~/Library/Mobile\ Documents/com\~apple\~CloudDocs/Code/notion-publisher-deploy
source venv/bin/activate
python3 main.py
```

### 코드 업데이트 (iCloud 자동 동기화됨)
```bash
cd ~/Library/Mobile\ Documents/com\~apple\~CloudDocs/Code/notion-publisher-deploy
source venv/bin/activate
python3 main.py
```
