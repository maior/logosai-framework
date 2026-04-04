"""AppController — 데스크톱 앱 제어 인터페이스.

모든 데스크톱 앱 컨트롤러가 구현해야 하는 표준 메서드.
FORGE가 데스크톱 에이전트를 생성할 때 이 인터페이스를 사용.

Usage:
    from logosai.desktop.apps.gmail import GmailController
    from logosai.desktop import get_platform

    ctrl = GmailController(platform=get_platform())
    await ctrl.open()
    result = await ctrl.action("compose", to="user@test.com", subject="Hi", body="Hello")
    await ctrl.close()
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from loguru import logger


class AppController(ABC):
    """데스크톱 앱 제어 인터페이스.

    Lifecycle: open() → navigate() → action() → verify() → close()
    """

    def __init__(self, platform=None, app_name: str = ""):
        """
        Args:
            platform: DesktopPlatform 인스턴스 (없으면 자동 감지)
            app_name: 앱 이름 (macOS 앱 이름)
        """
        if platform is None:
            from ..platform import get_platform
            platform = get_platform()
        self.platform = platform
        self.app_name = app_name
        self._prev_app: Optional[str] = None
        self.logger = logger.bind(app=app_name)

    async def open(self) -> bool:
        """앱 실행 + 활성화. 이전 활성 앱을 기억."""
        try:
            # 이전 앱 기억 (복원용)
            if self.platform.os_name == "macos":
                prev = self.platform.run_applescript(
                    'tell application "System Events" to get name of first application process whose frontmost is true'
                )
                self._prev_app = prev.strip() if prev else None

            result = self.platform.open_app(self.app_name)
            if result:
                self.platform.activate_app(self.app_name)
                import asyncio
                await asyncio.sleep(1)
            return result
        except Exception as e:
            self.logger.warning(f"Failed to open {self.app_name}: {e}")
            return False

    @abstractmethod
    async def navigate(self, target: str, **kwargs) -> bool:
        """특정 화면/대상으로 이동.

        Args:
            target: 이동 대상 (검색어, 페이지 이름, 메뉴 등)
        """

    @abstractmethod
    async def action(self, action_type: str, **params) -> Dict[str, Any]:
        """핵심 작업 실행.

        Args:
            action_type: 작업 종류 (send, read, compose, create 등)
            **params: 작업별 파라미터

        Returns:
            {"success": bool, "result": Any, "error": str}
        """

    async def verify(self, expected: str = "") -> bool:
        """작업 결과 확인. Vision AI 사용 가능."""
        return True  # 기본: 항상 성공 (서브클래스에서 오버라이드)

    async def close(self) -> bool:
        """앱/창 닫기 + 이전 상태 복원."""
        try:
            if self.platform.os_name == "macos":
                # Cmd+W로 창 닫기
                self.platform.hotkey("command", "w")
                import asyncio
                await asyncio.sleep(0.3)

                # 이전 앱으로 복원
                if self._prev_app and self._prev_app != self.app_name:
                    self.platform.activate_app(self._prev_app)
            return True
        except Exception as e:
            self.logger.warning(f"Failed to close {self.app_name}: {e}")
            return False
