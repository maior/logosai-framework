# LogosAI Framework — 다음 진행 작업

> 최종 업데이트: 2026-07-15
> Agentic 프레임워크 업그레이드 트랙 진행 중 — 상세 로드맵·진행 로그:
> `../../docs/AGENTIC_FRAMEWORK_UPGRADE_ROADMAP.md`

## 🔄 진행 중: Agentic 업그레이드 트랙 (2026-07-15 ~)

**목표**: 에이전트 간 실제 커뮤니케이션 + 플래너 워크플로우 신뢰성.
**원칙**: 능력은 프레임워크 계약으로 → 수제/FORGE 생성 에이전트 동일 상속.

| Phase | 내용 | 상태 |
|-------|------|------|
| 1 | **계약 3종**: `HandoffEnvelope`+`get_handoff()` (표준 스테이지 수신), `utils.extraction.extract_series_llm` (구조화 추출+가드), `utils.json_safe` | ✅ 07-15 |
| 2 | 오케스트레이터 Envelope 생산 (전 스테이지 무절단 탑재) | ✅ 07-15 |
| 3 | FORGE 생성 템플릿의 SDK 계약 타깃팅 (get_handoff·json_safe 내장) | ✅ 07-15 |
| 4 | `MultiAgentMixin.request_upstream` — 역방향 재요청 채널 (라이브 A2A 실증) | ✅ 07-15 |
| 5 | Plan Critique 관문 | ✅ 07-15 |
| 병행 | ko-sroberta 임베딩 + HybridSelector 재가동 | ⏳ |

## 완료된 작업 (2026-04-03~04)

### Tracing System (Phase G-2)
- TraceSpan (ContextVar 기반 span 전파)
- Root/LLM span 자동 기록
- LogosPulse span ingest + tree API
- SpanTreeView 프론트엔드 컴포넌트
- 테스트: 4/4 평가 항목 PASS

### 아키텍처 리팩터링
- agent.py Mixin 분리 (2191→1372줄, 5 Mixin)
- AgenticCore act() → tool_executor 실제 실행 연결
- 도구 시스템 통합 (register_tool_object)
- 임베딩 메모리 검색 (Gemini embedding + 코사인 유사도)
- 클래스 중복 정리 (agents/base.py → re-export)
- agentic/memory.py deprecated
- 테스트: 54/54 PASSED

---

## 우선순위 1: 프레임워크 기능 강화

### 1-1. LLM 토큰 스트리밍 (필요 시)
- **현황**: `invoke_stream()`이 버퍼링 방식이지만, 실전 에이전트 56개 중 사용하는 곳이 0개
- **분석 결과**: 대부분 에이전트는 LLM 응답을 후처리(API 조합, DB 조회 등)하므로 토큰 스트리밍이 맞지 않음. SSE 이벤트 스트리밍(단계별 알림)이 현재 아키텍처에 적합
- **적용 가능 에이전트**: `llm_search_agent` 등 LLM 응답 = 최종 결과인 경우만
- **시기**: LLM 응답을 실시간으로 보여주는 ChatGPT 스타일 UX가 필요할 때
- **방법**: `google.genai` `client.aio.models.generate_content_stream` (비동기 API 존재 확인됨)

### 1-2. LiteLLM 통합으로 LLM 프로바이더 확장
- **현황**: 4개 프로바이더 (Google, OpenAI, Anthropic, Ollama)
- **목표**: LiteLLM 어댑터 추가 → 100+ 모델 지원
- **영향**: 프레임워크 호환성 대폭 향상 (OpenClaw 15+, OpenAI SDK 100+ 수준)
- **난이도**: 중 (반나절)
- **위치**: `logosai/utils/llm_client.py` 새 프로바이더 `litellm` 추가

### 1-3. pgvector 설치 후 DB 레벨 벡터 검색 전환
- **현황**: 임베딩을 JSONB로 저장, Python에서 코사인 유사도 계산 (100개 로드 후 비교)
- **목표**: pgvector 설치 → `vector(3072)` 컬럼 + ivfflat 인덱스 → SQL 레벨 검색
- **영향**: 메모리 1000개 이상일 때 성능 향상
- **난이도**: 낮 (pgvector 설치가 핵심, 코드 변경 소)
- **전제**: 원격 DB 서버에 pgvector extension 설치 필요

