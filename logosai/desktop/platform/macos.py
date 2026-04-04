"""macOS Desktop Platform — AppleScript, Peekaboo, pbcopy, screencapture."""

import subprocess
from typing import Optional
from loguru import logger
from .base import DesktopPlatform


class MacOSPlatform(DesktopPlatform):
    """macOS-specific desktop operations."""

    @property
    def os_name(self) -> str:
        return "macos"

    def activate_app(self, name: str) -> bool:
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{name}" to activate'],
                capture_output=True, timeout=5
            )
            return True
        except Exception as e:
            logger.warning(f"activate_app failed: {e}")
            return False

    def open_app(self, name: str) -> bool:
        app_map = {
            "엑셀": "Microsoft Excel", "메모장": "TextEdit",
            "chrome": "Google Chrome", "크롬": "Google Chrome",
            "safari": "Safari", "terminal": "Terminal",
            "카카오톡": "KakaoTalk", "slack": "Slack",
        }
        app_name = app_map.get(name.lower(), name)
        try:
            subprocess.Popen(["open", "-a", app_name])
            return True
        except Exception as e:
            logger.warning(f"open_app failed: {e}")
            return False

    def clipboard_copy(self, text: str) -> bool:
        try:
            proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            proc.communicate(text.encode('utf-8'))
            return True
        except Exception as e:
            logger.warning(f"clipboard_copy failed: {e}")
            return False

    def clipboard_paste(self) -> bool:
        try:
            import pyautogui
            pyautogui.hotkey('command', 'v')
            return True
        except Exception:
            return False

    def screenshot(self, path: str) -> bool:
        try:
            subprocess.run(["screencapture", "-x", path], timeout=5)
            return True
        except Exception as e:
            logger.warning(f"screenshot failed: {e}")
            return False

    def press_key(self, key: str) -> bool:
        try:
            import pyautogui
            pyautogui.press(key.lower())
            return True
        except Exception:
            return False

    def hotkey(self, *keys: str) -> bool:
        try:
            import pyautogui
            pyautogui.hotkey(*keys)
            return True
        except Exception:
            return False

    def type_text(self, text: str) -> bool:
        if any(ord(c) > 127 for c in text):
            self.clipboard_copy(text)
            return self.clipboard_paste()
        else:
            try:
                import pyautogui
                pyautogui.typewrite(text, interval=0.03)
                return True
            except Exception:
                return False

    def run_applescript(self, script: str) -> str:
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15
            )
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"AppleScript error: {e}")
            return f"ERROR:{e}"

    def chrome_execute_js(self, js: str, url_contains: str = "") -> str:
        """Execute JavaScript in a Chrome tab via AppleScript.

        Args:
            js: JavaScript code to execute
            url_contains: URL filter — execute in tab containing this string.
                         Empty string = active tab.
        """
        escaped_js = js.replace('\\', '\\\\').replace('"', '\\"')
        if url_contains:
            script = f'''
            tell application "Google Chrome"
                repeat with w in windows
                    repeat with t in tabs of w
                        if URL of t contains "{url_contains}" then
                            return execute t javascript "{escaped_js}"
                        end if
                    end repeat
                end repeat
                return ""
            end tell
            '''
        else:
            script = f'''
            tell application "Google Chrome"
                return execute active tab of front window javascript "{escaped_js}"
            end tell
            '''
        return self.run_applescript(script)
