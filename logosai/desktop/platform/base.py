"""Desktop Platform Abstraction — cross-platform support for macOS and Linux.

Auto-detects OS and provides platform-specific implementations.
Missing tools are auto-installed on Linux (apt install).

Usage:
    from .platform import get_platform
    platform = get_platform()
    platform.activate_app("Google Chrome")
    platform.clipboard_copy("text")
    platform.screenshot("/tmp/screen.png")
    platform.press_key("Return")
    platform.type_text("hello")
"""

import platform as platform_mod
import subprocess
import shutil
from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger


class DesktopPlatform(ABC):
    """Abstract interface for desktop operations."""

    @abstractmethod
    def activate_app(self, name: str) -> bool:
        """Bring an app to the foreground."""

    @abstractmethod
    def open_app(self, name: str) -> bool:
        """Launch an application."""

    @abstractmethod
    def clipboard_copy(self, text: str) -> bool:
        """Copy text to system clipboard."""

    @abstractmethod
    def clipboard_paste(self) -> bool:
        """Simulate Cmd/Ctrl+V paste."""

    @abstractmethod
    def screenshot(self, path: str) -> bool:
        """Take a screenshot and save to path."""

    @abstractmethod
    def press_key(self, key: str) -> bool:
        """Press a keyboard key (Return, Down, Tab, etc.)."""

    @abstractmethod
    def hotkey(self, *keys: str) -> bool:
        """Press a hotkey combination (e.g., 'command', 'v')."""

    @abstractmethod
    def type_text(self, text: str) -> bool:
        """Type text. Uses clipboard for non-ASCII."""

    @abstractmethod
    def run_applescript(self, script: str) -> str:
        """Run AppleScript (macOS only, returns '' on Linux)."""

    @abstractmethod
    def chrome_execute_js(self, js: str, url_contains: str = "") -> str:
        """Execute JavaScript in a Chrome tab. url_contains filters by URL."""

    @property
    @abstractmethod
    def os_name(self) -> str:
        """Return 'macos' or 'linux'."""

    def ensure_tool(self, tool_name: str, install_cmd: Optional[str] = None) -> bool:
        """Check if a tool exists, try to install if not."""
        if shutil.which(tool_name):
            return True
        if install_cmd:
            logger.info(f"Installing missing tool: {tool_name}")
            try:
                result = subprocess.run(
                    install_cmd, shell=True, capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0 and shutil.which(tool_name):
                    logger.info(f"Installed {tool_name} successfully")
                    return True
                else:
                    logger.warning(f"Failed to install {tool_name}: {result.stderr[:200]}")
            except Exception as e:
                logger.warning(f"Install failed for {tool_name}: {e}")
        logger.warning(f"Tool not available: {tool_name}")
        return False


def get_platform() -> DesktopPlatform:
    """Auto-detect OS and return appropriate platform implementation."""
    system = platform_mod.system()
    if system == "Darwin":
        from .macos import MacOSPlatform
        return MacOSPlatform()
    elif system == "Linux":
        from .linux import LinuxPlatform
        return LinuxPlatform()
    else:
        logger.warning(f"Unsupported OS: {system}, falling back to Linux")
        from .linux import LinuxPlatform
        return LinuxPlatform()
