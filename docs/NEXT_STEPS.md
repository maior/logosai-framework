# LogosAI Framework — 다음 진행 작업

> 최종 업데이트: 2026-04-04
> 아키텍처 리팩터링 완료 후 다음 단계 정리

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

### 1-1. Google 스트리밍 진정한 비동기화
- **현황**: `llm_client.py`의 `_stream_google()`가 `run_in_executor()`로 동기 수집 후 yield — 첫 토큰이 전체 응답 생성 후에만 나옴
- **목표**: async generator로 토큰 단위 실시간 스트리밍
- **영향**: 사용자 체감 속도 직접 개선
- **난이도**: 중 (2시간)
- **위치**: `logosai/utils/llm_client.py` `_stream_google()` 메서드

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

### 3-3. TypeScript SDK
- **현황**: Python만 지원
- **목표**: TypeScript/Node.js SDK (SimpleAgent 패턴)
- **영향**: 프론트엔드 개발자 접근성 (Google ADK 4개 언어, OpenAI SDK 2개 대비)
- **난이도**: 높 (1주+)

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
