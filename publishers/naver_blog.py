"""
네이버 블로그 자동 게시 모듈
공식 API가 막혀 있어 Playwright(브라우저 자동화)로 구현

검증된 셀렉터 (2026-03-25, Smart Editor 3):
  - 제목: .se-title-text
  - 본문: Tab 키로 이동 후 execCommand('insertHTML') 사용
  - 발행 버튼: [data-click-area="tpb.publish"]
  - 이미지: .se-image-toolbar-button
  - 임시저장 팝업: .se-popup-button-cancel
  - 도움말 패널: .se-help-panel-close-button

주의사항:
  - 글쓰기 진입 시 "임시저장 복구" 팝업이 뜰 수 있음 → 취소 처리 필요
  - 도움말 패널이 발행 버튼을 가릴 수 있음 → 닫기 처리 필요
  - 세션 쿠키 캐시로 로그인 횟수 최소화
"""
import os
import re
import subprocess
import time
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import NAVER_ID, NAVER_PW, NAVER_BLOG_ID


# ── 상수 ──────────────────────────────────────────────
LOGIN_URL = "https://nid.naver.com/nidlogin.login"
WRITE_URL = f"https://blog.naver.com/PostWriteForm.naver?blogId={NAVER_BLOG_ID}"
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")

# 티끌레터™ 카테고리 번호 (categoryNo=63)
TIKKEUL_CATEGORY_NO = int(os.getenv("NAVER_CATEGORY_NO", "63"))


# ── 세션 관리 ──────────────────────────────────────────

