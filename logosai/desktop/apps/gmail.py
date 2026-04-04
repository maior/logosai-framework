"""Gmail AppController — Chrome JavaScript 기반 Gmail 제어.

Usage:
    from logosai.desktop.apps.gmail import GmailController
    from logosai.desktop import get_platform

    ctrl = GmailController(platform=get_platform())
    await ctrl.open()
    result = await ctrl.action("compose", to="user@test.com", subject="Hi", body="Hello")
    result = await ctrl.action("list")  # 받은편지함 목록
    result = await ctrl.action("read", index=1)  # 첫 번째 메일 읽기
    await ctrl.close()
"""

import asyncio
import os
import subprocess
import urllib.parse
from typing import Any, Dict, List

from loguru import logger

from .base import AppController


class GmailController(AppController):
    """Gmail 앱 제어 — Chrome JavaScript injection."""

    GMAIL_URL = "https://mail.google.com"

    def __init__(self, platform=None):
        super().__init__(platform=platform, app_name="Google Chrome")

    def _chrome_js(self, js: str) -> str:
        """Gmail 탭에서 JavaScript 실행."""
        return self.platform.chrome_execute_js(js, url_contains="mail.google")

    async def open(self) -> bool:
        """Gmail 열기."""
        # Chrome 활성화
        self.platform.activate_app("Google Chrome")
        await asyncio.sleep(1)

        # Gmail 탭이 이미 열려있는지 확인
        check = self._chrome_js("document.title")
        if not check or "Gmail" not in check:
            # Gmail 열기
            if self.platform.os_name == "macos":
                subprocess.run(["open", self.GMAIL_URL], timeout=5)
            else:
                subprocess.run(["xdg-open", self.GMAIL_URL], timeout=5)
            await asyncio.sleep(3)
        return True

    async def navigate(self, target: str, **kwargs) -> bool:
        """Gmail 검색."""
        search_url = f"{self.GMAIL_URL}/mail/u/0/#search/{urllib.parse.quote(target)}"
        self._chrome_js(f"window.location.href = '{search_url}'")
        await asyncio.sleep(2)
        return True

    async def action(self, action_type: str, **params) -> Dict[str, Any]:
        """Gmail 작업 실행.

        action_type:
            "list" — 받은편지함 목록
            "read" — 메일 읽기 (index)
            "compose" — 메일 작성 (to, subject, body)
            "search" — 메일 검색 (query)
        """
        if action_type == "list":
            return await self._list_inbox()
        elif action_type == "read":
            return await self._read_email(params.get("index", 1))
        elif action_type == "compose":
            return await self._compose(
                params.get("to", ""),
                params.get("subject", ""),
                params.get("body", ""),
            )
        elif action_type == "search":
            await self.navigate(params.get("query", ""))
            return await self._list_inbox()
        return {"success": False, "error": f"Unknown action: {action_type}"}

    async def _list_inbox(self) -> Dict[str, Any]:
        """받은편지함 목록 조회."""
        js = """
        (function() {
            var rows = document.querySelectorAll('tr.zA');
            var emails = [];
            for (var i = 0; i < Math.min(rows.length, 10); i++) {
                var row = rows[i];
                var sender = row.querySelector('.yW span');
                var subject = row.querySelector('.y6 span:first-child');
                var snippet = row.querySelector('.y2');
                var date = row.querySelector('.xW.xY span');
                var unread = row.classList.contains('zE');
                emails.push({
                    index: i + 1,
                    sender: sender ? sender.textContent.trim() : '',
                    subject: subject ? subject.textContent.trim() : '',
                    snippet: snippet ? snippet.textContent.trim() : '',
                    date: date ? date.textContent.trim() : '',
                    unread: unread
                });
            }
            return JSON.stringify(emails);
        })()
        """
        result = self._chrome_js(js)
        try:
            import json
            emails = json.loads(result)
            return {"success": True, "result": emails, "count": len(emails)}
        except Exception:
            return {"success": True, "result": [], "count": 0}

    async def _read_email(self, index: int) -> Dict[str, Any]:
        """메일 읽기."""
        # 클릭
        self._chrome_js(f"""
            var rows = document.querySelectorAll('tr.zA');
            if (rows[{index - 1}]) rows[{index - 1}].click();
        """)
        await asyncio.sleep(2)

        # 내용 읽기
        js = """
        (function() {
            var subject = document.querySelector('h2.hP');
            var sender = document.querySelector('.gD');
            var date = document.querySelector('.g3');
            var body = document.querySelector('.a3s.aiL');
            return JSON.stringify({
                subject: subject ? subject.textContent.trim() : '',
                sender_name: sender ? sender.getAttribute('name') || sender.textContent : '',
                sender_email: sender ? sender.getAttribute('email') || '' : '',
                date: date ? date.textContent.trim() : '',
                body: body ? body.textContent.trim().substring(0, 500) : ''
            });
        })()
        """
        result = self._chrome_js(js)
        try:
            import json
            email = json.loads(result)
            return {"success": True, "result": email}
        except Exception:
            return {"success": False, "error": "Failed to read email"}

    async def _compose(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """메일 작성 + 전송."""
        compose_url = (
            f"{self.GMAIL_URL}/mail/u/0/?view=cm&fs=1"
            f"&to={urllib.parse.quote(to)}"
            f"&su={urllib.parse.quote(subject)}"
            f"&body={urllib.parse.quote(body)}"
        )
        self._chrome_js(f"window.open('{compose_url}')")
        await asyncio.sleep(3)

        # 전송 버튼 클릭
        self._chrome_js("""
            var btn = document.querySelector('[data-tooltip*="Send"]') ||
                      document.querySelector('[aria-label*="Send"]');
            if (btn) btn.click();
        """)
        await asyncio.sleep(2)

        return {"success": True, "result": f"Email sent to {to}"}
