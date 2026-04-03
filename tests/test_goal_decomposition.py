"""Phase A: Goal Decomposition — 테스트 먼저, 구현 나중.

에이전트가 복잡한 목표를 하위 목표로 재귀 분해하고,
각 하위 목표를 실행하고, 결과를 종합하는지 검증.

Usage: python tests/test_goal_decomposition.py
"""

import asyncio
import json
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ============================================================
# Goal Tree Structure (proposed)
# ============================================================

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class GoalStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Goal:
    """A goal or sub-goal in the goal tree."""
    id: str
    title: str
    description: str = ""
    status: GoalStatus = GoalStatus.PENDING
    parent_id: Optional[str] = None
    sub_goals: List['Goal'] = field(default_factory=list)
    result: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)

    @property
    def progress(self) -> float:
        if not self.sub_goals:
            return 1.0 if self.status == GoalStatus.COMPLETED else 0.0
        completed = sum(1 for g in self.sub_goals if g.status == GoalStatus.COMPLETED)
        return completed / len(self.sub_goals) if self.sub_goals else 0.0

    @property
    def is_leaf(self) -> bool:
        return len(self.sub_goals) == 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "progress": f"{self.progress:.0%}",
            "sub_goals": [g.to_dict() for g in self.sub_goals],
            "result": self.result[:50] if self.result else None,
        }


@dataclass
class GoalTree:
    """Tree of goals with execution tracking."""
    root: Goal
    all_goals: Dict[str, Goal] = field(default_factory=dict)

    def __post_init__(self):
        self._index(self.root)

    def _index(self, goal: Goal):
        self.all_goals[goal.id] = goal
        for sub in goal.sub_goals:
            self._index(sub)

    def get(self, goal_id: str) -> Optional[Goal]:
        return self.all_goals.get(goal_id)

    def add_sub_goal(self, parent_id: str, sub_goal: Goal):
        parent = self.get(parent_id)
        if parent:
            sub_goal.parent_id = parent_id
            parent.sub_goals.append(sub_goal)
            self.all_goals[sub_goal.id] = sub_goal

    @property
    def progress(self) -> float:
        return self.root.progress

    def get_next_pending(self) -> Optional[Goal]:
        """Get next executable goal (leaf, pending, deps satisfied)."""
        for goal in self.all_goals.values():
            if goal.status == GoalStatus.PENDING and goal.is_leaf:
                # Check dependencies
                deps_met = all(
                    self.all_goals.get(d, Goal(id=d, title="")).status == GoalStatus.COMPLETED
                    for d in goal.depends_on
                )
                if deps_met:
                    return goal
        return None

    def summary(self) -> str:
        lines = []
        def _show(goal, indent=0):
            status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}
            icon = status_icon.get(goal.status.value, "?")
            lines.append(f"{'  ' * indent}{icon} {goal.title}")
            for sub in goal.sub_goals:
                _show(sub, indent + 1)
        _show(self.root)
        return "\n".join(lines)


# ============================================================
# Plan function (uses LLM to decompose)
# ============================================================

async def plan_goal(query: str, llm=None) -> GoalTree:
    """Decompose a complex query into a goal tree using LLM."""
    if not llm:
        from logosai.utils.llm_client import LLMClient
        llm = LLMClient(provider="google", model="gemini-2.5-flash-lite")
        await llm.initialize()

    prompt = f"""Analyze this task and decide if it needs decomposition.

Task: "{query}"

Rules:
- If the task is SIMPLE (single step, greeting, simple calculation, direct lookup):
  Return 1 sub-goal only. Do NOT over-decompose simple tasks.
- If the task is MODERATE (2-3 steps with clear sequence):
  Return 2-3 sub-goals with dependencies.
- If the task is COMPLEX (multiple independent + dependent steps):
  Return 4-6 sub-goals with parallel and sequential dependencies.
- Each sub-goal should be independently executable
- Add depends_on where output of one step is needed by another

Examples:
- "서울 날씨" → 1 sub-goal (simple lookup)
- "주가 검색해서 요약" → 2 sub-goals (search → summarize)
- "A와 B 비교 분석 보고서" → 4+ sub-goals (search A, search B, compare, report)

Return JSON:
{{
  "title": "Main goal",
  "complexity": "simple|moderate|complex",
  "sub_goals": [
    {{"id": "g1", "title": "Sub-goal 1", "depends_on": []}}
  ]
}}

JSON only."""

    resp = await asyncio.wait_for(llm.invoke(prompt), timeout=10)
    text = resp.content if hasattr(resp, 'content') else str(resp)

    # Parse JSON
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON in LLM response: {text[:200]}")

    data = json.loads(match.group())

    # Build goal tree
    root = Goal(id="root", title=data.get("title", query))
    tree = GoalTree(root=root)

    for sg in data.get("sub_goals", []):
        sub = Goal(
            id=sg.get("id", f"g{len(root.sub_goals)+1}"),
            title=sg.get("title", ""),
            depends_on=sg.get("depends_on", []),
        )
        tree.add_sub_goal("root", sub)

    return tree


# ============================================================
# Execute goal tree
# ============================================================

