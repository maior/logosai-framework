"""HandoffEnvelope 구조화 접근 계약 (2026-08-10 C1 실측 근거).

C1 실행("서울·부산·제주 날씨 + 원달러 환율 → 엑셀 표")에서 xlsx 에이전트가
만든 표의 환율 열이 전부 ₩0 이었다. 원인은 상류가 숫자를 안 낸 것이 아니다 —
currency_exchange_agent 는 `content["raw_data"][0]["rate"] == 1418.0` 을
**구조화된 채로** 냈다. 그런데 소비자가 쓸 수 있는 유일한 통로였던
`source_texts()` 가 산문만 돌려주고, `readable_text()` 의 `_unwrap` 이
`result` 문자열로 내려가면서 형제 키(raw_data)를 통째로 버렸다.

즉 계약은 있었지만 **구조화 값을 꺼낼 접근자가 없었다.** 소비자는 산문을
재파싱할 수밖에 없었고, 재파싱이 실패한 자리가 ₩0 이다.

이 파일이 고정하는 계약:
  ① stage1 이 구조화 값을 냈으면 stage2 가 산문 재파싱 없이 그 값에 닿는다
  ② 구조화 값이 없으면 그 사실이 드러난다 (None — 산문을 몰래 긁어오지 않는다)
  ③ 기존 텍스트 경로(source_texts/readable_text/data_points)는 그대로다

직접 실행: .venv/bin/python -m pytest logosai/tests/test_handoff_structured.py
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(_ROOT, "logosai") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "logosai"))

from logosai.handoff import HandoffEnvelope  # noqa: E402


# C1 라이브 실측 그대로의 상류 결과 모양 (acp_server/agents 실제 반환 형태)
CURRENCY_RESULT = {
    "result": "# 💱 환율 조회 결과\n\n1 USD = 1,418.00 KRW",
    "reasoning": "네이버 환율 API 조회",
    "raw_data": [{"from_currency": "USD", "to_currency": "KRW", "rate": 1418.0}],
    "source_info": {"data_provider": "네이버 환율 API"},
}
WEATHER_RESULT = {
    "answer": "# 제주 현재 날씨 🌈\n\n온도 24.33°C · 습도 84%",
    "location": "제주",
    "source_info": {"api_provider": "Tomorrow.io"},
}


def _env():
    return HandoffEnvelope.from_context(
        "[이전 단계 결과]\n## 대한민국 주요 도시 날씨 및 환율 정보\n\n[요청]\n엑셀 표로",
        {
            "original_query": "서울·부산·제주 날씨와 원달러 환율을 엑셀 표로",
            "previous_results": {
                "currency_exchange_agent": CURRENCY_RESULT,
                "weather_agent": WEATHER_RESULT,
            },
        },
    )


# ── ① 구조화 값이 산문 납작화를 넘어 소비자에게 닿는다 ──────────────────

def test_structured_value_survives_prose_flattening():
    """stage1 의 rate=1418 을 stage2 가 산문 재파싱 없이 얻는다 (C1 결함 A)."""
    env = _env()
    assert env.find_value("rate") == 1418.0


def test_structured_exposes_per_stage_payloads():
    """스테이지별 구조화 payload 가 납작해지기 전 모양으로 남는다."""
    env = _env()
    items = env.structured()
    by_agent = {i["agent_id"]: i["data"] for i in items}
    assert "currency_exchange_agent" in by_agent
    # _unwrap 이 result 문자열로 내려가며 버렸던 형제 키가 살아 있어야 한다
    assert by_agent["currency_exchange_agent"]["raw_data"][0]["rate"] == 1418.0
    assert by_agent["weather_agent"]["location"] == "제주"


def test_find_value_can_be_scoped_by_agent():
    """같은 키를 여러 상류가 낼 때 소비자가 출처를 지정할 수 있다."""
    env = HandoffEnvelope.from_context("q", {"previous_results": {
        "a_agent": {"value": 1},
        "b_agent": {"value": 2},
    }})
    assert env.find_value("value", agent_id="b_agent") == 2
    assert env.find_value("value", agent_id="a_agent") == 1


# ── ② 없으면 없다고 말한다 (산문 몰래 긁기 금지) ───────────────────────

def test_missing_structured_value_is_visible():
    """weather_agent 는 온도를 구조화로 내지 않는다 — 산문에 24.33 이 있어도 None.

    조용히 산문을 긁어오면 소비자는 '데이터를 받았다'고 착각한다. C1 에서
    xlsx 가 정확히 그 착각을 했고 결과가 ₩0 이었다. 없으면 드러나야 한다.
    """
    env = _env()
    assert env.find_value("temperature") is None
    assert env.find_value("temperature", default=0) == 0


def test_find_value_ignores_none_and_keeps_falsy_zero():
    """0·False 는 값이다 — None 과 구별되어야 한다."""
    env = HandoffEnvelope.from_context("q", {"previous_results": {
        "a": {"rate": None},
        "b": {"rate": 0},
    }})
    assert env.find_value("rate") == 0


def test_acp_envelope_is_unwrapped():
    """ACP 래핑({"success", "data": {"result": {...}}}) 은 껍데기이므로 통과한다."""
    env = HandoffEnvelope.from_context("q", {"previous_results": {
        "a": {"success": True, "data": {"result": {"rate": 1418.0}}},
    }})
    assert env.structured()[0]["data"] == {"rate": 1418.0}
    assert env.find_value("rate") == 1418.0


def test_sibling_data_key_is_not_treated_as_envelope():
    """형제 데이터가 남아 있으면 안으로 들어가지 않는다 — 들어가면 그 형제를 잃는다."""
    env = HandoffEnvelope.from_context("q", {"previous_results": {
        "a": {"answer": "산문", "data": {"rows": [1, 2]}, "rate": 1418.0},
    }})
    payload = env.structured()[0]["data"]
    assert payload["rate"] == 1418.0 and payload["answer"] == "산문"
    assert env.find_value("rows") == [1, 2]


def test_structured_is_empty_without_upstream():
    env = HandoffEnvelope.from_context("단독 쿼리", None)
    assert env.structured() == []
    assert env.find_value("rate") is None


# ── ③ 기존 텍스트 경로 하위 호환 ───────────────────────────────────────

def test_text_path_unchanged():
    """source_texts/raw_text/best_query 는 종전과 동일하게 산문만 나른다.

    data_visualization_agent 가 이 텍스트로 LLM 추출을 한다 — JSON 덤프가
    섞이면 extracted_numbers 가 오염된다(handoff.py 주석의 그 이유).
    """
    env = _env()
    joined = "\n".join(env.source_texts())
    assert "1 USD = 1,418.00 KRW" in joined       # 산문은 그대로
    assert "raw_data" not in joined                # 구조화 덤프는 섞이지 않는다
    assert "source_info" not in joined
    assert env.best_query() == "서울·부산·제주 날씨와 원달러 환율을 엑셀 표로"
    assert [s["agent_id"] for s in env.stages] == [
        "currency_exchange_agent", "weather_agent"]


def test_data_points_path_unchanged():
    env = HandoffEnvelope.from_context("q", {"previous_results": {
        "a": {"data_points": [{"x": 1}, {"x": 2}]},
    }})
    assert env.data_points == [{"x": 1}, {"x": 2}]
