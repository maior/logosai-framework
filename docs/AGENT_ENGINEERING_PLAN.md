# LogosAI Agent Engineering Upgrade Plan

> 작성: 2026-04-02 | 하네스 엔지니어링(100%) → 에이전트 엔지니어링

## 진화 단계

```
Context Engineering → Harness Engineering (완료) → Agent Engineering (현재)

하네스: "에이전트가 동작하는 인프라" — Tool Use, ReAct, Memory, Streaming
에이전트: "에이전트가 똑똑해지는 지능" — 계획, 학습, 판단, 안전, 관찰
```

## 현재 성숙도

| 카테고리 | 상태 | 비율 |
|----------|------|------|
| **Harness (인프라)** | ✅ 완료 | 100% (44/44) |
| **Agent (지능)** | 🟡 진행 중 | ~30% (Phase A 완료) |

## 핵심 지능 (Phase A-D)

### Phase A: Goal Decomposition — 목표 재귀 분해 ✅ 완료

**현재**: ~~QueryPlanner가 1회 분해 (사전 계획만)~~ → `plan()` + `plan_stream()` 구현 완료
**목표**: 에이전트가 실행 중 목표를 하위 목표로 재귀 분해 + 동적 재계획

#### 동작 예시

```
User: "테슬라 기업분석 보고서 만들어줘"

현재:
  QueryPlanner → [internet_agent, analysis_agent, report_agent] → 실행 → 끝

Agent Engineering:
  Agent.plan("테슬라 기업분석 보고서")
    → Goal: 기업분석 보고서 작성
    → Sub-goals:
       1. 재무 실적 수집 (internet search)
       2. 경쟁사 비교 (internet search × 2)
       3. 시장 전망 분석 (analysis)
       4. 보고서 구조 설계 (planning)
       5. 최종 보고서 작성 (writing)
    → 실행 중 sub-goal 2에서 "BYD 데이터 부족" 발견
    → 동적 재계획: sub-goal 2-1 추가 ("BYD 2026 실적 검색")
    → 모든 sub-goal 완료 → 보고서 조립
```

#### 구현 체크리스트

- [x] `agent.plan()` — 목표를 하위 목표 트리로 분해 (LLM) ✅
- [x] `GoalTree` 데이터 구조 — 목표/하위목표/상태/의존성 ✅
- [x] 동적 재계획 — 실행 중 목표 추가/수정 ✅
- [x] `plan()` + `react()` 통합 — 각 하위 목표를 ReAct로 실행 ✅
- [x] 진행률 추적 — 전체 목표 대비 완료 비율 ✅
- [x] 테스트: 복잡한 3+ 단계 작업 자동 분해 + 실행 ✅

#### GoalProgress UI 통합

- **접근방식 A (orchestrator event mapping)**: 오케스트레이터의 기존 SSE 이벤트를 GoalProgress UI 컴포넌트에 매핑
- `plan_stream()`: 스트리밍 방식으로 목표 분해 과정을 실시간 전달
- 프론트엔드에서 sub-goal 진행률을 시각적으로 표시

#### LLM 중앙 설정 (config.json bridge)

- `~/.logosai/config.json` → 프레임워크 전체 LLM 설정 자동 적용
- LLMClient가 초기화 시 config.json을 읽어 모델명, temperature 등 자동 설정
- gemini-2.0 → gemini-2.5-flash-lite 전체 마이그레이션 완료

#### 파일 변경

```
logosai/agentic/planner.py        — 새 파일 (GoalTree, plan(), plan_stream())
logosai/agent.py                  — plan(), plan_stream() 메서드 추가
logosai/utils/llm_client.py       — config.json 브릿지 연동
```

---

### Phase B: Adaptive Learning — 적응 학습

**현재**: Memory에 사실 저장 → 키워드 검색
**목표**: 실행 결과에서 패턴 학습, 사용자 선호 자동 감지, 전략 적응

#### 동작 예시

```
실행 1: Tavily 검색 실패 → Browser Search 성공
실행 2: Tavily 검색 실패 → Browser Search 성공
실행 3: Tavily 검색 실패 →
  Adaptive Learning: "Tavily 3회 연속 실패, Browser Search가 대안"
  → 자동 라우팅 조정: Tavily 실패 시 즉시 Browser Search 사용

사용자 패턴:
  - "항상 한국어 답변" → 언어 선호 자동 감지
  - "오전에 짧은 답변, 오후에 상세" → 시간별 적응
  - "이 사용자는 수치 데이터를 선호" → 답변 스타일 조정
```

