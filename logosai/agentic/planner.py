"""Goal Decomposition Planner — recursive goal tree with execution.

Agents can plan complex tasks by decomposing them into sub-goals,
execute each in dependency order, and dynamically re-plan if needed.

Usage:
    from logosai.agentic.planner import GoalTree, Goal, plan_goal, execute_goal_tree

    tree = await plan_goal("Tesla analysis report", llm=my_llm)
    await execute_goal_tree(tree, executor=my_func)
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


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
            "result": self.result[:100] if self.result else None,
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
                deps_met = all(
                    self.all_goals.get(d, Goal(id=d, title="")).status == GoalStatus.COMPLETED
                    for d in goal.depends_on
                )
                if deps_met:
                    return goal
        return None

    def get_completed_results(self) -> Dict[str, str]:
        """Get all completed goal results."""
        return {
            gid: g.result
            for gid, g in self.all_goals.items()
            if g.status == GoalStatus.COMPLETED and g.result
        }

    def summary(self) -> str:
        lines = []
        def _show(goal, indent=0):
            icons = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}
            icon = icons.get(goal.status.value, "?")
            lines.append(f"{'  ' * indent}{icon} {goal.title}")
            for sub in goal.sub_goals:
                _show(sub, indent + 1)
        _show(self.root)
        return "\n".join(lines)


async def plan_goal(query: str, llm=None) -> GoalTree:
    """Decompose a query into a goal tree using LLM.

    LLM determines complexity (simple/moderate/complex) and creates
    appropriate number of sub-goals with dependencies.
    """
    if not llm:
        from ..utils.llm_client import LLMClient
        from ..config.llm_defaults import get_default_provider, get_default_model
        llm = LLMClient(provider=get_default_provider(), model=get_default_model())
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

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        # Fallback: single goal
        root = Goal(id="root", title=query)
        root.sub_goals.append(Goal(id="g1", title=query))
        return GoalTree(root=root)

    data = json.loads(match.group())

    root = Goal(id="root", title=data.get("title", query))
    tree = GoalTree(root=root)

    for sg in data.get("sub_goals", []):
        sub = Goal(
            id=sg.get("id", f"g{len(root.sub_goals)+1}"),
            title=sg.get("title", ""),
            depends_on=sg.get("depends_on", []),
        )
        tree.add_sub_goal("root", sub)

    if not root.sub_goals:
        root.sub_goals.append(Goal(id="g1", title=query, parent_id="root"))
        tree.all_goals["g1"] = root.sub_goals[0]

    logger.info(f"Plan: '{query[:40]}' → {len(root.sub_goals)} goals ({data.get('complexity', '?')})")
    return tree


async def execute_goal_tree_stream(
    tree: GoalTree,
    executor: Callable = None,
    max_iterations: int = 20,
):
    """Execute goals and yield progress events.

    Yields:
        {"event": "goal_started", "data": {"goal_id", "title", "progress"}}
        {"event": "goal_completed", "data": {"goal_id", "title", "result", "progress"}}
        {"event": "goal_failed", "data": {"goal_id", "title", "error", "progress"}}
    """
    for _ in range(max_iterations):
        goal = tree.get_next_pending()
        if not goal:
            break

        goal.status = GoalStatus.IN_PROGRESS
        yield {
            "event": "goal_started",
            "data": {"goal_id": goal.id, "title": goal.title, "progress": f"{tree.progress:.0%}"},
        }

        try:
            context = tree.get_completed_results()
            if executor:
                if asyncio.iscoroutinefunction(executor):
                    result = await asyncio.wait_for(executor(goal.title, context), timeout=60)
                else:
                    result = executor(goal.title, context)
            else:
                result = f"[Executed: {goal.title}]"

            goal.result = str(result)
            goal.status = GoalStatus.COMPLETED
            logger.debug(f"  Goal [{goal.id}] completed: {goal.title[:40]}")

            yield {
                "event": "goal_completed",
                "data": {
                    "goal_id": goal.id,
                    "title": goal.title,
                    "result": str(result)[:200],
                    "progress": f"{tree.progress:.0%}",
                },
            }

        except Exception as e:
            goal.result = f"Error: {e}"
            goal.status = GoalStatus.FAILED
            logger.warning(f"  Goal [{goal.id}] failed: {e}")

            yield {
                "event": "goal_failed",
                "data": {"goal_id": goal.id, "title": goal.title, "error": str(e)[:100], "progress": f"{tree.progress:.0%}"},
            }

    # Update root
    if tree.root.sub_goals:
        if all(g.status == GoalStatus.COMPLETED for g in tree.root.sub_goals):
            tree.root.status = GoalStatus.COMPLETED
        elif any(g.status == GoalStatus.FAILED for g in tree.root.sub_goals):
            tree.root.status = GoalStatus.FAILED


async def execute_goal_tree(
    tree: GoalTree,
    executor: Callable = None,
    max_iterations: int = 20,
) -> GoalTree:
    """Execute all goals in dependency order.

    Args:
        tree: GoalTree to execute
        executor: async function(title, context) → result string
        max_iterations: Safety limit
    """
    for _ in range(max_iterations):
        goal = tree.get_next_pending()
        if not goal:
            break

        goal.status = GoalStatus.IN_PROGRESS

        try:
            # Pass completed results as context
            context = tree.get_completed_results()
            if executor:
                if asyncio.iscoroutinefunction(executor):
                    result = await asyncio.wait_for(executor(goal.title, context), timeout=60)
                else:
                    result = executor(goal.title, context)
            else:
                result = f"[Executed: {goal.title}]"

            goal.result = str(result)
            goal.status = GoalStatus.COMPLETED
            logger.debug(f"  Goal [{goal.id}] completed: {goal.title[:40]}")

        except Exception as e:
            goal.result = f"Error: {e}"
            goal.status = GoalStatus.FAILED
            logger.warning(f"  Goal [{goal.id}] failed: {e}")

    # Update root status
    if tree.root.sub_goals:
        if all(g.status == GoalStatus.COMPLETED for g in tree.root.sub_goals):
            tree.root.status = GoalStatus.COMPLETED
        elif any(g.status == GoalStatus.FAILED for g in tree.root.sub_goals):
            tree.root.status = GoalStatus.FAILED

    return tree
