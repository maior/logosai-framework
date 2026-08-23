"""
HttpToolMixin.call_tool_http 테스트 (TDD).

grounded 도구 호출 primitive: 에이전트가 외부 서비스에서 사실을 받아올 때
aiohttp 를 손수 쓰지 않고 이 헬퍼를 쓴다. grounded-tool 자동생성(FORGE)이
생성하는 relay 코드가 이 메서드를 호출한다.

aicoach(:8718) 가 떠 있어야 통합 테스트 통과 (down 이면 skip).
"""

import os
import sys
import asyncio

import pytest

AICOACH_BASE = os.getenv("AICOACH_BASE", "http://localhost:8718")


def _aicoach_up() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{AICOACH_BASE}/kg/products", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


aicoach_required = pytest.mark.skipif(
    not _aicoach_up(), reason=f"aicoach({AICOACH_BASE}) 미가동 — 통합 테스트 skip"
)


def _make_agent():
    from logosai import SimpleAgent, AgentResponse

    class _ToolAgent(SimpleAgent):
        agent_name = "도구 테스트"
        agent_description = "call_tool_http 테스트용"

        async def handle(self, query, context=None):
            return AgentResponse.success(content={})

    return _ToolAgent()


def test_call_tool_http_method_exists():
    """모든 에이전트(LogosAIAgent 파생)가 call_tool_http 를 가진다."""
    agent = _make_agent()
    assert hasattr(agent, "call_tool_http"), "call_tool_http 헬퍼가 없음"
    assert callable(agent.call_tool_http)


@aicoach_required
def test_post_returns_grounded_json():
    """POST + json payload → 파싱된 JSON dict 반환 (grounded 응답)."""
    agent = _make_agent()
    r = asyncio.run(agent.call_tool_http(
        "POST", "/kg/match",
        payload={"needs": ["잦은 운전", "가족 안전 보장"], "text": "35세 운전 많음"},
        base_url_env="AICOACH_BASE", base_url_default="http://localhost:8718",
    ))
    assert isinstance(r, dict), f"dict 가 아님: {type(r)}"
    assert "products" in r, f"grounded 응답에 products 없음: {list(r.keys())}"
    assert "error" not in r, f"에러 반환됨: {r.get('error')}"


@aicoach_required
def test_get_with_korean_params_url_encoded():
    """GET + 한글 params → 자동 URL 인코딩되어 정상 응답 (수기 curl 400 재발 방지)."""
    agent = _make_agent()
    r = asyncio.run(agent.call_tool_http(
        "GET", "/kg/product-doc",
        params={"label": "개인용 자동차보험(한화)"},
        base_url_default="http://localhost:8718",
    ))
    assert isinstance(r, dict)
    assert "clauses" in r, f"약관 조항 없음(URL 인코딩 실패 의심): {list(r.keys())}"


@aicoach_required
def test_get_params_with_bool_and_none_sanitized():
    """GET params 에 bool/None 이 있어도 aiohttp 타입 에러 없이 처리(coerce/drop).

    LLM _parse_query 가 bool 값을 만들어 params 로 넘어오던 compliance_guard
    'Invalid variable type: bool' 회귀 방지.
    """
    agent = _make_agent()
    r = asyncio.run(agent.call_tool_http(
        "GET", "/kg/compliance-checklist",
        params={"flag": True, "n": 3, "skip": None, "name": "x"},
        base_url_default="http://localhost:8718",
    ))
    assert isinstance(r, dict)
    assert "Invalid variable type" not in str(r.get("error", "")), r
    # compliance-checklist 는 params 무시하고 정상 응답
    assert "rules" in r or "error" not in r, r


@aicoach_required
def test_error_returns_dict_not_raise():
    """존재하지 않는 경로 → 예외 대신 error dict 반환 (relay 가 graceful 처리 가능)."""
    agent = _make_agent()
    r = asyncio.run(agent.call_tool_http(
        "GET", "/no/such/endpoint",
        base_url_default="http://localhost:8718", timeout=5,
    ))
    assert isinstance(r, dict)
    assert "error" in r, "실패 시 error 키가 있어야 함"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