---

## 우선순위 2: 프로덕션 안정성

### 2-1. ACP 에이전트 안정성 재검증
- **현황**: 데스크톱 에이전트(KakaoTalk, Mail, File) 이전 세션에서 수정했지만 리팩터링 후 재검증 필요
- **목표**: 주요 에이전트 10개 호출 테스트 + 오류 0건
- **난이도**: 중 (반나절)

### 2-2. LogosPulse 프론트엔드 UI 개선
- **현황**: SpanTreeView 생성했지만 실제 브라우저에서 UI 검증 미완
- **목표**: Traces 탭 → 트레이스 선택 → SpanTree 렌더링 확인, UX 개선
- **난이도**: 낮 (1-2시간)

### 2-3. Phase B Step 3 (프롬프트 자동 주입) 재검토
- **현황**: 보류 중 (잘못된 학습 주입 → 연쇄 장애 위험)
- **목표**: 학습 데이터 충분히 쌓인 후 안전 장치와 함께 재검토
- **전제**: LogosPulse에 feedback 데이터가 100건 이상 축적된 후

---

## 우선순위 3: 생태계 확장

### 3-1. FORGE 에이전트 리팩터링
- **현황**: `forge/docs/AGENT_REFACTORING_REQUEST.md` 문서 작성 완료
- **목표**: FORGE가 생성하는 에이전트 코드에 vision_react 패턴 적용
- **담당**: FORGE 세션에서 진행

### 3-2. README 및 사용 가이드 강화
- **현황**: README에 기본 사용법 있지만 Mixin 구조, 임베딩 메모리, Tracing 설명 부족
- **목표**: Quick Start, Architecture Guide, API Reference 업데이트
- **영향**: 오픈소스 커뮤니티 진입 장벽 낮춤

### 3-3. Desktop 라이브러리 앱 컨트롤러 확장
- **현황**: KakaoTalk, Gmail, Notion 3개 AppController + 5개 채널 구현 완료
- **목표**: 새 앱 추가 시 AppController 서브클래스 구현 (Excel, PowerPoint, Finder 등)
- **시기**: 새 데스크톱 에이전트 요구 시

### 3-4. 기업 제안 프레젠테이션 관리
- **현황**: 5개 기업별 맞춤 HTML 프레젠테이션 완성 (docs/)
- **대상**: 기술팀 일반, 은행(EY), 보험연수원, AIA생명, 에스원
- **원칙**: 컨설팅 형태 (As-Is→Gap→To-Be→시나리오→TCO→리스크→로드맵), 구체적 금액 미포함
- **시기**: 신규 기업 제안 시 해당 기업 맞춤 버전 생성

---

## 평가 점수 변화

| 항목 | 리팩터링 전 | 리팩터링 후 | 변화 |
|------|-----------|-----------|------|
| Agentic AI 엔지니어링 | 8.0 | 8.5 | +0.5 (도구/메모리 통합) |
| 코드 품질/아키텍처 | 7.0 | 8.5 | +1.5 (Mixin 분리, 중복 제거) |
| 개발자 경험 (DX) | 8.5 | 9.0 | +0.5 (3가지 도구 등록 방식) |
| 에러 복구/안정성 | 8.5 | 8.5 | — |
| Observability | 8.0 | 8.5 | +0.5 (Tracing 추가) |
| 차별화/혁신성 | 9.0 | 9.0 | — |
| 프로덕션 준비도 | 8.5 | 8.5 | — |
| 생태계/커뮤니티 | 5.5 | 5.5 | — |
| **종합** | **7.9** | **8.3** | **+0.4** |

주요 개선: 코드 품질 7.0→8.5 (+1.5)가 가장 큰 폭. Mixin 분리로 유지보수성이 크게 향상됨.
