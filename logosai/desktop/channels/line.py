"""LINE Messaging API Channel.

Usage:
    from logosai.desktop.channels.line import LINEChannel

    channel = LINEChannel(token=os.getenv("LINE_CHANNEL_TOKEN"))
    await channel.send_message("user_id", "Hello from LogosAI!")
"""

import os
from typing import Any, Dict, List

from .base import MessagingChannel


class LINEChannel(MessagingChannel):
    """LINE Messaging API 채널."""

    API_BASE = "https://api.line.me/v2/bot"

    def __init__(self, token: str = ""):
        super().__init__(channel_name="line")
        self.token = token or os.getenv("LINE_CHANNEL_TOKEN", "")

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """LINE 메시지 전송 (push message).

        Args:
            recipient: user ID
            text: 메시지 텍스트
        """
        if not self.token:
            return {"success": False, "error": "LINE_CHANNEL_TOKEN not set"}

        try:
            import aiohttp
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            payload = {
                "to": recipient,
                "messages": [{"type": "text", "text": text}],
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.API_BASE}/message/push", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return {"success": True, "message_id": ""}
                    data = await resp.json()
                    return {"success": False, "error": data.get("message", f"HTTP {resp.status}")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_file(self, recipient: str, file_path: str, caption: str = "") -> Dict[str, Any]:
        """LINE은 이미지/파일을 URL로 전송. 로컬 파일은 업로드 후 URL 필요."""
        return {"success": False, "error": "LINE requires file URL, not local path. Upload first."}

    async def health_check(self) -> bool:
        if not self.token:
            return False
        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {self.token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.API_BASE}/info", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False
