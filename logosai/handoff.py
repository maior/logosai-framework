"""표준 스테이지 핸드오프 수신 (HandoffEnvelope).

멀티스테이지 워크플로우에서 에이전트가 이전 결과를 받는 방식은 실경로상 제각각이다:
context["previous_results"] dict, "[이전 단계 결과]\\n{json}\\n\\n[요청]" 직렬화 문자열
(2000자 truncate 포함), DataTransformer 의 data_points 등. 2026-07-13~15 시각화
대수리에서 이 파싱을 에이전트별 사설로 반복 작성한 것을 SDK 계약으로 승격 —
수제 에이전트와 FORGE 생성물이 동일하게 `agent.get_handoff(query, context)` 로 받는다.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 읽을 텍스트 후보 키 (JSON 원문 덤프는 숫자 배열·타임스탬프로 LLM 추출을 오염시킴)
_READABLE_KEYS = ("answer", "summary", "text", "message")


def _unwrap(result: Any, depth: int = 4) -> Any:
    """ACP 응답 래핑({"success", "data": {"result": {...}}}) 해제."""
    cur = result
    for _ in range(depth):
        if isinstance(cur, dict):
            inner = cur.get("result") if isinstance(cur.get("result"), (dict, str)) else None
            if inner is None:
                inner = cur.get("data") if isinstance(cur.get("data"), dict) else None
            if inner is not None:
                cur = inner
                continue
        break
    return cur


def readable_text(result: Any) -> str:
    """이전 결과에서 사람이 읽는 텍스트(answer/summary 등)를 우선 추출.

    읽을 텍스트가 전혀 없을 때만 JSON 덤프로 폴백 (extracted_numbers 오염 방지)."""
    cur = _unwrap(result)
    candidates: List[str] = []
    if isinstance(cur, str):
        candidates.append(cur)
    elif isinstance(cur, dict):
        content = cur.get("content", cur)
        if isinstance(content, str) and content.strip():
            candidates.append(content)
        for container in (c for c in (content, cur) if isinstance(c, dict)):
            for key in _READABLE_KEYS:
                v = container.get(key)
                if isinstance(v, str) and v.strip():
                    candidates.append(v)
    readable = [c for c in dict.fromkeys(candidates) if c.strip()]
    if readable:
        return "\n".join(readable)
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        return str(result)


def parse_data_points_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """직렬화 핸드오프 문자열에서 data_points 배열 복원.

    "[이전 단계 결과]\\n{json}\\n\\n[요청]" 형식. 2000자 truncate 로 꼬리가 잘려도
    data_points 배열은 앞부분이라 살아있으므로 괄호 매칭으로 부분 파싱한다."""
    if '"data_points"' not in text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    req_pos = text.find("[요청]")
    end = text.rfind("}", start, req_pos) if req_pos > start else text.rfind("}")
    dp = None
    if end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            dp = parsed.get("data_points") if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            dp = None
    if dp is None:
        marker = text.find('"data_points"')
        arr_start = text.find("[", marker) if marker >= 0 else -1
        if arr_start > 0:
            depth = 0
            for i in range(arr_start, len(text)):
                ch = text[i]
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            dp = json.loads(text[arr_start:i + 1])
                        except (json.JSONDecodeError, ValueError):
                            dp = None
                        break
    if isinstance(dp, list) and len(dp) >= 2 and all(isinstance(p, dict) for p in dp):
        return dp
    return None


@dataclass
class HandoffEnvelope:
    """스테이지 간 표준 수신 봉투."""
    original_query: str = ""
    sub_query: str = ""
    stages: List[Dict[str, Any]] = field(default_factory=list)  # [{agent_id, result, text}]
    data_points: Optional[List[Dict[str, Any]]] = None
    raw_text: str = ""

    @classmethod
    def from_context(cls, query: Any, context: Optional[Dict[str, Any]]) -> "HandoffEnvelope":
        env = cls()
        ctx = context if isinstance(context, dict) else {}
        env.original_query = str(ctx.get("original_query") or "")

        # 이전 스테이지 결과 수집 — dict(previous_results) / list 모두 지원
        prev = ctx.get("previous_results")
        if isinstance(query, dict) and not prev:
            prev = query.get("previous_results")
        if isinstance(prev, dict):
            items = list(prev.items())
        elif isinstance(prev, list):
            items = [(f"stage_{i}", r) for i, r in enumerate(prev)]
        else:
            items = []
        for agent_id, result in items:
            if not result:
                continue
            env.stages.append({
                "agent_id": str(agent_id),
                "result": result,
                "text": readable_text(result),
            })
            if env.data_points is None and isinstance(result, dict):
                dp = result.get("data_points")
                if isinstance(dp, list) and len(dp) >= 2:
                    env.data_points = dp

        # 오케스트레이터가 직접 세우는 단일 자료 키.
        # `ontology/orchestrator/execution_engine.py` 가 `input_data` 를 세우고,
        # docx·pptx·llm_search·summarization 이 각자 사설로 읽어 왔다. 계약이 이걸
        # 빠뜨리면 get_handoff 로 갈아탄 에이전트만 데이터를 못 보게 된다 —
        # 계약을 만들었다는 것과 계약이 실경로를 덮는다는 것은 다른 이야기다.
        # previous_results 가 정본이므로 **뒤에** 붙인다 (밀어내지 않고 보조로).
        seen = {s["text"] for s in env.stages if s.get("text")}
        for key in ("input_data", "content", "previous_result"):
            val = ctx.get(key)
            if not val:
                continue
            text = readable_text(val)
            if not text or not text.strip() or text in seen:
                continue
            seen.add(text)
            env.stages.append({"agent_id": key, "result": val, "text": text})
            if env.data_points is None and isinstance(val, dict):
                dp = val.get("data_points")
                if isinstance(dp, list) and len(dp) >= 2:
                    env.data_points = dp

        # 입력 자체 처리 (문자열 핸드오프 실경로 / dict 입력)
        if isinstance(query, str):
            env.sub_query = query
            env.raw_text = query
            if env.data_points is None:
                env.data_points = parse_data_points_text(query)
        elif isinstance(query, dict):
            env.sub_query = str(query.get("query") or query.get("text") or "")
            if env.data_points is None:
                dp = query.get("data_points")
                if isinstance(dp, list) and len(dp) >= 2:
                    env.data_points = dp
        return env

    def source_texts(self, limit_each: int = 6000) -> List[str]:
        """LLM 추출용 소스 텍스트 (스테이지별 라벨 + 상한)."""
        out = [f"[{s['agent_id']}]\n{s['text'][:limit_each]}" for s in self.stages if s.get("text")]
        if not out and self.raw_text:
            out.append(f"[input]\n{self.raw_text[:limit_each]}")
        elif self.raw_text and self.raw_text not in (self.sub_query,):
            out.append(f"[input]\n{self.raw_text[:limit_each]}")
        return out

    def best_query(self) -> str:
        """추출 프롬프트의 [사용자 요청]으로 쓸 텍스트 — 원 쿼리 우선."""
        return self.original_query or self.sub_query
