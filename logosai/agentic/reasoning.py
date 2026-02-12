"""
AgenticReasoning - 고급 추론 기능

Chain of Thought, ReAct, Tree of Thoughts 등 다양한 추론 패턴을 제공합니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from loguru import logger
import json

# LogosAI imports
from ..utils.llm_client import LLMClient


class ReasoningType(Enum):
    """추론 타입"""
    CHAIN_OF_THOUGHT = "chain_of_thought"
    REACT = "react"
    TREE_OF_THOUGHTS = "tree_of_thoughts"
    SELF_CONSISTENCY = "self_consistency"
    LEAST_TO_MOST = "least_to_most"


@dataclass
class ReasoningStep:
    """추론 단계"""
    step_number: int
    description: str
    reasoning: str
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.5
    alternatives: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "description": self.description,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "alternatives": self.alternatives
        }


@dataclass
class ReasoningResult:
    """추론 결과"""
    reasoning_type: ReasoningType
    problem: str
    steps: List[ReasoningStep]
    conclusion: str
    confidence: float
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reasoning_type": self.reasoning_type.value,
            "problem": self.problem,
            "steps": [s.to_dict() for s in self.steps],
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class ChainOfThought:
    """Chain of Thought 추론"""
    problem: str
    initial_thoughts: List[str]
    step_by_step_reasoning: List[ReasoningStep]
    final_answer: str
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem": self.problem,
            "initial_thoughts": self.initial_thoughts,
            "steps": [s.to_dict() for s in self.step_by_step_reasoning],
            "final_answer": self.final_answer,
            "confidence": self.confidence
        }


@dataclass
class ReActPattern:
    """ReAct (Reasoning + Acting) 패턴"""
    observation: str
    thought: str
    action: str
    action_result: Optional[Any] = None
    next_observation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation": self.observation,
            "thought": self.thought,
            "action": self.action,
            "action_result": self.action_result,
            "next_observation": self.next_observation
        }


@dataclass
class TreeOfThoughts:
    """Tree of Thoughts 추론"""
    problem: str
    root_thought: str
    branches: List[Dict[str, Any]]  # 각 브랜치는 하위 사고들을 포함
    evaluations: Dict[str, float]  # 각 경로의 평가 점수
    best_path: List[str]
    best_solution: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem": self.problem,
            "root_thought": self.root_thought,
            "branches": self.branches,
            "evaluations": self.evaluations,
            "best_path": self.best_path,
            "best_solution": self.best_solution
        }


class AgenticReasoning:
    """
    고급 추론 기능 구현
    
    다양한 추론 패턴을 통해 복잡한 문제를 체계적으로 해결합니다.
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        AgenticReasoning 초기화
        
        Args:
            llm_client: LLM 클라이언트
        """
        self.llm_client = llm_client or self._create_default_llm()
        self.reasoning_history: List[ReasoningResult] = []
        
        logger.info("AgenticReasoning initialized")
    
    def _create_default_llm(self) -> LLMClient:
        """기본 LLM 클라이언트 생성"""
        return LLMClient(
            provider="google",
            model="gemini-2.5-flash-lite",
            temperature=0.7
        )
    
    async def chain_of_thought(self, problem: str, context: Optional[Dict[str, Any]] = None) -> ChainOfThought:
        """
        Chain of Thought 추론 수행
        
        Args:
            problem: 해결할 문제
            context: 추가 컨텍스트
            
        Returns:
            ChainOfThought: 추론 과정과 결과
        """
        logger.debug(f"Starting Chain of Thought for: {problem}")
        
        try:
            # CoT 프롬프트 생성
            cot_prompt = f"""
            Let's think step by step to solve this problem:
            
            Problem: {problem}
            Context: {context if context else 'No additional context'}
            
            Please provide:
            1. Initial thoughts about the problem
            2. Step-by-step reasoning process
            3. Evidence or justification for each step
            4. Final answer with confidence level
            
            Format your response as JSON:
            {{
                "initial_thoughts": ["thought1", "thought2"],
                "steps": [
                    {{
                        "step": 1,
                        "description": "what we do",
                        "reasoning": "why we do it",
                        "evidence": ["evidence1"],
                        "confidence": 0.8
                    }}
                ],
                "final_answer": "the answer",
                "confidence": 0.85
            }}
            """
            
            response = await self.llm_client.invoke(cot_prompt)
            
            # Parse response
            try:
                result = json.loads(response.content)
            except:
                # Fallback parsing
                result = {
                    "initial_thoughts": ["Analyzing the problem"],
                    "steps": [
                        {
                            "step": 1,
                            "description": "Process the problem",
                            "reasoning": response.content,
                            "evidence": [],
                            "confidence": 0.5
                        }
                    ],
                    "final_answer": response.content,
                    "confidence": 0.5
                }
            
            # Create reasoning steps
            reasoning_steps = []
            for step_data in result.get("steps", []):
                step = ReasoningStep(
                    step_number=step_data.get("step", len(reasoning_steps) + 1),
                    description=step_data.get("description", ""),
                    reasoning=step_data.get("reasoning", ""),
                    evidence=step_data.get("evidence", []),
                    confidence=float(step_data.get("confidence", 0.5))
                )
                reasoning_steps.append(step)
            
            cot = ChainOfThought(
                problem=problem,
                initial_thoughts=result.get("initial_thoughts", []),
                step_by_step_reasoning=reasoning_steps,
                final_answer=result.get("final_answer", ""),
                confidence=float(result.get("confidence", 0.5))
            )
            
            # Save to history
            self._save_to_history(
                ReasoningType.CHAIN_OF_THOUGHT,
                problem,
                reasoning_steps,
                cot.final_answer,
                cot.confidence
            )
            
            logger.info(f"Chain of Thought completed with confidence: {cot.confidence}")
            return cot
            
        except Exception as e:
            logger.error(f"Error in Chain of Thought: {e}")
            # Return basic result on error
            return ChainOfThought(
                problem=problem,
                initial_thoughts=["Error occurred during reasoning"],
                step_by_step_reasoning=[],
                final_answer=f"Error: {str(e)}",
                confidence=0.1
            )
    
    async def react(self, observation: str, available_actions: List[str] = None) -> ReActPattern:
        """
        ReAct 패턴 수행 (Reasoning + Acting)
        
        Args:
            observation: 현재 관찰
            available_actions: 사용 가능한 행동 목록
            
        Returns:
            ReActPattern: 추론과 행동 결과
        """
        logger.debug(f"Starting ReAct for observation: {observation}")
        
        try:
            actions_str = "\n".join(f"- {action}" for action in (available_actions or []))
            
            react_prompt = f"""
            You are using the ReAct pattern (Reason + Act).
            
            Current Observation: {observation}
            
            Available Actions:
            {actions_str if actions_str else "- Any reasonable action"}
            
            Please:
            1. Think about what the observation means
            2. Decide what action to take
            3. Explain your reasoning
            
            Respond in JSON format:
            {{
                "thought": "what you think about the observation",
                "reasoning": "why you choose this action",
                "action": "the action to take",
                "expected_outcome": "what you expect to happen"
            }}
            """
            
            response = await self.llm_client.invoke(react_prompt)
            
            # Parse response
            try:
                result = json.loads(response.content)
            except:
                result = {
                    "thought": "Processing observation",
                    "reasoning": response.content,
                    "action": "analyze",
                    "expected_outcome": "Better understanding"
                }
            
            react_pattern = ReActPattern(
                observation=observation,
                thought=result.get("thought", ""),
                action=result.get("action", "")
            )
            
            logger.info(f"ReAct pattern generated action: {react_pattern.action}")
            return react_pattern
            
        except Exception as e:
            logger.error(f"Error in ReAct: {e}")
            return ReActPattern(
                observation=observation,
                thought=f"Error: {str(e)}",
                action="error_recovery"
            )
    
    async def tree_of_thoughts(self, problem: str, max_branches: int = 3, depth: int = 3) -> TreeOfThoughts:
        """
        Tree of Thoughts 추론 수행
        
        Args:
            problem: 해결할 문제
            max_branches: 각 노드의 최대 분기 수
            depth: 트리의 최대 깊이
            
        Returns:
            TreeOfThoughts: 사고 트리와 최적 경로
        """
        logger.debug(f"Starting Tree of Thoughts for: {problem}")
        
        try:
            # Generate initial thoughts
            tot_prompt = f"""
            Generate multiple solution paths for this problem using Tree of Thoughts:
            
            Problem: {problem}
            
            Generate {max_branches} different initial approaches.
            For each approach, think {depth} steps ahead.
            Evaluate each path and identify the best solution.
            
            Respond in JSON format:
            {{
                "root_thought": "initial understanding",
                "branches": [
                    {{
                        "thought": "approach 1",
                        "steps": ["step1", "step2"],
                        "evaluation": 0.8,
                        "sub_branches": []
                    }}
                ],
                "best_path": ["thought1", "step1", "step2"],
                "best_solution": "the optimal solution"
            }}
            """
            
            response = await self.llm_client.invoke(tot_prompt)
            
            # Parse response
            try:
                result = json.loads(response.content)
            except:
                result = {
                    "root_thought": "Analyzing problem",
                    "branches": [
                        {
                            "thought": "Default approach",
                            "steps": ["Analyze", "Solve"],
                            "evaluation": 0.5,
                            "sub_branches": []
                        }
                    ],
                    "best_path": ["Default approach"],
                    "best_solution": response.content
                }
            
            # Build evaluations dictionary
            evaluations = {}
            for i, branch in enumerate(result.get("branches", [])):
                path_key = f"path_{i}"
                evaluations[path_key] = float(branch.get("evaluation", 0.5))
            
            tot = TreeOfThoughts(
                problem=problem,
                root_thought=result.get("root_thought", ""),
                branches=result.get("branches", []),
                evaluations=evaluations,
                best_path=result.get("best_path", []),
                best_solution=result.get("best_solution", "")
            )
            
            logger.info(f"Tree of Thoughts generated {len(tot.branches)} branches")
            return tot
            
        except Exception as e:
            logger.error(f"Error in Tree of Thoughts: {e}")
            return TreeOfThoughts(
                problem=problem,
                root_thought="Error in reasoning",
                branches=[],
                evaluations={},
                best_path=[],
                best_solution=f"Error: {str(e)}"
            )
    
    async def self_consistency(self, problem: str, num_samples: int = 3) -> ReasoningResult:
        """
        Self-Consistency 추론 (여러 추론 경로 생성 후 일관성 있는 답 선택)
        
        Args:
            problem: 해결할 문제
            num_samples: 생성할 추론 경로 수
            
        Returns:
            ReasoningResult: 가장 일관성 있는 추론 결과
        """
        logger.debug(f"Starting Self-Consistency with {num_samples} samples")
        
        try:
            # Generate multiple reasoning paths
            results = []
            for i in range(num_samples):
                cot = await self.chain_of_thought(problem)
                results.append(cot)
            
            # Find most consistent answer
            answers = [r.final_answer for r in results]
            confidences = [r.confidence for r in results]
            
            # Vote for most common answer
            from collections import Counter
            answer_counts = Counter(answers)
            best_answer = answer_counts.most_common(1)[0][0]
            
            # Average confidence for best answer
            best_confidence = sum(c for a, c in zip(answers, confidences) if a == best_answer) / len(answers)
            
            # Combine reasoning steps from all paths
            all_steps = []
            for result in results:
                all_steps.extend(result.step_by_step_reasoning)
            
            reasoning_result = ReasoningResult(
                reasoning_type=ReasoningType.SELF_CONSISTENCY,
                problem=problem,
                steps=all_steps[:10],  # Keep top 10 steps
                conclusion=best_answer,
                confidence=best_confidence,
                metadata={
                    "num_samples": num_samples,
                    "answer_distribution": dict(answer_counts)
                }
            )
            
            self.reasoning_history.append(reasoning_result)
            
            logger.info(f"Self-Consistency completed with confidence: {best_confidence}")
            return reasoning_result
            
        except Exception as e:
            logger.error(f"Error in Self-Consistency: {e}")
            return ReasoningResult(
                reasoning_type=ReasoningType.SELF_CONSISTENCY,
                problem=problem,
                steps=[],
                conclusion=f"Error: {str(e)}",
                confidence=0.1
            )
    
    async def least_to_most(self, complex_problem: str) -> ReasoningResult:
        """
        Least-to-Most 추론 (복잡한 문제를 작은 부분으로 분해)
        
        Args:
            complex_problem: 복잡한 문제
            
        Returns:
            ReasoningResult: 단계별 해결 결과
        """
        logger.debug(f"Starting Least-to-Most for: {complex_problem}")
        
        try:
            # Decompose problem
            decompose_prompt = f"""
            Break down this complex problem into smaller, manageable sub-problems.
            Start with the simplest and build up to the complete solution.
            
            Problem: {complex_problem}
            
            Respond in JSON format:
            {{
                "sub_problems": [
                    {{
                        "order": 1,
                        "problem": "simplest sub-problem",
                        "solution": "solution",
                        "builds_on": []
                    }}
                ],
                "final_solution": "complete solution"
            }}
            """
            
            response = await self.llm_client.invoke(decompose_prompt)
            
            # Parse response
            try:
                result = json.loads(response.content)
            except:
                result = {
                    "sub_problems": [
                        {
                            "order": 1,
                            "problem": "Understand the problem",
                            "solution": "Analysis",
                            "builds_on": []
                        }
                    ],
                    "final_solution": response.content
                }
            
            # Create reasoning steps from sub-problems
            steps = []
            for sub in result.get("sub_problems", []):
                step = ReasoningStep(
                    step_number=sub.get("order", len(steps) + 1),
                    description=sub.get("problem", ""),
                    reasoning=sub.get("solution", ""),
                    evidence=sub.get("builds_on", []),
                    confidence=0.7
                )
                steps.append(step)
            
            reasoning_result = ReasoningResult(
                reasoning_type=ReasoningType.LEAST_TO_MOST,
                problem=complex_problem,
                steps=steps,
                conclusion=result.get("final_solution", ""),
                confidence=0.75,
                metadata={
                    "decomposition_count": len(steps)
                }
            )
            
            self.reasoning_history.append(reasoning_result)
            
            logger.info(f"Least-to-Most completed with {len(steps)} sub-problems")
            return reasoning_result
            
        except Exception as e:
            logger.error(f"Error in Least-to-Most: {e}")
            return ReasoningResult(
                reasoning_type=ReasoningType.LEAST_TO_MOST,
                problem=complex_problem,
                steps=[],
                conclusion=f"Error: {str(e)}",
                confidence=0.1
            )
    
    def _save_to_history(self, reasoning_type: ReasoningType, problem: str,
                        steps: List[ReasoningStep], conclusion: str, confidence: float):
        """추론 결과를 히스토리에 저장"""
        result = ReasoningResult(
            reasoning_type=reasoning_type,
            problem=problem,
            steps=steps,
            conclusion=conclusion,
            confidence=confidence
        )
        self.reasoning_history.append(result)
    
    def get_history(self) -> List[Dict[str, Any]]:
        """추론 히스토리 반환"""
        return [r.to_dict() for r in self.reasoning_history]
    
    def clear_history(self):
        """추론 히스토리 초기화"""
        self.reasoning_history.clear()
        logger.info("Reasoning history cleared")