"""logosai 프레임워크 계약 3종 검증 (Agentic Upgrade Phase 1, 2026-07-15).

① HandoffEnvelope — 표준 스테이지 수신 (dict context / 직렬화 문자열 / truncate 폴백)
② utils.extraction.extract_series_llm — 구조화 시리즈 추출 + 가드 일원화
③ utils.safe_json.json_safe — RFC 8259 안전 직렬화

배경: 2026-07-13~15 시각화 대수리에서 같은 로직을 에이전트별 사설로 3벌 작성
(viz._extract_data_llm ≈ analysis._extract_series_llm, 핸드오프 파싱, NaN 방어).
FORGE 생성물이 상속받도록 SDK 계약으로 승격.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_framework_contracts.py  → 마지막 줄 `RESULT: GREEN`
"""

import asyncio
import json
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run_tests  # noqa: E402

from logosai.handoff import HandoffEnvelope  # noqa: E402
from logosai.utils.extraction import extract_series_llm  # noqa: E402
from logosai.utils.safe_json import json_safe  # noqa: E402


class FakeResp:
    def __init__(self, c):
        self.content = c


class FakeLLM:
    def __init__(self, payload=None, raise_error=False):
        self.payload = payload
        self.raise_error = raise_error
        self.prompts = []

    async def invoke(self, prompt, **kw):
        self.prompts.append(prompt)
        if self.raise_error:
            raise RuntimeError("simulated 503")
        return FakeResp(json.dumps(self.payload, ensure_ascii=False))


def _setup(mp):
    block_pulse(mp)


def _teardown():
    pass


def _ctx():
    """dict context (ACP 표준: previous_results + original_query)"""
    return {
        "original_query": "삼성전자 주가 EMA 차트",
        "previous_results": {
            "internet_agent": {"result": {"content": {"answer": "일별 종가는 7/1 60,000원 …"}}},
            "analysis_agent": {"success": True, "data": {"result": {
                "summary": "추세 상승", "results": {"date_price_pairs": []}}}},
        },
    }


def _handoff_str():
    """직렬화 문자열 핸드오프 (실경로) — data_points 에 EMA 키 포함, 2000자를 넘는다."""
    return "[이전 단계 결과]\n" + json.dumps({
        "chart_type": "line",
        "data_points": [
            {"label": "07/01", "value": 60000, "EMA(5)": 60000.0},
            {"label": "07/02", "value": 60500, "EMA(5)": 60166.7},
        ],
        "context": {"data": {"result": {"summary": "x" * 3000}}},
    }, ensure_ascii=False, indent=2) + "\n\n[요청]\n차트 생성"


_GDP = {"has_data": True, "title": "GDP", "unit": "%", "series": [
    {"label": "2020년", "value": -0.7}, {"label": "2021년", "value": 4.3},
    {"label": "2022년", "value": 2.6}]}

_BOARD = {"has_data": True, "layout": "dashboard", "title": "실적",
          "kpis": [{"label": "연매출", "value": 120, "unit": "억원"}],
          "charts": [
              {"title": "분기", "chart_type": "bar", "unit": "억원",
               "series": [{"label": "1Q", "value": 30}, {"label": "2Q", "value": 28}]},
              {"title": "비중", "chart_type": "pie", "unit": "%",
               "series": [{"label": "A", "value": 60}, {"label": "B", "value": 40}]}]}


def _extract(payload=None, query="차트", texts=("텍스트",), raise_error=False, **kw):
    llm = FakeLLM(payload, raise_error=raise_error)
    result = asyncio.run(extract_series_llm(llm, query, list(texts), **kw))
    return result, llm


def _assert_extraction_can_succeed():
    """대조군 — 같은 호출이 정상 데이터에는 ok 를 낸다 (no_data/error 가 '항상 그 값'이 아님)."""
    ok, _ = _extract(_GDP)
    assert ok["status"] == "ok"


# ══════════ ① HandoffEnvelope ══════════

def test_h1_original_query_is_kept():
    """H-1 original_query 보존"""
    env = HandoffEnvelope.from_context("stage sub query", _ctx())
    assert env.original_query == "삼성전자 주가 EMA 차트"


def test_h2_all_stages_collected():
    """H-2 전 스테이지 수집 (2개)"""
    env = HandoffEnvelope.from_context("stage sub query", _ctx())
    assert len(env.stages) == 2


