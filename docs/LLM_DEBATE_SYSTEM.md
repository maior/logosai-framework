# LLM-Based Debate System

## Overview

The LLM Debate System (`LLMDebateSystem`) enhances the existing keyword-based debate system by replacing Phase 1 (Query Analysis) with a single LLM call. This semantic analysis improves agent selection accuracy from **74.7% → 93.3% F1** on banking scenarios.

## Architecture

### Before: Keyword-Based (SimpleDebateSystem)

```
Query: "고객이 5억원 주택담보대출을 신청했습니다"
  │
  ▼
Phase 1: Keyword Matching
  │  "대출" in query → loan_reviewer (0.3)
  │  "고객" in query → customer_service (0.3)
  │  compliance_officer → no keyword match (0.0) ❌
  │
  ▼
Phase 2-5: Hardcoded roles → Generic discussion → Self-voting
  │
  ▼
Result: [loan_reviewer, customer_service]  ← compliance_officer missing
```

### After: LLM-Based (LLMDebateSystem)

```
Query: "고객이 5억원 주택담보대출을 신청했습니다"
  │
  ▼
Phase 1: LLM Analysis (1 call, ~2 seconds)
  │  ┌─────────────────────────────────────────────┐
  │  │ Input:                                      │
  │  │   - Query text                              │
  │  │   - All agents (name + description)         │
  │  │   - Domain knowledge (banking rules)        │
  │  │                                              │
  │  │ Output (per agent):                         │
  │  │   - relevance_score (0.0-1.0)              │
  │  │   - can_contribute (true/false)            │
  │  │   - proposed_role                           │
  │  │   - reasoning                               │
  │  └─────────────────────────────────────────────┘
  │
  │  loan_reviewer:      0.95 ✅ "신용평가 및 대출 심사"
  │  risk_analyst:       0.85 ✅ "담보 가치 및 리스크 평가"
  │  compliance_officer: 0.75 ✅ "대출 규제 준수 검토"
  │  fraud_detector:     0.20 ❌
  │  customer_service:   0.30 ❌
  │
  ▼
Phase 2: Role Assignment (reuses Phase 1 results — no extra LLM call)
  │
  ▼
Phase 3: Discussion (MVP — 1 round)
  │
  ▼
Phase 4: Voting → Workflow selection
  │
  ▼
Phase 5: Consensus → DebateResult
  │
  ▼
Result: [loan_reviewer, risk_analyst, compliance_officer] ✅
```

### 5-Phase Process

| Phase | SimpleDebateSystem (Keyword) | LLMDebateSystem (LLM) |
|-------|----------------------------|----------------------|
| 1. Query Analysis | Keyword matching per agent | **1 LLM call for all agents** |
| 2. Role Proposal | Hardcoded role_map | **Reuses Phase 1 LLM result** |
| 3. Discussion | Generic comments (MVP) | Same (MVP) |
| 4. Voting | Self-inclusion voting | Same |
| 5. Consensus | Formalize workflow | Same |

## Performance

### Banking Scenarios (5 tests)

| Metric | Keyword-Based | LLM-Based | Improvement |
|--------|:------------:|:---------:|:-----------:|
| Precision | 93.3% | 93.3% | — |
| Recall | 63.3% | **93.3%** | +30% |
| **F1 Score** | **74.7%** | **93.3%** | **+18.7%** |

### Per-Scenario Results

| Scenario | Keyword F1 | LLM F1 |
|----------|:----------:|:------:|
| 1. Loan Application | 67% | **100%** |
| 2. Fraud Detection | 80% | 67% |
| 3. Regulatory Review | 67% | **100%** |
| 4. Customer Complaint | 80% | **100%** |
| 5. Portfolio Risk | 80% | **100%** |

### Cost

- **LLM calls**: 1 per debate (Phase 1 only)
- **Latency**: ~2 seconds (gemini-2.5-flash-lite)
- **Tokens**: ~500 input, ~300 output per call

## Usage

### Basic

```python
from logosai.debate import LLMDebateSystem

debate = LLMDebateSystem()
result = await debate.start_debate("Analyze Q4 sales data", agents)
print(result.participating_agents)
print(result.workflow)
```

### With Domain Knowledge

```python
# Banking domain — includes financial compliance rules
debate = LLMDebateSystem(domain="banking")
result = await debate.start_debate(
    "고객이 5억원 주택담보대출을 신청했습니다.",
    banking_agents
)
```

### Custom LLM Provider

```python
debate = LLMDebateSystem(
    provider="openai",
    model="gpt-4o-mini",
    temperature=0.1,
    domain="banking",
    timeout=30,
)
```

### Fallback Behavior

If the LLM call fails (timeout, API error, malformed response), `LLMDebateSystem` automatically falls back to keyword-based analysis:

```
LLM call → Success → LLM-based analysis
         → Failure → Keyword-based fallback (SimpleDebateSystem)
```

## Domain Knowledge

Domain knowledge is injected into the LLM prompt to improve agent selection accuracy.

### Built-in Domains

| Domain | Key Rules |
|--------|-----------|
| `banking` | Loan → credit + risk + compliance; Fraud → detection + risk + customer |
| `healthcare` | Diagnosis → specialist + history; Treatment → specialist + pharmacy + consent |
| `general` | Primary work + supporting input + review/validation |

### Adding Custom Domains

```python
from logosai.debate.prompts import DOMAIN_KNOWLEDGE

DOMAIN_KNOWLEDGE["legal"] = (
    "In legal workflows:\n"
    "- Contract review requires: legal analysis + compliance check\n"
    "- Dispute resolution requires: legal + negotiation + documentation\n"
)

debate = LLMDebateSystem(domain="legal")
```

## File Structure

```
logosai/logosai/debate/
├── __init__.py          # Exports: SimpleDebateSystem, LLMDebateSystem, ...
├── debate_system.py     # SimpleDebateSystem (keyword-based, unchanged)
├── llm_debate.py        # LLMDebateSystem (LLM-based Phase 1)
├── prompts.py           # Domain knowledge & prompt builder
└── voting.py            # VotingSystem (unchanged)
```

## API Reference

### LLMDebateSystem

```python
class LLMDebateSystem(SimpleDebateSystem):
    def __init__(
        self,
        provider="google",           # LLM provider
        model="gemini-2.5-flash-lite", # Model name
        temperature=0.1,             # Low for consistency
        domain=None,                 # "banking", "healthcare", "general", None
        timeout=30,                  # LLM call timeout (seconds)
    ): ...

    async def start_debate(query, agents) -> DebateResult:
        """Same interface as SimpleDebateSystem"""
```

### build_analysis_prompt

```python
def build_analysis_prompt(
    query: str,                      # User query
    agents_info: List[Dict],         # [{"id", "name", "description"}, ...]
    domain: Optional[str] = None,    # Domain knowledge key
) -> str:
    """Build the Phase 1 LLM prompt"""
```
