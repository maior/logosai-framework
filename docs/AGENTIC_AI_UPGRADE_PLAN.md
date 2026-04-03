# LogosAI Agentic AI Upgrade Plan

> 작성: 2026-04-02 | 최종 완료: 2026-03-31 | 하네스 엔지니어링 기반 프레임워크 업그레이드

## 최종 성숙도: 100% (44/44 완료)

LogosAI Agentic AI 프레임워크 업그레이드 **전체 완료**. 경쟁 프레임워크(LangGraph, CrewAI, OpenAI SDK, Google ADK) 수준 달성.
추가로 Self-Evolution, Desktop Agent, Browser Search 등 LogosAI 고유 기능으로 차별화.

## 경쟁 프레임워크 대비 현황

| 기능 | LogosAI | LangGraph | CrewAI | OpenAI SDK | Google ADK |
|------|---------|-----------|--------|------------|------------|
| **Tool Use 루프** | ✅ 완료 (100%) | ✅ | ✅ | ✅ | ✅ |
| **ReAct 패턴** | ✅ 완료 (100%) | ✅ | ✅ | ✅ | ✅ |
| **영속 Memory** | ✅ 완료 (100%) | ✅ | ✅ | 제한적 | ✅ |
| **LLM 스트리밍** | ✅ 완료 (100%) | ✅ | ❌ | ✅ | ✅ |
| **에러 복구/재시도** | ✅ 완료 (100%) | ✅ | ✅ | ✅ | ✅ |
| **Structured Output** | ✅ 완료 (100%) | ✅ | ✅ | ✅ | ✅ |
| **Context Management** | ✅ 완료 (100%) | ✅ | ❌ | ✅ | ✅ |
| **Multi-Agent** | ✅ call_agent+debate | ✅ | ✅ | ✅ | ✅ |
| **Self-Evolution** | ✅ 자가 진화 | ❌ | ❌ | ❌ | ❌ |
| **Desktop 제어** | ✅ 56+ 에이전트 | ❌ | ❌ | ❌ | ❌ |
| **Browser Search** | ✅ Chrome 실제 검색 | ❌ | ❌ | ❌ | ❌ |

**LogosAI 고유 강점**: Self-Evolution, Desktop Agent, Browser Search — 다른 프레임워크에 없음.

### 추가 완료 (2026-04-02)

| 기능 | 설명 |
|------|------|
| **LLM 중앙 설정** | `~/.logosai/config.json` → 프레임워크 전체 자동 적용 (모델명, temperature 등). LLMClient 초기화 시 자동 로드. |
| **모델 일괄 업데이트** | gemini-2.0 계열 → gemini-2.5-flash-lite 전체 마이그레이션 완료 |
| **Goal Decomposition** | `plan()` + `plan_stream()` 구현 → Agent Engineering Phase A 완료 (별도 문서: `AGENT_ENGINEERING_PLAN.md`) |

## Phase 1: Tool-LLM 통합 루프

### 목표
에이전트가 LLM 추론 중 도구를 선택하고, 실행하고, 결과를 관찰하는 루프.

### 현재 상태
- `agentic/tools.py`: Tool 클래스, 레지스트리 정의 ✅
- `utils/llm_client.py`: `function_call` 필드 있으나 미사용 ❌
- LLM → Tool 선택 → 실행 → 결과 주입 루프 없음 ❌

### 구현 항목
- [x] `LLMClient`에 `invoke_with_tools()` 추가 (Gemini function calling) ✅
- [x] Tool 정의 → Gemini FunctionDeclaration 자동 변환 ✅
- [x] Tool 실행 루프: LLM 호출 → tool_call 감지 → 실행 → 결과 주입 → 재호출 ✅
- [x] `LogosAIAgent`에 `run_with_tools()` 메서드 추가 ✅
- [x] 최대 루프 횟수 제한 (max_iterations=5) ✅
- [x] 내장 도구: calculator, datetime_tool, text_tool ✅
- [x] E2E 테스트: 복리계산, 날짜, 글자수, 세금 — 5/5 통과 ✅

### 파일 변경
```
logosai/utils/llm_client.py      — tools 파라미터, function calling
logosai/agentic/tools.py         — JSON Schema 변환
logosai/agent.py                 — run_with_tools() 메서드
```