def test_h3_readable_text_first_not_raw_json_dump():
    """H-3 읽을 텍스트 우선 (answer/summary — JSON 원문 덤프 아님)"""
    texts = HandoffEnvelope.from_context("stage sub query", _ctx()).source_texts()
    assert any("일별 종가는" in s for s in texts)
    assert any("추세 상승" in s for s in texts)
    assert not any("date_price_pairs" in s for s in texts)


def test_h4_data_points_restored_from_string_handoff():
    """H-4 문자열 핸드오프에서 data_points 복원 (+지표 키 보존)"""
    env2 = HandoffEnvelope.from_context(_handoff_str(), {"original_query": "원 쿼리"})
    assert env2.data_points
    assert len(env2.data_points) == 2
    assert "EMA(5)" in env2.data_points[0]


def test_h5_truncated_handoff_still_parses_data_points():
    """H-5 truncate 된 핸드오프도 data_points 배열 부분 파싱"""
    full = _handoff_str()
    # 2000자 truncate 로 꼬리 잘린 JSON → 배열 부분 파싱
    truncated = full[:2000]
    assert len(full) > 2000 and not truncated.rstrip().endswith("차트 생성")   # 대조군: 실제로 잘렸다
    env3 = HandoffEnvelope.from_context(truncated, None)
    assert env3.data_points
    assert len(env3.data_points) == 2


def test_h6_empty_input_is_safe():
    """H-6 빈 입력 안전 (크래시 없음)"""
    env4 = HandoffEnvelope.from_context(None, None)
    assert env4.stages == []
    assert env4.data_points is None
    # 대조군: 입력이 있으면 같은 필드가 채워진다.
    assert HandoffEnvelope.from_context("q", _ctx()).stages
    assert HandoffEnvelope.from_context(_handoff_str(), None).data_points


def test_h7_input_data_is_absorbed():
    """H-7 input_data 흡수 (execution_engine 실경로)"""
    # input_data — ontology/orchestrator/execution_engine.py:511 이 실제로 세우는 키.
    # docx·pptx·llm_search·summarization 이 각자 사설로 읽던 것이라, 계약이 이걸
    # 빠뜨리면 get_handoff 로 갈아탄 에이전트는 데이터를 통째로 못 본다.
    # (2026-08-02 xlsx 에이전트 실측에서 드러남 — 자료를 쥐고도 인터넷 검색을 했다)
    env7 = HandoffEnvelope.from_context(
        "표로 만들어줘", {"input_data": "1월 매출 1,200만원\n2월 매출 1,850만원"})
    assert any("1월 매출" in s for s in env7.source_texts())


def test_h8_content_key_is_absorbed():
    """H-8 content 키도 흡수"""
    env8 = HandoffEnvelope.from_context("x", {"content": {"answer": "본문 텍스트"}})
    assert any("본문 텍스트" in s for s in env8.source_texts())


def test_h9_previous_results_first_input_data_alongside():
    """H-9 previous_results 우선, input_data 는 보조로 함께"""
    # previous_results 가 있으면 그쪽이 정본 — input_data 가 그걸 밀어내면 안 된다
    env9 = HandoffEnvelope.from_context("x", {
        "previous_results": {"internet_agent": {"content": {"answer": "스테이지 본문"}}},
        "input_data": "보조 자료",
    })
    txt9 = " ".join(env9.source_texts())
    assert "스테이지 본문" in txt9
    assert "보조 자료" in txt9
    assert env9.stages[0]["agent_id"] == "internet_agent"


# ══════════ ② extract_series_llm ══════════

def test_x1_normal_extraction_series_and_unit():
    """X-1 정상 추출: series + unit 전파"""
    r, _ = _extract(_GDP, "GDP 차트", ["2020년 -0.7% …"])
    assert r["status"] == "ok"
    assert len(r["series"]) == 3
    assert r["series"][0] == {"label": "2020년", "value": -0.7, "unit": "%"}


def test_x2_no_data_status():
    """X-2 데이터 없음 → no_data"""
    r2, _ = _extract({"has_data": False, "series": []}, "차트", ["뉴스 텍스트"])
    assert r2["status"] == "no_data"
    _assert_extraction_can_succeed()


def test_x3_year_valued_series_rejected():
    """X-3 연도값 시리즈 기각 → no_data"""
    years = {"has_data": True, "unit": "", "series": [
        {"label": f"항목{i}", "value": v} for i, v in enumerate([2020, 2021, 2022, 2023])]}
    r3, _ = _extract(years)
    assert r3["status"] == "no_data"
    # 대조군: 같은 모양인데 값만 연도가 아니면 받아들인다 — 기각 사유가 '연도값'이다.
    not_years = {"has_data": True, "unit": "", "series": [
        {"label": f"항목{i}", "value": v} for i, v in enumerate([12.5, 48.0, 7.25, 91.0])]}
    assert _extract(not_years)[0]["status"] == "ok"


