"""
LogosAI 쿼리 분해기 (Query Decomposer)

LLM을 사용해 복합 쿼리를 분석하고 실행 가능한 태스크로 분해합니다.
"""

import json
import time
import re
from typing import List, Dict, Any, Optional
from loguru import logger

from .models import (
    DecompositionResult, TaskInfo, ExecutionStrategy,
    QueryComplexity, TaskStatus
)


class QueryDecomposer:
    """
    LLM 기반 쿼리 분해기

    복합 쿼리를 분석하여 개별 태스크로 분해하고,
    각 태스크에 적합한 에이전트를 매핑합니다.
    """

    def __init__(self, llm=None):
        """
        초기화

        Args:
            llm: LangChain LLM 인스턴스 (None이면 기본 Gemini 사용)
        """
        self.llm = llm
        self._initialized = False

        # 복합 쿼리 감지용 키워드
        self.compound_keywords = [
            "그리고", "후에", "다음에", "그런 다음", "이후에",
            "and", "then", "after", "next",
            ",", "하고", "해서", "한 후", "한 다음",
            "먼저", "우선", "나중에", "마지막으로"
        ]

        # 단순 쿼리 판단용 패턴
        self.simple_patterns = [
            r"^[\d\s\+\-\*\/\(\)\.\,\%]*$",  # 순수 수식
            r"^\d+[\+\-\*\/]\d+",             # 간단한 계산
        ]

    async def initialize(self):
        """LLM 초기화"""
        if self._initialized:
            return

        try:
            if self.llm is None:
                from langchain_google_genai import ChatGoogleGenerativeAI
                self.llm = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash-lite",
                    temperature=0.3,
                    convert_system_message_to_human=True
                )
            self._initialized = True
            logger.info("QueryDecomposer 초기화 완료")
        except Exception as e:
            logger.error(f"QueryDecomposer 초기화 실패: {e}")
            raise

    async def decompose(
        self,
        query: str,
        available_agents: List[Dict[str, Any]]
    ) -> DecompositionResult:
        """
        쿼리를 분석하고 태스크로 분해

        Args:
            query: 사용자 쿼리
            available_agents: 사용 가능한 에이전트 목록
                - agent_id, name, description, capabilities

        Returns:
            DecompositionResult: 분해 결과
        """
        start_time = time.time()

        try:
            # 1. 빠른 단순 쿼리 체크 (LLM 호출 없이)
            if self._is_obviously_simple(query):
                logger.info(f"단순 쿼리 감지 (빠른 체크): {query[:50]}...")
                return self._create_simple_result(query, available_agents, start_time)

            # 2. 복합 쿼리 가능성 체크
            if not self._might_be_complex(query):
                logger.info(f"단순 쿼리 감지 (키워드 체크): {query[:50]}...")
                return self._create_simple_result(query, available_agents, start_time)

            # 3. LLM 기반 분석
            if not self._initialized:
                await self.initialize()

            decomposition = await self._llm_decompose(query, available_agents)
            decomposition.analysis_time = time.time() - start_time

            logger.info(
                f"쿼리 분해 완료: is_complex={decomposition.is_complex}, "
                f"tasks={decomposition.task_count}, "
                f"strategy={decomposition.suggested_strategy.value}"
            )

            return decomposition

        except Exception as e:
            logger.error(f"쿼리 분해 중 오류: {e}")
            # 오류 시 단순 쿼리로 폴백
            return DecompositionResult(
                original_query=query,
                is_complex=False,
                complexity=QueryComplexity.SIMPLE,
                complexity_score=0.0,
                tasks=[],
                reasoning=f"분해 오류로 단순 처리: {str(e)}",
                suggested_strategy=ExecutionStrategy.SEQUENTIAL,
                analysis_time=time.time() - start_time,
                error=str(e)
            )

    def _is_obviously_simple(self, query: str) -> bool:
        """빠른 단순 쿼리 체크"""
        # 매우 짧은 쿼리
        if len(query) < 20:
            return True

        # 순수 수식
        for pattern in self.simple_patterns:
            if re.match(pattern, query.strip()):
                return True

        return False

    def _might_be_complex(self, query: str) -> bool:
        """복합 쿼리 가능성 체크"""
        query_lower = query.lower()

        # 복합 키워드 포함 여부
        for keyword in self.compound_keywords:
            if keyword in query_lower:
                return True

        # 동사가 여러 개인 경우 (한국어)
        action_verbs = ["해줘", "알려줘", "만들어", "분석해", "검색해", "작성해", "생성해", "보여줘"]
        verb_count = sum(1 for verb in action_verbs if verb in query)
        if verb_count >= 2:
            return True

        return False

    def _create_simple_result(
        self,
        query: str,
        available_agents: List[Dict[str, Any]],
        start_time: float
    ) -> DecompositionResult:
        """단순 쿼리 결과 생성"""
        return DecompositionResult(
            original_query=query,
            is_complex=False,
            complexity=QueryComplexity.SIMPLE,
            complexity_score=0.1,
            tasks=[],  # 단순 쿼리는 기존 로직 사용
            reasoning="단순 쿼리로 판단되어 기존 에이전트 선택 로직 사용",
            suggested_strategy=ExecutionStrategy.SEQUENTIAL,
            analysis_time=time.time() - start_time
        )

    async def _llm_decompose(
        self,
        query: str,
        available_agents: List[Dict[str, Any]]
    ) -> DecompositionResult:
        """LLM을 사용한 쿼리 분해"""

        # 에이전트 정보 포맷팅
        agents_info = self._format_agents_info(available_agents)
        agent_ids = [a.get("agent_id", "") for a in available_agents if a.get("agent_id")]

        # 프롬프트 생성
        prompt = self._create_decomposition_prompt(query, agents_info, agent_ids)

        try:
            # LLM 호출
            response = await self.llm.ainvoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)

            # 응답 파싱
            return self._parse_llm_response(query, response_text, agent_ids)

        except Exception as e:
            logger.error(f"LLM 분해 호출 실패: {e}")
            raise

    def _format_agents_info(self, agents: List[Dict[str, Any]]) -> str:
        """에이전트 정보를 프롬프트용으로 포맷팅"""
        info_parts = []

        for idx, agent in enumerate(agents[:15], 1):  # 상위 15개만
            agent_id = agent.get("agent_id", "unknown")
            name = agent.get("name", "")
            description = agent.get("description", "")[:200]  # 설명 제한

            # capabilities 정리
            capabilities = agent.get("capabilities", [])
            cap_names = [c.get("name", "") for c in capabilities[:3] if c.get("name")]
            cap_text = ", ".join(cap_names) if cap_names else "일반"

            info_parts.append(
                f"{idx}. {agent_id} ({name})\n"
                f"   설명: {description}\n"
                f"   주요 기능: {cap_text}"
            )

        return "\n\n".join(info_parts)

    def _create_decomposition_prompt(
        self,
        query: str,
        agents_info: str,
        agent_ids: List[str]
    ) -> str:
        """LLM 분해 프롬프트 생성"""

        return f"""당신은 사용자 쿼리를 분석하여 실행 가능한 태스크로 분해하는 전문가입니다.

## 사용 가능한 에이전트
{agents_info}

## 사용자 쿼리
{query}

## 분석 지침
1. 쿼리가 **단일 작업**인지 **복합 작업**인지 판단하세요
2. 복합 작업이면 개별 태스크로 분해하세요 (최대 5개)
3. 각 태스크에 가장 적합한 에이전트를 매핑하세요
4. 태스크 간 의존성을 파악하세요:
   - 이전 작업 결과가 필요한 경우 depends_on에 task_id 추가
   - 독립적인 작업은 depends_on을 빈 배열로
5. 실행 전략 결정:
   - sequential: 모든 태스크가 순차적으로 실행
   - parallel: 모든 태스크가 병렬 실행 가능
   - hybrid: 일부는 순차, 일부는 병렬 (의존성 기반)

## 중요 규칙
- 단순한 질문이나 단일 작업은 is_complex=false로 설정하세요
- 복잡도 점수(complexity_score)는 0.0~1.0 사이입니다
- agent_id는 반드시 아래 목록에서 선택하세요

## 사용 가능한 agent_id 목록
{', '.join(agent_ids)}

## 응답 형식 (JSON만 출력)
```json
{{
    "is_complex": true 또는 false,
    "complexity_score": 0.0-1.0,
    "reasoning": "분석 이유 설명",
    "tasks": [
        {{
            "task_id": "task_1",
            "description": "태스크 설명",
            "agent_id": "에이전트 ID",
            "agent_query": "에이전트에 전달할 구체적인 쿼리",
            "depends_on": [],
            "priority": 1
        }}
    ],
    "suggested_strategy": "sequential" 또는 "parallel" 또는 "hybrid"
}}
```

JSON 응답만 출력하세요:"""

    def _parse_llm_response(
        self,
        original_query: str,
        response_text: str,
        agent_ids: List[str]
    ) -> DecompositionResult:
        """LLM 응답 파싱"""

        try:
            # JSON 추출 시도
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # JSON 블록 없으면 전체 텍스트에서 시도
                json_str = response_text.strip()
                # { } 찾기
                start = json_str.find('{')
                end = json_str.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = json_str[start:end]

            data = json.loads(json_str)

            # 결과 생성
            is_complex = data.get("is_complex", False)
            complexity_score = float(data.get("complexity_score", 0.0))
            reasoning = data.get("reasoning", "")

            # 태스크 파싱
            tasks = []
            for task_data in data.get("tasks", []):
                agent_id = task_data.get("agent_id", "")

                # 유효한 agent_id인지 확인
                if agent_id and agent_id not in agent_ids:
                    logger.warning(f"유효하지 않은 agent_id: {agent_id}")
                    continue

                task = TaskInfo(
                    task_id=task_data.get("task_id", ""),
                    description=task_data.get("description", ""),
                    agent_id=agent_id,
                    agent_query=task_data.get("agent_query", ""),
                    depends_on=task_data.get("depends_on", []),
                    priority=task_data.get("priority", 0),
                    status=TaskStatus.PENDING
                )
                tasks.append(task)

            # 전략 파싱
            strategy_str = data.get("suggested_strategy", "sequential").lower()
            try:
                strategy = ExecutionStrategy(strategy_str)
            except ValueError:
                strategy = ExecutionStrategy.SEQUENTIAL

            # 복잡도 결정
            if len(tasks) == 0:
                complexity = QueryComplexity.SIMPLE
                is_complex = False
            elif len(tasks) <= 2:
                complexity = QueryComplexity.MODERATE
            else:
                complexity = QueryComplexity.COMPLEX

            return DecompositionResult(
                original_query=original_query,
                is_complex=is_complex and len(tasks) > 1,
                complexity=complexity,
                complexity_score=complexity_score,
                tasks=tasks,
                reasoning=reasoning,
                suggested_strategy=strategy
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}\n응답: {response_text[:500]}")
            # 파싱 실패 시 단순 쿼리로 처리
            return DecompositionResult(
                original_query=original_query,
                is_complex=False,
                complexity=QueryComplexity.SIMPLE,
                complexity_score=0.0,
                tasks=[],
                reasoning=f"LLM 응답 파싱 실패: {str(e)}",
                suggested_strategy=ExecutionStrategy.SEQUENTIAL,
                error=f"JSON parse error: {str(e)}"
            )

    def _validate_decomposition(
        self,
        decomposition: DecompositionResult,
        agent_ids: List[str]
    ) -> DecompositionResult:
        """분해 결과 검증 및 보정"""

        valid_tasks = []
        for task in decomposition.tasks:
            # agent_id 검증
            if task.agent_id not in agent_ids:
                logger.warning(f"유효하지 않은 agent_id 제거: {task.agent_id}")
                continue

            # 의존성 검증
            valid_deps = [
                dep for dep in task.depends_on
                if any(t.task_id == dep for t in decomposition.tasks)
            ]
            task.depends_on = valid_deps

            valid_tasks.append(task)

        decomposition.tasks = valid_tasks

        # 태스크가 없으면 단순 쿼리로
        if len(valid_tasks) == 0:
            decomposition.is_complex = False
            decomposition.complexity = QueryComplexity.SIMPLE

        return decomposition
