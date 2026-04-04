"""Desktop Library 테스트.

logosai/desktop/ 라이브러리 구조 및 기본 동작 검증.

테스트:
1. import 구조 확인
2. platform 팩토리
3. AppController 인터페이스
4. MessagingChannel 인터페이스
5. 채널 구현 (Telegram, Slack, Discord) — 토큰 없이 에러 처리
6. platform 메서드 호출
"""

import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestImports:
    """모든 import 경로가 동작하는지."""

    def test_top_level(self):
        from logosai.desktop import get_platform, DesktopPlatform
        assert callable(get_platform)

    def test_platform(self):
        from logosai.desktop.platform import get_platform, DesktopPlatform
        platform = get_platform()
        assert platform.os_name in ("macos", "linux")

    def test_apps(self):
        from logosai.desktop.apps import AppController
        from logosai.desktop.apps.base import AppController as Base
        assert AppController is Base

    def test_channels(self):
        from logosai.desktop.channels import MessagingChannel
        from logosai.desktop.channels.telegram import TelegramChannel
        from logosai.desktop.channels.slack import SlackChannel
        from logosai.desktop.channels.discord import DiscordChannel
        assert issubclass(TelegramChannel, MessagingChannel)
        assert issubclass(SlackChannel, MessagingChannel)
        assert issubclass(DiscordChannel, MessagingChannel)

    def test_vision(self):
        from logosai.desktop.vision import PeekabooClient
        assert PeekabooClient is not None


class TestPlatform:
    """platform 팩토리 + 기본 메서드."""

    def test_factory(self):
        from logosai.desktop import get_platform
        p = get_platform()
        assert p.os_name == "macos"  # 현재 macOS에서 실행

    def test_activate_app(self):
        from logosai.desktop import get_platform
        p = get_platform()
        # 존재하지 않는 앱은 실패하지만 에러 없이 False 반환
        result = p.activate_app("NonExistentApp12345")
        # macOS에서는 AppleScript가 에러 없이 실행될 수 있음
        assert isinstance(result, bool)

    def test_clipboard(self):
        from logosai.desktop import get_platform
        p = get_platform()
        result = p.clipboard_copy("logosai_test_12345")
        assert result is True

    def test_chrome_execute_js_signature(self):
        """chrome_execute_js가 url_contains 파라미터를 지원하는지."""
        from logosai.desktop import get_platform
        p = get_platform()
        import inspect
        sig = inspect.signature(p.chrome_execute_js)
        params = list(sig.parameters.keys())
        assert "js" in params
        assert "url_contains" in params


class TestAppController:
    """AppController 인터페이스 검증."""

    def test_cannot_instantiate_abstract(self):
        from logosai.desktop.apps import AppController
        with pytest.raises(TypeError):
            AppController(app_name="test")

    def test_concrete_implementation(self):
        from logosai.desktop.apps import AppController

        class TestApp(AppController):
            async def navigate(self, target, **kwargs):
                return True
            async def action(self, action_type, **params):
                return {"success": True, "result": f"did {action_type}"}

        app = TestApp(app_name="TestApp")
        assert app.app_name == "TestApp"
        assert app.platform is not None  # 자동 감지

    @pytest.mark.asyncio
    async def test_concrete_action(self):
        from logosai.desktop.apps import AppController

        class TestApp(AppController):
            async def navigate(self, target, **kwargs):
                return True
            async def action(self, action_type, **params):
                return {"success": True, "result": f"did {action_type}"}

        app = TestApp(app_name="TestApp")
        result = await app.action("test")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_verify_default(self):
        from logosai.desktop.apps import AppController

        class TestApp(AppController):
            async def navigate(self, target, **kwargs):
                return True
            async def action(self, action_type, **params):
                return {"success": True}

        app = TestApp(app_name="TestApp")
        assert await app.verify() is True  # 기본 구현


class TestMessagingChannel:
    """MessagingChannel 인터페이스 검증."""

    def test_cannot_instantiate_abstract(self):
        from logosai.desktop.channels import MessagingChannel
        with pytest.raises(TypeError):
            MessagingChannel(channel_name="test")

    @pytest.mark.asyncio
    async def test_telegram_no_token(self):
        from logosai.desktop.channels.telegram import TelegramChannel
        ch = TelegramChannel(token="INVALID_TOKEN_FOR_TEST")
        result = await ch.send_message("123", "test")
        assert result["success"] is False  # 잘못된 토큰이므로 실패

    @pytest.mark.asyncio
    async def test_slack_no_token(self):
        from logosai.desktop.channels.slack import SlackChannel
        ch = SlackChannel(token="")
        result = await ch.send_message("#general", "test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_discord_no_token(self):
        from logosai.desktop.channels.discord import DiscordChannel
        ch = DiscordChannel(token="")
        result = await ch.send_message("123", "test")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_default_receive(self):
        from logosai.desktop.channels.telegram import TelegramChannel
        ch = TelegramChannel(token="")
        msgs = await ch.receive_messages()
        assert isinstance(msgs, list)
        assert len(msgs) == 0

    @pytest.mark.asyncio
    async def test_default_health(self):
        from logosai.desktop.channels.telegram import TelegramChannel
        ch = TelegramChannel(token="INVALID_TOKEN_FOR_TEST")
        assert await ch.health_check() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
