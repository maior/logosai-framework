"""LogosAI Desktop Library — 데스크톱 앱 제어 + API 채널 통합.

에이전트가 데스크톱 앱(KakaoTalk, Gmail, Notion 등)을 제어하거나,
API 채널(Telegram, Slack, Discord 등)로 메시지를 보낼 수 있는 라이브러리.

Usage:
    # 플랫폼 도구
    from logosai.desktop import get_platform
    platform = get_platform()
    platform.activate_app("Google Chrome")

    # 앱 컨트롤러
    from logosai.desktop.apps.gmail import GmailController
    gmail = GmailController(platform=get_platform())
    await gmail.compose_and_send("user@example.com", "제목", "본문")

    # 메시징 채널
    from logosai.desktop.channels.telegram import TelegramChannel
    channel = TelegramChannel(token="BOT_TOKEN")
    await channel.send_message("chat_id", "Hello!")
"""

from .platform.base import DesktopPlatform, get_platform

__all__ = [
    "DesktopPlatform",
    "get_platform",
]