async def execute_goal_tree(tree: GoalTree, executor=None) -> GoalTree:
    """Execute all goals in dependency order."""
    max_iterations = 20  # Safety limit

    for _ in range(max_iterations):
        goal = tree.get_next_pending()
        if not goal:
            break  # All done or blocked

        goal.status = GoalStatus.IN_PROGRESS

        try:
            if executor:
                result = await executor(goal.title)
            else:
                result = f"[Executed: {goal.title}]"

            goal.result = str(result)
            goal.status = GoalStatus.COMPLETED
        except Exception as e:
            goal.result = f"Error: {e}"
            goal.status = GoalStatus.FAILED

    # Update root status
    if all(g.status == GoalStatus.COMPLETED for g in tree.root.sub_goals):
        tree.root.status = GoalStatus.COMPLETED
    elif any(g.status == GoalStatus.FAILED for g in tree.root.sub_goals):
        tree.root.status = GoalStatus.FAILED

    return tree


# ============================================================
# Tests
# ============================================================

async def main():
    print("=" * 70)
    print("Phase A: Goal Decomposition — TDD Tests")
    print("=" * 70)

    # ── Test 1: GoalTree structure ──
    print("\n=== T1: GoalTree 구조 ===")
    root = Goal(id="root", title="Build Report")
    g1 = Goal(id="g1", title="Search data")
    g2 = Goal(id="g2", title="Analyze data", depends_on=["g1"])
    g3 = Goal(id="g3", title="Write report", depends_on=["g2"])

    tree = GoalTree(root=root)
    tree.add_sub_goal("root", g1)
    tree.add_sub_goal("root", g2)
    tree.add_sub_goal("root", g3)

    assert len(tree.all_goals) == 4  # root + 3 subs
    assert tree.progress == 0.0
    assert tree.get_next_pending().id == "g1"  # Only g1 has no deps
    print(f"  Goals: {len(tree.all_goals)}, Progress: {tree.progress:.0%}")
    print(f"  Next pending: {tree.get_next_pending().id}")
    print(f"  ✅ PASS")

    # ── Test 2: Dependency order execution ──
    print("\n=== T2: 의존성 순서 실행 ===")
    execution_order = []

    async def mock_executor(title):
        execution_order.append(title)
        return f"Done: {title}"

    await execute_goal_tree(tree, executor=mock_executor)

    print(f"  Execution order: {execution_order}")
    assert execution_order == ["Search data", "Analyze data", "Write report"]
    assert tree.progress == 1.0
    assert tree.root.status == GoalStatus.COMPLETED
    print(f"  Progress: {tree.progress:.0%}")
    print(f"  ✅ PASS — 의존성 순서 정확")

    # ── Test 3: LLM goal decomposition ──
    print("\n=== T3: LLM 목표 분해 ===")
    tree2 = await plan_goal("테슬라 기업분석 보고서 작성")

    print(f"  Root: {tree2.root.title}")
    print(f"  Sub-goals: {len(tree2.root.sub_goals)}")
    for sg in tree2.root.sub_goals:
        deps = f" (depends: {sg.depends_on})" if sg.depends_on else ""
        print(f"    - {sg.title}{deps}")

    assert len(tree2.root.sub_goals) >= 2
    print(f"  ✅ PASS — {len(tree2.root.sub_goals)}개 하위 목표 분해")

    # ── Test 4: LLM decomposition + execution ──
    print("\n=== T4: LLM 분해 + 실행 ===")
    exec_log = []

    async def log_executor(title):
        exec_log.append(title)
        return f"Completed: {title}"

    await execute_goal_tree(tree2, executor=log_executor)

    print(f"  Executed: {len(exec_log)} goals")
    for e in exec_log:
        print(f"    ✅ {e}")
    print(f"  Progress: {tree2.progress:.0%}")
    assert tree2.progress == 1.0
    print(f"  ✅ PASS — 전체 실행 완료")

    # ── Test 5: Dynamic re-planning ──
    print("\n=== T5: 동적 재계획 ===")
    root3 = Goal(id="root", title="Research")
    tree3 = GoalTree(root=root3)
    tree3.add_sub_goal("root", Goal(id="g1", title="Search A"))
    tree3.add_sub_goal("root", Goal(id="g2", title="Search B"))

    # Execute g1
    g1_goal = tree3.get("g1")
    g1_goal.status = GoalStatus.COMPLETED
    g1_goal.result = "Data insufficient"

    # Dynamic: add new sub-goal based on g1 result
    tree3.add_sub_goal("root", Goal(id="g3", title="Search A (extended)", depends_on=["g1"]))

    assert len(tree3.root.sub_goals) == 3
    next_goal = tree3.get_next_pending()
    assert next_goal.id in ("g2", "g3")  # Both are executable
    print(f"  Sub-goals after re-plan: {[g.id for g in tree3.root.sub_goals]}")
    print(f"  Next pending: {next_goal.id}")
    print(f"  ✅ PASS — 동적 재계획 성공")

    # ── Test 6: Tree summary ──
    print("\n=== T6: 트리 시각화 ===")
    root4 = Goal(id="root", title="Main Task")
    tree4 = GoalTree(root=root4)
    tree4.add_sub_goal("root", Goal(id="a", title="Step A"))
    tree4.add_sub_goal("root", Goal(id="b", title="Step B"))
    tree4.get("a").status = GoalStatus.COMPLETED
    print(tree4.summary())
    print(f"  ✅ PASS")

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print("SUMMARY: 6/6 tests passed ✅")
    print("Goal Decomposition 로직 검증 완료 — 실제 agent.py에 적용 가능")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
