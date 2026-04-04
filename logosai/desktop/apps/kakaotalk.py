"""KakaoTalk AppController — macOS AppleScript + Peekaboo 기반 메시지 전송.

Usage:
    from logosai.desktop.apps.kakaotalk import KakaoTalkController
    from logosai.desktop import get_platform

    ctrl = KakaoTalkController(platform=get_platform())
    await ctrl.open()
    result = await ctrl.action("send", recipient="홍길동", message="안녕하세요")
    await ctrl.close()
"""

import asyncio
import subprocess
from typing import Any, Dict, Optional

from loguru import logger

from .base import AppController

# AppleScript constants
SEARCH_CLICK_SCRIPT = '''
tell application "System Events"
tell process "KakaoTalk"
if (count of windows) = 0 then return "NO_WINDOW"
tell window 1
repeat with b in (every button)
if description of b is "Search" then
click b
return "OK"
end if
end repeat
return "NO_SEARCH_BUTTON"
end tell
end tell
end tell
'''

CHATS_TAB_SCRIPT = '''
tell application "System Events"
tell process "KakaoTalk"
if (count of windows) = 0 then return "NO_WINDOW"
tell window 1
set idx to 0
repeat with b in (every button)
set idx to idx + 1
if idx = 2 then
click b
return "OK_CHATS"
end if
end repeat
return "NO_TAB"
end tell
end tell
end tell
'''


class KakaoTalkController(AppController):
    """KakaoTalk 앱 제어 — macOS AppleScript + Peekaboo."""

    def __init__(self, platform=None, peekaboo=None, screen_analyzer=None):
        super().__init__(platform=platform, app_name="KakaoTalk")
        self._peekaboo = peekaboo
        self._screen = screen_analyzer

    def _applescript(self, script: str) -> str:
        """Run AppleScript and return stdout."""
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip()
        except Exception as e:
            logger.warning(f"AppleScript failed: {e}")
            return ""

    async def _ensure_peekaboo(self):
        """Lazy-load Peekaboo if not injected."""
        if self._peekaboo is None:
            try:
                from ..vision.peekaboo_client import PeekabooClient
                self._peekaboo = PeekabooClient
            except ImportError:
                logger.warning("PeekabooClient not available")

    async def navigate(self, target: str, **kwargs) -> bool:
        """KakaoTalk에서 대상 검색 + 선택.

        Args:
            target: 수신자 이름
        """
        await self._ensure_peekaboo()
        APP = self.app_name

        # 채팅 탭 클릭
        self._applescript(CHATS_TAB_SCRIPT)
        await asyncio.sleep(1)

        # Search 버튼 클릭
        result = self._applescript(SEARCH_CLICK_SCRIPT)
        if result == "NO_WINDOW":
            subprocess.run(["open", "-a", APP], timeout=5)
            await asyncio.sleep(3)
            self._applescript(f'tell application "{APP}" to activate')
            await asyncio.sleep(1)
            result = self._applescript(SEARCH_CLICK_SCRIPT)
            if result == "NO_WINDOW":
                return False

        await asyncio.sleep(1)

        # 이름 입력
        if self._peekaboo:
            await self._peekaboo.paste(target, APP)
        await asyncio.sleep(3)

        # Vision으로 검색결과 확인
        if self._screen:
            match = await self._screen.find_in_results(APP, target)
            if match.found and match.action and match.action.startswith("arrow_down_"):
                n = int(match.action.split("_")[-1])
                for _ in range(n):
                    await self._peekaboo.press("down", APP)
                    await asyncio.sleep(0.3)
                return True

        # Fallback: 첫 번째 결과 선택
        if self._peekaboo:
            await self._peekaboo.press("down", APP)
            await asyncio.sleep(0.3)
        return True

    async def action(self, action_type: str, **params) -> Dict[str, Any]:
        """KakaoTalk 작업 실행.

        action_type:
            "send" — 메시지 전송 (recipient, message 필수)
        """
        if action_type == "send":
            return await self._send_message(
                params.get("recipient", ""),
                params.get("message", ""),
            )
        return {"success": False, "error": f"Unknown action: {action_type}"}

    async def _send_message(self, recipient: str, message: str) -> Dict[str, Any]:
        """KakaoTalk 메시지 전송 전체 플로우."""
        await self._ensure_peekaboo()
        if not self._peekaboo:
            return {"success": False, "error": "Peekaboo not available"}

        APP = self.app_name

        try:
            # 1. Open
            await self.open()
            await asyncio.sleep(1)

            # 2. Navigate to recipient
            found = await self.navigate(recipient)
            if not found:
                return {"success": False, "error": f"'{recipient}'을(를) 찾을 수 없습니다."}

            # 3. Open chat (Enter)
            await self._peekaboo.press("enter", APP)
            await asyncio.sleep(3)

            # 4. Paste message
            await self._peekaboo.paste(message, APP)
            await asyncio.sleep(0.5)

            # 5. Send (Enter)
            await self._peekaboo.press("enter", APP)
            await asyncio.sleep(1)

            # 6. Close
            await self._peekaboo.press("escape", APP)
            await asyncio.sleep(0.5)
            await self._peekaboo.press("escape", APP)
            await asyncio.sleep(0.3)
            await self.close()

            return {
                "success": True,
                "result": f"'{recipient}'에게 메시지를 전송했습니다.",
            }
        except Exception as e:
            logger.error(f"KakaoTalk send failed: {e}")
            return {"success": False, "error": str(e)}