#### 구현 체크리스트

- [ ] `agent.learn_from_execution()` — 실행 결과에서 패턴 추출
- [ ] `PatternDetector` — 반복 성공/실패 패턴 감지
- [ ] `UserPreferenceTracker` — 사용자 선호 자동 감지 (언어, 길이, 스타일)
- [ ] `StrategyAdapter` — 감지된 패턴에 따라 행동 조정
- [ ] 학습 결과를 Memory에 자동 저장 (importance 자동 평가)
- [ ] 테스트: 반복 실행 후 행동 변화 확인

#### 파일 변경

```
logosai/agentic/learning.py       — 기존 파일 확장 (PatternDetector, StrategyAdapter)
logosai/agent.py                  — learn_from_execution() 추가
```

---

### Phase C: Composability — 에이전트 조합 파이프라인

**현재**: `call_agent()`, `delegate()` — 수동 호출
**목표**: 에이전트를 레고처럼 조합하는 파이프라인 DSL

#### 동작 예시

```python
# 현재: 하드코딩
result1 = await self.call_agent("internet_agent", query)
result2 = await self.call_agent("analysis_agent", result1["answer"])
result3 = await self.call_agent("report_agent", result2["answer"])

# Agent Engineering: 파이프라인 DSL
pipeline = (
    Pipeline("Research Report")
    .parallel(
        Step("search_a", "internet_agent", "테슬라 실적"),
        Step("search_b", "internet_agent", "BYD 실적"),
    )
    .then("analyze", "analysis_agent", depends_on=["search_a", "search_b"])
    .then("report", "report_agent", depends_on=["analyze"])
    .on_error(retry=2, fallback="llm_search_agent")
)
result = await agent.run_pipeline(pipeline)
```

#### 구현 체크리스트

- [ ] `Pipeline` 클래스 — 단계 정의 (parallel, then, on_error)
- [ ] `Step` — 개별 단계 (agent_id, query, depends_on)
- [ ] `agent.run_pipeline()` — 파이프라인 실행 엔진
- [ ] 파이프라인 직렬화/역직렬화 (JSON ↔ Pipeline)
- [ ] 에러 시 단계별 retry/fallback
- [ ] 테스트: parallel + sequential + error 복합 파이프라인

#### 파일 변경

```
logosai/pipeline.py               — 새 파일 (Pipeline, Step, PipelineRunner)
logosai/agent.py                  — run_pipeline() 추가
```

---

### Phase D: Long-term Goal Tracking — 멀티 세션 목표

**현재**: 세션 종료 시 목표 소실
**목표**: "이번 주까지 보고서 완성" 같은 장기 목표를 세션 간 추적

#### 동작 예시

```
세션 1 (월요일):
  User: "이번 주까지 테슬라 분석 보고서 완성해줘"
  Agent: 장기 목표 등록 → 재무 데이터 수집 시작 → 30% 완료

세션 2 (화요일):
  User: "보고서 어디까지 됐어?"
  Agent: Memory에서 목표 로드 → "재무 데이터 수집 완료 (30%), 경쟁사 분석 시작"
  → 경쟁사 분석 실행 → 60% 완료

세션 3 (수요일):
  Agent: 자동 알림 "보고서 60% 완료, 마감 2일 남음"
```

#### 구현 체크리스트

- [ ] `Goal` 데이터 모델 — title, deadline, progress, sub_goals, status
- [ ] `agent.set_goal()` / `agent.update_goal()` — 목표 관리
- [ ] Goals → AgentMemoryStore 영속화 (memory_type="goal")
- [ ] 세션 시작 시 미완료 목표 자동 로드
- [ ] 진행률 자동 업데이트
- [ ] 테스트: 멀티 세션 목표 생성 → 진행 → 완료

#### 파일 변경

```
logosai/agentic/goals.py          — 새 파일 (Goal, GoalTracker)
logosai/agent.py                  — set_goal(), update_goal(), load_goals()
```

---

## 안전 + 운영 (Phase E-H)

