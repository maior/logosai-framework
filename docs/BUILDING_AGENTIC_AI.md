# Building Agentic AI with LogosAI

A comprehensive guide to creating intelligent, autonomous AI agents using the LogosAI framework.

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Core Concepts](#core-concepts)
4. [Quick Start with SimpleAgent (v0.9.0)](#quick-start-with-simpleagent-v090)
5. [Building Your First Agent](#building-your-first-agent)
6. [Adding LLM Intelligence](#adding-llm-intelligence)
7. [Agent Collaboration](#agent-collaboration)
8. [Agentic AI Modules](#agentic-ai-modules)
9. [Agent Debate System](#agent-debate-system)
10. [Agent Self-Evolution](#agent-self-evolution)
11. [Streaming Responses](#streaming-responses)
12. [Production Patterns](#production-patterns)
13. [API Reference](#api-reference)

---

## Overview

LogosAI is a Python framework for building, orchestrating, and evolving AI agents. It provides:

- **SimpleAgent** (v0.9.0) — Zero-boilerplate agent base class with auto-managed lifecycle
- **`@agent` decorator** (v0.9.0) — Convert an async function into a full agent
- **`quick_llm()`** (v0.9.0) — One-shot LLM call with no setup needed
- **LogosAIAgent** base class with async lifecycle management
- **Multi-provider LLM client** (OpenAI, Anthropic, Google Gemini, Ollama)
- **Text utilities** (v0.9.0) — `parse_llm_json()`, `clean_markdown_code()`, and more
- **Agent Collaboration** for coordinated multi-agent task execution
- **Agent Debate System** for autonomous multi-agent negotiation
- **Self-Evolution System** for agents that learn and improve autonomously
- **Agentic AI Modules** for reasoning, memory, tools, and learning

## Installation

```bash
# Core framework
pip install logosai

# With LLM provider support
pip install logosai[llm]

# All optional dependencies
pip install logosai[all]

# From source
git clone https://github.com/maior/logosai-framework.git
cd logosai-framework
pip install -e .
```

## Core Concepts

### Architecture

```
LogosAIAgent (base class)
├── SimpleAgent (v0.9.0)   — Zero-boilerplate subclass (recommended for new agents)
├── AgentConfig            — Configuration (name, type, description, parameters)
├── AgentResponse          — Typed responses (SUCCESS, ERROR, PARTIAL)
├── LLMClient              — Multi-provider LLM integration
├── CollaborationService   — Inter-agent communication (injected at runtime)
├── SelfAssessment         — Query compatibility evaluation
└── DialogueProtocol       — Multi-agent conversation support

Standalone utilities:
├── quick_llm()            — One-shot LLM call (no agent needed)
└── parse_llm_json()       — Extract JSON from LLM responses
```

### Key Types

| Type | Description |
|------|-------------|
| `SimpleAgent` | Zero-boilerplate agent base class (v0.9.0, recommended) |
| `LogosAIAgent` | Full-control base class for all agents |
| `AgentConfig` | Agent configuration container |
| `AgentResponse` | Typed response with content, metadata, and message |
| `AgentResponseType` | Enum: `SUCCESS`, `ERROR`, `TEXT`, `HTML`, `JSON` |
| `AgentType` | Enum: `CUSTOM`, `SEARCH`, `GENERAL`, `LLM_INTEGRATION`, etc. |
| `LLMClient` | Unified LLM client for multiple providers |
| `quick_llm` | One-shot LLM function (v0.9.0) |

### Agent Lifecycle

```
# SimpleAgent (v0.9.0) — auto-manages lifecycle:
__init__() → process(query) → [auto-init, handle(), error handling] → AgentResponse

# LogosAIAgent — manual lifecycle:
__init__(config) → initialize() → process(query, context) → shutdown()
                                     ↕
                              process_stream()  (streaming variant)
```

---

## Quick Start with SimpleAgent (v0.9.0)

SimpleAgent eliminates boilerplate. You define class attributes and a `handle()` method — everything else (init, LLM setup, error handling, ACP compatibility) is automatic.

### Three Ways to Create Agents

#### 1. SimpleAgent Subclass (Recommended)

```python
import asyncio
from logosai import SimpleAgent, AgentResponse


class TranslatorAgent(SimpleAgent):
    agent_name = "Translator"
    agent_description = "Translates text to Korean"
    llm_temperature = 0.3

    async def handle(self, query, context=None):
        result = await self.ask_llm(f"Translate to Korean: {query}")
        return AgentResponse.success(
            message=result,
            content={"answer": result},
        )


async def main():
    agent = TranslatorAgent()
    result = await agent.process("Good morning")
    print(result.content["answer"])  # "좋은 아침"

asyncio.run(main())
```

**What SimpleAgent auto-manages:**

| Pattern | LOC saved | How |
|---------|-----------|-----|
| Init dance (config, super, hasattr) | ~25 | Class attributes → auto AgentConfig |
| `initialize()` idempotent | ~15 | Built-in |
| `publish_status()` safe wrapper | ~15 | Built-in with hasattr guard |
| `process()` error handling | ~10 | Wraps `handle()` automatically |
| LLM client lazy init | ~3 | Created on first `ask_llm()` call |
| `shutdown()`, `process_query()` | ~8 | Built-in |

#### 2. @agent Decorator

Convert an async function into a full agent:

```python
from logosai import agent, AgentResponse

@agent(name="Joke Agent", description="Tells jokes about any topic")
async def joke_agent(query, context=None, llm=None):
    response = await llm.invoke(f"Tell a short joke about: {query}")
    return AgentResponse.success(
        message=response.content,
        content={"answer": response.content},
    )

# Usage
instance = joke_agent()          # Creates SimpleAgent instance
result = await instance.process("cats")
print(result.content["answer"])
```

#### 3. quick_llm() — No Agent Needed

For services that just need an LLM call without agent overhead:

```python
from logosai import quick_llm

# Simple call
answer = await quick_llm("What is the capital of France?")

# With system prompt
translation = await quick_llm(
    "Hello, how are you?",
    system_prompt="Translate to Korean.",
    temperature=0.3,
)
```

### SimpleAgent Class Attributes

| Attribute | Default | Description |
|-----------|---------|-------------|
| `agent_name` | `"Unnamed Agent"` | Display name |
| `agent_description` | `""` | What the agent does |
| `agent_type_value` | `AgentType.CUSTOM` | Agent type enum |
| `llm_provider` | `"google"` | LLM provider |
| `llm_model` | `"gemini-2.5-flash-lite"` | Model name |
| `llm_temperature` | `0.7` | Generation temperature |
| `llm_max_tokens` | `4000` | Max output tokens |

### Convenience Methods

```python
class MyAgent(SimpleAgent):
    async def handle(self, query, context=None):
        # ask_llm: returns string
        text = await self.ask_llm("Explain quantum computing")

        # ask_llm_json: returns parsed dict
        data = await self.ask_llm_json(
            'Return JSON with keys "topic" and "summary"',
            fallback={"topic": "unknown", "summary": ""},
        )

        # With system prompt
        result = await self.ask_llm(
            query,
            system_prompt="You are a financial analyst.",
        )
```

### Text Utilities

Shared utilities for processing LLM responses:

```python
from logosai import parse_llm_json, clean_markdown_code

# Parse JSON from LLM response (handles ```json blocks, raw JSON, trailing text)
data = parse_llm_json('```json\n{"key": "value"}\n```')
# → {"key": "value"}

# With fallback for malformed output
data = parse_llm_json("not json", fallback={"default": True})
# → {"default": True}

# Remove markdown code fences
code = clean_markdown_code('```python\nprint("hello")\n```')
# → 'print("hello")'
```

---

## Building Your First Agent

> **Note**: For most use cases, [SimpleAgent](#quick-start-with-simpleagent-v090) above is the recommended approach. The classic `LogosAIAgent` below gives you full control when needed.

### Minimal Agent

```python
import asyncio
from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig
from logosai.agent_types import AgentType, AgentResponse, AgentResponseType


class HelloAgent(LogosAIAgent):
    """A minimal agent that echoes back the query."""

    def __init__(self):
        config = AgentConfig(
            name="Hello Agent",
            agent_type=AgentType.CUSTOM,
            description="A simple greeting agent",
        )
        super().__init__(config)

    async def process(self, query: str, context=None) -> AgentResponse:
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": f"Hello! You said: {query}"},
            message=f"Processed: {query}",
        )


async def main():
    agent = HelloAgent()
    await agent.initialize()
    result = await agent.process("Hi there!")
    print(result.content["answer"])  # "Hello! You said: Hi there!"


if __name__ == "__main__":
    asyncio.run(main())
```

### Agent with Custom Configuration

```python
class ConfigurableAgent(LogosAIAgent):
    def __init__(self, config=None):
        if config is None:
            config = AgentConfig(
                name="Configurable Agent",
                agent_type=AgentType.CUSTOM,
                description="Agent with custom parameters",
                config={
                    "provider": "google",
                    "model": "gemini-2.5-flash-lite",
                    "temperature": 0.7,
                    "max_tokens": 4000,
                }
            )
        super().__init__(config)

        # Extract parameters from config
        self.parameters = config.config if hasattr(config, 'config') else {}
        self.initialized = False

    async def initialize(self) -> bool:
        if self.initialized:
            return True
        await super().initialize()
        # Custom initialization logic here
        self.initialized = True
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.initialized:
            await self.initialize()

        try:
            result = self._do_work(query)
            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content={"answer": result},
                message=result,
                metadata={"model": self.parameters.get("model")},
            )
        except Exception as e:
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message=f"Error: {str(e)}",
            )

    def _do_work(self, query: str) -> str:
        return f"Processed with {self.parameters.get('model', 'default')}: {query}"
```

### Agent with Error Handling

```python
class RobustAgent(LogosAIAgent):
    """Agent with comprehensive error handling."""

    def __init__(self):
        config = AgentConfig(
            name="Robust Agent",
            agent_type=AgentType.CUSTOM,
            description="Agent with robust error handling",
        )
        super().__init__(config)
        self.message_bus = None  # Set by ACP server at runtime

    async def process(self, query: str, context=None) -> AgentResponse:
        try:
            # Publish status if message bus is available
            await self._publish_status("processing", {"query": query})

            # Core logic
            result = await self._process_logic(query, context)

            await self._publish_status("completed", {"query": query})
            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content={"answer": result},
                message=result,
            )

        except Exception as e:
            await self._publish_status("error", {"error": str(e)})
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message=f"Processing error: {str(e)}",
                metadata={"error_type": type(e).__name__},
            )

    async def _process_logic(self, query: str, context=None) -> str:
        # Your business logic here
        return f"Result for: {query}"

    async def _publish_status(self, status: str, data=None):
        """Publish status to message bus (safe — no-op if bus not available)."""
        if not hasattr(self, 'message_bus') or not self.message_bus:
            return
        try:
            from datetime import datetime
            await self.message_bus.publish("agent/status", {
                "agent_id": self.id,
                "agent_name": self.name,
                "status": status,
                **(data or {}),
                "timestamp": datetime.now().isoformat(),
            })
        except Exception:
            pass  # Status publishing should never break the agent

    async def process_query(self, query: str, context=None) -> AgentResponse:
        """Alias for process() — used by some ACP server versions."""
        return await self.process(query, context)

    async def shutdown(self) -> bool:
        self.initialized = False
        try:
            return await super().shutdown()
        except AttributeError:
            return True
```

---

## Adding LLM Intelligence

### Using LLMClient

```python
from logosai.utils.llm_client import LLMClient
from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig
from logosai.agent_types import AgentType, AgentResponse, AgentResponseType


class SmartAgent(LogosAIAgent):
    """Agent with LLM-powered responses."""

    def __init__(self, config=None):
        if config is None:
            config = AgentConfig(
                name="Smart Agent",
                agent_type=AgentType.CUSTOM,
                description="An LLM-powered intelligent agent",
                config={
                    "provider": "google",
                    "model": "gemini-2.5-flash-lite",
                    "temperature": 0.3,
                }
            )
        super().__init__(config)
        self.parameters = config.config or {}
        self.initialized = False

        # Initialize LLM client
        self.llm_client = LLMClient(
            provider=self.parameters.get("provider", "google"),
            model=self.parameters.get("model", "gemini-2.5-flash-lite"),
            temperature=self.parameters.get("temperature", 0.3),
        )

    async def initialize(self) -> bool:
        if self.initialized:
            return True
        await super().initialize()
        await self.llm_client.initialize()
        self.initialized = True
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.initialized:
            await self.initialize()

        # Ensure LLM client is ready
        if not hasattr(self.llm_client, '_initialized') or not self.llm_client._initialized:
            await self.llm_client.initialize()

        # Build prompt
        prompt = self._build_prompt(query, context)

        # Call LLM
        llm_response = await self.llm_client.invoke(prompt)
        content = llm_response.content

        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": content},
            message=content,
            metadata={
                "provider": self.llm_client.provider,
                "model": self.llm_client.model,
            },
        )

    def _build_prompt(self, query: str, context=None) -> str:
        system_instruction = "You are a helpful assistant. Answer concisely."
        return f"{system_instruction}\n\nUser query: {query}"
```

### Supported LLM Providers

| Provider | Value | Models |
|----------|-------|--------|
| Google Gemini | `"google"` | `gemini-2.5-flash-lite`, `gemini-2.5-pro` |
| OpenAI | `"openai"` | `gpt-4o`, `gpt-4o-mini` |
| Anthropic | `"anthropic"` | `claude-sonnet-4-5-20250929` |
| Ollama | `"ollama"` | Any local model |

### Chat-style Messages

```python
response = await llm_client.invoke_messages([
    {"role": "system", "content": "You are a financial analyst."},
    {"role": "user", "content": "Analyze Q4 earnings for AAPL"},
])
```

---

## Agent Collaboration

Agents can invoke other agents by capability, enabling coordinated multi-agent workflows.

### How It Works

1. **ACP server** loads agents and creates a `CollaborationService`
2. The service is **injected** into each agent via `agent.set_collaboration_service(service)`
3. Agents call `self.invoke_agent(capability, query)` to collaborate
4. The service finds the best agent, checks for loops, and executes the request

### Using Collaboration in Your Agent

```python
class SummarizationAgent(LogosAIAgent):
    async def process(self, query: str, context=None) -> AgentResponse:
        # Detect URL in query — delegate fetching to search agent
        import re
        url_match = re.search(r'https?://[^\s]+', query)

        if url_match and self.can_collaborate:
            url = url_match.group(0)
            try:
                result = await self.invoke_agent(
                    capability="search",
                    query=f"Fetch content from: {url}",
                    timeout=25.0,
                )
                if result.status.value == "completed" and result.data:
                    fetched_text = result.data.get("answer", "")
                    # Use fetched text for summarization...
            except Exception as e:
                # Graceful fallback — continue without fetched content
                pass

        # ... summarization logic ...
```

### Key Collaboration APIs

```python
# Check if collaboration is available
if self.can_collaborate:
    # Invoke another agent by capability
    result = await self.invoke_agent(
        capability="translation",       # What you need
        query="Translate to English: ...",  # The task
        timeout=20.0,                   # Timeout in seconds
    )

    # Check result
    from logosai.collaboration import CollaborationStatus
    if result.status == CollaborationStatus.COMPLETED:
        translated = result.data  # Agent's response
    elif result.status == CollaborationStatus.TIMEOUT:
        # Handle timeout
        pass
    elif result.status == CollaborationStatus.LOOP_DETECTED:
        # A→B→A loop was detected and prevented
        pass

# Discover agents with a specific capability
agents = await self.discover_agents("document_processing")
for agent_cap in agents:
    print(f"{agent_cap.agent_id}: {agent_cap.capabilities}")
```

### Safety Features

- **Loop Detection**: `GlobalCallGraph` prevents A→B→A cycles
- **Depth Limiting**: Maximum call depth of 5 (configurable)
- **Timeout Cascade**: Each nested call gets 70% of parent's timeout
- **Chain Tracking**: Full call chain recorded for debugging

---

## Agentic AI Modules

Enable advanced cognitive capabilities for your agents.

### Enabling Agentic Features

```python
config = AgentConfig(
    name="Cognitive Agent",
    agent_type=AgentType.CUSTOM,
    description="Agent with cognitive capabilities",
    config={
        "enable_agentic": True,
        "agentic_config": {
            "reasoning_type": "chain_of_thought",
            "memory_capacity": 100,
            "learning_rate": 0.1,
            "tools_enabled": True,
        }
    }
)
agent = MyAgent(config)
# Agentic modules auto-initialize based on config
```

### Module Overview

| Module | Class | Purpose |
|--------|-------|---------|
| **Core** | `AgenticCore` | Think-Plan-Act-Reflect cycle |
| **Reasoning** | `AgenticReasoning` | Chain of Thought, ReAct, Tree of Thoughts |
| **Memory** | `AgenticMemory` | Short-term and long-term memory |
| **Tools** | `AgenticTools` | Tool registration and execution |
| **Learning** | `AgenticLearning` | Learning from interactions |

### Using Reasoning

```python
from logosai.agentic import AgenticReasoning, ReasoningType

reasoning = AgenticReasoning()

# Chain of Thought
chain = await reasoning.create_chain(
    "Analyze quarterly revenue trends and predict next quarter",
    reasoning_type=ReasoningType.CHAIN_OF_THOUGHT,
)
```

### Using Memory

```python
from logosai.agentic import AgenticMemory, MemoryType

memory = AgenticMemory(capacity=100)

# Store a memory
memory.store(
    content="User prefers Korean language responses",
    memory_type=MemoryType.LONG_TERM,
)

# Retrieve relevant memories
results = memory.recall("language preference")
```

### Using Tools

```python
from logosai.agentic import AgenticTools, tool_decorator

tools = AgenticTools()

@tool_decorator(name="calculator", description="Perform math calculations")
async def calculator(expression: str) -> str:
    return str(eval(expression))

tools.register(calculator)
result = await tools.execute("calculator", expression="42 * 17")
```

---

## Agent Debate System

The Debate System (v0.5.0) enables autonomous multi-agent negotiation to decide on optimal workflows.

### 5-Phase Process

```
Phase 1: Query Analysis    — Each agent evaluates relevance to the query
Phase 2: Role Proposal     — Relevant agents propose their roles
Phase 3: Discussion        — Agents comment on each other's proposals
Phase 4: Voting           — Agents vote on workflow options (weighted by confidence)
Phase 5: Consensus        — Winner determined by weighted score
```

### Usage

```python
from logosai.debate import SimpleDebateSystem, DebateResult

# Create debate system
debate = SimpleDebateSystem()

# Create agents (any LogosAIAgent instances)
agents = [data_analyst, researcher, writer]

# Run debate
result: DebateResult = await debate.start_debate(
    query="Analyze Q4 sales data and generate a forecast report.",
    agents=agents,
)

# Access results
print(f"Workflow: {result.workflow}")
print(f"Participants: {result.participating_agents}")
print(f"Consensus: {result.consensus_reached}")
print(f"Transcript: {result.debate_transcript}")
```

### Voting System

```python
from logosai.debate import VotingSystem, Vote

vs = VotingSystem()
vs.cast_vote(Vote(voter_id="agent_1", choice="workflow_0", reasoning="Best fit", confidence=0.9))
vs.cast_vote(Vote(voter_id="agent_2", choice="workflow_1", reasoning="More logical", confidence=0.7))
vs.cast_vote(Vote(voter_id="agent_3", choice="workflow_0", reasoning="Agree", confidence=0.8))

result = vs.count_votes()
print(result["winner"])           # "workflow_0"
print(result["weighted_scores"])  # {"workflow_0": 1.7, "workflow_1": 0.7}
```

---

## Agent Self-Evolution

The Evolution System (v0.7.0) enables agents to detect problems, learn patterns, and improve autonomously.

### Capabilities

- **Self-Healing**: Automatically detect and fix errors
- **Self-Growing**: Add new features and improve existing ones
- **Self-Evaluation**: Quality scoring and feedback collection

### Basic Usage

```python
from logosai.evolution import EvolutionSystem, EvolutionConfig

# Create config (disabled by default for safety)
config = EvolutionConfig(
    enabled=True,
    llm_provider="google",
    llm_model="gemini-2.5-flash-lite",
)

# Attach to an agent
evolution = EvolutionSystem(agent, config)
await evolution.enable()

# Evolve based on a problematic response
result = await evolution.evolve(
    query="Convert 100 USD to KRW",
    response="This feature is not supported",
)

if result.improvements:
    for imp in result.improvements:
        print(f"Suggested: {imp.improvement_type} (confidence: {imp.confidence})")
```

### Safety Mechanisms

| Mechanism | Description |
|-----------|-------------|
| **Circuit Breaker** | 3 consecutive failures → 1 hour cooldown |
| **Confidence Gates** | 5-tier validation: AUTO_APPLY (>=0.95), STAGED_ROLLOUT (>=0.85), HUMAN_REVIEW (>=0.70), SUGGEST_ONLY (>=0.50), REJECT (<0.50) |
| **Fix History** | Tracks past fixes, prevents cycles (Jaccard similarity >= 0.85), max 3 attempts per problem |

### Configuration

```python
from logosai.evolution import EvolutionConfig, SafetyConfig

config = EvolutionConfig(
    enabled=True,
    llm_provider="google",
    llm_model="gemini-2.5-flash-lite",
    safety=SafetyConfig(
        circuit_breaker_threshold=3,   # Failures before cooldown
        cooldown_seconds=3600,         # 1 hour cooldown
        max_fix_attempts=3,            # Max attempts per problem
        auto_apply_threshold=0.95,     # Confidence for auto-apply
    ),
)
```

---

## Streaming Responses

Agents can stream responses for real-time UIs.

```python
# Using built-in process_stream()
async for event in agent.process_stream("Analyze this data..."):
    if event["type"] == "start":
        print(f"Agent {event['data']['agent_name']} started")
    elif event["type"] == "progress":
        print(f"Stage: {event['data']['stage']}")
    elif event["type"] == "chunk":
        print(event["data"]["content"], end="")
    elif event["type"] == "complete":
        print(f"\nDone: {event['data']['message']}")
    elif event["type"] == "error":
        print(f"Error: {event['data']['error']}")
```

### Event Types

| Type | Description |
|------|-------------|
| `start` | Processing started (agent_id, agent_name, query) |
| `progress` | Stage update (stage, message) |
| `chunk` | Partial content (content, index, is_last) |
| `complete` | Final result (result, response_type, message, metadata) |
| `error` | Error occurred (error, error_type) |

---

## Production Patterns

### Recommended: Use SimpleAgent

For new agents, **SimpleAgent handles all production boilerplate automatically**:

```python
from logosai import SimpleAgent, AgentResponse

class MyProductionAgent(SimpleAgent):
    agent_name = "My Production Agent"
    agent_description = "Does production work"
    llm_temperature = 0.3

    async def handle(self, query, context=None):
        result = await self.ask_llm(f"Process: {query}")
        return AgentResponse.success(content={"answer": result}, message=result)
```

This is equivalent to the full template below — SimpleAgent auto-manages init, error handling, publish_status, shutdown, process_query, and LLM lifecycle.

### Classic Agent Checklist

When building agents with `LogosAIAgent` directly, ensure:

1. **`config=None` default** in `__init__` for flexible instantiation
2. **`super().__init__(config)`** call
3. **`process(self, query, context=None)`** signature (ACP compatibility)
4. **Error handling** with `AgentResponse.ERROR` returns (never raise)
5. **`publish_status()`** with `hasattr` guard for message bus
6. **`process_query()`** alias pointing to `process()`
7. **`shutdown()`** with `AttributeError` guard on `super().shutdown()`
8. **`initialize()`** with idempotency check (`if self.initialized: return True`)

### Complete Classic Production Agent Template

```python
import json
import re
from typing import Dict, Any, Optional
from datetime import datetime

from loguru import logger
from logosai.utils.llm_client import LLMClient
from logosai.agent_types import AgentType, AgentResponse, AgentResponseType
from logosai.config import AgentConfig
from logosai.agent import LogosAIAgent


class ProductionAgent(LogosAIAgent):
    """Production-ready agent template."""

    def __init__(self, config: Optional[AgentConfig] = None):
        if config is None:
            config = AgentConfig(
                name="Production Agent",
                agent_type=AgentType.CUSTOM,
                description="A production-ready agent",
                config={
                    "provider": "google",
                    "model": "gemini-2.5-flash-lite",
                    "temperature": 0.3,
                    "max_tokens": 4000,
                }
            )
        super().__init__(config)

        self.name = config.name
        self.description = config.description
        self.parameters = config.config or {}
        self.message_bus = None
        self.initialized = False

        self.llm_client = LLMClient(
            provider=self.parameters.get("provider", "google"),
            model=self.parameters.get("model", "gemini-2.5-flash-lite"),
            temperature=self.parameters.get("temperature", 0.3),
        )

    async def initialize(self) -> bool:
        if self.initialized:
            return True
        try:
            await super().initialize()
            await self.llm_client.initialize()
            logger.info(f"Agent initialized: {self.name}")
            self.initialized = True
            return True
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            self.initialized = False
            return False

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        try:
            if not self.initialized:
                await self.initialize()

            await self._safe_publish("processing", {"query": query})

            if not self.llm_client._initialized:
                await self.llm_client.initialize()

            # Build prompt and call LLM
            prompt = self._build_prompt(query, context)
            llm_response = await self.llm_client.invoke(prompt)
            content = llm_response.content

            await self._safe_publish("completed", {"query": query})

            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content={"answer": content},
                message=content,
                metadata={
                    "provider": self.llm_client.provider,
                    "model": self.llm_client.model,
                },
            )

        except Exception as e:
            logger.error(f"Process error: {e}")
            await self._safe_publish("error", {"error": str(e)})
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message=f"Error: {str(e)}",
                metadata={"error_type": type(e).__name__},
            )

    def _build_prompt(self, query: str, context=None) -> str:
        return f"You are a helpful assistant.\n\nQuery: {query}"

    async def _safe_publish(self, status: str, data=None):
        if not hasattr(self, 'message_bus') or not self.message_bus:
            return
        try:
            await self.message_bus.publish("agent/status", {
                "agent_id": self.id,
                "agent_name": self.name,
                "status": status,
                **(data or {}),
                "timestamp": datetime.now().isoformat(),
            })
        except Exception:
            pass

    async def process_query(self, query: str, context=None) -> AgentResponse:
        return await self.process(query, context)

    async def shutdown(self) -> bool:
        logger.info(f"Shutting down: {self.name}")
        self.initialized = False
        try:
            return await super().shutdown()
        except AttributeError:
            return True
```

---

## API Reference

### SimpleAgent (v0.9.0)

| Method / Attribute | Signature | Description |
|--------------------|-----------|-------------|
| `agent_name` | `str` (class attr) | Agent display name |
| `agent_description` | `str` (class attr) | What the agent does |
| `agent_type_value` | `AgentType` (class attr) | Agent type (default: `CUSTOM`) |
| `llm_provider` | `str` (class attr) | LLM provider (default: `"google"`) |
| `llm_model` | `str` (class attr) | Model name (default: `"gemini-2.5-flash-lite"`) |
| `llm_temperature` | `float` (class attr) | Temperature (default: `0.7`) |
| `llm_max_tokens` | `int` (class attr) | Max tokens (default: `4000`) |
| `handle` | `(query: str, context=None) -> AgentResponse` | **Override this** — your business logic |
| `ask_llm` | `(prompt, system_prompt=None, **kwargs) -> str` | Call LLM, return text |
| `ask_llm_json` | `(prompt, fallback=None, **kwargs) -> dict` | Call LLM, parse JSON |
| `process` | `(query, context=None) -> AgentResponse` | ACP-facing (wraps `handle()` with lifecycle) |
| `initialize` | `() -> bool` | Auto-called on first `process()` |
| `shutdown` | `() -> bool` | Graceful shutdown |

### quick_llm (v0.9.0)

```python
async def quick_llm(
    prompt: str,
    provider: str = "google",
    model: str = "gemini-2.5-flash-lite",
    temperature: float = 0.7,
    system_prompt: str = None,
    max_tokens: int = 4000,
) -> str
```

One-shot LLM call with no setup. Returns the response text directly.

### Text Utilities (v0.9.0)

| Function | Signature | Description |
|----------|-----------|-------------|
| `parse_llm_json` | `(text: str, fallback=None) -> dict` | Extract JSON from LLM response (handles \`\`\`json blocks, raw JSON, trailing text) |
| `clean_markdown_code` | `(text: str) -> str` | Remove markdown code fences |
| `extract_code_block` | `(text: str, language="") -> Optional[str]` | Extract code block for a specific language |
| `truncate_for_prompt` | `(text: str, max_chars=500) -> str` | Truncate text for LLM prompt inclusion |

### @agent Decorator (v0.9.0)

```python
@agent(name="Agent Name", description="What it does", llm_model="gemini-2.5-flash-lite")
async def my_agent(query, context=None, llm=None):
    response = await llm.invoke(f"Process: {query}")
    return AgentResponse.success(content={"answer": response.content})

instance = my_agent()  # Returns a SimpleAgent instance
```

### LogosAIAgent

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(config: AgentConfig)` | Initialize agent with configuration |
| `initialize` | `() -> bool` | Async initialization |
| `process` | `(query: str, context=None) -> AgentResponse` | Process a query |
| `process_stream` | `(query: str, context=None) -> AsyncGenerator` | Stream processing events |
| `shutdown` | `() -> bool` | Graceful shutdown |
| `can_handle` | `(query, context) -> (bool, float, str)` | Evaluate query compatibility |
| `invoke_agent` | `(capability, query, context, timeout) -> CollaborationResult` | Collaborate with another agent |
| `discover_agents` | `(capability) -> List[AgentCapability]` | Find agents by capability |
| `can_collaborate` | `-> bool` | Whether collaboration service is available |
| `get_info` | `() -> Dict` | Agent info (name, type, description, capabilities) |

### AgentConfig

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Agent display name |
| `agent_type` | `AgentType` | Agent type enum |
| `description` | `str` | Agent description |
| `config` | `Dict` | Custom parameters (provider, model, temperature, etc.) |
| `api_config` | `Dict` | API connection settings |
| `llm_config` | `Dict` | LLM model settings |

### AgentResponse

| Field | Type | Description |
|-------|------|-------------|
| `type` | `AgentResponseType` | `SUCCESS`, `ERROR`, `TEXT`, `HTML`, `JSON` |
| `content` | `Dict[str, Any]` | Response payload (typically `{"answer": "..."}`) |
| `message` | `str` | Human-readable summary |
| `metadata` | `Dict[str, Any]` | Provider, model, timing, etc. |

### LLMClient

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(provider, model, temperature)` | Create client |
| `initialize` | `() -> None` | Async initialization |
| `invoke` | `(prompt, max_tokens, temperature) -> LLMResponse` | Single prompt |
| `invoke_messages` | `(messages) -> LLMResponse` | Chat-style messages |

### CollaborationResult

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | `str` | Unique request ID |
| `status` | `CollaborationStatus` | `COMPLETED`, `FAILED`, `TIMEOUT`, `LOOP_DETECTED`, `DEPTH_EXCEEDED` |
| `agent_id` | `str` | Agent that handled the request |
| `data` | `Any` | Result data |
| `error` | `Optional[str]` | Error message if failed |
| `execution_time` | `float` | Execution time in seconds |
| `call_chain` | `List[str]` | Full call chain for debugging |
