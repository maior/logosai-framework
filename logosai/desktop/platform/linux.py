"""Linux Desktop Platform — xdotool, xclip, scrot, Chrome CDP.

Missing tools are auto-installed via apt.
"""

import json
import os
import subprocess
import shutil
from typing import Optional
from loguru import logger
from .base import DesktopPlatform


class LinuxPlatform(DesktopPlatform):
    """Linux-specific desktop operations."""

    def __init__(self):
        self._check_deps()

    def _check_deps(self):
        """Check and auto-install required tools."""
        deps = {
            "xdotool": "sudo apt-get install -y xdotool",
            "xclip": "sudo apt-get install -y xclip",
            "scrot": "sudo apt-get install -y scrot",
        }
        for tool, install_cmd in deps.items():
            if not shutil.which(tool):
                logger.info(f"Linux: {tool} not found, attempting install...")
                self.ensure_tool(tool, install_cmd)

    @property
    def os_name(self) -> str:
        return "linux"

    def activate_app(self, name: str) -> bool:
        """Activate app window using xdotool."""
        if not shutil.which("xdotool"):
            logger.warning("xdotool not available — cannot activate app")
            return False
        try:
            # Search for window by name
            result = subprocess.run(
                ["xdotool", "search", "--name", name],
                capture_output=True, text=True, timeout=5
            )
            window_ids = result.stdout.strip().split('\n')
            if window_ids and window_ids[0]:
                subprocess.run(["xdotool", "windowactivate", window_ids[0]], timeout=5)
                return True
            # Try class name
            result = subprocess.run(
                ["xdotool", "search", "--class", name],
                capture_output=True, text=True, timeout=5
            )
            window_ids = result.stdout.strip().split('\n')
            if window_ids and window_ids[0]:
                subprocess.run(["xdotool", "windowactivate", window_ids[0]], timeout=5)
                return True
            return False
        except Exception as e:
            logger.warning(f"activate_app failed: {e}")
            return False

    def open_app(self, name: str) -> bool:
        app_map = {
            "chrome": "google-chrome", "크롬": "google-chrome",
            "google chrome": "google-chrome",
            "terminal": "gnome-terminal", "터미널": "gnome-terminal",
            "finder": "nautilus", "파인더": "nautilus",
            "calculator": "gnome-calculator", "계산기": "gnome-calculator",
            "firefox": "firefox",
        }
        cmd = app_map.get(name.lower(), name.lower())
        try:
            subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            # Try xdg-open
            try:
                subprocess.Popen(["xdg-open", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                logger.warning(f"Cannot open app: {name}")
                return False

    def clipboard_copy(self, text: str) -> bool:
        if shutil.which("xclip"):
            try:
                proc = subprocess.Popen(
                    ['xclip', '-selection', 'clipboard'],
                    stdin=subprocess.PIPE
                )
                proc.communicate(text.encode('utf-8'))
                return True
            except Exception:
                pass
        if shutil.which("xsel"):
            try:
                proc = subprocess.Popen(
                    ['xsel', '--clipboard', '--input'],
                    stdin=subprocess.PIPE
                )
                proc.communicate(text.encode('utf-8'))
                return True
            except Exception:
                pass
        logger.warning("No clipboard tool available (xclip or xsel)")
        return False

    def clipboard_paste(self) -> bool:
        try:
            import pyautogui
            pyautogui.hotkey('ctrl', 'v')
            return True
        except Exception:
            return False

    def screenshot(self, path: str) -> bool:
        if shutil.which("scrot"):
            try:
                subprocess.run(["scrot", path], timeout=5)
                return os.path.exists(path)
            except Exception:
                pass
        if shutil.which("gnome-screenshot"):
            try:
                subprocess.run(["gnome-screenshot", "-f", path], timeout=5)
                return os.path.exists(path)
            except Exception:
                pass
        # Fallback: pyautogui
        try:
            import pyautogui
            img = pyautogui.screenshot()
            img.save(path)
            return True
        except Exception as e:
            logger.warning(f"screenshot failed: {e}")
            return False

    def press_key(self, key: str) -> bool:
        key_map = {
            "return": "Return", "enter": "Return",
            "down": "Down", "up": "Up", "left": "Left", "right": "Right",
            "tab": "Tab", "escape": "Escape", "space": "space",
            "backspace": "BackSpace", "delete": "Delete",
        }
        xdo_key = key_map.get(key.lower(), key)
        if shutil.which("xdotool"):
            try:
                subprocess.run(["xdotool", "key", xdo_key], timeout=5)
                return True
            except Exception:
                pass
        try:
            import pyautogui
            pyautogui.press(key.lower())
            return True
        except Exception:
            return False

    def hotkey(self, *keys: str) -> bool:
        # Convert macOS keys to Linux
        key_map = {"command": "ctrl", "cmd": "ctrl"}
        linux_keys = [key_map.get(k.lower(), k.lower()) for k in keys]

        if shutil.which("xdotool"):
            try:
                combo = "+".join(linux_keys)
                subprocess.run(["xdotool", "key", combo], timeout=5)
                return True
            except Exception:
                pass
        try:
            import pyautogui
            pyautogui.hotkey(*linux_keys)
            return True
        except Exception:
            return False

    def type_text(self, text: str) -> bool:
        if any(ord(c) > 127 for c in text):
            self.clipboard_copy(text)
            return self.clipboard_paste()
        if shutil.which("xdotool"):
            try:
                subprocess.run(["xdotool", "type", "--", text], timeout=10)
                return True
            except Exception:
                pass
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=0.03)
            return True
        except Exception:
            return False

    def run_applescript(self, script: str) -> str:
        """AppleScript is not available on Linux."""
        logger.debug("AppleScript not available on Linux")
        return ""

    def chrome_execute_js(self, js: str) -> str:
        """Execute JavaScript in Chrome via CDP (cross-platform)."""
        try:
            import aiohttp
            import asyncio

            async def _exec():
                # Find Chrome debug port
                cdp_url = "http://localhost:9222/json"
                async with aiohttp.ClientSession() as session:
                    async with session.get(cdp_url) as resp:
                        tabs = await resp.json()

                # Find Gmail tab
                gmail_tab = None
                for tab in tabs:
                    if "mail.google" in tab.get("url", ""):
                        gmail_tab = tab
                        break

                if not gmail_tab:
                    return "NO_GMAIL_TAB"

                # Execute JS via CDP WebSocket
                import websockets
                ws_url = gmail_tab["webSocketDebuggerUrl"]
                async with websockets.connect(ws_url) as ws:
                    msg = json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {"expression": js, "returnByValue": True}
                    })
                    await ws.send(msg)
                    response = await ws.recv()
                    data = json.loads(response)
                    result = data.get("result", {}).get("result", {})
                    return result.get("value", str(result))

            return asyncio.get_event_loop().run_until_complete(_exec())

        except ImportError:
            logger.warning("CDP requires: pip install websockets aiohttp")
            return ""
        except Exception as e:
            logger.warning(f"Chrome CDP failed: {e}. Start Chrome with --remote-debugging-port=9222")
            return ""
