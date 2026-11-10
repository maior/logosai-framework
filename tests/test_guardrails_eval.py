"""Guardrails 평가 테스트 — 성능, 사용자 경험, 설정값 검증.

테스트 통과 여부가 아닌, 실제 운영 환경에서의 적합성 평가.

두 가지로 돈다 (2026-11-10):
  - pytest: 평가 1~6 이 각각 `async def test_*`. 예전엔 `async def main()`
    하나뿐이라 pytest 가 **0건을 수집**했고, 평가는 ✅/⚠️ 를 **출력만** 했다 —
    단언이 하나도 없어 어떤 결과가 나와도 종료 코드 0 이었다. 각 평가가
    ✅ 로 찍던 조건을 그대로 `assert` 로 옮겼다.
  - 직접 실행: python tests/test_guardrails_eval.py  → 종합 평가로 끝난다.

⚠️ 평가 대상은 `tests/test_guardrails.py` 에 정의된 클래스다 (라이브러리의
   동명 클래스가 아니다). 평가 3 은 고정 표의 산술이라 코드를 재지 않는다.
"""

import asyncio
import inspect
import time
import sys
import os

# 스크립트로 돌면 이 디렉터리가 sys.path[0] 이고, pytest(rootdir 에 __init__ 없음,
# prepend 모드)도 이 디렉터리를 넣어 준다 — sys.path 를 직접 건드리지 않는다.
from test_guardrails import TokenBucketRateLimiter, RequestCallCounter, LLMCallLimitExceeded

# 종합 평가에 찍을 측정값 — 각 평가가 채운다.
_REPORT = {}

_SCENARIOS = [
    ("단순 쿼리 (날씨)", 2, 10),
    ("중간 쿼리 (검색+요약)", 4, 10),
    ("복잡 쿼리 (비교 보고서)", 8, 10),
    ("매우 복잡 (plan 3 sub-goals × react)", 12, 10),
    ("최악 (retry 포함)", 17, 10),
]


def _setup(mp):
    """`mp` = pytest monkeypatch 또는 `_ScriptPatch`. 이 파일은 env 를 쓰지 않지만
    같은 자리를 둔다 — 나중에 env 가 필요해져도 import 시점에 세우지 않게."""
    mp.delenv("LOGOSAI_PULSE_ALLOW_IN_TESTS", raising=False)


async def test_eval1_normal_use_latency_under_1ms():
    """평가 1: 정상 사용 시 지연 (30/min 설정)"""
    rl = TokenBucketRateLimiter(calls_per_minute=30)

    latencies = []
    for i in range(10):
        t = time.time()
        await rl.acquire()
        lat = (time.time() - t) * 1000
        latencies.append(lat)

    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    _REPORT["avg_lat"] = avg_lat
    print(f"  10회 호출 평균 지연: {avg_lat:.1f}ms, 최대: {max_lat:.1f}ms")
    print(f"  평가: {'✅ OK (1ms 미만)' if avg_lat < 1 else '⚠️ 지연 발생'}")
    assert avg_lat < 1, f"토큰이 남아 있는데 평균 {avg_lat:.1f}ms 지연"


async def test_eval2_recovery_after_burst_under_3s():
    """평가 2: 30회 연속 호출 후 회복"""
    rl2 = TokenBucketRateLimiter(calls_per_minute=30)

    # 30회 즉시 소진
    for i in range(30):
        await rl2.acquire()

    # 31번째 호출 — 얼마나 기다리는가?
    t = time.time()
    await rl2.acquire()
    recovery = time.time() - t
    _REPORT["recovery"] = recovery

    print(f"  30회 소진 후 31번째 호출 대기: {recovery:.1f}s")
    print(f"  평가: {'✅ OK' if recovery < 3 else '⚠️ 대기 시간 김'} — 사용자가 {recovery:.0f}초 기다려야 함")
    assert recovery > 1.0, f"대조군: 버킷이 비었는데 {recovery:.2f}s 만에 통과 — 제한이 안 걸렸다"
    assert recovery < 3, f"회복 대기 {recovery:.1f}s"


async def test_eval3_per_request_limit_of_10_is_short_for_complex_queries():
    """평가 3: 요청당 호출 제한 적정성"""
    fits_all = []
    for name, calls, limit in _SCENARIOS:
        fits = calls <= limit
        fits_all.append(fits)
        print(f"  {name}: {calls}회 / {limit} {'✅' if fits else '❌ 초과!'}")

    print(f"\n  결론: max 10 → 복잡 쿼리에서 부족할 수 있음")
    print(f"  제안: max 15로 상향 (또는 단순=10, 복잡=20 동적 설정)")
    # 출력된 결론이 표와 일치하는지만 고정한다 (코드를 재는 검사가 아니다).
    assert fits_all == [True, True, True, False, False]


async def test_eval4_block_message_has_count_and_elapsed():
    """평가 4: 차단 시 에러 메시지"""
    counter = RequestCallCounter(max_calls=3)
    msg = None
    try:
        for i in range(5):
            counter.increment()
    except LLMCallLimitExceeded as e:
        msg = str(e)
    assert msg is not None, "상한 3 에 5회 호출했는데 차단되지 않았다"
    has_count = "/" in msg
    has_time = "elapsed" in msg
    print(f"  메시지: {msg}")
    print(f"  호출 수 포함: {has_count}")
    print(f"  경과 시간 포함: {has_time}")
    print(f"  평가: {'✅ 정보 충분' if has_count and has_time else '⚠️ 정보 부족'}")
    assert has_count and has_time, f"차단 메시지에 정보 부족: {msg}"