def _decrypt_chrome_cookie(encrypted: bytes, key: bytes) -> str:
    """Chrome 암호화 쿠키 복호화 (macOS AES-128-CBC)"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    # v10/v20 prefix (3 bytes) 제거
    if encrypted[:3] in (b"v10", b"v20"):
        encrypted = encrypted[3:]
    iv = b" " * 16
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted) + decryptor.finalize()
    # PKCS7 padding 제거
    pad_len = decrypted[-1]
    if 1 <= pad_len <= 16 and decrypted[-pad_len:] == bytes([pad_len]) * pad_len:
        decrypted = decrypted[:-pad_len]
    return decrypted.decode("utf-8")


def _get_chrome_decrypt_key() -> bytes:
    """macOS Keychain에서 Chrome Safe Storage 키 → AES 키 파생"""
    import hashlib
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
        capture_output=True, text=True, timeout=5
    )
    password = result.stdout.strip()
    if not password:
        raise RuntimeError("Chrome Safe Storage 키를 Keychain에서 찾을 수 없음")
    return hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), b"saltysalt", 1003, dklen=16)


def _get_naver_cookies() -> list | None:
    """
    네이버 세션 쿠키를 가져옵니다.
    우선순위: ① Chrome SQLite 직접 읽기+복호화 → ② 환경변수 fallback
    """
    # 전략 1: pycookiecheat로 Chrome 쿠키 직접 읽기
    try:
        from pycookiecheat import chrome_cookies
        chrome_dir = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        profiles = sorted([p.name for p in chrome_dir.iterdir()
                           if p.is_dir() and p.name.startswith("Profile")] + ["Default"])
        for profile in profiles:
            cookie_path = chrome_dir / profile / "Cookies"
            if not cookie_path.exists():
                continue
            try:
                raw = chrome_cookies("https://naver.com", cookie_file=str(cookie_path))
                if raw.get("NID_SES"):
                    cookies = [{"name": k, "value": v, "domain": ".naver.com", "path": "/"}
                               for k, v in raw.items()]
                    print(f"  ✅ 네이버 쿠키 발견 (Chrome/{profile}, {len(cookies)}개)")
                    return cookies
            except Exception as e:
                print(f"  ⚠️ Chrome/{profile} 쿠키 읽기 실패: {e}")
                continue
        print("  ⚠️ Chrome에 NID_SES 없음 (네이버 로그인 확인)")
    except Exception as e:
        print(f"  ⚠️ Chrome 쿠키 읽기 실패: {e}")

    # 전략 2: 환경변수 fallback
    cookies_json = os.getenv("NAVER_COOKIES_JSON", "")
    if cookies_json:
        try:
            import json as _json
            cookies = _json.loads(cookies_json)
            print(f"  ✅ 네이버 쿠키 로드 (JSON, {len(cookies)}개)")
            return cookies
        except Exception as e:
            print(f"  ⚠️ NAVER_COOKIES_JSON 파싱 오류: {e}")

    nid_ses = os.getenv("NAVER_NID_SES", "")
    nid_aut = os.getenv("NAVER_NID_AUT", "")
    if nid_ses:
        cookies = [{"name": "NID_SES", "value": nid_ses, "domain": ".naver.com", "path": "/"}]
        if nid_aut:
            cookies.append({"name": "NID_AUT", "value": nid_aut, "domain": ".naver.com", "path": "/"})
        print(f"  ✅ 네이버 쿠키 로드 (env, NID_SES{'+ NID_AUT' if nid_aut else ''})")
        return cookies

    print("  ❌ 네이버 쿠키 없음 (Chrome 로그인 또는 NAVER_NID_SES 설정 필요)")
    return None


# ── 에디터 조작 ────────────────────────────────────────

def _dismiss_popups(page) -> None:
    """글쓰기 페이지의 팝업/오버레이 닫기"""
    try:
        cancel = page.locator(".se-popup-button-cancel")
        if cancel.count() > 0 and cancel.first.is_visible(timeout=2000):
            cancel.first.click()
            time.sleep(1)
    except PWTimeout:
        pass

    try:
        help_close = page.locator(".se-help-panel-close-button")
        if help_close.count() > 0:
            help_close.first.click(force=True)
            time.sleep(1)
    except Exception:
        pass

    page.keyboard.press("Escape")
    time.sleep(0.5)


def _select_category(page, category: str, category_no: int = 0) -> None:
    """발행 패널에서 카테고리 선택. A→B→C→D 순서로 시도."""
    time.sleep(1.5)

    # ── 드롭다운 열기 (공통 사전 단계) ─────────────────
    dropdown_opened = False
    # A-0: data-click-area로 직접 열기 (확인된 값)
    for dca in ["tpb*i.category"]:
        try:
            btn = page.locator(f'[data-click-area="{dca}"]').first
            if btn.is_visible(timeout=1500):
                btn.click(force=True)
                time.sleep(1.5)
                print(f"    카테고리 드롭다운 열림 (dca={dca})")
                dropdown_opened = True
                break
        except Exception:
            continue

    if not dropdown_opened:
        for btn_text in ["WK마케팅그룹", "카테고리"]:
            try:
                btn = page.get_by_text(btn_text, exact=False).first
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=2000)
                    time.sleep(1.5)
                    print(f"    카테고리 드롭다운 열림 (text={btn_text})")
                    dropdown_opened = True
                    break
            except Exception:
                continue

    # ── 플랜 A: 드롭다운 목록 li에서 exact text 클릭 ──
    # 드롭다운이 열린 상태에서만 시도 (본문 텍스트 오클릭 방지)
    if dropdown_opened:
        try:
            items = page.locator('li, [role="option"], [class*="category_item"], [class*="categoryItem"]')
            for i in range(min(items.count(), 50)):
                item = items.nth(i)
                try:
                    if item.inner_text(timeout=300).strip().endswith(category) and item.is_visible(timeout=300):
                        item.click(force=True)
                        print(f"    카테고리 선택 완료 (A: dropdown li): {category}")
                        time.sleep(0.5)
                        return
                except Exception:
                    continue
        except Exception:
            pass

    # ── 플랜 B: categoryNo로 data 속성 탐색 후 클릭 (JS) ──
    if category_no:
        res = page.evaluate("""
            (no) => {
                const el = document.querySelector(
                    `[data-category-no="${no}"], [data-no="${no}"], [data-id="${no}"], [data-value="${no}"]`
                );
                if (el && el.getBoundingClientRect().width > 0) {
                    el.click();
                    return el.textContent.trim();
                }
                return null;
            }
        """, category_no)
        if res:
            print(f"    카테고리 선택 완료 (B: data-attr no={category_no}): {res}")
            time.sleep(0.5)
            return

    # ── 플랜 C: <select> option value=categoryNo 직접 설정 (JS) ──
    if category_no:
        res = page.evaluate("""
            ([cat, no]) => {
                for (const sel of document.querySelectorAll('select')) {
                    for (const opt of sel.options) {
                        if (String(opt.value) === String(no) || opt.text.trim() === cat) {
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change', {bubbles: true}));
                            sel.dispatchEvent(new Event('input', {bubbles: true}));
                            return opt.text.trim();
                        }
                    }
                }
                return null;
            }
        """, [category, category_no])
        if res:
            print(f"    카테고리 선택 완료 (C: select option): {res}")
            time.sleep(0.5)
            return

    # ── 플랜 D: visible li/option 중 exact text JS 클릭 ──
    # 단, SE 에디터 영역(se-component) 내부 요소는 제외
    res = page.evaluate("""
        (cat) => {
            const candidates = Array.from(
                document.querySelectorAll('li, option, [role="option"], [role="menuitem"]')
            ).filter(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0) return false;
                // SE 에디터 내부 요소 제외
                if (el.closest('.se-component, .se-editor, #se_text_content')) return false;
                return el.textContent.trim().endsWith(cat);
            });
            if (candidates.length > 0) {
                candidates[0].click();
                return candidates[0].textContent.trim();
            }
            // 디버그: 현재 visible li 샘플
            const sample = Array.from(document.querySelectorAll('li, option'))
                .filter(el => el.getBoundingClientRect().width > 0 &&
                              !el.closest('.se-component, .se-editor'))
                .map(el => el.textContent.trim().substring(0, 30))
                .filter(t => t.length > 0)
                .slice(0, 20);
            return {failed: true, sample};
        }
    """, category)
    if res and not isinstance(res, dict):
        print(f"    카테고리 선택 완료 (D: JS visible li): {res}")
        time.sleep(0.5)
        return

    print(f"  ⚠️ 카테고리 '{category}' 선택 실패 (A~D 모두 실패)")
    if isinstance(res, dict):
        print(f"     visible li 샘플: {res.get('sample', [])}")


def _input_tags(page, tags: list[str]) -> None:
    """발행 패널에서 태그 입력"""
    if not tags:
        return
    time.sleep(0.5)



    result = page.evaluate("""
        (tags) => {
            const selectors = [
                'input[placeholder*="태그"]',
                'input[placeholder*="Tag"]',
                '.tpb-tag-input input',
                '[class*="tag"] input[type="text"]',
                '[class*="Tag"] input',
                '.se-tag-input input',
                'input[class*="tag"]',
                'input[class*="Tag"]',
                'input[data-type="tag"]',
                // CSS module class는 일부 문자열 포함 여부로 탐색
                ...Array.from(document.querySelectorAll('input')).filter(i =>
                    (i.className || '').toLowerCase().includes('tag') ||
                    (i.placeholder || '').includes('태그') ||
                    (i.placeholder || '').toLowerCase().includes('tag')
                ).map(() => null),  // dummy, 아래에서 처리
            ];
            let input = null;
            for (const sel of selectors) {
                if (!sel) continue;
                input = document.querySelector(sel);
                if (input) break;
            }
            // 위에서 못 찾으면 class/placeholder 포함 탐색
            if (!input) {
                input = Array.from(document.querySelectorAll('input')).find(i =>
                    (i.className || '').toLowerCase().includes('tag') ||
                    (i.placeholder || '').includes('태그') ||
                    (i.placeholder || '').toLowerCase().includes('tag')
                ) || null;
            }
            if (!input) {
                // 발행 패널이 열린 상태의 모든 visible input 반환 (디버그용)
                const allInputs = Array.from(document.querySelectorAll('input'))
                    .filter(i => i.getBoundingClientRect().width > 0);
                return {ok: false, inputs: allInputs.map(i => i.className + '|' + i.placeholder).slice(0, 15)};
            }

            const nativeValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;

            for (const tag of tags) {
                input.focus();
                nativeValueSetter.call(input, tag);
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}));
                input.dispatchEvent(new KeyboardEvent('keyup',  {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}));
            }
            return {ok: true};
        }
    """, tags)

    if result and result.get("ok"):
        print(f"    태그 입력 완료: {', '.join(tags)}")
    else:
        print(f"  ⚠️ JS 태그 입력 실패, Playwright fallback 시도")
        if result:
            print(f"     사용 가능한 input: {result.get('inputs', [])}")
        # Playwright fallback: input 또는 contenteditable 모두 시도
        tag_locator = None
        for sel in [
            'input[placeholder*="태그"]',
            '[class*="tag"] input',
            '[class*="tpb"] input',
            '[placeholder*="태그"]',
        ]:
            try:
                candidate = page.locator(sel).first
                if candidate.is_visible(timeout=1500):
                    tag_locator = candidate
                    break
            except Exception:
                continue
        if tag_locator:
            for tag in tags:
                try:
                    tag_locator.click()
                    tag_locator.fill(tag)
                    page.keyboard.press("Enter")
                    time.sleep(0.3)
                except Exception:
                    break
            # fallback 후 드롭다운/포커스 정리
            page.keyboard.press("Escape")
            time.sleep(0.5)
            print(f"    태그 입력 완료 (fallback): {', '.join(tags)}")
        else:
            print(f"  ⚠️ 태그 input을 찾지 못함 - 태그 없이 발행 진행")


def _focus_body(page) -> None:
    """SE3 본문 영역으로 포커스 이동 (제목 이외의 첫 contenteditable 클릭)"""
    # 전략 1: 제목 박스 아래 위치를 마우스로 직접 클릭
    try:
        title_bb = page.locator(".se-title-text").first.bounding_box()
        if title_bb:
            body_x = title_bb["x"] + title_bb["width"] / 2
            body_y = title_bb["y"] + title_bb["height"] + 60
            page.mouse.click(body_x, body_y)
            time.sleep(0.4)
            return
    except Exception:
        pass

    # 전략 2: JS로 비-제목 contenteditable 찾아 포커스
    focused = page.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll('[contenteditable]'));
            for (const el of els) {
                if (!el.closest('[class*="title"]') && !el.closest('[id*="title"]')) {
                    el.click();
                    el.focus();
                    return true;
                }
            }
            return false;
        }
    """)
    if focused:
        time.sleep(0.3)
        return

    # 전략 3: 플레이스홀더 클릭
    for sel in [".se-placeholder", ".se-module-text", ".se-component-content"]:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                el.click(timeout=2000)
                time.sleep(0.3)
                return
        except Exception:
            continue