### Phase E: SSE Bidirectional V2 — Workflow-Level Interaction ✅ 완료 (2026-04-02)

**V1 (폐기)**: 에이전트 레벨에서 `request_approval()` → 에이전트 실행 중 승인 대기
**V2 (현재)**: logos_api InteractionEngine이 쿼리 분석 → 에이전트 실행 **전** 사전 인터랙션 → enriched context로 에이전트 호출

#### V2 아키텍처

```
User Query → InteractionEngine.analyze_query()
  → 인터랙션 필요? → Yes → interaction_required SSE 이벤트 → 프론트엔드 다이얼로그
                        → 사용자 응답 → POST /api/v1/interaction/{request_id}
                        → enriched context 생성 → 에이전트 호출
                   → No → 바로 에이전트 호출
```

#### 핵심 변경 (V1 → V2)

| V1 | V2 |
|----|-----|
| 에이전트가 `request_approval()` 호출 | InteractionEngine이 쿼리 사전 분석 |
| 에이전트 실행 중 블로킹 | 에이전트 실행 전 인터랙션 완료 |
| approval/choice/input 3종 | confirm/select/checkbox/form 4종 + multi-step |
| ACP 서버에 ApprovalManager | logos_api에 InteractionEngine |
| 에이전트 코드 수정 필요 | 에이전트 코드 수정 불필요 (enriched context만 받음) |

#### 인터랙션 타입 4종

| 타입 | 용도 | 예시 |
|------|------|------|
| `confirm` | 위험 작업 확인 | "일정을 삭제할까요?" |
| `select` | 단일 선택 | "어느 도시 날씨?" |
| `checkbox` | 복수 선택 | "분석 항목 선택" |
| `form` | 구조화 입력 | "일정 등록 (제목, 날짜, 시간)" |

#### 구현 체크리스트

- [x] `InteractionEngine` — 쿼리 분석 → 인터랙션 타입/옵션 결정 (LLM)
- [x] `interaction_required` SSE 이벤트 — 프론트엔드에 인터랙션 요청
- [x] REST API `POST /api/v1/interaction/{request_id}` — 사용자 응답 수신
- [x] enriched context 생성 — 사용자 응답을 에이전트 context에 주입
- [x] `stream_with_orchestrator` 통합 — 인터랙션 흐름 → 오케스트레이터 실행
- [x] `InteractionDialog.tsx` — confirm/select/checkbox/form 4종 UI
- [x] `streaming.ts` pendingInteraction 상태 관리
- [x] multi-step 인터랙션 (연속 질문)
- [x] 테스트: 31/31 통과 (unit + integration) + 7 evaluations 통과

#### 파일 변경

```
logos_api/app/services/interaction_engine.py   — 새 파일 (InteractionEngine: 쿼리 분석 + 인터랙션 관리)
logos_api/app/routers/interaction.py           — 새 파일 (POST /api/v1/interaction/{request_id})
logos_api/app/main.py                         — interaction router 등록
logos_api/app/services/orchestrator_service.py — interaction_required SSE 이벤트 + enriched context
logos_web/utils/streaming.ts                  — pendingInteraction 타입 + interaction_required 핸들러
logos_web/components/InteractionDialog.tsx     — 새 파일 (confirm/select/checkbox/form 다이얼로그)
logos_web/components/ChatView.tsx              — InteractionDialog 렌더링
```

---

### Phase F: Guardrails & Safety

**목표**: 비용 제한, 출력 필터링, 행동 제한

#### 구현 체크리스트

- [ ] `CostTracker` — LLM 호출 비용 추적 (토큰 × 단가)
- [ ] 월간 비용 한도 설정 + 초과 시 차단
- [ ] 출력 안전 필터 (개인정보 마스킹)
- [ ] Agent별 rate limiting
- [ ] 위험 도구 호출 제한 (subprocess, file delete 등)
- [ ] 테스트: 비용 한도 초과 시 차단

#### 파일 변경

```
logosai/agentic/guardrails.py     — 새 파일 (CostTracker, SafetyFilter)
logosai/utils/llm_client.py       — 비용 추적 연동
```

---

### Phase G: Observability & Audit

**목표**: 에이전트 결정 추적, 감사 로그, 행동 재현

#### 구현 체크리스트

