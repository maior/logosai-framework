"""Slack Web API Channel.

Usage:
    from logosai.desktop.channels.slack import SlackChannel

    channel = SlackChannel(token=os.getenv("SLACK_BOT_TOKEN"))
    await channel.send_message("#general", "Hello from LogosAI!")
"""

import os
from typing import Any, Dict, List

from .base import MessagingChannel


class SlackChannel(MessagingChannel):
    """Slack Web API 채널."""

    API_BASE = "https://slack.com/api"

    def __init__(self, token: str = ""):
        super().__init__(channel_name="slack")
        self.token = token or os.getenv("SLACK_BOT_TOKEN", "")

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Slack 메시지 전송.

        Args:
            recipient: channel ID or channel name (e.g., "#general", "C0123456")
            text: 메시지 텍스트
        """
        if not self.token:
            return {"success": False, "error": "SLACK_BOT_TOKEN not set"}

        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            payload = {"channel": recipient, "text": text}

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.API_BASE}/chat.postMessage", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return {"success": True, "message_id": data.get("ts", "")}
                    return {"success": False, "error": data.get("error", "Unknown error")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_file(self, recipient: str, file_path: str, caption: str = "") -> Dict[str, Any]:
        """Slack 파일 업로드."""
        if not self.token:
            return {"success": False, "error": "SLACK_BOT_TOKEN not set"}

        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {self.token}"}
            data = aiohttp.FormData()
            data.add_field("channels", recipient)
            data.add_field("file", open(file_path, "rb"), filename=os.path.basename(file_path))
            if caption:
                data.add_field("initial_comment", caption)

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.API_BASE}/files.upload", data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    result = await resp.json()
                    if result.get("ok"):
                        return {"success": True, "message_id": result.get("file", {}).get("id", "")}
                    return {"success": False, "error": result.get("error", "Unknown error")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self, limit: int = 10, **kwargs) -> List[Dict[str, Any]]:
        """채널 최근 메시지 조회.

        Args:
            kwargs["channel"]: 조회할 채널 ID (필수)
        """
        channel_id = kwargs.get("channel", "")
        if not self.token or not channel_id:
            return []

        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {self.token}"}
            params = {"channel": channel_id, "limit": limit}

            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.API_BASE}/conversations.history", params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        return []
                    return [
                        {
                            "sender": msg.get("user", ""),
                            "text": msg.get("text", ""),
                            "timestamp": msg.get("ts", ""),
                            "message_id": msg.get("ts", ""),
                        }
                        for msg in data.get("messages", [])
                    ]
        except Exception:
            return []

    async def health_check(self) -> bool:
        if not self.token:
            return False
        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {self.token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.API_BASE}/auth.test", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
                    return data.get("ok", False)
        except Exception:
            return False