### Phase 1 잔여 항목 (Phase 2 이후 진행)

Phase 1 핵심(function calling + 실행 루프 + 내장 도구)은 완료. 아래는 프로덕션 적용을 위한 잔여 항목:

- [x] **기존 ACP 에이전트에 Tool Use 적용** ✅
  - ACP server.py에서 `register_builtin_tools()` 런타임 주입
  - 에이전트 코드 변경 0줄 — 프레임워크가 자동 처리
  - `ask_llm()` 호출 시 도구 있으면 자동 `invoke_with_tools()` 사용

- [x] **사용자 커스텀 도구 등록 API** ✅
  - `agent.register_tool(name, description, executor, parameters)` 메서드
  - `agent.register_builtin_tools()` — 내장 도구 일괄 등록
  - `SimpleAgent.ask_with_tools()` — 등록된 도구 자동 사용
  - 런타임에 도구 추가/제거 가능

- [x] **오케스트레이터 통합** ✅ (런타임 주입으로 해결 — 에이전트가 도구를 자율 사용)

- [x] **도구 결과 검증** ✅ 빈/에러 결과 감지 → LLM에 재시도 안내
- [x] **도구 사용 메트릭** ✅ agent.tool_metrics → {calls, successes, failures}

---

## Phase 2: Think → Act → Observe 루프 (ReAct)

### 목표
에이전트가 복잡한 작업을 단계적으로 처리하는 ReAct 패턴.

### 현재 상태
- `agentic/core.py`: AgentState enum 정의 (THINKING, ACTING 등) ✅
- `agentic/reasoning.py`: ReasoningType enum 정의 ✅
- 실제 ReAct 루프 실행 없음 ❌

### 구현 항목
- [x] `react()` 메서드: ReAct 루프 (Think→Act→Observe 반복) ✅
- [x] Thought 파싱: LLM 응답에서 사고 과정 추출 ✅
- [x] Tool Use 통합: ReAct 루프 내에서 도구 자동 호출 ✅
- [x] Observation: 도구 결과 → messages에 주입 → LLM 재호출 ✅
- [x] Final Answer 감지: "Final Answer:" 마커로 종료 판단 ✅
- [x] Reasoning Trace: 전체 추론 과정 기록 (trace 필드) ✅
- [x] max_steps 제한 (기본 5) ✅
- [x] E2E: 복리+수익률(3 steps), 90일 후(3 steps), 파이+원넓이(5 steps) ✅

### 파일 변경
```
logosai/agent.py                 — ReAct 루프 통합
logosai/agentic/reasoning.py     — CoT/ReAct 실제 구현
logosai/agentic/core.py          — 상태 전이 로직
```

---

## Phase 3: Memory 영속화 + 컨텍스트 주입

### 목표
에이전트가 과거 경험을 기억하고, 관련 기억을 LLM 컨텍스트에 자동 주입.

### 현재 상태
- `agentic/memory.py`: Memory 타입 정의 (Short/Long/Episodic) ✅
- `storage/`: personal 브랜치에 LocalStore 있으나 코어에 없음 ❌
- LLM 호출 시 기억 주입 없음 ❌

### 구현 항목
- [x] `storage/agent_memory_store.py`: SQLite 기반 에이전트 기억 저장소 ✅
- [x] `_recall()`: 쿼리 관련 기억 검색 (키워드 + 시간 감쇠) ✅
- [x] `_memorize()`: 실행 결과를 기억으로 저장 ✅
- [x] LLM 호출 전 관련 기억 자동 주입 ✅
- [x] 기억 중요도 자동 평가 (Critical ~ Trivial) ✅
- [x] 기억 용량 관리 (오래된 것 정리, 중요한 것 유지) ✅
- [x] 테스트: 이전 대화 기억 활용 ✅

### 파일 변경
```
logosai/storage/agent_memory_store.py  — 새 파일
logosai/agentic/memory.py              — 영속화 연결
logosai/agent.py                       — _recall(), _memorize()
logosai/simple_agent.py                — ask_llm()에 기억 주입
```

---

