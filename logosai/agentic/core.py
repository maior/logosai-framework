"""
AgenticCore - Agentic AI 핵심 기능

Think-Plan-Act-Reflect 사이클을 구현하는 핵심 모듈입니다.
모든 Agentic AI 에이전트의 기본 동작 패턴을 제공합니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger

# LogosAI imports
from ..utils.llm_client import LLMClient


class AgenticState(Enum):
    """에이전트 상태"""
    IDLE = "idle"
    THINKING = "thinking"
    PLANNING = "planning"
    ACTING = "acting"
    REFLECTING = "reflecting"
    LEARNING = "learning"


@dataclass
class ThoughtProcess:
    """사고 과정"""
    query: str
    understanding: str
    key_concepts: List[str]
    context_analysis: Dict[str, Any]
    confidence: float
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "understanding": self.understanding,
            "key_concepts": self.key_concepts,
            "context_analysis": self.context_analysis,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class Action:
    """실행할 행동"""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    requires_tool: bool = False
    tool_name: Optional[str] = None
    priority: int = 0  # 0이 가장 높은 우선순위
    dependencies: List[str] = field(default_factory=list)
    expected_outcome: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "requires_tool": self.requires_tool,
            "tool_name": self.tool_name,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "expected_outcome": self.expected_outcome
        }


@dataclass
class ActionPlan:
    """행동 계획"""
    goal: str
    actions: List[Action]
    strategy: str
    estimated_time: Optional[float] = None
    success_criteria: List[str] = field(default_factory=list)
    fallback_plan: Optional['ActionPlan'] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "actions": [a.to_dict() for a in self.actions],
            "strategy": self.strategy,
            "estimated_time": self.estimated_time,
            "success_criteria": self.success_criteria,
            "fallback_plan": self.fallback_plan.to_dict() if self.fallback_plan else None
        }


@dataclass
class Reflection:
    """반영 및 학습 결과"""
    outcome: str
    success: bool
    lessons_learned: List[str]
    improvements: List[str]
    confidence_adjustment: float  # -1.0 ~ 1.0
    next_steps: List[str]
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "success": self.success,
            "lessons_learned": self.lessons_learned,
            "improvements": self.improvements,
            "confidence_adjustment": self.confidence_adjustment,
            "next_steps": self.next_steps,
            "timestamp": self.timestamp.isoformat()
        }


class AgenticCore:
    """
    Agentic AI 핵심 기능 구현
    
    Think-Plan-Act-Reflect 사이클을 통해 자율적인 의사결정과 학습을 수행합니다.
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        tool_executor=None,
    ):
        """
        AgenticCore 초기화

        Args:
            llm_client: LLM 클라이언트 (없으면 기본값 사용)
            agent_name: 에이전트 이름 (로깅/컨텍스트용)
            config: 에이전트 설정 (agentic_config dict)
            tool_executor: 도구 실행 콜백 — async def(tool_name, parameters) → result
                           agent.py에서 주입하여 실제 도구 실행을 연결.
                           None이면 기존 LLM 시뮬레이션 방식으로 동작.
        """
        self.agent_name = agent_name or "Agent"
        self.config = config or {}
        self.llm_client = llm_client or self._create_default_llm()
        self._tool_executor = tool_executor
        self.state = AgenticState.IDLE
        self.thought_history: List[ThoughtProcess] = []
        self.action_history: List[Action] = []
        self.reflection_history: List[Reflection] = []
        self.current_confidence = 0.5

        logger.info(f"AgenticCore initialized for {self.agent_name} (tool_executor={'connected' if tool_executor else 'none'})")
    
    def _create_default_llm(self) -> LLMClient:
        """기본 LLM 클라이언트 생성"""
        return LLMClient(
            provider="google",
            model="gemini-2.5-flash-lite",
            temperature=0.7
        )
    
    async def think(self, query: str, context: Optional[Dict[str, Any]] = None) -> ThoughtProcess:
        """
        주어진 쿼리에 대해 사고하고 이해합니다.
        
        Args:
            query: 처리할 쿼리
            context: 추가 컨텍스트
            
        Returns:
            ThoughtProcess: 사고 과정 결과
        """
        self.state = AgenticState.THINKING
        logger.debug(f"Thinking about: {query}")
        
        try:
            # LLM을 사용한 쿼리 분석
            analysis_prompt = f"""
            Analyze the following query and provide a structured understanding:
            
            Query: {query}
            Context: {context if context else 'No additional context'}
            
            Please provide:
            1. Your understanding of what is being asked
            2. Key concepts involved (list them)
            3. Important context to consider
            4. Your confidence level (0-1) in understanding this query
            
            Respond in JSON format:
            {{
                "understanding": "your understanding",
                "key_concepts": ["concept1", "concept2"],
                "context_analysis": {{"key": "value"}},
                "confidence": 0.8
            }}
            """
            
            response = await self.llm_client.invoke(analysis_prompt)
            
            # Parse LLM response
            import json
            try:
                result = json.loads(response.content)
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fallback if JSON parsing fails
                result = {
                    "understanding": response.content,
                    "key_concepts": [],
                    "context_analysis": {},
                    "confidence": 0.5
                }
            
            thought = ThoughtProcess(
                query=query,
                understanding=result.get("understanding", ""),
                key_concepts=result.get("key_concepts", []),
                context_analysis=result.get("context_analysis", {}),
                confidence=float(result.get("confidence", 0.5))
            )
            
            self.thought_history.append(thought)
            self.current_confidence = thought.confidence
            
            logger.info(f"Thought process completed with confidence: {thought.confidence}")
            return thought
            
        except Exception as e:
            logger.error(f"Error during thinking: {e}")
            # Return a basic thought process on error
            thought = ThoughtProcess(
                query=query,
                understanding=f"Error analyzing query: {str(e)}",
                key_concepts=[],
                context_analysis={},
                confidence=0.1
            )
            self.thought_history.append(thought)
            return thought
        finally:
            self.state = AgenticState.IDLE
    
    async def plan(self, goal: str, thought: Optional[ThoughtProcess] = None) -> ActionPlan:
        """
        목표를 달성하기 위한 행동 계획을 수립합니다.
        
        Args:
            goal: 달성할 목표
            thought: 관련 사고 과정 (선택적)
            
        Returns:
            ActionPlan: 수립된 행동 계획
        """
        self.state = AgenticState.PLANNING
        logger.debug(f"Planning for goal: {goal}")
        
        try:
            # Use thought context if available
            context = ""
            if thought:
                context = f"""
                Based on previous analysis:
                - Understanding: {thought.understanding}
                - Key concepts: {', '.join(thought.key_concepts)}
                - Confidence: {thought.confidence}
                """
            
            planning_prompt = f"""
            Create an action plan to achieve the following goal:
            
            Goal: {goal}
            {context}
            
            Please provide:
            1. A clear strategy
            2. Step-by-step actions (with priorities)
            3. Success criteria
            4. Estimated time (optional)
            
            Respond in JSON format:
            {{
                "strategy": "overall approach",
                "actions": [
                    {{
                        "name": "action_name",
                        "description": "what to do",
                        "priority": 0,
                        "requires_tool": false,
                        "expected_outcome": "expected result"
                    }}
                ],
                "success_criteria": ["criterion1", "criterion2"],
                "estimated_time": 30
            }}
            """
            
            response = await self.llm_client.invoke(planning_prompt)
            
            # Parse LLM response
            import json
            try:
                result = json.loads(response.content)
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fallback plan
                result = {
                    "strategy": "Direct approach",
                    "actions": [
                        {
                            "name": "execute_task",
                            "description": goal,
                            "priority": 0,
                            "requires_tool": False,
                            "expected_outcome": "Task completed"
                        }
                    ],
                    "success_criteria": ["Goal achieved"],
                    "estimated_time": None
                }
            
            # Create Action objects
            actions = []
            for action_data in result.get("actions", []):
                action = Action(
                    name=action_data.get("name", "unnamed_action"),
                    description=action_data.get("description", ""),
                    parameters=action_data.get("parameters", {}),
                    requires_tool=action_data.get("requires_tool", False),
                    tool_name=action_data.get("tool_name"),
                    priority=action_data.get("priority", 0),
                    dependencies=action_data.get("dependencies", []),
                    expected_outcome=action_data.get("expected_outcome")
                )
                actions.append(action)
            
            plan = ActionPlan(
                goal=goal,
                actions=actions,
                strategy=result.get("strategy", ""),
                estimated_time=result.get("estimated_time"),
                success_criteria=result.get("success_criteria", [])
            )
            
            logger.info(f"Created plan with {len(plan.actions)} actions")
            return plan
            
        except Exception as e:
            logger.error(f"Error during planning: {e}")
            # Return a simple fallback plan
            plan = ActionPlan(
                goal=goal,
                actions=[
                    Action(
                        name="fallback_action",
                        description=f"Attempt to {goal}",
                        priority=0
                    )
                ],
                strategy="Fallback strategy due to planning error",
                success_criteria=["Task attempted"]
            )
            return plan
        finally:
            self.state = AgenticState.IDLE
    
    async def act(self, action: Action) -> Dict[str, Any]:
        """
        행동을 실행합니다.

        도구가 필요한 행동(requires_tool=True)이고 tool_executor가 연결되어 있으면
        실제 도구를 실행합니다. 그렇지 않으면 LLM으로 결과를 생성합니다.

        Args:
            action: 실행할 행동

        Returns:
            Dict[str, Any]: 실행 결과 {"success", "result", "output", "issues"}
        """
        self.state = AgenticState.ACTING
        logger.debug(f"Executing action: {action.name}")

        try:
            self.action_history.append(action)

            # Case 1: 도구 필요 + executor 연결됨 → 실제 도구 실행
            if action.requires_tool and action.tool_name and self._tool_executor:
                logger.info(f"Action {action.name}: executing tool '{action.tool_name}' with real executor")
                try:
                    tool_result = await self._tool_executor(action.tool_name, action.parameters)
                    result = {
                        "success": True,
                        "result": str(tool_result),
                        "output": {"tool": action.tool_name, "raw": tool_result},
                        "issues": [],
                    }
                except Exception as tool_err:
                    logger.warning(f"Tool execution failed for {action.tool_name}: {tool_err}")
                    result = {
                        "success": False,
                        "result": f"Tool execution failed: {tool_err}",
                        "output": {},
                        "issues": [str(tool_err)],
                    }

                logger.info(f"Action {action.name} completed: success={result['success']}")
                return result

            # Case 2: 도구 불필요 또는 executor 없음 → LLM 생성
            execution_prompt = f"""
            Simulate the execution of the following action:

            Action: {action.name}
            Description: {action.description}
            Parameters: {action.parameters}
            Expected Outcome: {action.expected_outcome or 'Not specified'}

            Provide a realistic result of this action execution.
            Include:
            1. Whether it was successful
            2. What was accomplished
            3. Any data or output produced
            4. Any issues encountered

            Respond in JSON format:
            {{
                "success": true,
                "result": "what was accomplished",
                "output": {{}},
                "issues": []
            }}
            """

            response = await self.llm_client.invoke(execution_prompt)

            import json
            try:
                result = json.loads(response.content)
            except (json.JSONDecodeError, ValueError, TypeError):
                result = {
                    "success": True,
                    "result": f"Executed {action.name}",
                    "output": {},
                    "issues": []
                }

            logger.info(f"Action {action.name} completed: success={result.get('success', False)}")
            return result

        except Exception as e:
            logger.error(f"Error during action execution: {e}")
            return {
                "success": False,
                "result": f"Error executing action: {str(e)}",
                "output": {},
                "issues": [str(e)]
            }
        finally:
            self.state = AgenticState.IDLE
    
    async def reflect(self, results: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Reflection:
        """
        실행 결과를 반영하고 학습합니다.
        
        Args:
            results: 실행 결과 (단일 또는 복수)
            
        Returns:
            Reflection: 반영 결과
        """
        self.state = AgenticState.REFLECTING
        logger.debug("Reflecting on results")
        
        try:
            # Ensure results is a list
            if not isinstance(results, list):
                results = [results]
            
            # Prepare results summary
            results_summary = []
            for i, result in enumerate(results):
                results_summary.append(f"Result {i+1}: {result}")
            
            reflection_prompt = f"""
            Reflect on the following execution results:
            
            {chr(10).join(results_summary)}
            
            Please provide:
            1. Overall outcome assessment
            2. Whether the goal was achieved (true/false)
            3. Key lessons learned
            4. Suggestions for improvement
            5. Confidence adjustment (-1 to 1)
            6. Recommended next steps
            
            Respond in JSON format:
            {{
                "outcome": "overall assessment",
                "success": true,
                "lessons_learned": ["lesson1", "lesson2"],
                "improvements": ["improvement1", "improvement2"],
                "confidence_adjustment": 0.1,
                "next_steps": ["step1", "step2"]
            }}
            """
            
            response = await self.llm_client.invoke(reflection_prompt)
            
            # Parse response
            import json
            try:
                result = json.loads(response.content)
            except (json.JSONDecodeError, ValueError, TypeError):
                result = {
                    "outcome": "Reflection completed",
                    "success": True,
                    "lessons_learned": [],
                    "improvements": [],
                    "confidence_adjustment": 0,
                    "next_steps": []
                }
            
            reflection = Reflection(
                outcome=result.get("outcome", ""),
                success=result.get("success", False),
                lessons_learned=result.get("lessons_learned", []),
                improvements=result.get("improvements", []),
                confidence_adjustment=float(result.get("confidence_adjustment", 0)),
                next_steps=result.get("next_steps", [])
            )
            
            # Update confidence
            self.current_confidence = max(0, min(1, 
                self.current_confidence + reflection.confidence_adjustment))
            
            self.reflection_history.append(reflection)
            
            logger.info(f"Reflection completed: success={reflection.success}, "
                       f"new confidence={self.current_confidence}")
            return reflection
            
        except Exception as e:
            logger.error(f"Error during reflection: {e}")
            reflection = Reflection(
                outcome=f"Reflection error: {str(e)}",
                success=False,
                lessons_learned=[],
                improvements=[],
                confidence_adjustment=-0.1,
                next_steps=["Review and retry"]
            )
            self.reflection_history.append(reflection)
            return reflection
        finally:
            self.state = AgenticState.IDLE
    
    async def execute_cycle(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        완전한 Think-Plan-Act-Reflect 사이클을 실행합니다.
        
        Args:
            query: 처리할 쿼리
            context: 추가 컨텍스트
            
        Returns:
            Dict[str, Any]: 전체 사이클 결과
        """
        logger.info(f"Starting full agentic cycle for: {query}")
        
        # 1. Think
        thought = await self.think(query, context)
        
        # 2. Plan
        plan = await self.plan(query, thought)
        
        # 3. Act
        results = []
        for action in sorted(plan.actions, key=lambda a: a.priority):
            result = await self.act(action)
            results.append(result)
            
            # Stop if critical action fails
            if not result.get("success", False) and action.priority == 0:
                logger.warning(f"Critical action {action.name} failed, stopping execution")
                break
        
        # 4. Reflect
        reflection = await self.reflect(results)
        
        # Compile full cycle result
        cycle_result = {
            "query": query,
            "thought": thought.to_dict(),
            "plan": plan.to_dict(),
            "execution_results": results,
            "reflection": reflection.to_dict(),
            "final_confidence": self.current_confidence,
            "success": reflection.success
        }
        
        logger.info(f"Agentic cycle completed: success={reflection.success}")
        return cycle_result
    
    def get_history(self) -> Dict[str, Any]:
        """
        에이전트의 전체 히스토리를 반환합니다.
        
        Returns:
            Dict[str, Any]: 사고, 행동, 반영 히스토리
        """
        return {
            "thoughts": [t.to_dict() for t in self.thought_history],
            "actions": [a.to_dict() for a in self.action_history],
            "reflections": [r.to_dict() for r in self.reflection_history],
            "current_confidence": self.current_confidence,
            "current_state": self.state.value
        }
    
    def reset(self):
        """에이전트 상태를 초기화합니다."""
        self.state = AgenticState.IDLE
        self.thought_history.clear()
        self.action_history.clear()
        self.reflection_history.clear()
        self.current_confidence = 0.5
        logger.info("AgenticCore reset to initial state")