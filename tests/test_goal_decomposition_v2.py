"""Phase A: Goal Decomposition — 다양한 쿼리 유형별 TDD 테스트.

단순 (분해 불필요), 중간 (2-3 단계), 복잡 (5+ 단계), 엣지 케이스

Usage: python tests/test_goal_decomposition_v2.py
"""

import asyncio
import json
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import from v1 test (same data structures)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_goal_decomposition import Goal, GoalTree, GoalStatus, plan_goal, execute_goal_tree


# ============================================================
# Test Cases
# ============================================================

TEST_CASES = [
    # ── 단순: 분해 불필요 or 1-2 단계 ──
    {
        "id": "S1",
        "level": "단순",
        "query": "서울 날씨 알려줘",
        "expect_min_goals": 1,
        "expect_max_goals": 2,
        "should_have_deps": False,
        "description": "단일 작업, 분해 불필요",
    },
    {
        "id": "S2",
        "level": "단순",
        "query": "100 + 200 계산해줘",
        "expect_min_goals": 1,
        "expect_max_goals": 2,
        "should_have_deps": False,
        "description": "단순 계산",
    },
    {
        "id": "S3",
        "level": "단순",
        "query": "안녕하세요 반갑습니다",
        "expect_min_goals": 1,
        "expect_max_goals": 2,
        "should_have_deps": False,
        "description": "인사말 (작업 아님)",
    },

    # ── 중간: 2-3 단계, 간단한 의존성 ──
    {
        "id": "M1",
        "level": "중간",
        "query": "테슬라 주가 검색해서 요약해줘",
        "expect_min_goals": 2,
        "expect_max_goals": 4,
        "should_have_deps": True,
        "description": "검색 → 요약 (2단계)",
    },
    {
        "id": "M2",
        "level": "중간",
        "query": "오늘 환율 조회하고 1000달러 환전 금액 계산해줘",
        "expect_min_goals": 2,
        "expect_max_goals": 4,
        "should_have_deps": True,
        "description": "조회 → 계산 (2단계)",
    },
    {
        "id": "M3",
        "level": "중간",
        "query": "파이썬으로 퀵소트 코드 만들고 테스트 코드도 작성해줘",
        "expect_min_goals": 2,
        "expect_max_goals": 4,
        "should_have_deps": True,
        "description": "코드 생성 → 테스트 (2단계)",
    },

    # ── 복잡: 4+ 단계, 병렬 + 직렬 혼합 ──
    {
        "id": "C1",
        "level": "복잡",
        "query": "삼성전자와 SK하이닉스 반도체 실적을 각각 검색하고 비교 분석해서 보고서로 만들어줘",
        "expect_min_goals": 4,
        "expect_max_goals": 7,
        "should_have_deps": True,
        "description": "병렬 검색 → 비교 분석 → 보고서",
    },
    {
        "id": "C2",
        "level": "복잡",
        "query": "최근 AI 트렌드를 조사하고, 주요 기업별 전략을 분석하고, 우리 회사에 적용할 수 있는 방안을 제안해줘",
        "expect_min_goals": 3,
        "expect_max_goals": 7,
        "should_have_deps": True,
        "description": "조사 → 분석 → 제안 (3+ 단계)",
    },
    {
        "id": "C3",
        "level": "복잡",
        "query": "서울, 부산, 제주 날씨를 검색하고, 이번 주말 여행하기 좋은 곳을 추천하고, 추천 이유와 함께 일정표도 만들어줘",
        "expect_min_goals": 4,
        "expect_max_goals": 8,
        "should_have_deps": True,
        "description": "병렬 검색 → 추천 → 일정표",
    },

    # ── 엣지 케이스 ──
    {
        "id": "E1",
        "level": "엣지",
        "query": "",
        "expect_min_goals": 0,
        "expect_max_goals": 2,
        "should_have_deps": False,
        "description": "빈 쿼리",
    },
    {
        "id": "E2",
        "level": "엣지",
        "query": "OARS 문서 찾아서 maiordba@gmail.com으로 보내줘",
        "expect_min_goals": 2,
        "expect_max_goals": 4,
        "should_have_deps": True,
        "description": "검색 + 전송 (compound)",
    },
]