## Phase 4: LLM 스트리밍

### 목표
LLM 응답을 토큰 단위로 실시간 스트리밍.

### 현재 상태
- `LLMClient.invoke()`: 전체 응답 대기 후 반환 ❌
- `process_stream()`: 에이전트 이벤트는 스트리밍 가능 ✅
- 토큰 단위 스트리밍 없음 ❌

### 구현 항목
- [x] `LLMClient.invoke_stream()`: Google genai 스트리밍 API 사용 ✅
- [x] `LLMClient.invoke_messages_stream()`: 멀티턴 스트리밍 ✅
- [x] `SimpleAgent.ask_llm_stream()`: 스트리밍 래퍼 ✅
- [x] `process_stream()`에서 LLM 토큰을 chunk 이벤트로 전달 ✅
- [x] SSE 서버에서 실시간 토큰 전달 ✅
- [x] 테스트: 스트리밍 응답 수신 ✅

### 파일 변경
```
logosai/utils/llm_client.py      — invoke_stream() 추가
logosai/simple_agent.py          — ask_llm_stream() 추가
logosai/agent.py                 — process_stream() LLM 스트리밍 통합
logosai/acp/simple_server.py     — SSE 토큰 전달
```

---

## Phase 5: 에러 복구 + 재시도

### 목표
LLM/도구 실패 시 자동 재시도, 프롬프트 수정, 대체 도구 사용.

### 현재 상태
- 단순 try/except 후 에러 반환 ❌
- 재시도 없음 ❌
- 프롬프트 수정 재시도 없음 ❌

### 구현 항목
- [x] `@retry` 데코레이터: 지수 백오프 (max_retries=3) ✅
- [x] LLM JSON 파싱 실패 → "JSON으로 답해줘" 재프롬프트 ✅
- [x] Tool 실행 실패 → 대체 도구 탐색 ✅
- [x] 에러 분류: recoverable vs non-recoverable ✅
- [x] max_iterations 초과 시 graceful 종료 ✅
- [x] 테스트: 의도적 실패 후 복구 ✅

### 파일 변경
```
logosai/utils/retry.py           — 새 파일 (@retry 데코레이터)
logosai/utils/llm_client.py      — 재시도 로직
logosai/agent.py                 — 에러 분류 + 복구
logosai/agentic/tools.py         — 도구 실패 대체
```

---

## 완료 기준

| Phase | 완료 기준 |
|-------|----------|
| 1 | 에이전트가 도구를 선택하고 실행 결과를 활용하여 답변 |
| 2 | 복잡한 쿼리를 3+ 단계로 분해하여 단계적 처리 |
| 3 | 이전 대화를 기억하고 관련 기억을 답변에 활용 |
| 4 | LLM 응답이 토큰 단위로 실시간 표시 |
| 5 | LLM/도구 실패 시 자동 재시도 후 정상 답변 |

## 성숙도 추적 (정밀 측정: 8카테고리 44항목)

```
시작:        34% ██████████░░░░░░░░░░░░░░░░░░░░  (15/44)
Phase 1:     40% ████████████░░░░░░░░░░░░░░░░░░  (18/44)
Phase 2:     50% ███████████████░░░░░░░░░░░░░░░  (24/44)
Phase 3:     58% █████████████████░░░░░░░░░░░░░  (26/44)
Phase 4:     65% ███████████████████░░░░░░░░░░░  (29/44)
Phase 5:     72% █████████████████████░░░░░░░░░  (32/44)
Phase 1 잔여: 81% ████████████████████████░░░░░░  (36/44)
최종:       100% ██████████████████████████████  (44/44) ← 완료
```

### 항목별 상세

| 카테고리 | 항목수 | 완료 | 비율 |
|----------|--------|------|------|
| Tool Use | 8 | 8 | 100% |
| ReAct | 7 | 7 | 100% |
| Memory | 6 | 6 | 100% |
| Multi-Agent | 6 | 6 | 100% |
| Streaming | 4 | 4 | 100% |
| Error Recovery | 5 | 5 | 100% |
| Structured Output | 4 | 4 | 100% |
| Context Window | 4 | 4 | 100% |
| **합계** | **44** | **44** | **100%** |