async def test_eval5_plan_execution_ends_gracefully_at_limit():
    """평가 5: 중간 차단 시 처리"""
    results = []
    counter2 = RequestCallCounter(max_calls=3)

    async def simulate_plan_execution():
        sub_goals = ["검색 A", "검색 B", "비교 분석"]
        for goal in sub_goals:
            try:
                counter2.increment()
                results.append(f"완료: {goal}")
            except LLMCallLimitExceeded:
                results.append(f"차단: {goal}")
                # 부분 결과라도 반환해야 함
                break

    await simulate_plan_execution()
    print(f"  결과: {results}")
    completed = sum(1 for r in results if "완료" in r)
    blocked = sum(1 for r in results if "차단" in r)
    print(f"  완료: {completed}, 차단: {blocked}")
    print(f"  평가: {'✅ graceful 종료' if blocked <= 1 else '⚠️'} — 부분 결과 반환 필요")
    assert blocked <= 1
    assert completed == 3, f"상한 3 안의 하위 목표 3개 중 {completed}개만 완료"


async def test_eval6_concurrent_requests_fair():
    """평가 6: 동시 요청 공정성"""
    rl3 = TokenBucketRateLimiter(calls_per_minute=10)

    async def user_request(user_id, num_calls):
        times = []
        for i in range(num_calls):
            t = time.time()
            await rl3.acquire()
            times.append(time.time() - t)
        return user_id, sum(times)

    # 3명 동시 요청
    tasks = [
        user_request("user_A", 3),
        user_request("user_B", 3),
        user_request("user_C", 3),
    ]
    results = await asyncio.gather(*tasks)

    for uid, total_wait in results:
        print(f"  {uid}: 총 대기 {total_wait:.1f}s")

    waits = [w for _, w in results]
    fairness = max(waits) / (min(waits) + 0.001)
    _REPORT["fairness"] = fairness
    print(f"  공정성 비율: {fairness:.1f}x (1.0=완벽, >3.0=불공정)")
    print(f"  평가: {'✅ 공정' if fairness < 3 else '⚠️ 불공정'}")
    assert len(results) == 3
    assert fairness < 3, f"공정성 {fairness:.1f}x"


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _eval_env(monkeypatch):
        _setup(monkeypatch)


# ══ 스크립트 모드 러너 (pytest 없이도 돈다) ════════════════════════════════

class _ScriptPatch:
    """pytest monkeypatch 의 최소 대역 — 세운 것을 `undo()` 로 전부 되돌린다."""

    def __init__(self):
        self._undo = []

    def setenv(self, key, value):
        self._remember_env(key)
        os.environ[key] = str(value)

    def delenv(self, key, raising=True):
        if key not in os.environ:
            if raising:
                raise KeyError(key)
            return
        self._remember_env(key)
        del os.environ[key]

    def setattr(self, obj, name, value):
        old = getattr(obj, name)
        self._undo.append(lambda: setattr(obj, name, old))
        setattr(obj, name, value)

    def _remember_env(self, key):
        old = os.environ.get(key)

        def restore():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

        self._undo.append(restore)

    def undo(self):
        while self._undo:
            self._undo.pop()()


def _script_tests():
    """이 모듈의 `test_*` 를 정의 순서대로 — 목록을 따로 두지 않아 빠뜨릴 수 없다."""
    return [fn for name, fn in list(globals().items())
            if name.startswith("test_") and inspect.isfunction(fn)]


def _mark(ok):
    return "✅" if ok else "⚠️"


async def main():
    print("=" * 70)
    print("Guardrails 평가 테스트")
    print("=" * 70)

    _REPORT.clear()
    failed = []
    for fn in _script_tests():
        label = (fn.__doc__ or fn.__name__).strip().splitlines()[0]
        print(f"\n=== {label} ===")
        mp = _ScriptPatch()
        try:
            _setup(mp)
            await fn()
        except AssertionError as e:
            print(f"  ❌ FAIL — {e}")
            failed.append(label)
        finally:
            mp.undo()

    def bad(n):
        return any(label.startswith(f"평가 {n}:") for label in failed)

    avg_lat = _REPORT.get("avg_lat", float("nan"))
    recovery = _REPORT.get("recovery", float("nan"))
    fairness = _REPORT.get("fairness", float("nan"))

    # ── 종합 평가 ──
    print(f"\n{'=' * 70}")
    print("종합 평가")
    print(f"{'=' * 70}")
    print(f"  1. 정상 사용 지연: {_mark(not bad(1))} ({avg_lat:.1f}ms)")
    print(f"  2. 버스트 회복: {_mark(not bad(2))} ({recovery:.1f}s)")
    print(f"  3. 요청당 제한: ⚠️ max 10 → 15 상향 권장")
    print(f"  4. 에러 메시지: {_mark(not bad(4))} {'충분한 정보' if not bad(4) else '정보 부족'}")
    print(f"  5. 부분 결과: {_mark(not bad(5))} graceful 종료")
    print(f"  6. 동시 요청: {_mark(not bad(6))} (공정성 {fairness:.1f}x)")

    if failed:
        print(f"\n  ❌ {len(failed)} FAILED: {failed}")
        return 1
    print(f"\n  → 적용 권장 (max_calls 15로 조정 후)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
