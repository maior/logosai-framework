"""MessagingChannel — API 기반 메시징 채널 인터페이스.

GUI 자동화 없이 API만으로 메시지를 주고받음.
FORGE가 채널 에이전트를 생성할 때 이 인터페이스를 사용.

Usage:
    from logosai.desktop.channels.telegram import TelegramChannel

    channel = TelegramChannel(token="BOT_TOKEN")
    await channel.send_message("chat_id", "Hello!")
    messages = await channel.receive_messages(limit=5)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from loguru import logger


class MessagingChannel(ABC):
    """API 기반 메시징 채널 인터페이스."""

    def __init__(self, channel_name: str = ""):
        self.channel_name = channel_name
        self.logger = logger.bind(channel=channel_name)

    @abstractmethod
    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """메시지 전송.

        Args:
            recipient: 수신자 (chat_id, channel_id, email 등)
            text: 메시지 텍스트

        Returns:
            {"success": bool, "message_id": str, "error": str}
        """

    async def send_file(self, recipient: str, file_path: str, caption: str = "") -> Dict[str, Any]:
        """파일 전송. 지원하지 않는 채널은 에러 반환."""
        return {"success": False, "error": f"{self.channel_name} does not support file sending"}

    async def receive_messages(self, limit: int = 10, **kwargs) -> List[Dict[str, Any]]:
        """최근 메시지 수신.

        Returns:
            [{"sender": str, "text": str, "timestamp": str, "message_id": str}]
        """
        return []  # 기본: 빈 리스트 (지원하지 않는 채널)

    async def health_check(self) -> bool:
        """채널 연결 상태 확인."""
        return True
