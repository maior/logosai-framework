"""logosai 프레임워크 계약 3종 검증 (Agentic Upgrade Phase 1, 2026-07-15).

① HandoffEnvelope — 표준 스테이지 수신 (dict context / 직렬화 문자열 / truncate 폴백)
② utils.extraction.extract_series_llm — 구조화 시리즈 추출 + 가드 일원화
③ utils.safe_json.json_safe — RFC 8259 안전 직렬화

배경: 2026-07-13~15 시각화 대수리에서 같은 로직을 에이전트별 사설로 3벌 작성
(viz._extract_data_llm ≈ analysis._extract_series_llm, 핸드오프 파싱, NaN 방어).
FORGE 생성물이 상속받도록 SDK 계약으로 승격.

직접 실행: .venv/bin/python logosai/tests/test_framework_contracts.py
"""

import asyncio
import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "logosai"))

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


def t_factory(fails):
    def t(name, cond):
        print(("PASS  " if cond else "FAIL  ") + name)
        if not cond:
            fails.append(name)
    return t


def main():
    fails = []
    t = t_factory(fails)

    # ══════════ ① HandoffEnvelope ══════════
    # dict context (ACP 표준: previous_results + original_query)
    ctx = {
        "original_query": "삼성전자 주가 EMA 차트",
        "previous_results": {
            "internet_agent": {"result": {"content": {"answer": "일별 종가는 7/1 60,000원 …"}}},
            "analysis_agent": {"success": True, "data": {"result": {
                "summary": "추세 상승", "results": {"date_price_pairs": []}}}},
        },
    }
    env = HandoffEnvelope.from_context("stage sub query", ctx)
    t("H-1 original_query 보존", env.original_query == "삼성전자 주가 EMA 차트")
    t("H-2 전 스테이지 수집 (2개)", len(env.stages) == 2)
    texts = env.source_texts()
    t("H-3 읽을 텍스트 우선 (answer/summary — JSON 원문 덤프 아님)",
      any("일별 종가는" in s for s in texts) and any("추세 상승" in s for s in texts)
      and not any("date_price_pairs" in s for s in texts))

    # 직렬화 문자열 핸드오프 (실경로) + data_points(EMA 키) 복원
    handoff_str = "[이전 단계 결과]\n" + json.dumps({
        "chart_type": "line",
        "data_points": [
            {"label": "07/01", "value": 60000, "EMA(5)": 60000.0},
            {"label": "07/02", "value": 60500, "EMA(5)": 60166.7},
        ],
        "context": {"data": {"result": {"summary": "x" * 3000}}},
    }, ensure_ascii=False, indent=2) + "\n\n[요청]\n차트 생성"
    env2 = HandoffEnvelope.from_context(handoff_str, {"original_query": "원 쿼리"})
    t("H-4 문자열 핸드오프에서 data_points 복원 (+지표 키 보존)",
      env2.data_points and len(env2.data_points) == 2 and "EMA(5)" in env2.data_points[0])

    # 2000자 truncate 로 꼬리 잘린 JSON → 배열 부분 파싱
    truncated = handoff_str[:2000]
    env3 = HandoffEnvelope.from_context(truncated, None)
    t("H-5 truncate 된 핸드오프도 data_points 배열 부분 파싱",
      env3.data_points and len(env3.data_points) == 2)

    # 입력이 없거나 이상해도 안전
    env4 = HandoffEnvelope.from_context(None, None)
    t("H-6 빈 입력 안전 (크래시 없음)", env4.stages == [] and env4.data_points is None)

    # input_data — ontology/orchestrator/execution_engine.py:511 이 실제로 세우는 키.
    # docx·pptx·llm_search·summarization 이 각자 사설로 읽던 것이라, 계약이 이걸
    # 빠뜨리면 get_handoff 로 갈아탄 에이전트는 데이터를 통째로 못 본다.
    # (2026-08-02 xlsx 에이전트 실측에서 드러남 — 자료를 쥐고도 인터넷 검색을 했다)
    env7 = HandoffEnvelope.from_context(
        "표로 만들어줘", {"input_data": "1월 매출 1,200만원\n2월 매출 1,850만원"})
    t("H-7 input_data 흡수 (execution_engine 실경로)",
      any("1월 매출" in s for s in env7.source_texts()))

    env8 = HandoffEnvelope.from_context("x", {"content": {"answer": "본문 텍스트"}})
    t("H-8 content 키도 흡수", any("본문 텍스트" in s for s in env8.source_texts()))

    # previous_results 가 있으면 그쪽이 정본 — input_data 가 그걸 밀어내면 안 된다
    env9 = HandoffEnvelope.from_context("x", {
        "previous_results": {"internet_agent": {"content": {"answer": "스테이지 본문"}}},
        "input_data": "보조 자료",
    })
    txt9 = " ".join(env9.source_texts())
    t("H-9 previous_results 우선, input_data 는 보조로 함께",
      "스테이지 본문" in txt9 and "보조 자료" in txt9
      and env9.stages[0]["agent_id"] == "internet_agent")

    # ══════════ ② extract_series_llm ══════════
    GDP = {"has_data": True, "title": "GDP", "unit": "%", "series": [
        {"label": "2020년", "value": -0.7}, {"label": "2021년", "value": 4.3},
        {"label": "2022년", "value": 2.6}]}

    r = asyncio.run(extract_series_llm(FakeLLM(GDP), "GDP 차트", ["2020년 -0.7% …"]))
    t("X-1 정상 추출: series + unit 전파",
      r["status"] == "ok" and len(r["series"]) == 3
      and r["series"][0] == {"label": "2020년", "value": -0.7, "unit": "%"})

    r2 = asyncio.run(extract_series_llm(FakeLLM({"has_data": False, "series": []}), "차트", ["뉴스 텍스트"]))
    t("X-2 데이터 없음 → no_data", r2["status"] == "no_data")

    years = {"has_data": True, "unit": "", "series": [
        {"label": f"항목{i}", "value": v} for i, v in enumerate([2020, 2021, 2022, 2023])]}
    r3 = asyncio.run(extract_series_llm(FakeLLM(years), "차트", ["텍스트"]))
    t("X-3 연도값 시리즈 기각 → no_data", r3["status"] == "no_data")

    dup = {"has_data": True, "unit": "원", "series":
           [{"label": "A", "value": 1.5}, {"label": "A", "value": 1.5}]
           + [{"label": f"L{i}", "value": 100.0 + i} for i in range(40)]}
    r4 = asyncio.run(extract_series_llm(FakeLLM(dup), "차트", ["텍스트"]))
    t("X-4 중복 제거 + 30개 상한",
      r4["status"] == "ok" and [s["label"] for s in r4["series"]].count("A") == 1
      and len(r4["series"]) <= 30)

    llm5 = FakeLLM(GDP)
    asyncio.run(extract_series_llm(llm5, "차트", ["텍스트"]))
    p = llm5.prompts[0]
    t("X-5 가드 규칙이 프롬프트에 포함 (연도→label, 파생지표 제외, 지어내기 금지)",
      "연도" in p and ("EMA" in p or "파생 지표" in p) and "지어내지" in p)

    r6 = asyncio.run(extract_series_llm(FakeLLM(raise_error=True), "차트", ["텍스트"]))
    t("X-6 LLM 에러 → status error (호출측 폴백 판단)", r6["status"] == "error")

    board = {"has_data": True, "layout": "dashboard", "title": "실적",
             "kpis": [{"label": "연매출", "value": 120, "unit": "억원"}],
             "charts": [
                 {"title": "분기", "chart_type": "bar", "unit": "억원",
                  "series": [{"label": "1Q", "value": 30}, {"label": "2Q", "value": 28}]},
                 {"title": "비중", "chart_type": "pie", "unit": "%",
                  "series": [{"label": "A", "value": 60}, {"label": "B", "value": 40}]}]}
    r7 = asyncio.run(extract_series_llm(FakeLLM(board), "대시보드로", ["텍스트"], allow_layouts=True))
    t("X-7 allow_layouts: dashboard 스키마 (charts+kpis)",
      r7["status"] == "ok_multi" and len(r7["charts"]) == 2 and len(r7["kpis"]) == 1)
    board_with_series = {**board, "series": [
        {"label": "1Q", "value": 30}, {"label": "2Q", "value": 28}]}
    r8 = asyncio.run(extract_series_llm(FakeLLM(board_with_series), "대시보드로", ["텍스트"]))
    t("X-8 allow_layouts=False 면 layout/charts 무시하고 series 만 (single 계약 유지)",
      r8["status"] == "ok" and len(r8["series"]) == 2 and "charts" not in r8)

    # ══════════ ③ json_safe ══════════
    obj = {"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": -float("inf"), "e": 5}, "s": "ok"}
    safe = json_safe(obj)
    dumped = json.dumps(safe, allow_nan=False)
    t("J-1 NaN/±Inf → None, RFC 직렬화 성공",
      safe["a"] is None and safe["b"][1] is None and safe["c"]["d"] is None)
    t("J-2 유한값·타입 보존", safe["c"]["e"] == 5 and safe["s"] == "ok" and safe["b"][0] == 1.0)

    # ══════════ ④ LogosAIAgent.get_handoff ══════════
    from logosai.agent import LogosAIAgent
    agent = LogosAIAgent.__new__(LogosAIAgent)
    env5 = agent.get_handoff("서브 쿼리", ctx)
    t("G-1 에이전트 표준 수신 API — FORGE 생성물 상속 지점",
      isinstance(env5, HandoffEnvelope) and env5.original_query == "삼성전자 주가 EMA 차트")

    print("\nRESULT:", "GREEN" if not fails else f"RED ({len(fails)} failing)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
