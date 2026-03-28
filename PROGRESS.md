# 노션 자동 발행 시스템 - 작업 진행 기록

## 마지막 업데이트: 2026-03-25 05:00 KST

---

## 1. 전체 구조

```
노션(글 작성) → 발행요청 상태 변경 → 자동 발행 시스템 실행
                                      ├── 1. 네이버 블로그 (Playwright)
                                      ├── 2. 아임웹 홈페이지 (REST API)
                                      ├── 3. 페이스북 (Meta Graph API)
                                      └── 4. 스티비 뉴스레터 (내부 API) ✅
```

GitHub: https://github.com/bskim23/notion-publisher (private)
배포 대상: Railway (Hobby $5/월, 아직 미결제)

---

## 2. 플랫폼별 진행 상태

### ✅ 노션 (완료)
- 토큰: `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`
- DB: `4abca0c8ee634eb4ada3a19137394a83` (티끌 뉴스 발행 관리)
- 기능: DB 폴링(60초), 블록→HTML/텍스트 변환, 이미지 추출, 상태 업데이트
- 테스트: ✅ 연결 성공 확인

### ✅ 스티비 (내부 API 연동 완료, E2E 테스트 성공)

#### 핵심 발견 사항
1. **공식 API** (`api.stibee.com/v1`) = 구독자 관리만 가능 (이메일 발송 불가)
2. **내부 API** (`stibee.com/api/v1.0`) = 이메일 생성/발송 가능 (세션 토큰 필요)
3. 세션 토큰: 브라우저 localStorage의 `satellizer_token`
4. **인증 헤더**: `accessToken` (NOT `Authorization: Bearer`)
5. **MFA 활성화**: wkmg@wkmg.co.kr 계정에 SMS 2단계 인증이 켜져 있어 완전 자동 로그인 불가 → 세션 파일 캐시 방식으로 우회

#### 검증된 API 플로우 (2026-03-25 테스트 성공)
```
[인증] 헤더: accessToken = satellizer_token 값
       쿠키: 브라우저에서 수집한 쿠키 전달

[Step 0] POST /api/v1.0/emails/{소스이메일ID}/copy
         → 정수(새 이메일 ID) 직접 반환  ⚠️ JSON 객체 아님!
         ※ 소스: 3298304 (여백도 전략이 된다, templateId=10)

[Step 1] PUT /api/v1.0/emails/{newId}/step1
         Content-Type: application/json
         Body: {"listId": 438426, "listGroupIds": [], "listSegmentIds": [], "groupSegmentCondition": "or"}

[Step 2] PUT /api/v1.0/emails/{newId}/step2
         Body: {"isAb": false}

[Step 3] PUT /api/v1.0/emails/{newId}/step3
         Body: {"subjectA": "제목", "senderNameA": "티끌레터", "senderEmail": "wkmg@wkmg.co.kr"}
         ⚠️ senderNameA (NOT senderName)
         ⚠️ senderEmail은 스티비에 검증된 이메일만 가능 (news@wkmg.co.kr 불가)

[Step 4] PUT /api/v1.0/editor/{newId}/contents/html
         Content-Type: application/x-www-form-urlencoded  ⚠️ JSON 아님!
         Body: html=<URL인코딩된 HTML>
         ⚠️ param name = "html" (NOT "htmlContent", "content")

[발송]   POST /api/v1.0/emails/{newId}/reserve
         Content-Type: application/x-www-form-urlencoded  ⚠️ JSON 아님!
         Body: reservedTime=2026-03-25+04%3A28
         ⚠️ format = "YYYY-MM-DD HH:MM" (NOT ISO 8601)
         ※ 현재시간+1분 = 즉시발송
```

#### 실제 테스트 결과 (2026-03-25)
- **E2E 성공**: 이메일 3301089 → kbs 주소록(438426, 1명) 발송 완료
  - Step 1~4 모두 200 OK
  - 예약발송 200 OK → 04:28 KST 발송
  - 제목: [TEST] notion-publisher 자동발송
  - 발신자: WKMG 테스트 <wkmg@wkmg.co.kr>

#### 세션 관리 방식
- **파일 캐시**: `/tmp/stibee_session.json` (토큰 + 쿠키)
- **유효성 검증**: `GET /api/v1.0/accounts/me/role` 호출로 확인
- **갱신 방법**: Chrome remote debugging으로 수동 로그인 후 CDP로 토큰 추출
  ```bash
  # Chrome을 remote debugging으로 실행
  pkill -f "Google Chrome"
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=9222 --remote-allow-origins="*" \
    --user-data-dir="/tmp/chrome_debug_profile" --no-first-run &
  # → 스티비 로그인 + MFA 완료 → CDP로 토큰 추출 스크립트 실행
  ```
- **Playwright fallback**: MFA 없는 환경에서는 자동 로그인 가능

#### API 키 정보
- 공식 API 키 (WKMG-Auto): `ce201ebb738b...c6e5b` → 구독자 관리용
- 기존 API 키 (WKMG): `2cbede3ba91...da26` → 구독자 관리용

#### 주소록 목록
| ID | 이름 | 용도 |
|----|------|------|
| 438426 | kbs | 테스트용 (1명) |
| 471503 | 티끌레터 홍보용 | 실제 발송 (21,822명) |
| 466923 | 티끌 모아 실력! 티끌레터™ | 소스 이메일 템플릿용 (67명) |
| 478416 | 마케팅스파르타 전기수 | (68명) |

