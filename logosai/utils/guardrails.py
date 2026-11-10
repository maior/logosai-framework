"""Guardrails — Rate limiting + call counting for LLM safety.

Prevents:
- 429 Rate Limit errors (TokenBucketRateLimiter)
- Agent runaway / LLM call explosion (RequestCallCounter)

Integrated into LLMClient.invoke_messages() automatically.

Config via ~/.logosai/config.json:
    "guardrails": {
        "rate_limit_per_minute": 30,
        "max_calls_per_request": 15
    }
"""

import asyncio
import time
from loguru import logger


class LLMCallLimitExceeded(Exception):
    """Raised when per-request LLM call limit is exceeded."""
    pass


class TokenBucketRateLimiter:
    """Token bucket rate limiter — prevents 429 errors.

    Limits LLM calls per minute globally. If bucket is empty,
    waits until a token is available (instead of getting 429).
    """

    def __init__(self, calls_per_minute: int = 30):
        self.max_tokens = calls_per_minute
        self.tokens = float(calls_per_minute)
        self.refill_rate = calls_per_minute / 60.0
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume one."""
        async with self._lock:
            self._refill()
            while self.tokens < 1:
                wait_time = (1 - self.tokens) / self.refill_rate
                logger.debug(f"Rate limiter: waiting {wait_time:.1f}s")
                await asyncio.sleep(min(wait_time, 2.0))
                self._refill()
            self.tokens -= 1

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now


class RequestCallCounter:
    """Per-request LLM call counter — prevents agent runaway.

    Each request gets a counter. Raises LLMCallLimitExceeded when limit hit.
    Agent should catch this and return partial results gracefully.
    """

    def __init__(self, max_calls: int = 15):
        self.max_calls = max_calls
        self.current_calls = 0

    def increment(self):
        self.current_calls += 1
        if self.current_calls > self.max_calls:
            raise LLMCallLimitExceeded(
                f"LLM call limit exceeded: {self.current_calls}/{self.max_calls}"
            )

    def reset(self):
        self.current_calls = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.current_calls)


# ── Global singleton (shared across all LLMClient instances) ──

_rate_limiter = None
_request_counter = None


def get_rate_limiter() -> TokenBucketRateLimiter:
    """Get global rate limiter (created once, reused)."""
    global _rate_limiter
    if _rate_limiter is None:
        rate = _get_config("rate_limit_per_minute", 30)
        _rate_limiter = TokenBucketRateLimiter(calls_per_minute=rate)
    return _rate_limiter


def get_request_counter() -> RequestCallCounter:
    """Get global request counter (reset per request by caller)."""
    global _request_counter
    if _request_counter is None:
        max_calls = _get_config("max_calls_per_request", 15)
        _request_counter = RequestCallCounter(max_calls=max_calls)
    return _request_counter


def reset_request_counter():
    """Reset counter for new request."""
    global _request_counter
    if _request_counter:
        _request_counter.reset()


def _get_config(key: str, default):
    """Read guardrails config from ~/.logosai/config.json."""
    import json
    import os
    try:
        path = os.path.expanduser("~/.logosai/config.json")
        if os.path.exists(path):
            with open(path) as f:
                config = json.load(f)
            return config.get("guardrails", {}).get(key, default)
    except Exception:
        pass
    return default


# ── Per-execution 하네스 예산 (호출 수·토큰 상한) — P0-2 확장 (2026-07-06) ──
# 글로벌 RequestCallCounter 와 달리 ContextVar 로 실행별 격리한다.
# 하네스 래퍼(observability.observe_process)가 process() 진입 시 begin,
# 종료 시 reset. LLMClient 가 호출 전 precheck / 호출 후 record_tokens 를 부른다.
# caps 미설정(None)이면 완전 no-op → 비하네스 경로 성능/동작 불변.
from contextvars import ContextVar
from typing import Optional as _Optional, Tuple as _Tuple

_exec_calls: ContextVar[int] = ContextVar("_hb_exec_calls", default=0)
_exec_tokens: ContextVar[int] = ContextVar("_hb_exec_tokens", default=0)
_exec_max_calls: ContextVar[_Optional[int]] = ContextVar("_hb_max_calls", default=None)
_exec_max_tokens: ContextVar[_Optional[int]] = ContextVar("_hb_max_tokens", default=None)


class HarnessBudgetExceeded(Exception):
    """실행당 LLM 호출/토큰 상한 초과 — 하네스가 graceful error 로 변환한다."""
    pass


# ── 신규 경로(tools · stream) 커버 — LOGOSAI_HARNESS_NEW_PATHS ──
# 실측: 상한 3 에 `invoke_with_tools` 10회가 전부 돌았다. 도구 경로는 예산을
# 아예 지나지 않았다. 그렇다고 바로 막으면 지금 도는 도구 루프가 그날부터 잘린다.
# 그래서 기본은 observe — **따로** 세고, 막았을 자리에서 이벤트만 낸다.
# 메시지 경로의 카운터를 건드리지 않으므로 기존 차단 시점은 한 호출도 안 움직인다.
#
# 이 상태가 dict(가변)인 이유: mixins/tool_use.py·react.py 는
# `asyncio.wait_for(llm.invoke_with_tools(...))` 로 부른다. 자식 태스크는 ContextVar
# **사본**을 받으므로 위의 정수 카운터는 거기서 올려도 부모에게 안 보인다(매번 1).
# 같은 dict 객체를 가리키게 하면 태스크를 넘어 누적된다.
_exec_state: ContextVar[_Optional[dict]] = ContextVar("_hb_exec_state", default=None)

_NEW_PATH_MODES = ("observe", "enforce", "off")


def new_paths_mode() -> str:
    """신규 경로 모드. 모르는 값은 observe — 오타가 차단을 켜면 안 된다."""
    import os
    m = os.getenv("LOGOSAI_HARNESS_NEW_PATHS", "observe").strip().lower()
    return m if m in _NEW_PATH_MODES else "observe"


# ── 자식 태스크 커버 — LOGOSAI_HARNESS_CHILD_TASKS ──
# 실측: 상한 3 에 `asyncio.wait_for(one(), 5)` 10회 · `gather` 10개가 **기존 경로**
# 에서 전부 돌았다. 호출·토큰 계수가 ContextVar 정수라, 자식 태스크는 사본을 올리고
# 부모는 영영 모른다. mixins/react.py 가 정확히 이 모양으로 LLM 을 부른다.
# 기본은 observe — 공유 dict 에 쌓고, 막았을 자리에서 이벤트만 낸다. 지금 도는
# 병렬 호출이 이 변경 때문에 그날부터 잘리면 안 된다.
def child_tasks_mode() -> str:
    """자식 태스크 모드. 모르는 값은 observe — 오타가 차단을 켜면 안 된다."""
    import os
    m = os.getenv("LOGOSAI_HARNESS_CHILD_TASKS", "observe").strip().lower()
    return m if m in _NEW_PATH_MODES else "observe"


def _current_task():
    try:
        return asyncio.current_task()
    except RuntimeError:  # 실행 중인 루프가 없다(동기 호출) — 소유 태스크로 취급
        return None


def _in_child_task(st: _Optional[dict]) -> bool:
    """예산을 연 태스크가 아닌 곳에서 부르고 있나. 모르면 False(= 예전 동작)."""
    owner = st.get("owner") if st else None
    if owner is None:
        return False
    cur = _current_task()
    return cur is not None and cur is not owner


def claim_execution_owner() -> None:
    """지금 태스크를 예산의 소유 태스크로 삼는다.

    observe_process 는 예산을 연 뒤 `wait_for(process(...))` 로 본문을 돌린다.
    3.11 의 wait_for 는 태스크를 새로 만들므로, 넘겨받지 않으면 process 본문의
    평범한 호출이 전부 '자식 태스크 호출'로 분류된다.
    """
    st = _exec_state.get()
    if st is not None:
        st["owner"] = _current_task()


def _shared_calls(st: dict) -> int:
    """소유 태스크 밖에서 쌓인 호출(자식 메시지 + enforce 도구 경로의 자식분)."""
    return st.get("child_calls", 0) + st.get("_enf_child_calls", 0)


def _shared_tokens(st: dict) -> int:
    return st.get("child_tokens", 0) + st.get("_enf_child_tokens", 0)


def _new_state(agent_id: str = "", observe_only: bool = False,
               calls_seed: int = 0, tokens_seed: int = 0) -> dict:
    return {
        "agent_id": str(agent_id or ""),
        # 스트림이 observe 모드로 연 예산 — 메시지 경로도 세기만 하고 막지 않는다.
        "observe_only": bool(observe_only),
        "tool_calls": 0, "tool_tokens": 0,      # observe: 메시지 경로와 분리된 계수
        "_enf_calls": 0, "_enf_tokens": 0,      # enforce: 태스크를 넘는 거울 계수
        # 자식 태스크: 메시지 경로가 소유 태스크 밖에서 쓴 양(태스크를 넘어 누적).
        "child_calls": 0, "child_tokens": 0,
        "_enf_child_calls": 0, "_enf_child_tokens": 0,   # 도구 enforce 의 자식분
        # 소유 태스크 정수 계수의 거울 — 자식은 사본만 보므로 여기서 읽는다.
        "own_calls": calls_seed, "own_tokens": tokens_seed, "owner": None,
        "would_block": [],
    }


def begin_execution_budget(max_calls: _Optional[int],
                           max_tokens: _Optional[int],
                           agent_id: str = "",
                           observe_only: bool = False,
                           resume: _Optional[_Tuple] = None) -> _Tuple:
    """실행 예산 시작. 반환한 토큰을 reset_execution_budget 에 넘겨 복원한다.

    resume: execution_snapshot() 이 준 값. 스트림 래퍼가 항목 사이마다 예산을
    내렸다 다시 올릴 때 계수를 이어 붙인다(0 에서 다시 시작하지 않는다).
    """
    state, calls, tokens = (None, 0, 0)
    if resume:
        state, calls, tokens = resume
    if state is None:
        state = _new_state(agent_id, observe_only, calls, tokens)
    # 예산을 연 태스크를 기억한다(스트림은 항목마다 다시 열므로 매번 갱신).
    state["owner"] = _current_task()
    return (
        _exec_calls.set(calls),
        _exec_tokens.set(tokens),
        _exec_max_calls.set(max_calls),
        _exec_max_tokens.set(max_tokens),
        _exec_state.set(state),
    )


def reset_execution_budget(tokens: _Optional[_Tuple]) -> None:
    """begin_execution_budget 이 반환한 토큰으로 ContextVar 복원."""
    if not tokens:
        return
    c, t, mc, mt, *rest = tokens
    try:
        # 끝난 실행의 state 가 태스크를 붙들고 있지 않게. 뒤늦게 도는 고아 태스크는
        # 소유자 불명 → 예전 동작으로 떨어진다.
        st = _exec_state.get()
        if st is not None:
            st["owner"] = None
        _exec_calls.reset(c)
        _exec_tokens.reset(t)
        _exec_max_calls.reset(mc)
        _exec_max_tokens.reset(mt)
        if rest:
            _exec_state.reset(rest[0])
    except (ValueError, LookupError):
        # 다른 context 에서 reset 시도(비정상) — 방어적 무시.
        pass


def budget_active() -> bool:
    """지금 컨텍스트에 실행 예산이 열려 있나 (스트림 래퍼의 중첩 판정용)."""
    return (_exec_state.get() is not None
            or _exec_max_calls.get() is not None
            or _exec_max_tokens.get() is not None)


def execution_snapshot() -> _Tuple:
    """(state, calls, tokens) — begin_execution_budget(resume=...) 에 되넘긴다."""
    return (_exec_state.get(), _exec_calls.get(), _exec_tokens.get())


def execution_usage() -> dict:
    """현재 실행의 사용량 (테스트·span metadata 용, 읽기 전용).

    calls/tokens 는 차단에 쓰이는 계수, tool_calls/tool_tokens 는 observe 모드에서
    도구 경로가 따로 센 값이다(enforce 에서는 calls/tokens 에 합쳐지므로 0).
    """
    st = _exec_state.get() or {}
    return {
        "calls": _exec_calls.get(),
        "tokens": _exec_tokens.get(),
        "tool_calls": int(st.get("tool_calls", 0)),
        "tool_tokens": int(st.get("tool_tokens", 0)),
        # 소유 태스크 밖(wait_for · gather 자식)에서 메시지 경로가 쓴 양.
        "child_calls": int(st.get("child_calls", 0)),
        "child_tokens": int(st.get("child_tokens", 0)),
        "would_block": list(st.get("would_block", [])),
    }


def _would_block(st: dict, kind: str, path: str, detail: str,
                 mc: _Optional[int], mt: _Optional[int]) -> None:
    """'enforce 였다면 여기서 막혔다' — 실행당 종류별 1회만 발행한다.

    상한을 넘긴 뒤의 호출마다 발행하면 폭주 에이전트 하나가 이벤트를 쏟는다.
    observability 는 여기서 지연 import 한다(모듈 import 시점 순환 회피).
    발행 실패는 절대 전파하지 않는다 — 관측이 실행을 죽이면 observe 가 아니다.
    """
    seen = st.setdefault("would_block", [])
    if kind in seen:
        return
    seen.append(kind)
    try:
        from logosai import observability as _obs
        _obs.emit_harness_block(
            "would_block", st.get("agent_id") or "unknown", detail,
            {"path": path, "budget_kind": kind,
             "max_calls": mc, "max_tokens": mt, "mode": "observe"})
    except Exception:  # noqa: BLE001
        pass


def _observe_overrun(st: dict, path: str, mc: _Optional[int], mt: _Optional[int],
                     calls: int, tokens: int) -> None:
    """합산(메시지+도구)이 상한을 넘었으면 would_block. enforce 의 판정식과 같다."""
    if mt is not None and tokens >= mt:
        _would_block(st, "tokens", path, f"token budget exceeded: {tokens}/{mt}", mc, mt)
    if mc is not None and calls > mc:
        _would_block(st, "calls", path, f"LLM call budget exceeded: {calls}/{mc}", mc, mt)


def _precheck_tools(mc: _Optional[int], mt: _Optional[int]) -> None:
    mode = new_paths_mode()
    if mode == "off":
        return
    st = _exec_state.get()
    if mode == "enforce" and not (st and st.get("observe_only")):
        # 메시지 경로와 **같은** 계수. 거울 계수(_enf_*)는 wait_for 자식 태스크에서
        # 정수 ContextVar 가 누적되지 않는 것을 메운다. 둘 다 실제 총량의 하한이라
        # 큰 쪽으로 판정해도 거짓 차단은 없다.
        e_calls = st["_enf_calls"] if st else 0
        e_tokens = st["_enf_tokens"] if st else 0
        used = max(_exec_tokens.get(), e_tokens)
        if mt is not None and used >= mt:
            raise HarnessBudgetExceeded(f"token budget exceeded: {used}/{mt}")
        if mc is not None:
            n = _exec_calls.get() + 1
            _exec_calls.set(n)
            if st is not None:
                st["_enf_calls"] = e_calls + 1
                # 자식 태스크 합산용 — 판정(아래)은 건드리지 않는다.
                if _in_child_task(st):
                    st["_enf_child_calls"] += 1
                else:
                    st["own_calls"] = n
            n = max(n, e_calls + 1)
            if n > mc:
                raise HarnessBudgetExceeded(f"LLM call budget exceeded: {n}/{mc}")
        return
    if st is None:
        return
    st["tool_calls"] += 1
    _observe_overrun(st, "tools", mc, mt,
                     _exec_calls.get() + st["tool_calls"],
                     _exec_tokens.get() + st["tool_tokens"])


def precheck_llm_call(path: str = "messages") -> None:
    """각 LLM 호출 '전' 호출. 예산 미활성이면 no-op.

    누적 토큰이 상한 이상이면 즉시 차단. 아니면 호출 카운트 +1 후 상한 초과 시 차단.
    path="tools" 는 LOGOSAI_HARNESS_NEW_PATHS 를 따른다(기본 observe = 세기만).
    """
    mc = _exec_max_calls.get()
    mt = _exec_max_tokens.get()
    if mc is None and mt is None:
        return  # 예산 미활성
    if path != "messages":
        _precheck_tools(mc, mt)
        return
    st = _exec_state.get()
    # 자식 태스크 판정. off 면 child=False 로 두어 아래가 한 글자도 안 달라진다.
    in_child = _in_child_task(st)
    cmode = child_tasks_mode() if st is not None else "off"
    child = in_child and cmode != "off"
    if st is not None and st.get("observe_only"):
        # 스트림(observe)이 연 예산 — 어제까지 예산이 없던 자리다. 세기만 한다.
        n = _exec_calls.get() + 1
        _exec_calls.set(n)
        if child:
            st["child_calls"] += 1
            _observe_overrun(st, "child_task", mc, mt,
                             st["own_calls"] + _shared_calls(st) + st["tool_calls"],
                             st["own_tokens"] + _shared_tokens(st) + st["tool_tokens"])
            return
        if not in_child:
            st["own_calls"] = n
        _observe_overrun(st, "stream", mc, mt,
                         n + st["tool_calls"] + _shared_calls(st),
                         _exec_tokens.get() + st["tool_tokens"] + _shared_tokens(st))
        return
    if child and cmode == "enforce":
        # 소유 태스크와 **같은** 상한. 지역 정수(사본)는 이 태스크 것만 알므로
        # 공유 계수로 판정한다 — 공유 합은 사본 값 이상이라 예전보다 늦게 막히지 않는다.
        used = st["own_tokens"] + _shared_tokens(st)
        if mt is not None and used >= mt:
            raise HarnessBudgetExceeded(f"token budget exceeded: {used}/{mt}")
        st["child_calls"] += 1
        _exec_calls.set(_exec_calls.get() + 1)
        n = st["own_calls"] + _shared_calls(st)
        if mc is not None and n > mc:
            raise HarnessBudgetExceeded(f"LLM call budget exceeded: {n}/{mc}")
        _observe_overrun(st, "child_task", mc, mt, n + st["tool_calls"],
                         used + st["tool_tokens"])
        return
    # 소유 태스크의 enforce 에서만 자식분을 얹는다. 그 밖(observe·off·자식 없음)은
    # xc=xt=0 이라 차단 시점도 문구도 예전과 같다.
    xc = xt = 0
    if st is not None and not in_child and cmode == "enforce":
        xc, xt = _shared_calls(st), _shared_tokens(st)
    if mt is not None and _exec_tokens.get() + xt >= mt:
        raise HarnessBudgetExceeded(
            f"token budget exceeded: {_exec_tokens.get() + xt}/{mt}")
    if mc is not None:
        n = _exec_calls.get() + 1
        _exec_calls.set(n)
        if st is not None and not in_child:
            st["own_calls"] = n
        if n + xc > mc:
            raise HarnessBudgetExceeded(
                f"LLM call budget exceeded: {n + xc}/{mc}")
    if st is None:
        return
    if child:
        # observe: 위의 예전 판정(사본 기준)을 통과한 호출만 공유 계수에 쌓는다.
        # 이 누적 때문에 예외가 나는 일은 없다 — 넘으면 이벤트 1회뿐.
        st["child_calls"] += 1
        _observe_overrun(st, "child_task", mc, mt,
                         st["own_calls"] + _shared_calls(st) + st["tool_calls"],
                         st["own_tokens"] + _shared_tokens(st) + st["tool_tokens"])
        return
    # 여기까지 왔으면 메시지 경로는 통과했다(위 동작은 그대로). 도구 경로나 자식
    # 태스크가 따로 센 것이 있을 때만, 합치면 넘는지 본다 — 도구 2 + 메시지 2(상한 3)는
    # 도구 경로 precheck 만 봐서는 영영 안 보인다. 둘 다 안 쓴 실행은 이 줄을 지나지 않는다.
    shared = (st["child_calls"] or st["child_tokens"]) if cmode != "off" else 0
    if st["tool_calls"] or st["tool_tokens"] or shared:
        _observe_overrun(st, "child_task" if shared else "tools", mc, mt,
                         _exec_calls.get() + st["tool_calls"] + _shared_calls(st),
                         _exec_tokens.get() + st["tool_tokens"] + _shared_tokens(st))


def record_llm_tokens(input_tokens: int, output_tokens: int,
                      path: str = "messages") -> None:
    """LLM 호출 '후' 호출. 토큰 예산 미활성이면 no-op."""
    if path != "messages":
        mode = new_paths_mode()
        if mode == "off":
            return
        st = _exec_state.get()
        if st is None:
            return
        try:
            used = int(input_tokens or 0) + int(output_tokens or 0)
        except (TypeError, ValueError):
            used = 0
        if mode == "enforce" and not st.get("observe_only"):
            st["_enf_tokens"] += used
            if _exec_max_tokens.get() is not None:
                _exec_tokens.set(_exec_tokens.get() + used)
            if _in_child_task(st):
                st["_enf_child_tokens"] += used
            elif _exec_max_tokens.get() is not None:
                st["own_tokens"] = _exec_tokens.get()
        else:
            st["tool_tokens"] += used
        return
    st = _exec_state.get()
    in_child = _in_child_task(st)
    try:
        used = int(input_tokens or 0) + int(output_tokens or 0)
    except (TypeError, ValueError):
        used = 0
    if in_child and child_tasks_mode() != "off":
        # 자식 태스크가 쓴 토큰 — 사본에만 더하면 부모는 0 으로 본다.
        st["child_tokens"] += used
    if _exec_max_tokens.get() is None:
        return
    _exec_tokens.set(_exec_tokens.get() + used)
    if st is not None and not in_child:
        st["own_tokens"] = _exec_tokens.get()


def refund_llm_call(path: str = "tools") -> None:
    """방금 센 도구 경로 호출 1건을 되돌린다.

    프롬프트 폴백(`_call_with_tools_fallback`)은 내부에서 `invoke_messages` 를
    부르고, 그쪽이 이미 센다. 되돌리지 않으면 호출 하나가 둘로 세져 enforce 에서
    상한의 절반에 잘린다(거짓 차단).
    """
    if _exec_max_calls.get() is None and _exec_max_tokens.get() is None:
        return
    mode = new_paths_mode()
    if mode == "off":
        return
    st = _exec_state.get()
    if mode == "enforce" and not (st and st.get("observe_only")):
        if _exec_max_calls.get() is not None:
            _exec_calls.set(max(0, _exec_calls.get() - 1))
            if st is not None:
                st["_enf_calls"] = max(0, st["_enf_calls"] - 1)
                if _in_child_task(st):
                    st["_enf_child_calls"] = max(0, st["_enf_child_calls"] - 1)
                else:
                    st["own_calls"] = _exec_calls.get()
    elif st is not None:
        st["tool_calls"] = max(0, st["tool_calls"] - 1)