def _paste_html_to_editor(page, html: str, plain_fallback: str) -> None:
    """
    SE3 에디터에 HTML 삽입.
    전략 1: ClipboardEvent paste 시뮬레이션 — SE3가 paste 이벤트를 처리
    전략 2: Playwright clipboard API + Cmd+V
    전략 3: plain text keyboard.type() fallback
    """
    # 전략 1: ClipboardEvent paste 시뮬레이션
    # SE3은 contenteditable에 직접 DOM 조작하면 무시하지만,
    # paste 이벤트는 자체 핸들러로 처리하므로 이 방식이 가장 확실함
    try:
        result = page.evaluate("""
            (html) => {
                // SE3 본문 영역 찾기
                const editor = document.querySelector(
                    '.se-text-paragraph[contenteditable="true"]'
                ) || document.querySelector(
                    '[contenteditable="true"]:not([class*="title"])'
                );
                if (!editor) return {ok: false, error: 'editor not found'};

                editor.focus();

                // DataTransfer로 HTML paste 이벤트 생성
                const dt = new DataTransfer();
                dt.setData('text/html', html);
                dt.setData('text/plain', html.replace(/<[^>]+>/g, ''));

                const pasteEvent = new ClipboardEvent('paste', {
                    clipboardData: dt,
                    bubbles: true,
                    cancelable: true,
                });

                const handled = !editor.dispatchEvent(pasteEvent);
                return {ok: true, handled: handled, length: html.length};
            }
        """, html)
        if result and result.get("ok"):
            print(f"    HTML paste 이벤트 발송 (handled={result.get('handled')}, {result.get('length')}자)")
            time.sleep(2)

            # paste 후 본문이 실제로 삽입되었는지 확인
            body_len = page.evaluate("""
                () => {
                    const paragraphs = document.querySelectorAll('.se-text-paragraph');
                    let total = 0;
                    paragraphs.forEach(p => { total += (p.textContent || '').trim().length; });
                    return total;
                }
            """)
            if body_len and body_len > 10:
                print(f"    ✅ 본문 확인: {body_len}자 삽입됨")
                return
            else:
                print(f"  ⚠️ paste 이벤트 후 본문 비어있음 ({body_len}자) → 전략 2로")
        else:
            print(f"  ⚠️ paste 이벤트 실패: {result}")
    except Exception as e:
        print(f"  ⚠️ paste 이벤트 오류: {e}")

    # 전략 2: Playwright의 evaluate + clipboard API로 붙여넣기
    try:
        # Playwright의 cdp를 통해 클립보드에 HTML 쓰기 후 paste
        page.evaluate("""
            async (html) => {
                // Clipboard API로 HTML 쓰기
                const blob = new Blob([html], {type: 'text/html'});
                const plainBlob = new Blob([html.replace(/<[^>]+>/g, '')], {type: 'text/plain'});
                const item = new ClipboardItem({
                    'text/html': blob,
                    'text/plain': plainBlob,
                });
                await navigator.clipboard.write([item]);
            }
        """, html)
        time.sleep(0.3)
        page.keyboard.press("Meta+v")
        time.sleep(2)

        body_len = page.evaluate("""
            () => {
                const paragraphs = document.querySelectorAll('.se-text-paragraph');
                let total = 0;
                paragraphs.forEach(p => { total += (p.textContent || '').trim().length; });
                return total;
            }
        """)
        if body_len and body_len > 10:
            print(f"    ✅ 본문 확인 (clipboard API): {body_len}자")
            return
        else:
            print(f"  ⚠️ clipboard API 후 본문 비어있음 ({body_len}자) → 전략 3로")
    except Exception as e:
        print(f"  ⚠️ clipboard API 오류: {e}")

    # 전략 3: plain text fallback — 최소한 텍스트라도 넣기
    content = plain_fallback or re.sub(r"<[^>]+>", "", html)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    print(f"  ⚠️ HTML 삽입 모두 실패 → plain text 입력 ({len(content)}자)")
    for para in content.split("\n\n"):
        if para.strip():
            page.keyboard.type(para.strip(), delay=10)
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")