#### 티끌레터 HTML 템플릿 ✅ 분석 완료 (2026-03-25)
- 원본 이메일(3298304) HTML: 25,039자, 13개 블록 구조
- `GET /api/v1.0/editor/{emailId}/contents/html` 로 조회
- **고정 블록 7개**: 헤더 배너[0], 구분선[1,7,10], 액션 배너[8], 마무리[11], 푸터[12]
- **가변 블록 6개**: 날짜[2], 뉴스이미지[3], 본문1+링크[4], 중간이미지[5], 본문2[6], 실천포인트[9]
- `publishers/tikkeul_template.py` — `build_tikkeul_html()` 함수로 조립
- `formatters.py` — `format_for_stibee()` 가 템플릿 엔진 사용

### 🔶 네이버 블로그 (로그인 ✅, 에디터 ✅, 블로그 초기설정 필요)
- ID: wkmarketing / PW: wkppdx1125 / Blog ID: wkmarketing
- **로그인**: ✅ 성공 (추가인증 후 쿠키 59개 저장, 캐시 재사용 가능)
- **에디터 진입**: ✅ 성공 (Smart Editor 3 로드 확인)
- **제목/본문 입력**: ✅ 성공
- **발행**: ⚠️ 블로그 자체가 초기 설정 미완료 (아이디 설정 필요)
- 검증된 셀렉터 (SE3, 2026-03-25):
  - 제목: `.se-title-text` (NOT `.se-title-input`)
  - 본문: `Tab` 키로 이동
  - 발행: `[data-click-area="tpb.publish"]` (NOT `button:has-text("발행")`)
  - 이미지: `.se-image-toolbar-button`
  - 임시저장 팝업: `.se-popup-button-cancel`
  - 도움말 패널: `.se-help-panel-close-button`
- **TODO**: 블로그 초기 설정 완료 후 발행 재테스트 필요

### ❌ 아임웹 (미설정)
- API 키/시크릿 미입력
- 게시판 코드 미확인

### ❌ 페이스북 (미설정)
- Page ID / Access Token 미입력

---

## 3. 코드 파일 목록

```
notion-publisher/
├── .env                    # 환경변수 (노션✅, 네이버✅, 스티비✅, 아임웹❌, FB❌)
├── .gitignore
├── config.py               # 환경변수 로딩, 상태 상수
├── notion_fetcher.py       # 노션 DB 폴링, 블록→HTML 변환
├── formatters.py           # 플랫폼별 포매터
├── main.py                 # 메인 (폴링/원샷/테스트 모드)
├── publishers/
│   ├── naver_blog.py       # ✅ Playwright 네이버 자동화 (셀렉터 검증 완료)
│   ├── tikkeul_template.py # ✅ 티끌레터 HTML 템플릿 엔진 (13블록 조립)
│   ├── imweb_publisher.py  # 아임웹 REST API
│   ├── facebook_publisher.py # Meta Graph API
│   └── stibee_publisher.py # ✅ 내부 API 연동 완료 (세션 캐시 + E2E 검증)
├── railway.toml
├── nixpacks.toml
├── Procfile
└── requirements.txt
```

---

## 4. 다음 단계 (우선순위)

### 즉시 해야 할 것
1. **~~stibee_publisher.py 재작성~~** ✅ 완료 (2026-03-25)
   - 세션 파일 캐시 → Playwright fallback
   - 검증된 API 사양 적용 (accessToken 헤더, senderNameA, html param 등)
   - kbs 주소록 E2E 테스트 성공

2. **~~티끌레터 HTML 템플릿 분석~~** ✅ 완료 (2026-03-25)
   - 13블록 구조 분석, 고정 7개 + 가변 6개 식별
   - `tikkeul_template.py` 엔진 구현 + 12개 체크포인트 전체 통과

3. **~~네이버 블로그 실제 테스트~~** 🔶 부분 완료 (2026-03-25)
   - 로그인 ✅, 에디터 ✅, 제목/본문 입력 ✅
   - 발행은 블로그 초기 설정 미완료로 확인 불가 → 설정 완료 후 재테스트

### 나중에 할 것
4. 아임웹 API 키 설정
5. 페이스북 API 토큰 설정
6. Railway 배포 ($5/월 결제 후)
7. 엔드투엔드 테스트 (노션 글 → 4개 플랫폼 동시 발행)
8. kbs 테스트 완료 후 → 실제 주소록(471503, 21,822명)으로 전환
9. 세션 토큰 자동 갱신 스케줄 (Railway cron 또는 별도 job)

---

## 5. 주의사항

- 스티비 인증 헤더: **`accessToken`** (NOT `Authorization: Bearer`)
- 스티비 Step 3 발신자명: **`senderNameA`** (NOT `senderName`)
- 스티비 Step 4 HTML param: **`html`** (NOT `htmlContent`)
- 스티비 reserve 시간 형식: **`YYYY-MM-DD HH:MM`** (NOT ISO 8601)
- 스티비 `reserve`, `editor/.../html`: **반드시 form-encoded** (JSON 보내면 400)
- 스티비 copy 응답: **정수 직접 반환** (JSON 객체 아님)
- 스티비 MFA: SMS 2단계 활성화 → 완전 자동 로그인 불가, 세션 파일 캐시 필수
- 스티비 senderEmail: 검증된 이메일만 가능 (wkmg@wkmg.co.kr ✅, news@wkmg.co.kr ❌)
- 네이버 블로그: Playwright headless 모드에서 anti-detection 헤더 필요
- Railway 배포 시 Chrome/Chromium 설치 위해 `nixpacks.toml` 필요
