"""라이브러리 GmailController 전송 방식 검증 (2026-07-06 감사).

발견: 배포 라이브러리 gmail.py `_compose` 가 JS 로 Send 버튼 클릭(`btn.click()`)해
전송하는데, ACP mail_agent 는 이 방식이 "작성만 되고 전송 안 됨"이라 명시.
게다가 항상 `success:True` 반환 → SDK 사용자가 조용히 실패.

계약: _compose 는 (1) Cmd+Enter 키스트로크(AppleScript System Events)로 전송하고
(2) 결과를 정직하게 반환(applescript 실패 시 success=False).

직접 실행: python logosai/tests/test_desktop_gmail_send.py
"""
import asyncio
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PKG)


class FakePlatform:
    os_name = "macos"

    def __init__(self, applescript_fail=False):
        self.calls = []
        self.applescript_fail = applescript_fail

    def chrome_execute_js(self, js, url_contains=""):
        self.calls.append(("js", js))
        return "Compose"

    def run_applescript(self, script):
        self.calls.append(("applescript", script))
        if self.applescript_fail:
            return "ERROR: automation not permitted"
        return "ok"

    def activate_app(self, name):
        self.calls.append(("activate", name))
        return True


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def main():
    fails = []

    def t(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    from logosai.desktop.apps.gmail import GmailController

    # ── 정상: Cmd+Enter 로 전송 ──
    pf = FakePlatform()
    ctrl = GmailController(platform=pf)
    res = run(ctrl._compose("a@b.com", "제목", "본문"))
    scripts = " ".join(s for k, s in pf.calls if k == "applescript").lower()

    t("G-1 AppleScript 전송 사용 (JS-click 의존 탈피)",
      any(k == "applescript" for k, _ in pf.calls))
    t("G-2 Cmd+Enter 키스트로크 (command down + return)",
      "return" in scripts and "command" in scripts)
    t("G-3 정상 시 success True", res.get("success") is True)

    # ── 실패: applescript 오류 시 정직하게 success False ──
    pf2 = FakePlatform(applescript_fail=True)
    ctrl2 = GmailController(platform=pf2)
    res2 = run(ctrl2._compose("a@b.com", "s", "b"))
    t("G-4 전송 실패 시 success False (조용한 실패 차단)",
      res2.get("success") is False)
    t("G-5 실패 시 error 메시지 포함", bool(res2.get("error")))

    print("RESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