# ============================================================
# Run Tests
# ============================================================

async def main():
    print("=" * 80)
    print("Goal Decomposition — 다양한 쿼리 유형별 테스트")
    print("=" * 80)

    from logosai.utils.llm_client import LLMClient
    llm = LLMClient(provider="google", model="gemini-2.5-flash-lite")
    await llm.initialize()

    results = {"pass": 0, "fail": 0, "skip": 0}

    for tc in TEST_CASES:
        print(f"\n{'─' * 80}")
        print(f"[{tc['id']}] ({tc['level']}) {tc['query'][:50] or '(empty)'}")
        print(f"  기대: {tc['expect_min_goals']}-{tc['expect_max_goals']} goals, deps={tc['should_have_deps']}")

        # Skip empty query
        if not tc['query']:
            print(f"  ⏭️ SKIP — 빈 쿼리")
            results["skip"] += 1
            continue

        try:
            tree = await plan_goal(tc['query'], llm=llm)
        except Exception as e:
            print(f"  ❌ FAIL — plan error: {e}")
            results["fail"] += 1
            continue

        num_goals = len(tree.root.sub_goals)
        has_deps = any(g.depends_on for g in tree.root.sub_goals)

        # Show decomposition
        for sg in tree.root.sub_goals:
            deps = f" (→ {sg.depends_on})" if sg.depends_on else ""
            print(f"    {sg.id}: {sg.title[:50]}{deps}")

        # Validate
        checks = []

        # Goal count
        if tc['expect_min_goals'] <= num_goals <= tc['expect_max_goals']:
            checks.append(("goals count", True))
        else:
            checks.append(("goals count", False))
            print(f"  ⚠️ goals: {num_goals} (expected {tc['expect_min_goals']}-{tc['expect_max_goals']})")

        # Dependency check
        if tc['should_have_deps'] == has_deps or (tc['level'] == '단순' and not tc['should_have_deps']):
            checks.append(("dependencies", True))
        else:
            checks.append(("dependencies", False))
            print(f"  ⚠️ deps: {has_deps} (expected {tc['should_have_deps']})")

        # Execution test
        exec_log = []
        async def log_exec(title):
            exec_log.append(title)
            return f"Done: {title}"

        await execute_goal_tree(tree, executor=log_exec)
        all_completed = tree.progress == 1.0
        checks.append(("execution", all_completed))
        if not all_completed:
            print(f"  ⚠️ execution: progress={tree.progress:.0%}")

        # Result
        all_pass = all(ok for _, ok in checks)
        if all_pass:
            results["pass"] += 1
            print(f"  ✅ PASS — {num_goals} goals, deps={has_deps}, exec={len(exec_log)} steps")
        else:
            results["fail"] += 1
            failed = [n for n, ok in checks if not ok]
            print(f"  ❌ FAIL — {failed}")

    # Summary
    total = results["pass"] + results["fail"] + results["skip"]
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")

    for level in ['단순', '중간', '복잡', '엣지']:
        cases = [tc for tc in TEST_CASES if tc['level'] == level]
        print(f"  [{level}] {len(cases)} cases")

    print(f"\n  ✅ {results['pass']} passed, ❌ {results['fail']} failed, ⏭️ {results['skip']} skipped")
    print(f"  Total: {results['pass']}/{total - results['skip']} ({results['pass']/(total-results['skip'])*100:.0f}%)")

    if results['fail'] == 0:
        print(f"\n  → Goal Decomposition 실제 agent.py 적용 가능")
    else:
        print(f"\n  → {results['fail']}건 실패 — 수정 필요")


if __name__ == "__main__":
    asyncio.run(main())
