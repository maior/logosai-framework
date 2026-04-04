"""Notion AppController — Keyboard + Vision 기반 Notion 제어.

Usage:
    from logosai.desktop.apps.notion import NotionController
    from logosai.desktop import get_platform

    ctrl = NotionController(platform=get_platform())
    await ctrl.open()
    result = await ctrl.action("create", title="Meeting Notes", content="Today's agenda...")
    result = await ctrl.action("search", query="Project Plan")
    await ctrl.close()
"""

import asyncio
import subprocess
from typing import Any, Dict

from loguru import logger

from .base import AppController


class NotionController(AppController):
    """Notion 앱 제어 — Keyboard shortcuts + Vision."""

    def __init__(self, platform=None, peekaboo=None):
        super().__init__(platform=platform, app_name="Notion")
        self._peekaboo = peekaboo

    async def _ensure_peekaboo(self):
        if self._peekaboo is None:
            try:
                from ..vision.peekaboo_client import PeekabooClient
                self._peekaboo = PeekabooClient
            except ImportError:
                logger.warning("PeekabooClient not available")

    async def navigate(self, target: str, **kwargs) -> bool:
        """Notion 페이지 검색 (Cmd+K)."""
        await self._ensure_peekaboo()
        if not self._peekaboo:
            return False

        APP = self.app_name
        await self._peekaboo.hotkey("command+k", APP)
        await asyncio.sleep(1)
        await self._peekaboo.paste(target, APP)
        await asyncio.sleep(2)
        await self._peekaboo.press("enter", APP)
        await asyncio.sleep(2)
        return True

    async def action(self, action_type: str, **params) -> Dict[str, Any]:
        """Notion 작업 실행.

        action_type:
            "create" — 새 페이지 (title, content)
            "search" — 페이지 검색 (query)
            "add_text" — 현재 페이지에 텍스트 추가 (text)
            "add_todos" — 체크박스 목록 추가 (items: list)
        """
        if action_type == "create":
            return await self._create_page(
                params.get("title", ""),
                params.get("content", ""),
            )
        elif action_type == "search":
            found = await self.navigate(params.get("query", ""))
            return {"success": found, "result": "페이지로 이동" if found else "검색 실패"}
        elif action_type == "add_text":
            return await self._add_text(params.get("text", ""))
        elif action_type == "add_todos":
            return await self._add_todos(params.get("items", []))
        return {"success": False, "error": f"Unknown action: {action_type}"}

    async def _create_page(self, title: str, content: str) -> Dict[str, Any]:
        """새 페이지 생성."""
        await self._ensure_peekaboo()
        if not self._peekaboo:
            return {"success": False, "error": "Peekaboo not available"}

        APP = self.app_name
        try:
            await self.open()

            # Cmd+N 새 페이지
            await self._peekaboo.hotkey("command+n", APP)
            await asyncio.sleep(2)

            # 제목 입력
            if title:
                await self._peekaboo.paste(title, APP)
                await asyncio.sleep(0.5)
                await self._peekaboo.press("enter", APP)
                await asyncio.sleep(0.5)

            # 본문 입력
            if content:
                await self._peekaboo.paste(content, APP)
                await asyncio.sleep(0.5)

            return {"success": True, "result": f"페이지 '{title}' 생성 완료"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _add_text(self, text: str) -> Dict[str, Any]:
        """현재 페이지 끝에 텍스트 추가."""
        await self._ensure_peekaboo()
        if not self._peekaboo:
            return {"success": False, "error": "Peekaboo not available"}

        APP = self.app_name
        try:
            # 페이지 끝으로 이동
            await self._peekaboo.hotkey("command+end", APP)
            await asyncio.sleep(0.5)
            await self._peekaboo.press("enter", APP)
            await asyncio.sleep(0.3)
            await self._peekaboo.paste(text, APP)
            return {"success": True, "result": "텍스트 추가 완료"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _add_todos(self, items: list) -> Dict[str, Any]:
        """체크박스 TODO 목록 추가."""
        await self._ensure_peekaboo()
        if not self._peekaboo:
            return {"success": False, "error": "Peekaboo not available"}

        APP = self.app_name
        try:
            await self._peekaboo.hotkey("command+end", APP)
            await asyncio.sleep(0.5)

            for item in items:
                await self._peekaboo.press("enter", APP)
                await asyncio.sleep(0.2)
                await self._peekaboo.paste("/todo", APP)
                await asyncio.sleep(0.3)
                await self._peekaboo.press("enter", APP)
                await asyncio.sleep(0.3)
                await self._peekaboo.paste(str(item), APP)
                await asyncio.sleep(0.2)

            return {"success": True, "result": f"{len(items)}개 TODO 추가 완료"}
        except Exception as e:
            return {"success": False, "error": str(e)}
