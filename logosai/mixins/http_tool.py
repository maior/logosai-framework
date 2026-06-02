"""HttpToolMixin — 외부 grounded 도구를 HTTP 로 호출하는 primitive.

grounding 원칙: 에이전트가 외부 서비스(예: aicoach KG/RAG)에서 *사실*을 받아올 때
aiohttp 를 손수 쓰지 않고 이 헬퍼를 쓴다. 사실을 만들지 않고 받아온 것만 쓰도록
한 곳에 모은다. FORGE grounded-tool 생성이 만드는 relay 코드도 이 메서드를 호출한다.

상태(state) 없음 → __init__ 초기화 불필요. 순수 additive.
"""

from __future__ import annotations

import os
from typing import Dict, Any, Optional


class HttpToolMixin:
    """외부 HTTP 도구 호출 헬퍼."""

    async def call_tool_http(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        *,
        base_url: Optional[str] = None,
        base_url_env: Optional[str] = None,
        base_url_default: str = "",
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 15.0,
    ) -> Any:
        """외부 grounded 도구를 호출하고 파싱된 JSON 을 반환한다.

        base_url 해석 순서: base_url > env[base_url_env] > base_url_default.
        - GET/DELETE: params (aiohttp 가 자동 URL 인코딩 — 한글/괄호 안전)
        - POST/PUT/PATCH: json=payload (+ params 있으면 함께)

        반환: 2xx 면 파싱된 JSON (dict/list). 실패/4xx/5xx/예외 면 예외를
        던지지 않고 {"error": ..., "_status": N} dict 를 반환한다 (relay 가
        graceful 하게 처리 가능하도록).
        """
        import aiohttp

        # base_url 해석: 명시 > 환경변수 > 기본값
        resolved = (
            base_url
            or (os.getenv(base_url_env) if base_url_env else None)
            or base_url_default
        )
        if not resolved:
            return {"error": "base_url 미지정 (base_url/base_url_env/base_url_default 중 하나 필요)"}

        url = resolved.rstrip("/") + "/" + path.lstrip("/")
        m = (method or "GET").upper()

        # aiohttp params 는 str/int/float 만 허용 → bool/None/기타를 안전 변환.
        # (LLM 파싱 결과가 bool 을 섞어 보내는 경우 'Invalid variable type' 방지)
        if params:
            _safe = {}
            for k, v in params.items():
                if v is None:
                    continue
                if isinstance(v, bool):
                    _safe[k] = "true" if v else "false"
                elif isinstance(v, (str, int, float)):
                    _safe[k] = v
                else:
                    _safe[k] = str(v)
            params = _safe

        # 관측: TraceSpan (있으면). 실패해도 호출엔 영향 없음.
        _span = None
        try:
            from logosai.utils.trace_span import TraceSpan
            _span = TraceSpan.start(
                name=f"tool_http({m} {path})",
                input_text=str(payload or params or "")[:200],
            )
        except Exception:
            _span = None

        try:
            to = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=to) as session:
                kwargs: Dict[str, Any] = {}
                if headers:
                    kwargs["headers"] = headers
                if m in ("POST", "PUT", "PATCH"):
                    kwargs["json"] = payload or {}
                    if params:
                        kwargs["params"] = params
                elif params:
                    kwargs["params"] = params  # GET/DELETE — 자동 인코딩

                async with session.request(m, url, **kwargs) as resp:
                    status = resp.status
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        text = await resp.text()
                        data = {"error": "비-JSON 응답", "_text": text[:500]}

                    if status >= 400:
                        if _span:
                            _span.end(success=False, output=f"HTTP {status}")
                        if isinstance(data, dict):
                            data.setdefault("error", f"HTTP {status}")
                            data["_status"] = status
                            return data
                        return {"error": f"HTTP {status}", "_status": status, "_body": data}

                    if _span:
                        _span.end(success=True, output=str(data)[:200])
                    return data

        except Exception as e:
            if _span:
                try:
                    _span.end(success=False, output=str(e)[:200])
                except Exception:
                    pass
            return {"error": f"도구 호출 실패: {e}", "_url": url}
