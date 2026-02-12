"""
간단한 워크플로우 구현 모듈

이 모듈은 간단한 워크플로우 기능을 제공합니다.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable, Union
from datetime import datetime

from ..agent import LogosAIAgent
from ..types import AgentResponse, AgentResponseType

# 로깅 설정
logger = logging.getLogger(__name__)


class WorkflowStep:
    """워크플로우 단계 클래스"""
    
    def __init__(
        self,
        name: str,
        agent: Optional[LogosAIAgent] = None,
        input_query: Optional[str] = None,
        input_template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        output_var: Optional[str] = None
    ):
        """워크플로우 단계 초기화
        
        Args:
            name: 단계 이름
            agent: 단계에서 사용할 에이전트 (없으면 템플릿 기반 단계)
            input_query: 에이전트에 전달할 쿼리 템플릿
            input_template: 직접 처리할 입력 템플릿 (에이전트가 없을 때 사용)
            context: 추가 컨텍스트 정보
            output_var: 결과 저장 변수 이름
        """
        self.name = name
        self.agent = agent
        self.input_query = input_query
        self.input_template = input_template
        self.context = context or {}
        self.output_var = output_var
    
    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """템플릿 렌더링
        
        {{변수}} 형식의 변수를 컨텍스트에서 가져온 값으로 대체합니다.
        
        Args:
            template: 렌더링할 템플릿
            context: 컨텍스트 정보
            
        Returns:
            렌더링된 문자열
        """
        result = template
        
        # 변수 대체
        import re
        var_pattern = r'{{([^{}]+)}}'
        
        for match in re.finditer(var_pattern, template):
            var_path = match.group(1).strip()
            var_value = self._get_nested_value(context, var_path)
            
            if var_value is not None:
                result = result.replace(match.group(0), str(var_value))
            else:
                logger.warning(f"변수를 찾을 수 없음: {var_path}")
        
        return result
    
    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """중첩된 딕셔너리에서 값 가져오기
        
        예: "results.content" 경로는 data["results"]["content"]를 가져옵니다.
        
        Args:
            data: 데이터 딕셔너리
            path: 점으로 구분된 경로
            
        Returns:
            찾은 값 (없으면 None)
        """
        parts = path.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 단계 실행
        
        Args:
            context: 워크플로우 컨텍스트
            
        Returns:
            업데이트된 컨텍스트
        """
        # 단계 시작 기록
        logger.info(f"워크플로우 단계 실행: {self.name}")
        context["current_step"] = self.name
        context["step_start_time"] = datetime.now().isoformat()
        
        # 에이전트가 있으면 에이전트로 처리
        if self.agent and self.input_query:
            # 쿼리 렌더링
            query = self._render_template(self.input_query, context)
            
            # 에이전트 컨텍스트 병합
            agent_context = {**self.context, **context.get("agent_context", {})}
            
            # 에이전트 실행
            try:
                response = await self.agent.process(query, agent_context)
                
                # 결과 저장
                if self.output_var:
                    context[self.output_var] = response
                
                logger.info(f"에이전트 응답 유형: {response.type}")
                
            except Exception as e:
                logger.error(f"에이전트 실행 중 오류: {str(e)}")
                context["error"] = str(e)
                context["error_step"] = self.name
        
        # 템플릿만 있으면 직접 처리
        elif self.input_template:
            # 템플릿 렌더링
            result = self._render_template(self.input_template, context)
            
            # 결과 저장
            if self.output_var:
                context[self.output_var] = result
        
        # 단계 종료 기록
        context["step_end_time"] = datetime.now().isoformat()
        
        return context


class Workflow:
    """워크플로우 클래스"""
    
    def __init__(self, name: str):
        """워크플로우 초기화
        
        Args:
            name: 워크플로우 이름
        """
        self.name = name
        self.steps: List[WorkflowStep] = []
        self.context: Dict[str, Any] = {}
    
    def add_step(self, step: WorkflowStep):
        """워크플로우 단계 추가
        
        Args:
            step: 추가할 워크플로우 단계
        """
        self.steps.append(step)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 실행
        
        Args:
            context: 초기 컨텍스트
            
        Returns:
            최종 컨텍스트
        """
        # 컨텍스트 초기화
        workflow_context = {**self.context, **context}
        workflow_context["workflow_name"] = self.name
        workflow_context["workflow_start_time"] = datetime.now().isoformat()
        
        logger.info(f"워크플로우 실행 시작: {self.name}")
        
        # 단계별 실행
        for i, step in enumerate(self.steps):
            logger.info(f"워크플로우 단계 {i+1}/{len(self.steps)}: {step.name}")
            
            # 단계 실행
            try:
                workflow_context = await step.execute(workflow_context)
                
                # 오류 확인
                if "error" in workflow_context:
                    logger.error(f"워크플로우 단계 오류: {workflow_context['error']}")
                    break
                    
            except Exception as e:
                logger.error(f"워크플로우 단계 실행 중 예외 발생: {str(e)}")
                workflow_context["error"] = str(e)
                workflow_context["error_step"] = step.name
                break
        
        # 워크플로우 종료 기록
        workflow_context["workflow_end_time"] = datetime.now().isoformat()
        logger.info(f"워크플로우 실행 완료: {self.name}")
        
        return workflow_context 