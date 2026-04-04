"""Microsoft Teams Channel — Microsoft Graph API.

Usage:
    from logosai.desktop.channels.teams import TeamsChannel

    channel = TeamsChannel(
        tenant_id=os.getenv("TEAMS_TENANT_ID"),
        client_id=os.getenv("TEAMS_CLIENT_ID"),
        client_secret=os.getenv("TEAMS_CLIENT_SECRET"),
    )
    await channel.send_message("channel_id", "Hello from LogosAI!")
"""

import os
from typing import Any, Dict, List

from .base import MessagingChannel


class TeamsChannel(MessagingChannel):
    """Microsoft Teams — Graph API 채널."""

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def __init__(self, tenant_id: str = "", client_id: str = "", client_secret: str = ""):
        super().__init__(channel_name="teams")
        self.tenant_id = tenant_id or os.getenv("TEAMS_TENANT_ID", "")
        self.client_id = client_id or os.getenv("TEAMS_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("TEAMS_CLIENT_SECRET", "")
        self._access_token = ""

    async def _get_token(self) -> str:
        """OAuth2 client_credentials로 토큰 획득."""
        if self._access_token:
            return self._access_token

        if not all([self.tenant_id, self.client_id, self.client_secret]):
            return ""

        try:
            import aiohttp
            url = self.AUTH_URL.format(tenant=self.tenant_id)
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    result = await resp.json()
                    self._access_token = result.get("access_token", "")
                    return self._access_token
        except Exception:
            return ""

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Teams 채널에 메시지 전송.

        Args:
            recipient: "team_id/channel_id" 형식
            text: 메시지 텍스트
        """
        token = await self._get_token()
        if not token:
            return {"success": False, "error": "Teams authentication failed. Check TEAMS_TENANT_ID, TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET."}

        try:
            import aiohttp
            parts = recipient.split("/")
            if len(parts) != 2:
                return {"success": False, "error": "recipient must be 'team_id/channel_id'"}

            team_id, channel_id = parts
            url = f"{self.GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "body": {"contentType": "text", "content": text},
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 201:
                        data = await resp.json()
                        return {"success": True, "message_id": data.get("id", "")}
                    return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def health_check(self) -> bool:
        token = await self._get_token()
        return bool(token)
