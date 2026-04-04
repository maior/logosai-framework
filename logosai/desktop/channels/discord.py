"""Discord Bot API Channel.

Usage:
    from logosai.desktop.channels.discord import DiscordChannel

    channel = DiscordChannel(token=os.getenv("DISCORD_BOT_TOKEN"))
    await channel.send_message("channel_id", "Hello from LogosAI!")
"""

import os
from typing import Any, Dict, List

from .base import MessagingChannel


class DiscordChannel(MessagingChannel):
    """Discord Bot API 채널."""

    API_BASE = "https://discord.com/api/v10"

    def __init__(self, token: str = ""):
        super().__init__(channel_name="discord")
        self.token = token or os.getenv("DISCORD_BOT_TOKEN", "")

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Discord 채널에 메시지 전송.

        Args:
            recipient: channel_id
            text: 메시지 텍스트
        """
        if not self.token:
            return {"success": False, "error": "DISCORD_BOT_TOKEN not set"}

        try:
            import aiohttp
            headers = {"Authorization": f"Bot {self.token}", "Content-Type": "application/json"}
            payload = {"content": text}

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.API_BASE}/channels/{recipient}/messages", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"success": True, "message_id": data.get("id", "")}
                    return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_file(self, recipient: str, file_path: str, caption: str = "") -> Dict[str, Any]:
        """Discord 파일 전송."""
        if not self.token:
            return {"success": False, "error": "DISCORD_BOT_TOKEN not set"}

        try:
            import aiohttp
            headers = {"Authorization": f"Bot {self.token}"}
            data = aiohttp.FormData()
            data.add_field("file", open(file_path, "rb"), filename=os.path.basename(file_path))
            if caption:
                data.add_field("content", caption)

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.API_BASE}/channels/{recipient}/messages", data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return {"success": True, "message_id": result.get("id", "")}
                    return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def health_check(self) -> bool:
        if not self.token:
            return False
        try:
            import aiohttp
            headers = {"Authorization": f"Bot {self.token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.API_BASE}/users/@me", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False
