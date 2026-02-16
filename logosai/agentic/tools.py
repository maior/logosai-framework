"""
AgenticTools - 도구 사용 프레임워크

에이전트가 다양한 도구를 등록하고 사용할 수 있는 프레임워크를 제공합니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from loguru import logger
import inspect
import json
from functools import wraps


class ToolCategory(Enum):
    """도구 카테고리"""
    DATA_PROCESSING = "data_processing"
    WEB_ACCESS = "web_access"
    FILE_SYSTEM = "file_system"
    DATABASE = "database"
    API_CALL = "api_call"
    CALCULATION = "calculation"
    TEXT_ANALYSIS = "text_analysis"
    IMAGE_PROCESSING = "image_processing"
    CUSTOM = "custom"


@dataclass
class ToolParameter:
    """도구 파라미터 정의"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default": self.default
        }


@dataclass
class Tool:
    """도구 정의"""
    name: str
    description: str
    category: ToolCategory
    function: Callable
    parameters: List[ToolParameter] = field(default_factory=list)
    returns: str = "Any"
    examples: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "parameters": [p.to_dict() for p in self.parameters],
            "returns": self.returns,
            "examples": self.examples,
            "metadata": self.metadata
        }
    
    async def execute(self, **kwargs) -> 'ToolResult':
        """도구 실행"""
        try:
            # 필수 파라미터 검증
            for param in self.parameters:
                if param.required and param.name not in kwargs:
                    if param.default is not None:
                        kwargs[param.name] = param.default
                    else:
                        raise ValueError(f"Required parameter '{param.name}' is missing")
            
            # 함수 실행
            if inspect.iscoroutinefunction(self.function):
                result = await self.function(**kwargs)
            else:
                result = self.function(**kwargs)
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                result=result,
                execution_time=0  # Will be set by caller
            )
            
        except Exception as e:
            logger.error(f"Error executing tool {self.name}: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e),
                execution_time=0
            )


@dataclass
class ToolResult:
    """도구 실행 결과"""
    tool_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }


