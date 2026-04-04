"""Peekaboo CLI wrapper for macOS desktop automation.

Provides async Python interface to Peekaboo commands:
- paste: Clipboard-based text input (Korean support)
- press: Keyboard key press
- click: Coordinate-based click
- image: Screenshot capture
- see_or_fallback: UI element detection with LLM Vision fallback
- list_apps: List running applications
"""

import asyncio
import json
import os
import shutil
import subprocess
from typing import Optional, Tuple, Dict, List
from loguru import logger


class PeekabooClient:
    """Async wrapper for Peekaboo CLI commands."""

    @staticmethod
    async def paste(text: str, app: Optional[str] = None) -> bool:
        """Paste text via clipboard (Cmd+V). Supports Korean."""
        cmd = f'peekaboo paste "{text}"'
        if app:
            cmd += f' --app "{app}"'
        return await PeekabooClient._run(cmd, f"paste to {app or 'frontmost'}")

    @staticmethod
    async def press(key: str, app: Optional[str] = None) -> bool:
        """Press a keyboard key (enter, down, up, tab, escape, etc.)."""
        cmd = f'peekaboo press {key}'
        if app:
            cmd += f' --app "{app}"'
        return await PeekabooClient._run(cmd, f"press {key}")

    @staticmethod
    async def hotkey(keys: str, app: Optional[str] = None) -> bool:
        """Press a hotkey combination (e.g., 'command+c')."""
        cmd = f'peekaboo hotkey {keys}'
        if app:
            cmd += f' --app "{app}"'
        return await PeekabooClient._run(cmd, f"hotkey {keys}")

    @staticmethod
    async def click(coords: Tuple[int, int], app: Optional[str] = None,
                    double: bool = False) -> bool:
        """Click at screen coordinates."""
        x, y = coords
        cmd = f'peekaboo click --coords {x},{y}'
        if double:
            cmd += ' --double'
        if app:
            cmd += f' --app "{app}"'
        return await PeekabooClient._run(cmd, f"click ({x},{y})")

    @staticmethod
    async def image(app: str, path: str) -> bool:
        """Capture screenshot of an app."""
        cmd = f'peekaboo image --app "{app}" --path "{path}"'
        return await PeekabooClient._run(cmd, f"screenshot {app}")

    @staticmethod
    async def list_apps() -> str:
        """List running applications."""
        result = subprocess.run(
            "peekaboo list apps", shell=True,
            capture_output=True, text=True, timeout=10
        )
        return result.stdout

    @staticmethod
    async def see(app: str, timeout: int = 30) -> Optional[Dict]:
        """Capture UI element map. Returns parsed JSON or None on timeout."""
        if not shutil.which("peekaboo"):
            return None
        try:
            result = subprocess.run(
                f'peekaboo see --app "{app}" --json --timeout-seconds {timeout}',
                shell=True, capture_output=True, text=True, timeout=timeout + 5
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return None

    @staticmethod
    async def see_or_fallback(app: str, target: str, llm_client=None) -> Optional[Dict[str, int]]:
        """Find UI element coordinates. Tries Peekaboo see first, falls back to LLM Vision.

        Args:
            app: Application name
            target: Description of element to find (e.g., "Send button")
            llm_client: LLMClient for Vision fallback

        Returns:
            {"x": int, "y": int} or None
        """
        # Strategy 1: Peekaboo see (fast, accurate when it works)
        see_result = await PeekabooClient.see(app, timeout=15)
        if see_result and see_result.get("success"):
            elements = see_result.get("elements", [])
            # Search by text match
            target_lower = target.lower()
            for elem in elements:
                name = (elem.get("text", "") or elem.get("label", "") or "").lower()
                if target_lower in name or name in target_lower:
                    return {"x": elem.get("x", 0), "y": elem.get("y", 0)}

        # Strategy 2: Screenshot + LLM Vision (slower but works for any app)
        if llm_client:
            screenshot_path = f"/tmp/desktop_agent/see_fallback_{app.replace(' ', '_')}.png"
            captured = await PeekabooClient.image(app, screenshot_path)
            if not captured or not os.path.exists(screenshot_path):
                return None

            try:
                import base64
                with open(screenshot_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()

                from PIL import Image
                img = Image.open(screenshot_path)
                img_w, img_h = img.size
                img.close()

                # Get pyautogui screen size for coordinate conversion
                import pyautogui
                screen_w, screen_h = pyautogui.size()
                scale = img_w / screen_w

                from google import genai
                client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
                response = client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=[{"parts": [
                        {"text": (
                            f"Find the UI element '{target}' in this screenshot.\n"
                            f"Image dimensions: {img_w}x{img_h} pixels.\n"
                            f'Return ONLY JSON: {{"x": number, "y": number, "found": true}}\n'
                            f'If not found: {{"found": false}}'
                        )},
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                    ]}],
                )

                import re
                match = re.search(r'\{[^{}]*\}', response.text)
                if match:
                    loc = json.loads(match.group())
                    if loc.get("found"):
                        # Convert image coords to screen coords
                        x = int(loc["x"] / scale)
                        y = int(loc["y"] / scale)
                        logger.info(f"Peekaboo fallback: found '{target}' at ({x},{y})")
                        return {"x": x, "y": y}
            except Exception as e:
                logger.warning(f"Peekaboo Vision fallback failed: {e}")

        return None

    @staticmethod
    async def _run(cmd: str, desc: str, timeout: int = 15) -> bool:
        """Execute a Peekaboo command."""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            ok = result.returncode == 0
            if ok:
                logger.debug(f"Peekaboo {desc}: OK")
            else:
                logger.warning(f"Peekaboo {desc}: FAIL — {result.stderr[:200]}")
            return ok
        except subprocess.TimeoutExpired:
            logger.error(f"Peekaboo {desc}: timeout ({timeout}s)")
            return False
        except Exception as e:
            logger.error(f"Peekaboo {desc}: error — {e}")
            return False
