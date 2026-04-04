"""ScreenAnalyzer — See before you act.

Common module for all desktop sub-agents. Takes a screenshot and asks
LLM Vision to analyze the current screen state before deciding what to do.

Usage:
    analyzer = ScreenAnalyzer(llm_client)

    # Before any action: check what's on screen
    state = await analyzer.see_and_decide("KakaoTalk", "메시지를 보내려면 메인 채팅 목록이 필요")
    if state.needs_login:
        return "로그인이 필요합니다"
    if not state.is_ready:
        # Execute state.next_action first (e.g., "press Escape to go back")

    # After search: find the right item in results
    match = await analyzer.find_in_results("Google Chrome", "PyPI에서 온 메일")
"""

import asyncio
import base64
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from loguru import logger


@dataclass
class ScreenState:
    """Result of analyzing a screenshot."""
    current_state: str = ""          # Human-readable description: "채팅방 안", "메인 목록", etc.
    is_ready: bool = False           # Can we proceed with the goal?
    needs_login: bool = False        # Login screen detected?
    next_action: str = ""            # What to do: "press_escape", "click_search", "ready", etc.
    action_detail: str = ""          # Extra info: coordinates, element name, etc.
    confidence: float = 0.0          # How sure is the analysis (0-1)


@dataclass
class SearchMatch:
    """A matched item in search results."""
    found: bool = False
    index: int = -1                  # Position in list (0-based)
    text: str = ""                   # Matched text
    action: str = ""                 # How to select it: "click", "arrow_down_N", etc.
    confidence: float = 0.0


SCREENSHOT_DIR = "/tmp/desktop_agent"