class ToolRegistry:
    """도구 레지스트리"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.categories: Dict[ToolCategory, List[str]] = {}
        self.execution_history: List[ToolResult] = []
        
        # 기본 도구 등록
        self._register_default_tools()
        
        logger.info("ToolRegistry initialized")
    
    def _register_default_tools(self):
        """기본 도구 등록"""
        # 텍스트 분석 도구
        self.register_tool(Tool(
            name="text_summary",
            description="텍스트 요약 도구",
            category=ToolCategory.TEXT_ANALYSIS,
            function=self._text_summary,
            parameters=[
                ToolParameter("text", "str", "요약할 텍스트"),
                ToolParameter("max_length", "int", "최대 길이", False, 100)
            ],
            returns="str"
        ))
        
        # 계산 도구
        self.register_tool(Tool(
            name="calculator",
            description="수학 계산 도구",
            category=ToolCategory.CALCULATION,
            function=self._calculator,
            parameters=[
                ToolParameter("expression", "str", "계산할 수식")
            ],
            returns="float"
        ))
        
        # JSON 파싱 도구
        self.register_tool(Tool(
            name="json_parser",
            description="JSON 문자열 파싱",
            category=ToolCategory.DATA_PROCESSING,
            function=self._json_parser,
            parameters=[
                ToolParameter("json_str", "str", "JSON 문자열")
            ],
            returns="dict"
        ))
    
    async def _text_summary(self, text: str, max_length: int = 100) -> str:
        """텍스트 요약 (간단한 구현)"""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."
    
    def _calculator(self, expression: str) -> float:
        """계산기"""
        try:
            # 안전한 eval을 위한 제한된 환경
            allowed_names = {
                k: v for k, v in math.__dict__.items() if not k.startswith("__")
            }
            code = compile(expression, "<string>", "eval")
            for name in code.co_names:
                if name not in allowed_names:
                    raise NameError(f"Use of {name} not allowed")
            return eval(code, {"__builtins__": {}}, allowed_names)
        except Exception:
            # math 모듈이 없는 경우 기본 eval
            return eval(expression, {"__builtins__": {}})
    
    def _json_parser(self, json_str: str) -> Dict[str, Any]:
        """JSON 파서"""
        return json.loads(json_str)
    
    def register_tool(self, tool: Tool) -> None:
        """도구 등록"""
        self.tools[tool.name] = tool
        
        # 카테고리별 분류
        if tool.category not in self.categories:
            self.categories[tool.category] = []
        if tool.name not in self.categories[tool.category]:
            self.categories[tool.category].append(tool.name)
        
        logger.info(f"Tool registered: {tool.name} ({tool.category.value})")
    
    def unregister_tool(self, tool_name: str) -> bool:
        """도구 등록 해제"""
        if tool_name in self.tools:
            tool = self.tools[tool_name]
            del self.tools[tool_name]
            
            # 카테고리에서 제거
            if tool.category in self.categories:
                self.categories[tool.category].remove(tool_name)
            
            logger.info(f"Tool unregistered: {tool_name}")
            return True
        return False
    
    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """도구 조회"""
        return self.tools.get(tool_name)
    
    def get_tools_by_category(self, category: ToolCategory) -> List[Tool]:
        """카테고리별 도구 목록"""
        tool_names = self.categories.get(category, [])
        return [self.tools[name] for name in tool_names if name in self.tools]
    
    def list_tools(self) -> List[str]:
        """모든 도구 이름 목록"""
        return list(self.tools.keys())
    
    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """도구 정보 조회"""
        tool = self.get_tool(tool_name)
        return tool.to_dict() if tool else None


class AgenticTools:
    """
    도구 사용 관리 시스템
    
    에이전트가 다양한 도구를 등록하고 사용할 수 있도록 지원합니다.
    """
    
    def __init__(self):
        """AgenticTools 초기화"""
        self.registry = ToolRegistry()
        self.execution_count = 0
        self.total_execution_time = 0.0
        
        logger.info("AgenticTools initialized")
    
    def register_tool(self, tool: Tool) -> None:
        """도구 등록"""
        self.registry.register_tool(tool)
    
    def register_function_as_tool(self, name: str, description: str, 
                                 category: ToolCategory = ToolCategory.CUSTOM) -> Callable:
        """데코레이터: 함수를 도구로 등록"""
        def decorator(func: Callable) -> Callable:
            # 함수 시그니처 분석
            sig = inspect.signature(func)
            parameters = []
            
            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue
                    
                param_type = "Any"
                if param.annotation != inspect.Parameter.empty:
                    param_type = str(param.annotation)
                
                required = param.default == inspect.Parameter.empty
                default = None if required else param.default
                
                parameters.append(ToolParameter(
                    name=param_name,
                    type=param_type,
                    description=f"Parameter {param_name}",
                    required=required,
                    default=default
                ))
            
            # 도구 생성 및 등록
            tool = Tool(
                name=name,
                description=description,
                category=category,
                function=func,
                parameters=parameters,
                returns=str(sig.return_annotation) if sig.return_annotation != inspect.Parameter.empty else "Any"
            )
            
            self.register_tool(tool)
            
            @wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)
            
            return wrapper
        
        return decorator
    
    async def use_tool(self, tool_name: str, **params) -> ToolResult:
        """도구 사용"""
        import time
        start_time = time.time()
        
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' not found"
            )
        
        logger.debug(f"Using tool: {tool_name} with params: {params}")
        
        try:
            # 도구 실행
            result = await tool.execute(**params)
            
            # 실행 시간 설정
            execution_time = time.time() - start_time
            result.execution_time = execution_time
            
            # 통계 업데이트
            self.execution_count += 1
            self.total_execution_time += execution_time
            
            # 히스토리에 추가
            self.registry.execution_history.append(result)
            
            logger.info(f"Tool {tool_name} executed successfully in {execution_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Error using tool {tool_name}: {e}")
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time
            )
            self.registry.execution_history.append(result)
            return result
    
    def get_available_tools(self) -> List[Tool]:
        """사용 가능한 도구 목록"""
        return list(self.registry.tools.values())
    
    def get_tools_by_category(self, category: ToolCategory) -> List[Tool]:
        """카테고리별 도구 목록"""
        return self.registry.get_tools_by_category(category)
    
    def find_tools_for_task(self, task_description: str) -> List[Tool]:
        """작업에 적합한 도구 찾기"""
        task_lower = task_description.lower()
        suitable_tools = []
        
        for tool in self.registry.tools.values():
            # 도구 이름이나 설명에 관련 키워드가 있는지 확인
            if any(keyword in task_lower for keyword in [tool.name.lower(), 
                                                         tool.description.lower()]):
                suitable_tools.append(tool)
            # 카테고리 기반 매칭
            elif "계산" in task_lower and tool.category == ToolCategory.CALCULATION:
                suitable_tools.append(tool)
            elif "텍스트" in task_lower and tool.category == ToolCategory.TEXT_ANALYSIS:
                suitable_tools.append(tool)
            elif "데이터" in task_lower and tool.category == ToolCategory.DATA_PROCESSING:
                suitable_tools.append(tool)
        
        return suitable_tools
    
    def get_statistics(self) -> Dict[str, Any]:
        """도구 사용 통계"""
        avg_execution_time = (self.total_execution_time / self.execution_count 
                             if self.execution_count > 0 else 0)
        
        # 도구별 사용 횟수
        tool_usage = {}
        for result in self.registry.execution_history:
            tool_usage[result.tool_name] = tool_usage.get(result.tool_name, 0) + 1
        
        return {
            "total_tools": len(self.registry.tools),
            "total_executions": self.execution_count,
            "total_execution_time": self.total_execution_time,
            "average_execution_time": avg_execution_time,
            "tool_usage": tool_usage,
            "categories": {cat.value: len(tools) for cat, tools in self.registry.categories.items()}
        }
    
    def clear_history(self):
        """실행 히스토리 초기화"""
        self.registry.execution_history.clear()
        logger.info("Tool execution history cleared")


def tool_decorator(name: str, description: str, category: ToolCategory = ToolCategory.CUSTOM):
    """
    함수를 도구로 변환하는 데코레이터
    
    사용 예:
    @tool_decorator("my_tool", "My custom tool", ToolCategory.CUSTOM)
    async def my_function(param1: str, param2: int = 10) -> str:
        return f"Result: {param1} - {param2}"
    """
    def decorator(func: Callable) -> Tool:
        # 함수 시그니처 분석
        sig = inspect.signature(func)
        parameters = []
        
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
                
            param_type = "Any"
            if param.annotation != inspect.Parameter.empty:
                param_type = str(param.annotation)
            
            required = param.default == inspect.Parameter.empty
            default = None if required else param.default
            
            parameters.append(ToolParameter(
                name=param_name,
                type=param_type,
                description=f"Parameter {param_name}",
                required=required,
                default=default
            ))
        
        # 도구 생성
        tool = Tool(
            name=name,
            description=description,
            category=category,
            function=func,
            parameters=parameters,
            returns=str(sig.return_annotation) if sig.return_annotation != inspect.Parameter.empty else "Any"
        )
        
        return tool
    
    return decorator


# math 모듈 import (계산기 도구용)
try:
    import math
except ImportError:
    pass