def _upload_local_image(page, local_path: str) -> bool:
    """로컬 파일 → SE3 에디터 업로드. 성공 여부 반환."""
    if not os.path.exists(local_path):
        print(f"  ⚠️ 로컬 이미지 없음: {local_path}")
        return False
    try:
        with page.expect_file_chooser(timeout=5000) as fc_info:
            img_btn = page.locator(".se-image-toolbar-button")
            if img_btn.count() > 0:
                img_btn.first.click()
            else:
                print("  ⚠️ 이미지 버튼을 찾을 수 없습니다")
                return False
        fc_info.value.set_files(local_path)
        time.sleep(3)
        return True
    except Exception as e:
        print(f"  ⚠️ 로컬 이미지 업로드 실패: {e}")
        return False


def _upload_image(page, image_url: str) -> bool:
    """이미지 URL → 로컬 다운로드 → 에디터 업로드. 성공 여부 반환."""
    suffix = ".png" if ".png" in image_url.lower() else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name

    try:
        req = urllib.request.Request(
            image_url,
            headers={"User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            with open(tmp_path, "wb") as f:
                f.write(resp.read())
    except Exception as e:
        print(f"  ⚠️ 이미지 다운로드 실패: {e}")
        return False

    try:
        with page.expect_file_chooser(timeout=5000) as fc_info:
            img_btn = page.locator(".se-image-toolbar-button")
            if img_btn.count() > 0:
                img_btn.first.click()
            else:
                print("  ⚠️ 이미지 버튼을 찾을 수 없습니다")
                return False

        file_chooser = fc_info.value
        file_chooser.set_files(tmp_path)
        time.sleep(3)
        return True

    except Exception as e:
        print(f"  ⚠️ 이미지 업로드 실패: {e}")
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _add_image_link(page, link_url: str) -> bool:
    """업로드된 이미지에 SE3 툴바 링크 추가. 성공 True, 실패 False"""
    try:
        # 마지막 이미지 클릭해서 선택
        img_el = page.locator(".se-image-container img, .se-component-image img").last
        if img_el.count() > 0:
            img_el.click(timeout=2000)
            time.sleep(1.5)

        # 전략 1: SE3 이미지 툴바에서 링크 버튼 클릭
        link_btn = page.locator(
            '[class*="link"][class*="se-"], [data-click-area*="link"], '
            'button[title*="링크"], button[title*="Link"], '
            '[class*="toolbar"] button:has-text("링크")'
        )
        if link_btn.count() > 0 and link_btn.first.is_visible(timeout=1000):
            link_btn.first.click()
            time.sleep(0.8)
            print("    이미지 툴바 링크 버튼 클릭")
        else:
            # 전략 2: Meta+K 단축키
            page.keyboard.press("Meta+k")
            time.sleep(1.0)

        # 링크 입력 다이얼로그 탐색
        url_input = page.locator(
            'input[type="url"], input[placeholder*="http"], '
            'input[placeholder*="URL"], input[placeholder*="주소"], '
            '[class*="link"] input, [class*="Link"] input'
        ).last
        if url_input.count() > 0 and url_input.is_visible(timeout=2000):
            url_input.fill(link_url)
            page.keyboard.press("Enter")
            time.sleep(0.5)
            print(f"    이미지 링크 추가 완료: {link_url}")
            return True

        # 다이얼로그 안 뜨면 닫기
        page.keyboard.press("Escape")
        print("  ⚠️ 이미지 링크 다이얼로그 못 찾음 (text link fallback 사용)")
        return False
    except Exception as e:
        print(f"  ⚠️ 이미지 링크 추가 실패: {e}")
        return False


def _select_thumbnail(page) -> None:
    """
    에디터 본문의 첫 번째 이미지(기사 고유 이미지)를 대표 이미지로 설정.
    발행 패널 열기 전에 호출. 이미지 hover → 이미지 클릭.
    삽입 순서: 기사 이미지(0) → 헤더 배너(1) → ...
    """
    time.sleep(0.5)

    # 에디터 본문 이미지 컴포넌트 (.se-component.se-image)
    image_components = page.locator('.se-component.se-image')
    count = image_components.count()
    print(f"    [THUMB] 에디터 이미지 수: {count}")

    if count < 1:
        print("  ⚠️ 대표 이미지 선택 실패 (이미지 없음)")
        return

    # 첫 번째 이미지(index=0) = 기사 고유 이미지 (섹션 순서 변경 후)
    target = image_components.nth(0)
    target.hover(timeout=3000)
    time.sleep(0.7)

    # 첫 번째 이미지 클릭 = 대표 이미지 설정
    try:
        target.click(force=True)
        print(f"    ✅ 대표 이미지 설정 완료 (index=0)")
    except Exception as e:
        print(f"  ⚠️ 대표 이미지 클릭 실패: {e}")


def _write_post(page, payload: dict) -> str | None:
    """블로그 글쓰기 (Smart Editor 3). 성공 시 게시물 URL, 실패 시 None 반환"""
    title = payload["title"]
    html_body = payload.get("html_body", "")
    text = payload.get("text", "")
    image_urls = payload.get("image_urls", [])
    category = payload.get("category", "티끌레터™")
    tags = payload.get("tags", [])

    # 글쓰기 페이지 이동
    page.goto(WRITE_URL)
    page.wait_for_load_state("networkidle", timeout=20_000)
    print(f"    글쓰기 페이지 URL: {page.url[:100]}")
    if "login" in page.url or "nidlogin" in page.url:
        print("  ❌ 글쓰기 접근 실패 - 로그인 페이지로 리다이렉트됨 (쿠키 만료)")
        return None
    time.sleep(5)

    # 팝업 닫기
    _dismiss_popups(page)

    # ── 제목 입력 ────────────────────────────────────────
    try:
        title_el = page.locator(".se-title-text")
        title_el.first.click(force=True)
        time.sleep(0.3)
        page.keyboard.type(title, delay=25)
    except Exception as e:
        print(f"  ❌ 제목 입력 실패: {e}")
        return None

    # ── 섹션 기반 콘텐츠 삽입 ────────────────────────────
    # sections: [{"type": "html"|"image", "content"|"url": ...}]
    sections = payload.get("sections", [])

    if not sections:
        # 하위 호환: sections 없으면 html_body + image_urls 사용
        if html_body:
            sections = [{"type": "html", "content": html_body}]
        if image_urls:
            sections.append({"type": "image", "url": image_urls[0]})

    _focus_body(page)

    for idx, sec in enumerate(sections):
        sec_type = sec.get("type")

        if sec_type == "html":
            content = sec.get("content", "").strip()
            if content:
                if idx > 0:
                    page.keyboard.press("End")
                    # leading_newline=False: 이미지 직후 한 줄 이미 있으므로 Enter 생략
                    if sec.get("leading_newline", True):
                        page.keyboard.press("Enter")
                        time.sleep(0.2)
                _paste_html_to_editor(page, content, "")
                print(f"    [섹션{idx}] HTML 삽입")

        elif sec_type in ("image", "image_link"):
            url = sec.get("url", "")
            link = sec.get("link", "")
            if url:
                page.keyboard.press("End")
                page.keyboard.press("Enter")
                time.sleep(0.3)
                print(f"    [섹션{idx}] 이미지 업로드: {url[:60]}...")
                ok = _upload_image(page, url)
                if ok and link:
                    time.sleep(1.5)
                    _add_image_link(page, link)
                page.keyboard.press("ArrowDown")
                time.sleep(0.5)

        elif sec_type == "local_file":
            local_path = sec.get("path", "")
            link = sec.get("link", "")
            if local_path:
                page.keyboard.press("End")
                page.keyboard.press("Enter")
                time.sleep(0.3)
                print(f"    [섹션{idx}] 로컬 이미지 업로드: {os.path.basename(local_path)}")
                ok = _upload_local_image(page, local_path)
                if ok and link:
                    time.sleep(1.5)
                    _add_image_link(page, link)
                page.keyboard.press("ArrowDown")
                time.sleep(0.5)


    time.sleep(1)

    # 대표 이미지: 첫 번째 이미지(기사 이미지)를 대표로 설정 + 에디터 포커스 리셋
    _select_thumbnail(page)

    # ── 발행 패널 열기 ───────────────────────────────────
    try:
        page.locator('[data-click-area="tpb.publish"]').click(force=True)
        time.sleep(4)  # 패널 완전 로드 대기
    except Exception as e:
        print(f"  ❌ 발행 버튼 클릭 실패: {e}")
        return None

    # ── 발행 패널 상태 확인 & 재오픈 ────────────────────
    # 썸네일 선택 후 패널이 닫힐 수 있으므로 카테고리/태그 입력 전에 확인
    EXCLUDED_DCA = {"tpb.publish", "tpb*t.schedule"}

    def _ensure_panel_open():
        panel_open = page.evaluate("""
            (excluded) => {
                const btns = Array.from(document.querySelectorAll('button'));
                return btns.some(b => {
                    const d = b.getAttribute('data-click-area') || '';
                    const rect = b.getBoundingClientRect();
                    return d && !excluded.includes(d) &&
                           (b.textContent || '').trim().includes('발행') &&
                           rect.width > 0;
                });
            }
        """, list(EXCLUDED_DCA))
        if not panel_open:
            print("    발행 패널 재오픈...")
            page.locator('[data-click-area="tpb.publish"]').click(force=True)
            time.sleep(4)

    _ensure_panel_open()

    # ── 카테고리 선택 ────────────────────────────────────
    if category:
        try:
            _select_category(page, category, category_no=TIKKEUL_CATEGORY_NO)
        except Exception as e:
            print(f"  ⚠️ 카테고리 선택 오류: {e}")

    # 카테고리 선택 후 패널이 닫혔으면 재오픈
    _ensure_panel_open()

    # ── 태그 입력 ────────────────────────────────────────
    if tags:
        try:
            _input_tags(page, tags)
        except Exception as e:
            print(f"  ⚠️ 태그 입력 오류: {e}")

    # ── 최종 발행 (여러 후보 순서대로 시도) ─────────────
    publish_clicked = False

    # 후보 A: tpb*i.publish (확인된 최종 발행 버튼)
    try:
        btn = page.locator('[data-click-area="tpb*i.publish"]').first
        if btn.is_visible(timeout=2000):
            btn.click(force=True)
            print("    최종 발행 클릭 (A: tpb*i.publish)")
            publish_clicked = True
    except Exception:
        pass

    # 후보 B: exclusion 제외한 data-click-area + "발행" 텍스트
    if not publish_clicked:
        try:
            final_btn = page.locator(
                ':not([data-click-area="tpb.publish"]):not([data-click-area="tpb*t.schedule"])[data-click-area]'
            ).filter(has_text=re.compile(r"발행")).last
            if final_btn.count() > 0 and final_btn.is_visible(timeout=1500):
                dca = final_btn.get_attribute("data-click-area")
                final_btn.click(force=True)
                print(f"    최종 발행 클릭 (B: dca={dca})")
                publish_clicked = True
        except Exception:
            pass

    # 후보 G: 클래스명에 publish/confirm/ok 포함한 버튼
    if not publish_clicked:
        for cls_pat in ["btn_publish", "confirm_btn", "ok_btn", "submit_btn", "btnPublish", "btnConfirm"]:
            try:
                btn = page.locator(f'button[class*="{cls_pat}"]').last
                if btn.is_visible(timeout=800):
                    btn.click(force=True)
                    print(f"    최종 발행 클릭 (G: class*={cls_pat})")
                    publish_clicked = True
                    break
            except Exception:
                continue

    # 후보 H: JS - exclusion 제외하고 "발행" 텍스트 마지막 visible 버튼
    if not publish_clicked:
        result = page.evaluate("""
            (excluded) => {
                const btns = Array.from(document.querySelectorAll('button'));
                const all_visible = btns.filter(b => {
                    const d = b.getAttribute('data-click-area') || '';
                    const rect = b.getBoundingClientRect();
                    return (b.textContent || '').trim() === '발행' &&
                           rect.width > 0 && !excluded.includes(d);
                });
                // 전체 visible 버튼 목록도 같이 반환 (디버그용)
                const all_btns = btns
                    .filter(b => b.getBoundingClientRect().width > 0)
                    .map(b => ({
                        text: (b.textContent || '').trim().substring(0, 20),
                        dca: b.getAttribute('data-click-area') || '',
                        cls: b.className.substring(0, 40),
                    }));
                if (all_visible.length > 0) {
                    all_visible[all_visible.length - 1].click();
                    return {clicked: true, all: all_btns};
                }
                return {clicked: false, all: all_btns};
            }
        """, list(EXCLUDED_DCA))
        if result and result.get("clicked"):
            print(f"    최종 발행 클릭 (H: JS fallback)")
            publish_clicked = True
        else:
            visible_btns = (result or {}).get("all", [])
            print(f"    ⚠️ 최종 발행 버튼 없음. 현재 visible 버튼: {visible_btns}")

    # ── 발행 후 페이지 이동 대기 ───────────────────────────
    try:
        page.wait_for_url(
            lambda url: "PostWriteForm" not in url,
            timeout=30_000,
        )
    except PWTimeout:
        pass

    # ── URL 추출 ─────────────────────────────────────────
    current_url = page.url
    print(f"    발행 후 URL: {current_url[:120]}")

    if "PostWriteForm" in current_url:
        # 발행은 됐을 수 있으나 URL 이동 안 됨 → 블로그 홈에서 최신 글 URL 추출
        try:
            page.goto(f"https://blog.naver.com/{NAVER_BLOG_ID}", wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            # JS로 blogId/숫자 패턴 링크 중 logNo 최대값 (= 최신 글) 추출
            guessed_url = page.evaluate(f"""
                () => {{
                    const links = Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => /blog\\.naver\\.com\\/{NAVER_BLOG_ID}\\/\\d{{5,}}/.test(h));
                    if (!links.length) return null;
                    return links.reduce((best, url) => {{
                        const m = url.match(/\\/(\d+)(?:[?#].*)?$/);
                        const bm = best ? best.match(/\\/(\d+)(?:[?#].*)?$/) : null;
                        return (!bm || (m && parseInt(m[1]) > parseInt(bm[1]))) ? url : best;
                    }}, null);
                }}
            """)
            if guessed_url:
                # 쿼리스트링 제거 후 정규화
                clean_url = guessed_url.split("?")[0].split("#")[0]
                print(f"  ⚠️ 발행 완료 추정 (최신 글 URL): {clean_url}")
                return clean_url
        except Exception as e:
            print(f"  ⚠️ 폴백 URL 추출 오류: {e}")
        print(f"  ⚠️ 발행 후 URL 확인 불가")
        return None

    post_url = _extract_post_url(current_url)
    print(f"  ✅ 네이버 블로그 게시 완료: {post_url}")
    return post_url


def _extract_post_url(page_url: str) -> str:
    import re
    match = re.search(r'logNo=(\d+)', page_url)
    if match:
        log_no = match.group(1)
        return f"https://blog.naver.com/{NAVER_BLOG_ID}/{log_no}"
    return page_url


# ── 퍼블릭 함수 ───────────────────────────────────────

def post_to_naver_blog(payload: dict) -> dict:
    """
    네이버 블로그 게시 실행
    payload: format_for_naver_blog() 반환값
      - title, html_body, text, image_urls, category, tags
    """
    if not NAVER_BLOG_ID:
        msg = "NAVER_BLOG_ID가 .env에 설정되지 않았습니다"
        print(f"  ❌ {msg}")
        return {'success': False, 'url': None, 'error': msg}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )

        page = context.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        try:
            cookies = _get_naver_cookies()
            if not cookies:
                return {'success': False, 'url': None, 'error': '네이버 쿠키 없음 (Chrome 로그인 확인)'}
            context.add_cookies(cookies)

            post_url = _write_post(page, payload)
            if post_url:
                return {'success': True, 'url': post_url}
            return {'success': False, 'url': None, 'error': '발행 후 URL 확인 실패'}

        except Exception as e:
            print(f"  ❌ 네이버 블로그 게시 오류: {e}")
            return {'success': False, 'url': None, 'error': str(e)}

        finally:
            browser.close()
