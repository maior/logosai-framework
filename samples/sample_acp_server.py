"""
LogosAI Sample ACP Server — 6 agents on port 8888.

Agents:
  - LLM Chat Agent      — General conversation (Gemini/OpenAI)
  - Calculator Agent     — Math expressions
  - Translation Agent    — Multi-language translation
  - Code Agent           — Code generation and explanation
  - Summarization Agent  — Text summarization
  - Writing Agent        — Email, report, letter writing

Requirements:
    pip install logosai

Run:
    python sample_acp_server.py
    # Test: curl http://localhost:8888/jsonrpc -d '{"jsonrpc":"2.0","method":"list_agents","id":1}'

For use with logos_api:
    1. Start this server: python sample_acp_server.py
    2. Start logos_api:   cd logosai-api && uvicorn app.main:app --port 8090
    3. Start logos_web:   cd logosai-web && npm run dev (port 8010)
"""

import asyncio
import re
import json
import os
import time
from datetime import datetime
from aiohttp import web

from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

# Try to import LLMClient for smart agents
try:
    from logosai.utils.llm_client import LLMClient
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


# ═══════════════════════════════════════════
# Helper: get LLM client
# ═══════════════════════════════════════════
def create_llm_client():
    """Create LLM client from available API keys."""
    if not LLM_AVAILABLE:
        return None

    google_key = os.getenv("GOOGLE_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if google_key:
        return LLMClient(provider="google", model="gemini-2.5-flash-lite", temperature=0.7, max_tokens=4096)
    elif openai_key:
        return LLMClient(provider="openai", model="gpt-4.1-mini", temperature=0.7, max_tokens=4096)
    return None


async def llm_call_with_retry(llm, messages, timeout=30, max_retries=3):
    """Call LLM with automatic retry on 503/overload errors."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.wait_for(llm.invoke_messages(messages), timeout=timeout)
            return response if isinstance(response, str) else str(response)
        except asyncio.TimeoutError:
            last_error = "Request timed out"
        except Exception as e:
            last_error = str(e)
            if "503" in last_error or "UNAVAILABLE" in last_error or "overload" in last_error.lower():
                wait = attempt * 2  # 2s, 4s, 6s
                print(f"  [retry] LLM 503 — waiting {wait}s (attempt {attempt}/{max_retries})")
                await asyncio.sleep(wait)
                continue
            raise  # Non-retryable error
    raise Exception(f"LLM failed after {max_retries} retries: {last_error}")


# ═══════════════════════════════════════════
# Agent 1: LLM Chat Agent
# ═══════════════════════════════════════════
class LLMChatAgent(LogosAIAgent):
    """General-purpose conversational agent powered by LLM."""

    def __init__(self):
        config = AgentConfig(
            name="LLM Chat Agent",
            agent_type=AgentType.CUSTOM,
            description="General conversation, Q&A, knowledge queries, reasoning, and creative tasks. Handles any topic.",
        )
        super().__init__(config)
        self.llm = None

    async def initialize(self):
        await super().initialize()
        self.llm = create_llm_client()
        if self.llm:
            await self.llm.initialize()
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.llm:
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": "No LLM API key configured. Set GOOGLE_API_KEY or OPENAI_API_KEY."},
                message="LLM not available",
            )
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            messages = [
                {"role": "system", "content": f"You are LogosAI, a helpful AI assistant. Today is {today}. Answer clearly and concisely. Respond in the same language as the user's query."},
                {"role": "user", "content": query},
            ]
            answer = await llm_call_with_retry(self.llm, messages, timeout=30)
            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content={"answer": answer},
                message="Response generated",
            )
        except Exception as e:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": str(e)}, message="LLM error")


# ═══════════════════════════════════════════
# Agent 2: Calculator Agent
# ═══════════════════════════════════════════
class CalculatorAgent(LogosAIAgent):
    """Calculator agent that evaluates math expressions."""

    def __init__(self):
        config = AgentConfig(
            name="Calculator Agent",
            agent_type=AgentType.CUSTOM,
            description="Evaluates arithmetic expressions: addition, subtraction, multiplication, division, percentages, and unit conversions.",
        )
        super().__init__(config)
        self.llm = None

    async def initialize(self):
        await super().initialize()
        self.llm = create_llm_client()
        if self.llm:
            await self.llm.initialize()
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        # Try direct evaluation first
        expr = re.sub(r"[^0-9+\-*/().\s%]", "", query)
        if expr.strip():
            try:
                clean_expr = expr.replace("%", "/100")
                result = eval(clean_expr, {"__builtins__": {}}, {})
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": f"{expr.strip()} = {result}"},
                    message="Calculation complete",
                )
            except Exception:
                pass

        # Fall back to LLM for complex math queries
        if self.llm:
            try:
                messages = [
                    {"role": "system", "content": "You are a math assistant. Solve the problem step by step. Show the calculation and final answer. Respond in the same language as the user."},
                    {"role": "user", "content": query},
                ]
                answer = await llm_call_with_retry(self.llm, messages, timeout=15)
                return AgentResponse(type=AgentResponseType.SUCCESS, content={"answer": answer}, message="Calculation complete")
            except Exception:
                pass

        return AgentResponse(type=AgentResponseType.ERROR, content={"error": "Could not evaluate expression"}, message="Parse error")


# ═══════════════════════════════════════════
# Agent 3: Translation Agent
# ═══════════════════════════════════════════
class TranslationAgent(LogosAIAgent):
    """Multi-language translation agent."""

    def __init__(self):
        config = AgentConfig(
            name="Translation Agent",
            agent_type=AgentType.CUSTOM,
            description="Translates text between languages: English, Korean, Japanese, Chinese, Spanish, French, German, and more.",
        )
        super().__init__(config)
        self.llm = None

    async def initialize(self):
        await super().initialize()
        self.llm = create_llm_client()
        if self.llm:
            await self.llm.initialize()
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.llm:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": "LLM not available"}, message="No LLM")
        try:
            messages = [
                {"role": "system", "content": "You are a professional translator. Detect the source language and translate to the requested target language. If no target is specified, translate Korean to English or English to Korean. Preserve tone and nuance."},
                {"role": "user", "content": query},
            ]
            answer = await llm_call_with_retry(self.llm, messages, timeout=20)

            return AgentResponse(type=AgentResponseType.SUCCESS, content={"answer": answer}, message="Translation complete")
        except Exception as e:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": str(e)}, message="Translation error")


# ═══════════════════════════════════════════
# Agent 4: Code Agent
# ═══════════════════════════════════════════
class CodeAgent(LogosAIAgent):
    """Code generation and explanation agent."""

    def __init__(self):
        config = AgentConfig(
            name="Code Agent",
            agent_type=AgentType.CUSTOM,
            description="Generates, explains, debugs, and reviews code. Supports Python, JavaScript, TypeScript, Java, Go, SQL, and more.",
        )
        super().__init__(config)
        self.llm = None

    async def initialize(self):
        await super().initialize()
        self.llm = create_llm_client()
        if self.llm:
            await self.llm.initialize()
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.llm:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": "LLM not available"}, message="No LLM")
        try:
            messages = [
                {"role": "system", "content": "You are an expert software engineer. Write clean, well-commented code. Explain your approach briefly. Use markdown code blocks with language tags. Respond in the same language as the user's query."},
                {"role": "user", "content": query},
            ]
            answer = await llm_call_with_retry(self.llm, messages, timeout=30)

            return AgentResponse(type=AgentResponseType.SUCCESS, content={"answer": answer}, message="Code generated")
        except Exception as e:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": str(e)}, message="Code error")


# ═══════════════════════════════════════════
# Agent 5: Summarization Agent
# ═══════════════════════════════════════════
class SummarizationAgent(LogosAIAgent):
    """Text summarization agent."""

    def __init__(self):
        config = AgentConfig(
            name="Summarization Agent",
            agent_type=AgentType.CUSTOM,
            description="Summarizes long text, articles, documents, and reports into concise bullet points or paragraphs.",
        )
        super().__init__(config)
        self.llm = None

    async def initialize(self):
        await super().initialize()
        self.llm = create_llm_client()
        if self.llm:
            await self.llm.initialize()
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.llm:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": "LLM not available"}, message="No LLM")
        try:
            messages = [
                {"role": "system", "content": "You are a summarization expert. Provide clear, structured summaries. Use bullet points for key findings. Keep it concise. Respond in the same language as the input text."},
                {"role": "user", "content": f"Summarize the following:\n\n{query}"},
            ]
            answer = await llm_call_with_retry(self.llm, messages, timeout=30)

            return AgentResponse(type=AgentResponseType.SUCCESS, content={"answer": answer}, message="Summary generated")
        except Exception as e:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": str(e)}, message="Summarization error")


# ═══════════════════════════════════════════
# Agent 6: Writing Agent
# ═══════════════════════════════════════════
class WritingAgent(LogosAIAgent):
    """Professional writing assistant."""

    def __init__(self):
        config = AgentConfig(
            name="Writing Agent",
            agent_type=AgentType.CUSTOM,
            description="Writes emails, reports, proposals, letters, blog posts, and other professional documents.",
        )
        super().__init__(config)
        self.llm = None

    async def initialize(self):
        await super().initialize()
        self.llm = create_llm_client()
        if self.llm:
            await self.llm.initialize()
        return True

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.llm:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": "LLM not available"}, message="No LLM")
        try:
            messages = [
                {"role": "system", "content": "You are a professional writer. Write well-structured, polished content appropriate for the requested format (email, report, proposal, etc.). Match the formality level to the context. Respond in the same language as the user's query."},
                {"role": "user", "content": query},
            ]
            answer = await llm_call_with_retry(self.llm, messages, timeout=30)

            return AgentResponse(type=AgentResponseType.SUCCESS, content={"answer": answer}, message="Writing complete")
        except Exception as e:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": str(e)}, message="Writing error")


# ═══════════════════════════════════════════
# Agent 7: Internet Search Agent (requires TAVILY_API_KEY)
# ═══════════════════════════════════════════
class InternetSearchAgent(LogosAIAgent):
    """Internet search agent powered by Tavily API + LLM."""

    def __init__(self):
        config = AgentConfig(
            name="Internet Search Agent",
            agent_type=AgentType.CUSTOM,
            description="Searches the internet for real-time information: news, weather, prices, current events, and factual queries.",
        )
        super().__init__(config)
        self.llm = None
        self.tavily_key = os.getenv("TAVILY_API_KEY", "")

    async def initialize(self):
        await super().initialize()
        self.llm = create_llm_client()
        if self.llm:
            await self.llm.initialize()
        return True

    def is_available(self):
        return bool(self.tavily_key)

    async def _tavily_search(self, query: str, topic: str = "general", max_results: int = 5) -> dict:
        """Call Tavily Search API."""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            payload = {
                "api_key": self.tavily_key,
                "query": query,
                "search_depth": "basic",
                "include_answer": True,
                "max_results": max_results,
                "topic": topic,
            }
            async with session.post("https://api.tavily.com/search", json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    raise Exception(f"Tavily API error: {resp.status}")

    async def process(self, query: str, context=None) -> AgentResponse:
        if not self.tavily_key:
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": "TAVILY_API_KEY not set. Get a free key at https://tavily.com"},
                message="Tavily not configured",
            )

        try:
            today = datetime.now().strftime("%Y-%m-%d")

            # Step 1: Optimize query with LLM (detect time intent)
            search_query = query
            topic = "general"
            if self.llm:
                try:
                    analysis_msgs = [
                        {"role": "system", "content": f"Today is {today}. Extract a search-optimized query from the user input. Return JSON: {{\"query\": \"optimized search query with dates if relevant\", \"topic\": \"news\" or \"general\"}}. JSON only."},
                        {"role": "user", "content": query},
                    ]
                    analysis = await llm_call_with_retry(self.llm, analysis_msgs, timeout=10)
                    json_match = re.search(r'\{[^{}]*\}', analysis, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group())
                        search_query = parsed.get("query", query)
                        topic = parsed.get("topic", "general")
                except Exception:
                    pass  # Use original query

            # Step 2: Search
            results = await self._tavily_search(search_query, topic=topic)
            tavily_answer = results.get("answer", "")
            search_results = results.get("results", [])

            # Step 3: Synthesize with LLM
            if self.llm and search_results:
                sources = "\n".join([
                    f"- {r.get('title', '')}: {r.get('content', '')[:300]} ({r.get('url', '')})"
                    for r in search_results[:5]
                ])
                synth_msgs = [
                    {"role": "system", "content": f"Today is {today}. You are a search assistant. Answer the user's question based on the search results. Cite sources with URLs. If data is old, note the date. Respond in the same language as the user's query."},
                    {"role": "user", "content": f"Question: {query}\n\nTavily summary: {tavily_answer}\n\nSearch results:\n{sources}\n\nProvide a clear, concise answer with sources."},
                ]
                answer = await llm_call_with_retry(self.llm, synth_msgs, timeout=20)
            elif tavily_answer:
                answer = tavily_answer
            else:
                answer = "No results found."

            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content={"answer": answer},
                message="Search complete",
            )
        except Exception as e:
            return AgentResponse(type=AgentResponseType.ERROR, content={"error": str(e)}, message="Search error")


# ═══════════════════════════════════════════
# Agent Registry
# ═══════════════════════════════════════════
AGENTS = {}


async def _load_agents():
    agents = [
        LLMChatAgent(),
        CalculatorAgent(),
        TranslationAgent(),
        CodeAgent(),
        SummarizationAgent(),
        WritingAgent(),
        InternetSearchAgent(),
    ]

    loaded = []
    skipped = []
    for a in agents:
        # Skip agents that require unavailable API keys
        if hasattr(a, 'is_available') and not a.is_available():
            skipped.append(a.config.name)
            continue
        await a.initialize()
        agent_id = a.config.name.lower().replace(" ", "_")
        AGENTS[agent_id] = a
        loaded.append(agent_id)

    llm_status = "with LLM" if LLM_AVAILABLE and create_llm_client() else "without LLM (set GOOGLE_API_KEY)"
    print(f"Loaded {len(AGENTS)} agents ({llm_status}): {loaded}")
    if skipped:
        print(f"  Skipped (missing API key): {skipped}")


# ═══════════════════════════════════════════
# JSON-RPC Handler
# ═══════════════════════════════════════════
async def jsonrpc_handler(request: web.Request) -> web.Response:
    body = await request.json()
    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id", 1)

    if method == "list_agents":
        agent_list = [
            {
                "agent_id": aid,
                "name": a.config.name,
                "description": a.config.description,
            }
            for aid, a in AGENTS.items()
        ]
        return web.json_response(
            {"jsonrpc": "2.0", "id": req_id, "result": {"agents": agent_list}}
        )

    if method == "process":
        agent_id = params.get("agent_id", "")
        query = params.get("query", "")
        agent = AGENTS.get(agent_id)
        if not agent:
            return web.json_response(
                {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown agent: {agent_id}"}},
            )
        result = await agent.process(query)
        return web.json_response(
            {"jsonrpc": "2.0", "id": req_id, "result": result.content}
        )

    return web.json_response(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}},
    )


# ═══════════════════════════════════════════
# SSE Stream Handler (logos_api compatible)
# ═══════════════════════════════════════════
async def stream_handler(request: web.Request) -> web.StreamResponse:
    """SSE streaming endpoint compatible with logos_api's ACP client."""
    body = await request.json()
    query = body.get("query", "")
    agent_query = body.get("agent_query", query)
    sessionid = body.get("sessionid", "default")
    requested_agents = body.get("agents", [])

    response = web.StreamResponse()
    response.content_type = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    await response.prepare(request)

    start_time = time.time()

    async def send_event(event_type: str, data: dict):
        payload = json.dumps(data, ensure_ascii=False)
        await response.write(f"event: {event_type}\ndata: {payload}\n\n".encode())

    # Initialization
    await send_event("initialization", {"message": "System initializing", "session_id": sessionid})

    # Select agent — use requested agent or find best match
    agent_id = None
    if requested_agents:
        for ra in requested_agents:
            aid = ra.get("agent_id", "") if isinstance(ra, dict) else str(ra)
            if aid in AGENTS:
                agent_id = aid
                break

    # Fallback: simple keyword matching to pick best agent
    if not agent_id:
        q_lower = query.lower()
        if any(kw in q_lower for kw in ["계산", "더하기", "빼기", "곱하기", "나누기", "calculate", "+", "-", "*", "/"]):
            agent_id = "calculator_agent"
        elif any(kw in q_lower for kw in ["번역", "translate", "영어로", "한국어로", "일본어"]):
            agent_id = "translation_agent"
        elif any(kw in q_lower for kw in ["코드", "code", "프로그램", "함수", "python", "javascript", "function", "class"]):
            agent_id = "code_agent"
        elif any(kw in q_lower for kw in ["요약", "summarize", "summary", "정리"]):
            agent_id = "summarization_agent"
        elif any(kw in q_lower for kw in ["작성", "이메일", "보고서", "write", "email", "report", "letter"]):
            agent_id = "writing_agent"
        elif any(kw in q_lower for kw in ["검색", "찾아", "search", "뉴스", "news", "날씨", "weather", "오늘", "today", "현재", "최신", "가격", "price", "환율", "주가"]):
            agent_id = "internet_search_agent" if "internet_search_agent" in AGENTS else "llm_chat_agent"
        else:
            agent_id = "llm_chat_agent"  # Default to general chat

    if agent_id not in AGENTS:
        agent_id = "llm_chat_agent"

    agent = AGENTS[agent_id]

    # Agent selection event
    await send_event("agents_selected", {
        "agents": [{"agent_id": agent_id, "agent_name": agent.config.name}],
    })

    # Agent started
    await send_event("agent_started", {
        "agent_id": agent_id,
        "agent_name": agent.config.name,
    })

    # Execute agent
    use_query = agent_query if agent_query != query else query
    result = await agent.process(use_query)
    exec_time = round(time.time() - start_time, 2)

    # Agent completed
    await send_event("agent_completed", {
        "agent_id": agent_id,
        "agent_name": agent.config.name,
        "result": result.content,
        "execution_time": exec_time,
    })

    # Final result
    answer = result.content.get("answer", result.content.get("error", str(result.content)))
    await send_event("final_result", {
        "code": 0 if result.type == AgentResponseType.SUCCESS else 1,
        "data": {
            "result": answer,
            "agent_results": [{
                "agent_id": agent_id,
                "agent_name": agent.config.name,
                "result": result.content,
                "confidence": 0.9,
                "execution_time": exec_time,
            }],
            "metadata": {
                "total_agents": 1,
                "successful_agents": 1 if result.type == AgentResponseType.SUCCESS else 0,
                "execution_time": exec_time,
            },
        },
    })

    return response


# ═══════════════════════════════════════════
# App Setup
# ═══════════════════════════════════════════
async def init_app():
    await _load_agents()
    app = web.Application()
    app.router.add_post("/jsonrpc", jsonrpc_handler)
    app.router.add_post("/stream/multi", stream_handler)
    return app


if __name__ == "__main__":
    PORT = 8888
    print(f"Starting LogosAI ACP server on http://localhost:{PORT}")
    print(f"  JSON-RPC:    POST http://localhost:{PORT}/jsonrpc")
    print(f"  SSE Stream:  POST http://localhost:{PORT}/stream/multi")
    print(f"  Agents:      6 (Chat, Calculator, Translation, Code, Summary, Writing)")
    print(f"  Test: curl http://localhost:{PORT}/jsonrpc -d '{{\"jsonrpc\":\"2.0\",\"method\":\"list_agents\",\"id\":1}}'")
    print()
    web.run_app(init_app(), port=PORT)