- [ ] `AuditLog` — 모든 에이전트 행동 기록 (PostgreSQL)
- [ ] 결정 추적: "왜 이 도구를 선택했는가?" trace
- [ ] 행동 재현: 동일 입력 → 동일 출력 검증
- [ ] 대시보드: 에이전트별 행동 타임라인
- [ ] 테스트: 감사 로그 기록 + 재현

#### 파일 변경

```
logosai/agentic/audit.py          — 새 파일
logosai/agent.py                  — 행동 로깅 연동
```

---

### Phase H: Multi-Modal

**목표**: 이미지, 문서, 음성 입출력

#### 구현 체크리스트

- [ ] `LLMClient.invoke_with_image()` — Vision API 연동
- [ ] PDF/DOCX 파싱 도구 (내장 도구 추가)
- [ ] 이미지 생성 도구 (차트, 다이어그램)
- [ ] 테스트: 이미지 분석 + 문서 요약

#### 파일 변경

```
logosai/utils/llm_client.py       — Vision API 추가
logosai/tools/builtin.py          — PDF/이미지 도구 추가
```

---

## 성숙도 추적

```
현재 (Harness 100% + Agent 70%):
  █████████████████████████░░░░░  ~85% overall

Phase A (Goal Decomposition):    +10%  → 70% ✅ 완료
Phase B (Adaptive Learning):     +10%  → 80% ✅ 완료 (Step 3 보류)
Phase C (Composability):         +5%   → 85% ✅ 완료 (기존 구현 확인)
Phase D (Long-term Goal):        +5%   → 90% ⏸️ 보류 (우선순위 낮음)
Phase E (SSE Bidirectional V2):  +3%   → 93% ✅ 완료
Phase F (Guardrails):            +3%   → 96% ✅ 부분 완료 (Rate Limiter + Call Counter)
Phase G (Observability):         +2%   → 98% ✅ LogosPulse 기반 완료
Phase H (Multi-Modal):           +2%   → 100%
```

## 경쟁 프레임워크 대비 — Agent Engineering

| 기능 | LogosAI | LangGraph | CrewAI | OpenAI SDK | Google ADK |
|------|---------|-----------|--------|------------|------------|
| Goal Decomposition | ✅ 완료 | ✅ Subgraph | ❌ | ❌ | ✅ |
| Adaptive Learning | 🔴 TODO | ❌ | ❌ | ❌ | ❌ |
| Composability (Pipeline) | ✅ WorkflowOrchestrator | ✅ Graph DSL | ✅ Process | ❌ | ✅ |
| Long-term Goal | 🔴 TODO | ❌ | ❌ | ❌ | ❌ |
| Human-in-the-Loop | ✅ SSE Bidirectional V2 (Workflow-Level) | ✅ Interrupt | ❌ | ❌ | ✅ |
| Guardrails | ✅ Rate Limiter + Call Counter | ❌ | ❌ | ✅ Moderation | ✅ |
| Observability | 🟡 Partial | ✅ LangSmith | ❌ | ❌ | ✅ |
| Multi-Modal | 🔴 TODO | ✅ | ❌ | ✅ | ✅ |
| **Self-Evolution** | ✅ UNIQUE | ❌ | ❌ | ❌ | ❌ |
| **Desktop Control** | ✅ UNIQUE | ❌ | ❌ | ❌ | ❌ |
| **Adaptive Learning** | 🔴 (구현 시 UNIQUE) | ❌ | ❌ | ❌ | ❌ |

**Adaptive Learning + Long-term Goal은 구현하면 LogosAI만의 추가 고유 기능이 됩니다.**

## 구현 순서 (확정)

| 순서 | Phase | 항목 | 체크리스트 | 난이도 |
|------|-------|------|-----------|--------|
| 1 | **A** | Goal Decomposition | 6개 | 높음 |
| 2 | **B** | Adaptive Learning | 6개 | 높음 |
| 3 | **C** | Composability (Pipeline) | 6개 | 높음 |
| 4 | **D** | Long-term Goal | 6개 | 높음 |
| 5 | **E** | SSE Bidirectional V2 | 9개 | 중 |
| 6 | **F** | Guardrails & Safety | 6개 | 중 |
| 7 | **G** | Observability & Audit | 5개 | 중 |
| 8 | **H** | Multi-Modal | 4개 | 중 |
| | | **합계** | **45개** | |