def test_x4_dedup_and_cap_30():
    """X-4 중복 제거 + 30개 상한"""
    dup = {"has_data": True, "unit": "원", "series":
           [{"label": "A", "value": 1.5}, {"label": "A", "value": 1.5}]
           + [{"label": f"L{i}", "value": 100.0 + i} for i in range(40)]}
    assert len(dup["series"]) > 30      # 대조군: 입력은 상한을 넘는다
    r4, _ = _extract(dup)
    assert r4["status"] == "ok"
    assert [s["label"] for s in r4["series"]].count("A") == 1
    assert len(r4["series"]) <= 30


def test_x5_guard_rules_in_prompt():
    """X-5 가드 규칙이 프롬프트에 포함 (연도→label, 파생지표 제외, 지어내기 금지)"""
    _, llm5 = _extract(_GDP)
    p = llm5.prompts[0]
    assert "연도" in p
    assert "EMA" in p or "파생 지표" in p
    assert "지어내지" in p


def test_x6_llm_error_returns_error_status():
    """X-6 LLM 에러 → status error (호출측 폴백 판단)"""
    r6, llm6 = _extract(raise_error=True)
    assert llm6.prompts, "LLM 이 호출되지 않았다 — 에러 경로를 타지 않았다"
    assert r6["status"] == "error"
    _assert_extraction_can_succeed()


def test_x7_allow_layouts_dashboard_schema():
    """X-7 allow_layouts: dashboard 스키마 (charts+kpis)"""
    r7, _ = _extract(_BOARD, "대시보드로", allow_layouts=True)
    assert r7["status"] == "ok_multi"
    assert len(r7["charts"]) == 2
    assert len(r7["kpis"]) == 1


def test_x8_layouts_ignored_when_not_allowed():
    """X-8 allow_layouts=False 면 layout/charts 무시하고 series 만 (single 계약 유지)"""
    board_with_series = {**_BOARD, "series": [
        {"label": "1Q", "value": 30}, {"label": "2Q", "value": 28}]}
    r8, _ = _extract(board_with_series, "대시보드로")
    assert r8["status"] == "ok"
    assert len(r8["series"]) == 2
    assert "charts" not in r8
    # 대조군: 같은 입력에 allow_layouts=True 면 charts 가 나온다.
    assert "charts" in _extract(board_with_series, "대시보드로", allow_layouts=True)[0]


# ══════════ ③ json_safe ══════════

def _unsafe_obj():
    return {"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": -float("inf"), "e": 5}, "s": "ok"}


def test_j1_nan_inf_become_none_and_serialize():
    """J-1 NaN/±Inf → None, RFC 직렬화 성공"""
    # 대조군: 원본은 RFC 직렬화가 안 된다.
    rejected = False
    try:
        json.dumps(_unsafe_obj(), allow_nan=False)
    except ValueError:
        rejected = True
    assert rejected

    safe = json_safe(_unsafe_obj())
    json.dumps(safe, allow_nan=False)       # 예외 없이 직렬화된다
    assert safe["a"] is None
    assert safe["b"][1] is None
    assert safe["c"]["d"] is None


def test_j2_finite_values_and_types_kept():
    """J-2 유한값·타입 보존"""
    safe = json_safe(_unsafe_obj())
    assert safe["c"]["e"] == 5
    assert safe["s"] == "ok"
    assert safe["b"][0] == 1.0


# ══════════ ④ LogosAIAgent.get_handoff ══════════

def test_g1_agent_get_handoff_standard_api():
    """G-1 에이전트 표준 수신 API — FORGE 생성물 상속 지점"""
    from logosai.agent import LogosAIAgent
    agent = LogosAIAgent.__new__(LogosAIAgent)
    env5 = agent.get_handoff("서브 쿼리", _ctx())
    assert isinstance(env5, HandoffEnvelope)
    assert env5.original_query == "삼성전자 주가 EMA 차트"


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _env(monkeypatch):
        _setup(monkeypatch)
        yield
        monkeypatch.undo()
        _teardown()


def main():
    return run_tests(globals(), setup=_setup, teardown=_teardown,
                     pass_prefix="PASS  ", fail_prefix="FAIL  ", blank_before_result=True)


if __name__ == "__main__":
    sys.exit(main())
