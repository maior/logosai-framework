"""Telegram Bot API Channel.

Usage:
    from logosai.desktop.channels.telegram import TelegramChannel

    channel = TelegramChannel(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    await channel.send_message("123456789", "Hello from LogosAI!")
    messages = await channel.receive_messages(limit=5)
"""

import os
from typing import Any, Dict, List

from .base import MessagingChannel


class TelegramChannel(MessagingChannel):
    """Telegram Bot API 채널."""

    API_BASE = "https://api.telegram.org/bot{token}"

    def __init__(self, token: str = ""):
        super().__init__(channel_name="telegram")
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._base_url = self.API_BASE.format(token=self.token)

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Telegram 메시지 전송.

        Args:
            recipient: chat_id (숫자 문자열)
            text: 메시지 텍스트
            parse_mode: "HTML" or "Markdown" (optional)
        """
        if not self.token:
            return {"success": False, "error": "TELEGRAM_BOT_TOKEN not set"}

        try:
            import aiohttp
            payload = {
                "chat_id": recipient,
                "text": text,
                "parse_mode": kwargs.get("parse_mode", "HTML"),
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self._base_url}/sendMessage", json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return {"success": True, "message_id": str(data["result"]["message_id"])}
                    return {"success": False, "error": data.get("description", "Unknown error")}
        except Exception as e:
            self.logger.error(f"Telegram send failed: {e}")
            return {"success": False, "error": str(e)}

    async def send_file(self, recipient: str, file_path: str, caption: str = "") -> Dict[str, Any]:
        """Telegram 파일 전송."""
        if not self.token:
            return {"success": False, "error": "TELEGRAM_BOT_TOKEN not set"}

        try:
            import aiohttp
            data = aiohttp.FormData()
            data.add_field("chat_id", recipient)
            data.add_field("document", open(file_path, "rb"), filename=os.path.basename(file_path))
            if caption:
                data.add_field("caption", caption)

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self._base_url}/sendDocument", data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    result = await resp.json()
                    if result.get("ok"):
                        return {"success": True, "message_id": str(result["result"]["message_id"])}
                    return {"success": False, "error": result.get("description", "Unknown error")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self, limit: int = 10, **kwargs) -> List[Dict[str, Any]]:
        """최근 메시지 수신 (getUpdates)."""
        if not self.token:
            return []

        try:
            import aiohttp
            params = {"limit": limit, "timeout": 0}
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self._base_url}/getUpdates", params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        return []
                    return [
                        {
                            "sender": str(u.get("message", {}).get("from", {}).get("id", "")),
                            "sender_name": u.get("message", {}).get("from", {}).get("first_name", ""),
                            "text": u.get("message", {}).get("text", ""),
                            "timestamp": str(u.get("message", {}).get("date", "")),
                            "message_id": str(u.get("message", {}).get("message_id", "")),
                        }
                        for u in data.get("result", [])
                        if u.get("message", {}).get("text")
                    ]
        except Exception as e:
            self.logger.error(f"Telegram receive failed: {e}")
            return []

    async def health_check(self) -> bool:
        """Bot API 연결 확인 (getMe)."""
        if not self.token:
            return False
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self._base_url}/getMe", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
                    return data.get("ok", False)
        except Exception:
            return False
