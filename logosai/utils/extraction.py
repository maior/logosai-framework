"""LLM 기반 구조화 시리즈 추출 (프레임워크 공용).

2026-07-13~15 실측으로 확립한 가드 규칙의 단일 구현:
- 연도/날짜는 label, 측정값만 value (값 60%+가 1900~2100 정수면 오추출로 기각)
- 통계 요약·타임스탬프·ID·파생 지표(EMA/SMA)는 데이터가 아님
- (label, value) 중복 제거 + 30개 상한, 단위(unit) 전파
- 실패 정책은 호출측 소관: no_data → passthrough, error → 레거시 폴백

viz/analysis 의 사설 구현 2벌을 이 함수로 일원화 — FORGE 생성물도 이 함수를 쓴다.
"""

import json
from typing import Any, Dict, List, Optional, Sequence

MAX_SERIES_ITEMS = 30
MAX_CHARTS = 4
MAX_KPIS = 6

_PROMPT_TEMPLATE = """사용자의 요청과 조회된 정보에서 분석·차트용 실제 데이터 시리즈를 추출하라.

[사용자 요청]
{query}

[조회된 정보]
{sources}

규칙:
- 사용자 요청과 직접 관련된 수치만 추출한다.
- 연도/날짜/기간/항목명은 label, 측정값은 value(숫자)에 넣는다. 연도나 날짜 자체를 value로 넣지 마라. (예: "2021년 4.3%" → label "2021년", value 4.3)
- 통계 요약(평균, 표준편차, 데이터 개수), 타임스탬프, ID, 기사 번호 등 메타데이터는 데이터가 아니다.
- EMA/이동평균/SMA 같은 파생 지표 값은 series 에 넣지 마라. 원본 측정값만 추출한다 (지표는 시스템이 별도 계산).
- 같은 label을 반복하지 마라. 항목은 최대 30개.
- 차트로 그릴 실제 시리즈(서로 다른 항목 2개 이상)가 없으면 has_data를 false로 하라. 값을 지어내지 마라.
{layout_rules}
다음 JSON 형식으로만 응답하라{layout_hint}:
{schema}"""

_LAYOUT_RULES = """- 사용자 요청에 "대시보드"가 있으면 layout은 반드시 "dashboard"다. 여러 차트를 요청하면("~는 파이로, ~는 라인으로") "multi"다. 그 외에는 layout "single"에 series 하나만.
- dashboard/multi 에서는 성격이 다른 수치를 절대 한 시리즈로 합치지 마라. 예:
  "연매출 120억, 분기별 30/28/32/30억, 제품 비중 A 45% B 55%" →
  kpis=[{"label":"연매출","value":120,"unit":"억원"}],
  charts=[{"title":"분기별 매출","chart_type":"bar",...}, {"title":"제품 비중","chart_type":"pie",...}]
"""

_SCHEMA_SINGLE = '{"has_data": true, "title": "차트 제목", "unit": "단위", "series": [{"label": "항목", "value": 숫자}]}'
_SCHEMA_LAYOUT = ('{"has_data": true, "layout": "single", "title": "차트 제목", "unit": "단위", '
                  '"series": [{"label": "항목", "value": 숫자}], '
                  '"charts": [{"title": "차트별 제목", "chart_type": "bar|line|pie", "unit": "단위", '
                  '"series": [{"label": "항목", "value": 숫자}]}], '
                  '"kpis": [{"label": "지표명", "value": 숫자, "unit": "단위"}]}')


def _year_like_ratio(series: List[Dict[str, Any]]) -> float:
    if not series:
        return 0.0
    year_like = sum(
        1 for s in series
        if float(s["value"]).is_integer() and 1900 <= s["value"] <= 2100
    )
    return year_like / len(series)


def _sanitize_series(raw: Any, unit: str) -> List[Dict[str, Any]]:
    series: List[Dict[str, Any]] = []
    seen = set()
    for item in (raw or []):
        try:
            label = str(item["label"])
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if (label, value) in seen:
            continue
        seen.add((label, value))
        entry: Dict[str, Any] = {"label": label, "value": value}
        if unit:
            entry["unit"] = unit
        series.append(entry)
    return series[:MAX_SERIES_ITEMS]


async def extract_series_llm(
    llm: Any,
    query: str,
    sources: Sequence[str],
    *,
    allow_layouts: bool = False,
    total_source_limit: int = 14000,
) -> Dict[str, Any]:
    """LLM structured output 시리즈 추출.

    반환 status:
      - "ok": {series, unit, title}
      - "ok_multi" (allow_layouts): {layout, charts, kpis, title}
      - "no_data": 실제 시리즈 없음/오추출 기각 → 호출측 passthrough
      - "error": LLM 사용 불가/호출 실패 → 호출측 레거시 폴백
    """
    if llm is None:
        return {"status": "error", "reason": "no llm client"}

    prompt = _PROMPT_TEMPLATE.format(
        query=(query or "(없음)")[:2000],
        sources="\n\n".join(sources)[:total_source_limit] or "(없음)",
        layout_rules=_LAYOUT_RULES if allow_layouts else "",
        layout_hint=" (single 이면 charts/kpis 생략)" if allow_layouts else "",
        schema=_SCHEMA_LAYOUT if allow_layouts else _SCHEMA_SINGLE,
    )

    try:
        resp = await llm.invoke(prompt)
        content = resp.content if hasattr(resp, "content") else str(resp)
        start, end = content.find("{"), content.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError(f"JSON 없음: {content[:200]}")
        parsed = json.loads(content[start:end])
    except Exception as e:
        return {"status": "error", "reason": str(e)[:200]}

    if not isinstance(parsed, dict) or not parsed.get("has_data"):
        return {"status": "no_data"}

    # 멀티차트/대시보드 (사용자 명시 시에만 LLM 이 layout 을 세움)
    if allow_layouts:
        layout = str(parsed.get("layout") or "single").lower()
        if layout in ("multi", "dashboard") and isinstance(parsed.get("charts"), list):
            charts = []
            for c in parsed["charts"][:MAX_CHARTS]:
                if not isinstance(c, dict):
                    continue
                c_unit = str(c.get("unit") or "")
                c_series = _sanitize_series(c.get("series"), c_unit)
                if len(c_series) >= 2:
                    charts.append({
                        "title": str(c.get("title") or ""),
                        "chart_type": str(c.get("chart_type") or "bar").lower(),
                        "unit": c_unit,
                        "series": c_series,
                    })
            kpis = []
            for k in (parsed.get("kpis") or [])[:MAX_KPIS]:
                try:
                    kpis.append({"label": str(k["label"]), "value": float(k["value"]),
                                 "unit": str(k.get("unit") or "")})
                except (KeyError, TypeError, ValueError):
                    continue
            if len(charts) >= 2 or (charts and kpis):
                return {"status": "ok_multi", "layout": layout, "charts": charts,
                        "kpis": kpis, "title": str(parsed.get("title") or "")}
            if charts:  # 멀티 조건 미달 → 첫 차트를 single 로 강등
                parsed["series"] = charts[0]["series"]
                parsed.setdefault("unit", charts[0]["unit"])

    unit = str(parsed.get("unit") or "").strip()
    series = _sanitize_series(parsed.get("series"), unit)
    if len(series) < 2:
        return {"status": "no_data"}
    if _year_like_ratio(series) > 0.6:
        # 연도 목록을 측정값으로 오추출한 케이스 (실측: 연도 41개 시리즈 사고)
        return {"status": "no_data", "reason": "year-like values"}

    return {"status": "ok", "series": series, "unit": unit,
            "title": str(parsed.get("title") or "")}