class ScreenAnalyzer:
    """Analyze screen state via screenshot + LLM Vision.

    Only called at decision points — not on every action.
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # ══════════════════════════════════════════════════════════
    # Lightweight Check (~0.1s) — AppleScript/JS first
    # ══════════════════════════════════════════════════════════

    async def lightweight_check(self, app: str) -> Optional[ScreenState]:
        """Fast check using AppleScript/JS. Returns None if can't determine.

        ~0.1s vs Vision ~3s. Tries to determine state without a screenshot.
        Returns ScreenState if confident, None if Vision is needed.
        """
        import subprocess

        try:
            if app == "KakaoTalk":
                # Check if KakaoTalk window exists and get title
                result = subprocess.run(
                    ["osascript", "-e", '''
                    tell application "System Events"
                        tell process "KakaoTalk"
                            if (count of windows) = 0 then return "NO_WINDOW"
                            set wTitle to name of window 1
                            set btnCount to count of buttons of window 1
                            return wTitle & "|" & btnCount
                        end tell
                    end tell
                    '''],
                    capture_output=True, text=True, timeout=3,
                )
                output = result.stdout.strip()

                if output == "NO_WINDOW":
                    return ScreenState(current_state="no_window", is_ready=False,
                                       next_action="open_app", confidence=0.95)

                # KakaoTalk main list has "KakaoTalk" as title with many buttons
                # A chat room has the person's name as title
                if "|" in output:
                    title, btn_count = output.rsplit("|", 1)
                    if title == "KakaoTalk" or title == "카카오톡":
                        return ScreenState(current_state="메인 채팅 목록", is_ready=True,
                                           next_action="ready", confidence=0.85)
                    else:
                        return ScreenState(current_state=f"채팅방: {title}", is_ready=False,
                                           next_action="press_escape", confidence=0.8)

            elif app == "Google Chrome":
                # Check active tab URL
                result = subprocess.run(
                    ["osascript", "-e", '''
                    tell application "Google Chrome"
                        if (count of windows) = 0 then return "NO_WINDOW"
                        set tabURL to URL of active tab of front window
                        set tabTitle to title of active tab of front window
                        return tabURL & "|" & tabTitle
                    end tell
                    '''],
                    capture_output=True, text=True, timeout=3,
                )
                output = result.stdout.strip()

                if output == "NO_WINDOW":
                    return ScreenState(current_state="no_window", is_ready=False,
                                       next_action="open_app", confidence=0.95)

                if "|" in output:
                    url, title = output.split("|", 1)
                    if "mail.google" in url:
                        if "view=cm" in url or "compose" in url.lower():
                            return ScreenState(current_state="Gmail compose", is_ready=True,
                                               next_action="ready", confidence=0.9)
                        return ScreenState(current_state="Gmail inbox", is_ready=True,
                                           next_action="ready", confidence=0.9)
                    elif "login" in url.lower() or "signin" in url.lower() or "accounts.google" in url:
                        return ScreenState(current_state="login page", is_ready=False,
                                           needs_login=True, next_action="login_required", confidence=0.9)
                    elif "chatgpt.com" in url or "claude.ai" in url or "gemini.google" in url:
                        if "login" in title.lower() or "sign" in title.lower():
                            return ScreenState(current_state="AI login", is_ready=False,
                                               needs_login=True, next_action="login_required", confidence=0.85)
                        return ScreenState(current_state=f"AI service: {title[:30]}", is_ready=True,
                                           next_action="ready", confidence=0.85)

            elif app == "Notion":
                result = subprocess.run(
                    ["osascript", "-e", '''
                    tell application "System Events"
                        if not (exists process "Notion") then return "NOT_RUNNING"
                        tell process "Notion"
                            if (count of windows) = 0 then return "NO_WINDOW"
                            return name of window 1
                        end tell
                    end tell
                    '''],
                    capture_output=True, text=True, timeout=3,
                )
                output = result.stdout.strip()
                if output == "NOT_RUNNING" or output == "NO_WINDOW":
                    return ScreenState(current_state="not_running", is_ready=False,
                                       next_action="open_app", confidence=0.9)
                return ScreenState(current_state=f"Notion: {output[:30]}", is_ready=True,
                                   next_action="ready", confidence=0.8)

        except Exception as e:
            logger.debug(f"lightweight_check failed for {app}: {e}")

        return None  # Can't determine → need Vision

    # ══════════════════════════════════════════════════════════
    # Core: See and Decide (lightweight first, Vision fallback)
    # ══════════════════════════════════════════════════════════

    async def see_and_decide(self, app: str, goal: str) -> ScreenState:
        """Analyze screen state — lightweight check first, Vision fallback.

        1. Try lightweight_check (~0.1s) — AppleScript/JS
        2. If inconclusive → Fall back to Vision (~3s) — screenshot + Gemini

        Args:
            app: Application name (e.g., "KakaoTalk", "Google Chrome")
            goal: What we're trying to do

        Returns:
            ScreenState with current state and recommended next action
        """
        # Step 1: Lightweight check (~0.1s)
        quick = await self.lightweight_check(app)
        if quick and quick.confidence >= 0.8:
            logger.info(f"  ScreenAnalyzer: lightweight → {quick.current_state} (conf={quick.confidence})")
            return quick

        # Step 2: Vision fallback (~3s)
        logger.debug(f"  ScreenAnalyzer: lightweight inconclusive, using Vision for {app}")
        screenshot_path = await self._capture(app)
        if not screenshot_path:
            return quick or ScreenState(current_state="screenshot_failed", next_action="retry")

        img_b64 = self._encode_image(screenshot_path)
        if not img_b64:
            return quick or ScreenState(current_state="encode_failed", next_action="retry")

        prompt = (
            f"앱: {app}\n"
            f"목표: {goal}\n\n"
            "이 스크린샷을 분석해주세요.\n\n"
            "1. 현재 화면 상태를 한 줄로 설명 (예: '채팅방 안', '메인 채팅 목록', '로그인 화면')\n"
            "2. 목표를 수행할 수 있는 상태인가? (is_ready: true/false)\n"
            "3. 로그인이 필요한가? (needs_login: true/false)\n"
            "4. 목표 수행을 위해 다음에 해야 할 행동 (next_action):\n"
            "   - 'ready': 바로 진행 가능\n"
            "   - 'press_escape': 뒤로가기/닫기 필요\n"
            "   - 'close_dialog': 팝업/다이얼로그 닫기 필요\n"
            "   - 'login_required': 로그인 필요\n"
            "   - 'navigate_home': 메인 화면으로 이동 필요\n"
            "   - 기타 구체적 행동\n\n"
            'JSON만 반환:\n'
            '{"current_state": "...", "is_ready": true/false, "needs_login": false, '
            '"next_action": "ready", "confidence": 0.9}'
        )

        result = await self._vision_query(img_b64, prompt)
        if not result:
            # Vision failed — assume ready and proceed (fallback)
            logger.warning(f"ScreenAnalyzer: Vision failed for {app}, assuming ready")
            return ScreenState(current_state="unknown", is_ready=True, next_action="ready", confidence=0.3)

        return ScreenState(
            current_state=result.get("current_state", "unknown"),
            is_ready=result.get("is_ready", False),
            needs_login=result.get("needs_login", False),
            next_action=result.get("next_action", "ready"),
            action_detail=result.get("action_detail", ""),
            confidence=result.get("confidence", 0.5),
        )

    # ══════════════════════════════════════════════════════════
    # Login Check (lightweight — for web apps)
    # ══════════════════════════════════════════════════════════

    async def check_login(self, app: str) -> bool:
        """Quick check: is the app showing a login page?

        Tries lightweight check first (URL inspection), Vision only if needed.

        Returns:
            True if login is needed, False if logged in
        """
        # Lightweight: check URL for login indicators
        quick = await self.lightweight_check(app)
        if quick and quick.confidence >= 0.8:
            return quick.needs_login
        screenshot_path = await self._capture(app)
        if not screenshot_path:
            return False  # Can't tell, assume OK

        img_b64 = self._encode_image(screenshot_path)
        if not img_b64:
            return False

        prompt = (
            f"이 {app} 스크린샷이 로그인/가입 화면인지 판단해주세요.\n"
            "로그인 버튼, 이메일/비밀번호 입력 필드, 'Sign in', 'Log in' 등이 보이면 로그인 화면.\n"
            "채팅, 입력창, 콘텐츠가 보이면 이미 로그인된 상태.\n\n"
            'JSON만 반환: {"needs_login": true/false, "confidence": 0.9}'
        )

        result = await self._vision_query(img_b64, prompt)
        return result.get("needs_login", False) if result else False

    # ══════════════════════════════════════════════════════════
    # Search Results: Find matching item
    # ══════════════════════════════════════════════════════════

    async def find_in_results(self, app: str, target: str) -> SearchMatch:
        """Look at search results and find the matching item.

        Args:
            app: Application name
            target: What we're looking for (e.g., "이성정", "PyPI에서 온 메일")

        Returns:
            SearchMatch with position and how to select it
        """
        screenshot_path = await self._capture(app)
        if not screenshot_path:
            return SearchMatch()

        img_b64 = self._encode_image(screenshot_path)
        if not img_b64:
            return SearchMatch()

        prompt = (
            f"앱: {app}\n"
            f"찾으려는 항목: {target}\n\n"
            "이 스크린샷의 목록/검색 결과에서 해당 항목을 찾아주세요.\n\n"
            "중요 규칙:\n"
            "- 메신저(카카오톡 등)에서 사람을 찾을 때: 반드시 **개인 채팅(1:1)**을 선택하세요\n"
            "- 그룹 채팅방(여러 이름이 나열된 항목)은 절대 선택하지 마세요\n"
            "- 개인 채팅 = 이름 하나만 표시, 그룹 = 이름 여러 개 또는 그룹명 표시\n"
            "- 이름이 정확히 일치하는 것을 우선 선택하세요\n\n"
            "1. 항목이 보이면 몇 번째인지 (0부터 시작)\n"
            "2. 해당 항목의 텍스트\n"
            "3. 선택 방법: 'arrow_down_N' (화살표 N번)\n\n"
            'JSON만 반환:\n'
            '{"found": true, "index": 0, "text": "매칭된 텍스트", '
            '"action": "arrow_down_1", "confidence": 0.9}\n\n'
            '못 찾으면: {"found": false, "confidence": 0.9}'
        )

        result = await self._vision_query(img_b64, prompt)
        if not result:
            return SearchMatch()

        return SearchMatch(
            found=result.get("found", False),
            index=result.get("index", -1),
            text=result.get("text", ""),
            action=result.get("action", ""),
            confidence=result.get("confidence", 0.5),
        )

    # ══════════════════════════════════════════════════════════
    # Internals
    # ══════════════════════════════════════════════════════════

    async def _capture(self, app: str) -> Optional[str]:
        """Take a screenshot of the app window.

        Strategy (in order):
          1. CGWindowListCopyWindowInfo → get real CG window ID → screencapture -l
             This works for ALL apps (including KakaoTalk) regardless of
             System Events accessibility support.
          2. Peekaboo app-specific screenshot (if available)
          3. Activate + full-screen screencapture (last resort)
        """
        ts = int(time.time() * 1000)
        safe_name = app.replace(" ", "_").lower()
        path = os.path.join(SCREENSHOT_DIR, f"{safe_name}_{ts}.png")

        # Auto-cleanup old screenshots (non-blocking, every 5 min)
        self.cleanup_old_screenshots()

        # ── Strategy 1: CoreGraphics window ID (most reliable) ──
        cg_wid = await self._get_cg_window_id(app)
        if cg_wid:
            try:
                subprocess.run(
                    ["screencapture", "-x", "-o", "-l", str(cg_wid), path],
                    timeout=5, capture_output=True,
                )
                if os.path.exists(path) and os.path.getsize(path) > 1000:
                    logger.info(f"  Captured CG window {cg_wid} of {app}")
                    return path
            except Exception as e:
                logger.debug(f"  screencapture -l {cg_wid} failed: {e}")

        # ── Strategy 2: Peekaboo (app-specific) ──
        try:
            from .peekaboo_client import PeekabooClient
            captured = await PeekabooClient.image(app, path)
            if captured and os.path.exists(path) and os.path.getsize(path) > 1000:
                logger.info(f"  Captured via Peekaboo for {app}")
                return path
        except Exception:
            pass

        # ── Strategy 3: Activate + full screen (fallback) ──
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app}" to activate'],
                timeout=3, capture_output=True,
            )
            await asyncio.sleep(1.5)
            subprocess.run(["screencapture", "-x", path], timeout=5, capture_output=True)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                logger.info(f"  Captured full screen (fallback) for {app}")
                return path
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")

        return None

    async def _get_cg_window_id(self, app: str) -> Optional[int]:
        """Get the CoreGraphics window ID for an app using Quartz.

        Uses CGWindowListCopyWindowInfo which works for ALL apps,
        even those that don't expose windows via System Events (like KakaoTalk).
        Searches ALL windows (including off-screen/secondary displays) and
        picks the largest layer-0 window owned by the app.
        """
        try:
            import Quartz
            window_list = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            )
            best_wid = None
            best_area = 0
            for win in window_list:
                owner = win.get(Quartz.kCGWindowOwnerName, "")
                layer = win.get(Quartz.kCGWindowLayer, 999)
                if owner == app and layer == 0:
                    bounds = win.get(Quartz.kCGWindowBounds, {})
                    w = bounds.get("Width", 0)
                    h = bounds.get("Height", 0)
                    area = w * h
                    # Pick the largest normal window (skip menu bar items, tiny popups)
                    if area > best_area and w > 100 and h > 100:
                        best_area = area
                        best_wid = win.get(Quartz.kCGWindowNumber, 0)
            if best_wid:
                logger.debug(f"  CG window ID for {app}: {best_wid} (area={best_area})")
                return int(best_wid)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"  Quartz CG lookup failed: {e}")

        # Fallback: subprocess with system Python
        try:
            script = (
                "import Quartz\n"
                "wins = Quartz.CGWindowListCopyWindowInfo("
                "Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,"
                "Quartz.kCGNullWindowID)\n"
                "best, best_a = 0, 0\n"
                "for w in wins:\n"
                f"    if w.get(Quartz.kCGWindowOwnerName,'') == '{app}' and w.get(Quartz.kCGWindowLayer,999) == 0:\n"
                "        b = w.get(Quartz.kCGWindowBounds, {})\n"
                "        a = b.get('Width',0) * b.get('Height',0)\n"
                "        if a > best_a and b.get('Width',0) > 100 and b.get('Height',0) > 100:\n"
                "            best_a = a\n"
                "            best = w.get(Quartz.kCGWindowNumber, 0)\n"
                "if best: print(best)\n"
            )
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    ["/usr/bin/python3", "-c", script],
                    capture_output=True, text=True, timeout=5,
                ),
                timeout=8,
            )
            wid_str = result.stdout.strip()
            if wid_str and wid_str.isdigit() and int(wid_str) > 0:
                logger.debug(f"  CG window ID for {app}: {wid_str} (subprocess)")
                return int(wid_str)
        except Exception as e:
            logger.debug(f"  CG subprocess lookup failed: {e}")

        return None

    def _encode_image(self, path: str) -> Optional[str]:
        """Read image, resize if too large, and encode to base64."""
        try:
            from PIL import Image
            import io

            img = Image.open(path)
            # Resize if larger than 1280px width (retina screens are huge)
            max_width = 1280
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            # PIL not available — use raw file
            try:
                with open(path, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                return None
        except Exception:
            try:
                with open(path, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                return None

    async def _vision_query(self, img_b64: str, prompt: str) -> Optional[Dict]:
        """Send image + prompt to Gemini Vision and parse JSON response."""
        try:
            from google import genai
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                logger.warning("ScreenAnalyzer: GOOGLE_API_KEY not set")
                return None

            client = genai.Client(api_key=api_key)
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-2.5-flash-lite",
                    contents=[{"parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                    ]}],
                ),
                timeout=15,
            )

            text = response.text if hasattr(response, 'text') else str(response)
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            logger.debug(f"ScreenAnalyzer: no JSON in response: {text[:100]}")

        except asyncio.TimeoutError:
            logger.warning("ScreenAnalyzer: Vision timeout (15s)")
        except Exception as e:
            logger.warning(f"ScreenAnalyzer: Vision error: {e}")

        return None

    # ══════════════════════════════════════════════════════════
    # Intent Verification — verify before final action
    # ══════════════════════════════════════════════════════════

    async def verify_ready_to_act(self, app: str, checklist: Dict[str, str]) -> Dict[str, Any]:
        """Verify all preconditions before executing a final action.

        Uses ONE Vision call to check multiple items.
        Uses lightweight_check first — Vision only if needed.

        Args:
            app: "Google Chrome"
            checklist: {
                "compose_open": "Gmail compose 창이 열려있는가",
                "recipient_filled": "받는사람이 입력되어 있는가",
                "attachment_visible": "첨부 파일이 보이는가",
            }

        Returns:
            {
                "all_passed": bool,
                "results": {"compose_open": True, "attachment_visible": False},
                "details": {"attachment_visible": "첨부 파일 안 보임"}
            }
        """
        # Try lightweight check first
        quick = await self.lightweight_check(app)
        if quick and quick.confidence >= 0.85:
            # Can answer some questions from lightweight
            results = {}
            details = {}
            for key, question in checklist.items():
                if "login" in key.lower() and quick.needs_login:
                    results[key] = False
                    details[key] = "로그인 필요"
                elif "open" in key.lower() and quick.is_ready:
                    results[key] = True
                else:
                    # Can't answer this from lightweight → need Vision for remaining
                    break
            else:
                # All answered by lightweight
                return {"all_passed": all(results.values()), "results": results, "details": details}

        # Vision: check all items in one call
        screenshot_path = await self._capture(app)
        if not screenshot_path:
            return {"all_passed": True, "results": {}, "details": {"warning": "스크린샷 실패 — 판단 불가, 진행 허용"}}

        img_b64 = self._encode_image(screenshot_path)
        if not img_b64:
            return {"all_passed": True, "results": {}, "details": {"warning": "이미지 인코딩 실패 — 판단 불가, 진행 허용"}}

        checklist_text = "\n".join(f'- "{k}": {v}' for k, v in checklist.items())
        prompt = (
            f"앱: {app}\n\n"
            f"아래 항목들이 현재 화면에서 충족되는지 확인해주세요:\n{checklist_text}\n\n"
            "각 항목에 대해 true/false와 설명을 JSON으로 반환:\n"
            '{"results": {"항목1": true, "항목2": false}, "details": {"항목2": "안 보이는 이유"}}'
        )

        result = await self._vision_query(img_b64, prompt)
        if not result:
            return {"all_passed": True, "results": {}, "details": {"warning": "Vision 분석 실패 — 판단 불가, 진행 허용"}}

        results = result.get("results", {})
        details = result.get("details", {})
        return {
            "all_passed": all(results.values()) if results else True,  # Empty = can't determine = allow
            "results": results,
            "details": details,
        }

    _last_cleanup = 0.0

    def cleanup_old_screenshots(self, max_age_seconds: int = 300):
        """Remove screenshots older than max_age_seconds. Auto-called every 5 min."""
        now = time.time()
        if now - ScreenAnalyzer._last_cleanup < 300:
            return  # Skip if cleaned recently
        ScreenAnalyzer._last_cleanup = now
        try:
            removed = 0
            for f in os.listdir(SCREENSHOT_DIR):
                path = os.path.join(SCREENSHOT_DIR, f)
                if os.path.isfile(path) and now - os.path.getmtime(path) > max_age_seconds:
                    os.remove(path)
                    removed += 1
            if removed:
                logger.debug(f"Cleaned up {removed} old screenshots")
        except Exception:
            pass
