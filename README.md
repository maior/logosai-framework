# LogosAI

[![Version](https://img.shields.io/badge/version-0.7.0-blue.svg)](https://github.com/logosai/logosai)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

LogosAI는 다양한 AI 에이전트를 쉽게 생성하고 관리할 수 있는 Python 라이브러리입니다.

## 🎯 Recent Updates

### 🆕 v0.7.0 (2025-01) - Agent Self-Evolution System

**NEW: 에이전트 자가 진화 시스템**
- ✅ **Self-Healing**: 에러 및 버그 자동 감지 및 수정
- ✅ **Self-Growing**: 새로운 기능 추가 및 기존 기능 개선
- ✅ **Self-Evaluation**: 응답 품질 평가 및 피드백
- ✅ **Circuit Breaker**: 3회 연속 실패 시 1시간 쿨다운
- ✅ **Confidence Gates**: 4단계 신뢰도 게이트 (AUTO_APPLY ≥0.95 → REJECT <0.50)
- ✅ **Fix History**: 수정 사이클 방지 (최대 3회 시도)
- ✅ **LLM 설정**: gemini-2.5-flash-lite 기본값 (변경 가능)

**Quick Start**:
```python
from logosai.evolution import EvolutionSystem, EvolutionConfig

# 설정 생성 (기본값: 비활성화)
config = EvolutionConfig(
    enabled=True,  # 활성화
    llm_provider="google",
    llm_model="gemini-2.5-flash-lite"
)

# 에이전트에 진화 시스템 적용
evolution = EvolutionSystem(agent, config)
await evolution.enable()

# 분석 및 개선
result = await evolution.evolve(
    query="100달러를 원화로 환전해줘",
    response="이 기능은 지원하지 않습니다"
)

if result.improvements:
    print(f"개선안: {result.improvements[0].suggested_changes}")
```

자세한 내용은 [Agent Self-Evolution System 가이드](logosai/docs/AGENT_SELF_EVOLUTION_SYSTEM.md)를 참조하세요.

---

### v0.6.0 (2025-01) - Streaming API

**NEW: Real-time Streaming Response**
- ✅ **process_stream() 메서드**: AsyncGenerator 기반 실시간 스트리밍
- ✅ **SSE 엔드포인트**: Server-Sent Events 스트리밍 지원
- ✅ **청크 기반 응답**: 긴 응답을 500자 단위로 분할 전송
- ✅ **이벤트 타입**: start, progress, chunk, complete, error
- ✅ **에이전트 선택 이벤트**: 선택된 에이전트와 신뢰도 표시

**Quick Start**:
```python
async for event in agent.process_stream("쿼리"):
    if event["type"] == "chunk":
        print(event["data"]["content"])
```

**SSE 서버 엔드포인트**: `POST /stream`

자세한 내용은 [스트리밍 API 가이드](logosai/docs/streaming_api_guide.md)를 참조하세요.

---

### v0.5.0 (2025-01-04) - Agent Debate System

**NEW: Autonomous Multi-Agent Debate & Decision-Making**
- ✅ **Agent Debate System**: 에이전트들이 자율적으로 토론하여 역할 결정
- ✅ **5-Phase Debate Process**: 쿼리 분석 → 역할 제안 → 토론 → 투표 → 합의
- ✅ **Workflow Transparency**: 워크플로우 결정 과정 100% 투명화
- ✅ **Multiple Strategies**: 전문성 우선 vs. 업무 논리 순서 전략
- ✅ **Domain Specialization**: 은행 업무 등 도메인 특화 에이전트 지원
- ✅ **Comprehensive Documentation**: 12+ Mermaid 다이어그램, 실제 사용 사례

**Performance**:
- 100% consensus rate
- <0.1s debate time (keyword-based)
- 63.6% agent match accuracy (banking scenarios)

**Examples**:
- General purpose: 3 demo agents (data analyst, researcher, writer)
- Banking domain: 5 specialized agents (loan, fraud, compliance, risk, service)

### v0.4.0 (2025-08-08) - FORGE AI Integration

- ✅ **FORGE AI 시스템**: 12단계 파이프라인을 통한 동적 에이전트 생성
- ✅ **Agentic AI 모듈**: AgenticCore, AgenticReasoning, AgenticTools, AgenticMemory, AgenticLearning
- ✅ **향상된 LLM Client**: invoke_messages 및 강화된 JSON 파싱
- ✅ **WebSocket 실시간 스트리밍**: 에이전트 생성 과정 실시간 모니터링
- ✅ **템플릿 시스템 강화**: 10+ 특수 템플릿 추가 (PDF, 이미지, 이메일, 주식 분석 등)

## 설치 방법

```bash
pip install logosai
```

또는 소스에서 직접 설치:

```bash
git clone https://github.com/logosai/logosai.git
cd logosai
pip install -e .
```

## 주요 기능

- 다양한 유형의 AI 에이전트 생성 및 관리
- 에이전트 간 통신 및 작업 분배
- 설정 기반의 유연한 에이전트 구성
- LLM 통합 지원
- 실시간 인터넷 검색 및 데이터 분석
- 작업 분류 및 에이전트 추천
- **스트리밍 API를 통한 실시간 응답 수신**
- **Agent Debate System을 통한 자율 협상 및 워크플로우 결정**
- **FORGE AI를 통한 동적 에이전트 생성**
- **Agentic AI 모듈을 통한 고급 추론 및 학습**
- **Agent Self-Evolution System을 통한 자가 진화 (Self-Healing, Self-Growing, Self-Evaluation)** 🆕

## 🚀 FORGE AI - 동적 에이전트 생성 시스템

FORGE AI는 자연어 쿼리를 기반으로 AI 에이전트를 자동으로 생성하는 혁신적인 시스템입니다.

### FORGE AI 사용법

```python
from forge import forge_agent, ForgeSystem, ForgeConfig

# 간단한 에이전트 생성
async def create_agent():
    result = await forge_agent(
        "PDF 문서를 분석하고 요약하는 에이전트를 만들어줘"
    )
    print(f"생성된 에이전트: {result['agent']['name']}")
    print(f"에이전트 코드:\n{result['code']}")

# 고급 설정
async def advanced_forge():
    config = ForgeConfig(
        primary_llm_provider="gemini",
        enable_validation=True,
        enable_sandbox_execution=True,
        use_template_matcher=True
    )
    
    forge = ForgeSystem(config)
    result = await forge.process_query(
        "감정 분석 에이전트를 만들어줘"
    )
    return result

asyncio.run(create_agent())
```

### FORGE AI 특수 템플릿

| 템플릿 | 설명 | 사용 예시 |
|--------|------|-----------|
| **pdf_analyzer** | PDF 문서 처리 및 분석 | 계약서 분석, 보고서 요약 |
| **image_analyzer** | 컴퓨터 비전 및 이미지 처리 | 객체 인식, 이미지 분류 |
| **email_automation** | 이메일 전송 및 관리 | 자동 응답, 뉴스레터 |
| **stock_analyzer** | 금융 데이터 분석 | 주가 예측, 포트폴리오 분석 |
| **sentiment_analyzer** | 텍스트 감정 분석 | 리뷰 분석, 소셜 미디어 모니터링 |
| **news_aggregator** | 뉴스 수집 및 요약 | 트렌드 분석, 뉴스 브리핑 |
| **time_series_forecaster** | 시계열 예측 | 매출 예측, 수요 예측 |

자세한 내용은 [FORGE AI 문서](https://github.com/maior/logosai-forge)를 참조하세요.

## 💬 Agent Debate System - 자율 협상 및 의사결정 (v0.5.0)

Agent Debate System은 에이전트들이 자율적으로 토론하여 역할을 협상하고, 투표를 통해 최적의 워크플로우를 결정하는 시스템입니다.

### Quick Start

```python
from logosai.debate import SimpleDebateSystem
from banking_agents import create_banking_agents

# 은행 업무 에이전트 생성
agents = create_banking_agents()  # 5개 전문 에이전트

# 토론 시스템 초기화
debate_system = SimpleDebateSystem()

# 토론 시작
result = await debate_system.start_debate(
    query="고객이 5억원 주택담보대출을 신청했습니다. 신용평가하고 심사해주세요.",
    agents=agents
)

# 결과 확인
print(f"합의 도달: {result.consensus_reached}")
print(f"참여 에이전트: {result.participating_agents}")
print(f"최종 워크플로우:")
for step in result.workflow:
    print(f"  - {step['agent_id']}: {step['role']}")
```

### 5-Phase Debate Process

```
Phase 1: Query Analysis
├─ 각 에이전트가 쿼리 분석
├─ 관련도 점수 계산 (0.0 ~ 1.0)
└─ 기여 가능 여부 결정

Phase 2: Role Proposal
├─ 기여 가능 에이전트들이 역할 제안
├─ 다른 에이전트들의 분석 참고
└─ 자신의 전문성 기반 역할 제시

Phase 3: Discussion
├─ 제안된 역할에 대해 토론
├─ 충돌 사항 조율
└─ 협력 방안 합의

Phase 4: Voting
├─ 여러 워크플로우 후보 생성
│   ├─ Workflow 0: 전문성 우선 순서
│   └─ Workflow 1: 업무 논리 순서
├─ 각 에이전트가 투표 (확신도 포함)
└─ 가중치 합산으로 최적 워크플로우 선택

Phase 5: Consensus
├─ 최종 워크플로우 확인
├─ 모든 참여 에이전트 동의 확인
└─ 합의 완료 및 실행 준비
```

### Workflow Transparency

모든 워크플로우 결정 과정이 투명하게 기록됩니다:

```
📋 Workflow 0: 전문성 우선 순차 실행
   이유: 가장 관련도 높은 'loan_reviewer'부터 시작하여 순차 처리
   순서: loan_reviewer → risk_analyst → customer_service
   전략: expertise_first

📋 Workflow 1: 업무 논리 순서 기반 실행
   이유: 업무 프로세스 순서에 따라 처리
   순서: customer_service → risk_analyst → loan_reviewer
   전략: logical_flow

🗳️ 투표 진행:
   [대출심사역] Workflow 0 (확신도: 0.80) - "내가 참여하는 워크플로우"
   [리스크분석가] Workflow 0 (확신도: 0.80) - "내가 참여하는 워크플로우"

✅ 최종 선택: Workflow 0
```

### Example Agents

**Banking Domain** (5 agents):
```python
agents = [
    LoanReviewAgent(),      # 대출 심사
    FraudDetectionAgent(),  # 이상거래 탐지
    ComplianceAgent(),      # 규제 준수
    RiskAnalystAgent(),     # 리스크 평가
    CustomerServiceAgent()  # 고객 응대
]
```

**General Purpose** (3 agents):
```python
agents = [
    DataAnalystAgent(),     # 데이터 분석
    ResearchAgent(),        # 정보 조사
    WriterAgent()          # 문서 작성
]
```

### Testing & Documentation

```bash
cd examples/agent_debate_demo

# Quick demo
python run_debate.py simple

# Full demo
python run_debate.py

# Comprehensive testing (6 scenarios)
python test_scenarios.py

# Banking domain testing (5 scenarios)
python banking_scenarios.py
```

**Documentation**:
- `ARCHITECTURE.md` - 12+ Mermaid diagrams
- `TEST_RESULTS.md` - 6 general scenarios
- `BANKING_USE_CASE.md` - 5 banking workflows
- `README.md` - Setup guide

### Performance Metrics (MVP)

| Metric | Value |
|--------|-------|
| Consensus Rate | 100% |
| Debate Speed | <0.1s (keyword-based) |
| Agent Match Accuracy | 63.6% (banking) |
| Workflow Transparency | 100% |

### Known Limitations & Roadmap

**Current Limitations**:
- Keyword-based query analysis (33% ambiguous query failure)
- Workflow ordering bias (100% expertise-first)
- Single-round discussion only

**Future Improvements**:
- Phase 1: LLM-based query analysis
- Phase 2: Multi-round deliberation (2-3 rounds)
- Phase 3: Agent creation proposals, parallel workflows

## 🔄 Agent Self-Evolution System - 에이전트 자가 진화 (v0.7.0)

Agent Self-Evolution System은 에이전트가 스스로 학습하고 개선하는 자가 진화 시스템입니다.

### 핵심 구성 요소

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Agent Self-Evolution System                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐           │
│  │ Self-Healing │   │ Self-Growing │   │Self-Evaluation│           │
│  │  에러 수정    │   │  기능 추가    │   │  품질 평가    │           │
│  └──────────────┘   └──────────────┘   └──────────────┘           │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Safety Mechanisms                         │   │
│  │  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐     │   │
│  │  │Circuit Breaker│ │Confidence Gate│ │ Fix History   │     │   │
│  │  │ 3회 실패→대기 │ │ 4단계 검증   │ │ 사이클 방지   │     │   │
│  │  └───────────────┘ └───────────────┘ └───────────────┘     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 기본 사용법

```python
from logosai.evolution import EvolutionSystem, EvolutionConfig

# 설정 생성 (기본값: 비활성화)
config = EvolutionConfig(
    enabled=True,  # 활성화
    llm_provider="google",
    llm_model="gemini-2.5-flash-lite",
    mode=EvolutionMode.BOTH  # HEALING, GROWING, BOTH
)

# 에이전트에 진화 시스템 적용
evolution = EvolutionSystem(agent, config)
await evolution.enable()

# 전체 진화 프로세스 실행
result = await evolution.evolve(
    query="100달러를 원화로 환전해줘",
    response="이 기능은 지원하지 않습니다"
)

# 결과 확인
print(f"감지된 문제: {len(result.problems_detected)}")
print(f"생성된 개선안: {len(result.improvements)}")
print(f"적용된 개선: {len(result.applied_improvements)}")
```

### Confidence Gates (신뢰도 게이트)

| 액션 | 신뢰도 범위 | 설명 |
|------|------------|------|
| AUTO_APPLY | ≥ 0.95 | 자동 적용 |
| STAGED_ROLLOUT | ≥ 0.85 | 단계적 롤아웃 |
| HUMAN_REVIEW | ≥ 0.70 | 사람 검토 필요 |
| SUGGEST_ONLY | ≥ 0.50 | 제안만 |
| REJECT | < 0.50 | 거부 |

### Safety Mechanisms

**Circuit Breaker**:
- 3회 연속 실패 시 1시간 쿨다운
- 자동 복구 후 재시도

**Fix History**:
- 동일 문제 최대 3회 시도
- 수정 사이클 자동 감지 및 방지

### 고급 사용법

```python
# 분석만 수행 (개선안 생성 없음)
result = await evolution.analyze_only(
    query="복잡한 쿼리",
    response="에이전트 응답"
)

# 상태 확인
status = await evolution.get_status()
print(f"활성화: {status['enabled']}")
print(f"Circuit Breaker: {status['circuit_breaker']['state']}")

# 시스템 비활성화
await evolution.disable()
```

자세한 내용은 [Agent Self-Evolution System 가이드](logosai/docs/AGENT_SELF_EVOLUTION_SYSTEM.md)를 참조하세요.

## 🧠 Agentic AI 모듈

LogosAI v0.4.0부터 고급 AI 기능을 위한 Agentic AI 모듈을 제공합니다.

### Agentic AI 모듈 사용법

```python
from logosai.agentic import (
    AgenticCore,
    AgenticReasoning,
    AgenticTools,
    AgenticMemory,
    AgenticLearning
)

# 에이전트에서 Agentic 모듈 초기화
class MyAdvancedAgent(LogosAIAgent):
    def __init__(self, config=None):
        super().__init__(config)
        
        # Agentic AI 모듈 초기화
        self.agentic_core = AgenticCore()  # 핵심 추론 엔진
        self.agentic_reasoning = AgenticReasoning()  # 체인 추론
        self.agentic_tools = AgenticTools()  # 도구 사용 (파라미터 없음!)
        self.agentic_memory = AgenticMemory()  # 단기/장기 메모리
        self.agentic_learning = AgenticLearning()  # 학습 시스템
    
    async def process(self, query: str, context=None):
        # 추론 체인 생성
        chain = await self.agentic_reasoning.create_chain(query)
        
        # 메모리에서 관련 정보 검색
        memories = await self.agentic_memory.retrieve(query)
        
        # 도구 실행
        if chain.requires_tools:
            tool_results = await self.agentic_tools.execute(chain.tools)
        
        # 학습 업데이트
        await self.agentic_learning.update(query, result)
        
        return result
```

### Agentic AI 모듈 구성

| 모듈 | 기능 | 초기화 파라미터 |
|------|------|----------------|
| **AgenticCore** | 핵심 추론 엔진 | `llm_client` (선택) |
| **AgenticReasoning** | 체인 추론 및 계획 | `llm_client` (선택) |
| **AgenticTools** | 도구 등록 및 실행 | **없음** |
| **AgenticMemory** | 단기/장기 메모리 관리 | `short_term_capacity`, `long_term_size` (선택) |
| **AgenticLearning** | 학습 및 개선 | `strategy`, `learning_rate` (선택) |

## 기본 사용법

### 기존 방식 (v0.1.x)
```python
from logosai import LogosAIAgent, AgentType, AgentConfig

# 에이전트 생성
config = AgentConfig(
    name="Task Classifier",
    agent_type=AgentType.TASK_CLASSIFIER,
    description="작업 분류 에이전트"
)
agent = LogosAIAgent(config)
```

### 새로운 방식 (v0.4.0)
```python
from logosai import EnhancedLogosAIAgent, ResponseBuilder
from logosai.utils.llm_client import LLMClient

class MyAgent(EnhancedLogosAIAgent):
    async def initialize(self):
        # LLM Client 초기화
        self.llm_client = LLMClient(
            provider="gemini",
            model="gemini-2.5-flash-lite"
        )
        await self.llm_client.initialize()
        return await super().initialize()
    
    async def _process_logic(self, query, context):
        # invoke_messages 사용 (메시지 리스트)
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": query}
        ]
        response = await self.llm_client.invoke_messages(messages)
        
        # 또는 invoke 사용 (단일 문자열)
        # response = await self.llm_client.invoke(query)
        
        return self._create_success_response(
            content={"answer": response.content}
        )
```

## 향상된 LLM Client (v0.4.0)

### LLM Client 사용법

```python
from logosai.utils.llm_client import LLMClient

# LLM Client 초기화
llm_client = LLMClient(
    provider="gemini",  # openai, anthropic, ollama도 지원
    model="gemini-2.5-flash-lite",
    temperature=0.7
)

# 초기화
await llm_client.initialize()

# 방법 1: 단일 메시지
response = await llm_client.invoke("파이썬 비동기 프로그래밍 설명해줘")

# 방법 2: 메시지 리스트 (대화형)
messages = [
    {"role": "system", "content": "당신은 전문 프로그래머입니다"},
    {"role": "user", "content": "async/await 패턴을 설명해주세요"}
]
response = await llm_client.invoke_messages(messages)

print(response.content)
```

### JSON 파싱 개선사항

v0.4.0부터 LLM 응답의 JSON 파싱이 크게 개선되었습니다:

```python
async def extract_structured_data(query: str):
    messages = [
        {"role": "system", "content": "Return ONLY valid JSON format"},
        {"role": "user", "content": query}
    ]
    
    response = await llm_client.invoke_messages(messages)
    
    # 자동으로 마크다운 코드 블록 제거
    # ```json ... ``` 형식 자동 처리
    # 파싱 실패 시 폴백 메커니즘 작동
    
    return response.content  # 깨끗한 JSON 또는 텍스트
```

## 설정 파일 구조

에이전트 설정은 `agents.json` 파일에서 관리됩니다. 현재 지원되는 에이전트 유형:

1. **LLM 검색 에이전트** (`llm_search_agent`)
   - LLM의 내장 지식을 활용한 직접 검색
   - 지식 기반 질의응답
   - 사실 확인 및 개념 설명

2. **데이터 분석 에이전트** (`analysis_agent`)
   - 주제 분석
   - 감정 분석
   - 키워드 추출

3. **작업 분류 에이전트** (`task_classifier_agent`)
   - 사용자 쿼리 분석
   - 적절한 에이전트 추천
   - 작업 유형 분류

4. **인터넷 검색 에이전트** (`internet_agent`)
   - 실시간 웹 검색
   - 웹 스크래핑
   - 최신 정보 수집

5. **계산기 에이전트** (`calculator_agent`)
   - 수학적 계산
   - 단위 변환
   - 공식 계산

## 디렉토리 구조

```
logosai/
├── __init__.py
├── agent_types.py          # 에이전트 타입 정의
├── config.py               # 설정 관리
├── agent.py                # 기본 에이전트 클래스
├── base_agent.py           # 향상된 기본 클래스
├── agentic/                # Agentic AI 모듈 (v0.4.0)
│   ├── __init__.py
│   ├── core.py            # AgenticCore
│   ├── reasoning.py       # AgenticReasoning
│   ├── tools.py           # AgenticTools
│   ├── memory.py          # AgenticMemory
│   └── learning.py        # AgenticLearning
├── evolution/              # Self-Evolution 시스템 (v0.7.0)
│   ├── __init__.py
│   ├── config.py          # EvolutionConfig
│   ├── types.py           # 타입 정의
│   ├── detector.py        # ProblemDetector
│   ├── feedback.py        # FeedbackCollector
│   ├── learner.py         # PatternLearner
│   ├── improver.py        # ImprovementGenerator
│   ├── validator.py       # ImprovementValidator
│   ├── system.py          # EvolutionSystem
│   └── safety/            # 안전 메커니즘
│       ├── circuit_breaker.py
│       ├── confidence_gate.py
│       └── history_tracker.py
├── utils/
│   └── llm_client.py      # 통합 LLM 클라이언트
└── examples/
    ├── configs/
    │   └── agents.json     # 에이전트 설정
    └── agents/             # 예제 에이전트
        ├── calculator_agent.py
        └── weather_agent.py
```

## Agent Market과 LLM 통합

LogosAI는 다양한 AI 에이전트를 쉽게 등록, 검색, 활성화할 수 있는 Agent Market을 제공합니다. 이를 통해 LLM은 ACP(Agent Collaboration Protocol)를 사용하여 필요한 에이전트와 원활하게 협업할 수 있습니다.

### Agent Market 아키텍처

```
┌─────────────┐    JSON-RPC     ┌─────────────┐     ┌─────────────┐
│             │   (ACP 프로토콜)  │             │     │  Agent #1   │
│    LLM      │<───────────────>│  ACP 게이트웨이 │<────│  Agent #2   │
│   시스템      │                 │             │     │  Agent #3   │
└─────────────┘                 └──────┬──────┘     └─────────────┘
                                       │
                                       ▼
                               ┌─────────────────┐
                               │  에이전트 레지스트리 │
                               └─────────────────┘
```

### LLM과 Agent Market 통합 예제

```python
import asyncio
from logosai.market import AgentMarket
from logosai.acp import ACPClient

async def main():
    # 에이전트 마켓에 연결
    market = AgentMarket(endpoint="https://market.logosai.com")
    
    # 사용 가능한 에이전트 목록 조회
    agents = await market.list_agents(category="search")
    print(f"사용 가능한 검색 에이전트: {len(agents)}개")
    
    # 에이전트 인스턴스 요청
    agent_instance = await market.provision_agent(
        agent_id="internet_search_agent",
        config={"max_results": 5}
    )
    
    # ACP 클라이언트로 에이전트와 통신
    client = ACPClient(endpoint=agent_instance.endpoint)
    
    # 에이전트에 쿼리 전송
    response = await client.query("파이썬에서 비동기 프로그래밍하는 방법은?")
    
    # 결과 처리
    if response.get("status") == "success":
        print(f"에이전트 응답: {response['result']['content']}")
        
        # 에이전트 사용 완료 후 해제
        await market.release_agent(agent_instance.id)

if __name__ == "__main__":
    asyncio.run(main())
```

## 🐛 Troubleshooting (2025-08-08 수정사항)

### 1. AgenticTools 초기화 오류
```python
# ❌ 잘못된 코드 (v0.3.x 이전)
self.agentic_tools = AgenticTools(self)

# ✅ 올바른 코드 (v0.4.0)
self.agentic_tools = AgenticTools()  # 파라미터 없음!
```

### 2. JSON 파싱 오류
```python
# 에러: Expecting value: line 1 column 1 (char 0)
# 해결: v0.4.0에서 자동으로 마크다운 제거 및 폴백 처리

# LLM이 ```json 형식으로 응답해도 자동 처리
response = await llm_client.invoke_messages(messages)
# response.content는 이미 정제된 JSON 또는 텍스트
```

### 3. LLM 응답 형식 문제
```python
# v0.3.x: JSON 형식 강제
# v0.4.0: 코드 블록 형식 사용

# 이제 LLM은 다음 형식으로 응답:
```python
# Python code here
```
# JSON 대신 코드 블록 사용으로 파싱 성공률 향상
```

## 버전 정보

현재 버전: 0.7.0

### 주요 변경사항
- v0.7.0: Agent Self-Evolution System (Self-Healing, Self-Growing, Self-Evaluation), 안전 메커니즘, LLM 기반 진화
- v0.6.0: 스트리밍 API (process_stream, SSE 엔드포인트), 실시간 응답 지원
- v0.5.0: Agent Debate System, 자율 협상 및 워크플로우 결정
- v0.4.0: FORGE AI 통합, Agentic AI 모듈, LLM Client 개선
- v0.2.0: 향상된 기본 클래스, 에이전트 템플릿, 개발 유틸리티 추가
- v0.1.5: 멀티 에이전트 워크플로우 개선, 온톨로지 시스템 통합
- v0.1.0: 초기 릴리즈

## 라이선스

MIT License

## 기여하기

프로젝트에 기여하고 싶으신가요? [기여 가이드라인](CONTRIBUTING.md)을 확인해보세요.

## 문의

문제가 있거나 질문이 있으신가요? [이슈 트래커](https://github.com/logosai/logosai/issues)에 등록해주세요.

## 관련 프로젝트

- [FORGE AI](https://github.com/maior/logosai-forge) - 자연어 기반 동적 에이전트 생성 시스템
- [LogosAI Server](https://github.com/logosai/logos-server) - LogosAI 백엔드 서버

---

**LogosAI**: AI 에이전트의 미래를 만들어갑니다. 🤖✨

*Last Updated: 2025-01*