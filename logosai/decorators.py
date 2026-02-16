"""
LogosAI 에이전트 개발용 고급 데코레이터

에이전트 개발을 더욱 간소화하는 고급 데코레이터들을 제공합니다.
"""

import re
import inspect
from typing import Dict, Any, Optional, List, Union, Callable, Type, get_type_hints
from functools import wraps
from dataclasses import dataclass
from loguru import logger

from .conversational_agent import (
    ConversationalAgent, ParameterDefinition, VisualizationConfig
)
from .agent_types import AgentType


@dataclass
class ValidationRule:
    """파라미터 검증 규칙"""
    rule_type: str  # "regex", "range", "choices", "length", "custom"
    rule_value: Any
    error_message: str


def parameter(name: str,
             description: str,
             required: bool = True,
             parameter_type: str = "string",
             default_value: Any = None,
             validation: Optional[Union[str, ValidationRule, List[ValidationRule]]] = None,
             collection_prompt: Optional[str] = None):
    """고급 파라미터 정의 데코레이터
    
    Args:
        name: 파라미터 이름
        description: 파라미터 설명
        required: 필수 여부
        parameter_type: 파라미터 타입
        default_value: 기본값
        validation: 검증 규칙
        collection_prompt: 수집용 프롬프트
    
    Usage:
        @parameter("location", "위치 정보", validation="^[가-힣]+$")
        @parameter("count", "개수", parameter_type="number", validation=ValidationRule("range", (1, 100), "1-100 사이의 값"))
        class MyAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        # 검증 규칙 처리
        validation_rules = None
        if validation:
            if isinstance(validation, str):
                # 정규식 패턴
                validation_rules = [ValidationRule(
                    rule_type="regex",
                    rule_value=validation,
                    error_message=f"{name}의 형식이 올바르지 않습니다"
                )]
            elif isinstance(validation, ValidationRule):
                validation_rules = [validation]
            elif isinstance(validation, list):
                validation_rules = validation
        
        # 파라미터 정의 생성
        param_def = ParameterDefinition(
            name=name,
            description=description,
            required=required,
            parameter_type=parameter_type,
            default_value=default_value,
            validation_rules={
                "rules": [r.__dict__ for r in validation_rules] if validation_rules else []
            },
            collection_prompt=collection_prompt
        )
        
        # 클래스 초기화 수정
        original_init = cls.__init__
        
        @wraps(original_init)
        def new_init(self, *args, **kwargs):
            # 파라미터 추가
            kwargs.setdefault('parameters', {})[name] = param_def
            original_init(self, *args, **kwargs)
        
        cls.__init__ = new_init
        return cls
    
    return decorator


def auto_validate():
    """자동 검증 데코레이터
    
    execute_with_parameters 메서드 실행 전 자동으로 파라미터를 검증합니다.
    
    Usage:
        @auto_validate()
        class MyAgent(ConversationalAgent):
            async def execute_with_parameters(self, query, parameters):
                # 여기서 parameters는 이미 검증됨
                pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        original_execute = cls.execute_with_parameters
        
        @wraps(original_execute)
        async def validated_execute(self, query: str, parameters: Dict[str, Any]):
            # 파라미터 검증 실행
            validated_params = await self._validate_parameters(parameters)
            return await original_execute(self, query, validated_params)
        
        cls.execute_with_parameters = validated_execute
        
        # 검증 메서드 추가
        async def _validate_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
            """파라미터 검증"""
            validated = parameters.copy()
            errors = []
            
            for param_name, param_def in self.parameters.items():
                value = parameters.get(param_name)
                
                # 필수 파라미터 확인
                if param_def.required and value is None:
                    errors.append(f"필수 파라미터 누락: {param_name}")
                    continue
                
                # 값이 있는 경우 검증 규칙 적용
                if value is not None and param_def.validation_rules:
                    validation_errors = await self._apply_validation_rules(
                        param_name, value, param_def.validation_rules.get("rules", [])
                    )
                    errors.extend(validation_errors)
            
            if errors:
                raise ValueError(f"파라미터 검증 실패: {'; '.join(errors)}")
            
            return validated
        
        async def _apply_validation_rules(self, param_name: str, value: Any, rules: List[Dict[str, Any]]) -> List[str]:
            """검증 규칙 적용"""
            errors = []
            
            for rule in rules:
                rule_type = rule.get("rule_type")
                rule_value = rule.get("rule_value")
                error_message = rule.get("error_message", f"{param_name} 검증 실패")
                
                try:
                    if rule_type == "regex":
                        if not re.match(rule_value, str(value)):
                            errors.append(error_message)
                    
                    elif rule_type == "range":
                        min_val, max_val = rule_value
                        if not (min_val <= float(value) <= max_val):
                            errors.append(error_message)
                    
                    elif rule_type == "choices":
                        if value not in rule_value:
                            errors.append(error_message)
                    
                    elif rule_type == "length":
                        min_len, max_len = rule_value
                        if not (min_len <= len(str(value)) <= max_len):
                            errors.append(error_message)
                    
                    elif rule_type == "custom":
                        # 커스텀 검증 함수
                        if callable(rule_value) and not rule_value(value):
                            errors.append(error_message)
                
                except Exception as e:
                    logger.warning(f"검증 규칙 적용 실패: {e}")
                    errors.append(f"{param_name} 검증 중 오류 발생")
            
            return errors
        
        cls._validate_parameters = _validate_parameters
        cls._apply_validation_rules = _apply_validation_rules
        
        return cls
    
    return decorator


def smart_caching(cache_key_func: Optional[Callable] = None,
                 ttl_seconds: int = 300,
                 max_size: int = 100):
    """스마트 캐싱 데코레이터
    
    에이전트 실행 결과를 지능적으로 캐싱합니다.
    
    Args:
        cache_key_func: 캐시 키 생성 함수
        ttl_seconds: TTL (초)
        max_size: 최대 캐시 크기
    
    Usage:
        @smart_caching(ttl_seconds=600)
        class WeatherAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        cache_storage = {}
        cache_timestamps = {}
        
        def default_cache_key(query: str, parameters: Dict[str, Any]) -> str:
            """기본 캐시 키 생성"""
            import hashlib
            key_data = f"{query}:{sorted(parameters.items())}"
            return hashlib.md5(key_data.encode()).hexdigest()
        
        key_func = cache_key_func or default_cache_key
        
        original_execute = cls.execute_with_parameters
        
        @wraps(original_execute)
        async def cached_execute(self, query: str, parameters: Dict[str, Any]):
            cache_key = key_func(query, parameters)
            
            # 캐시 확인
            if cache_key in cache_storage:
                import time
                if time.time() - cache_timestamps[cache_key] < ttl_seconds:
                    logger.info(f"캐시 히트: {cache_key}")
                    return cache_storage[cache_key]
                else:
                    # 만료된 캐시 제거
                    del cache_storage[cache_key]
                    del cache_timestamps[cache_key]
            
            # 실행 및 캐시 저장
            result = await original_execute(self, query, parameters)
            
            # 캐시 크기 관리
            if len(cache_storage) >= max_size:
                # 가장 오래된 항목 제거
                oldest_key = min(cache_timestamps.keys(), key=lambda k: cache_timestamps[k])
                del cache_storage[oldest_key]
                del cache_timestamps[oldest_key]
            
            import time
            cache_storage[cache_key] = result
            cache_timestamps[cache_key] = time.time()
            
            logger.info(f"캐시 저장: {cache_key}")
            return result
        
        cls.execute_with_parameters = cached_execute
        return cls
    
    return decorator


def retry_on_failure(max_retries: int = 3,
                    delay_seconds: float = 1.0,
                    exponential_backoff: bool = True,
                    retry_exceptions: Optional[List[Type[Exception]]] = None):
    """실패 시 재시도 데코레이터
    
    Args:
        max_retries: 최대 재시도 횟수
        delay_seconds: 재시도 간격 (초)
        exponential_backoff: 지수 백오프 사용 여부
        retry_exceptions: 재시도할 예외 타입들
    
    Usage:
        @retry_on_failure(max_retries=3, exponential_backoff=True)
        class APIAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        import asyncio
        
        if retry_exceptions is None:
            exceptions_to_retry = (ConnectionError, TimeoutError)
        else:
            exceptions_to_retry = tuple(retry_exceptions)
        
        original_execute = cls.execute_with_parameters
        
        @wraps(original_execute)
        async def retry_execute(self, query: str, parameters: Dict[str, Any]):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await original_execute(self, query, parameters)
                
                except exceptions_to_retry as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        # 재시도 지연
                        if exponential_backoff:
                            delay = delay_seconds * (2 ** attempt)
                        else:
                            delay = delay_seconds
                        
                        logger.warning(f"실행 실패 (시도 {attempt + 1}/{max_retries + 1}), {delay}초 후 재시도: {e}")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"최대 재시도 횟수 초과: {e}")
                        raise
                
                except Exception as e:
                    # 재시도하지 않을 예외
                    logger.error(f"재시도하지 않을 예외 발생: {e}")
                    raise
            
            # 이 부분에 도달하면 모든 재시도 실패
            raise last_exception
        
        cls.execute_with_parameters = retry_execute
        return cls
    
    return decorator


def rate_limit(requests_per_minute: int = 60,
              per_user: bool = True):
    """요청 속도 제한 데코레이터
    
    Args:
        requests_per_minute: 분당 요청 제한
        per_user: 사용자별 제한 여부
    
    Usage:
        @rate_limit(requests_per_minute=30, per_user=True)
        class ExpensiveAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        import time
        from collections import defaultdict, deque
        
        request_history = defaultdict(deque)
        
        original_process = cls.process_with_conversation
        
        @wraps(original_process)
        async def rate_limited_process(self, request, websocket_handler=None):
            # 키 결정 (사용자별 또는 전체)
            if per_user and hasattr(self, 'conversation_context') and self.conversation_context:
                key = self.conversation_context.user_id or 'anonymous'
            else:
                key = 'global'
            
            current_time = time.time()
            history = request_history[key]
            
            # 1분 이전 기록 제거
            while history and current_time - history[0] > 60:
                history.popleft()
            
            # 요청 제한 확인
            if len(history) >= requests_per_minute:
                raise Exception(f"요청 속도 제한 초과: 분당 {requests_per_minute}회 제한")
            
            # 현재 요청 기록
            history.append(current_time)
            
            return await original_process(self, request, websocket_handler)
        
        cls.process_with_conversation = rate_limited_process
        return cls
    
    return decorator


def type_aware_parameters():
    """타입 힌트 기반 자동 파라미터 정의
    
    execute_with_parameters 메서드의 타입 힌트를 분석하여
    자동으로 파라미터를 정의합니다.
    
    Usage:
        @type_aware_parameters()
        class MyAgent(ConversationalAgent):
            async def execute_with_parameters(self, 
                                            query: str, 
                                            parameters: Dict[str, Any],
                                            location: str,
                                            count: int = 10,
                                            enabled: bool = True) -> Dict[str, Any]:
                # location, count, enabled가 자동으로 파라미터로 정의됨
                pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        # execute_with_parameters 메서드의 타입 힌트 분석
        if hasattr(cls, 'execute_with_parameters'):
            execute_method = cls.execute_with_parameters
            
            # 타입 힌트 가져오기
            try:
                type_hints = get_type_hints(execute_method)
                signature = inspect.signature(execute_method)
                
                # 파라미터 정의 생성
                auto_parameters = {}
                
                for param_name, param in signature.parameters.items():
                    # 기본 파라미터들 제외
                    if param_name in ['self', 'query', 'parameters']:
                        continue
                    
                    # 타입 정보 추출
                    param_type = type_hints.get(param_name, str)
                    
                    # 기본값 확인
                    has_default = param.default != inspect.Parameter.empty
                    default_value = param.default if has_default else None
                    
                    # 타입을 문자열로 변환
                    if param_type == str:
                        type_str = "string"
                    elif param_type == int:
                        type_str = "number"
                    elif param_type == float:
                        type_str = "number"
                    elif param_type == bool:
                        type_str = "boolean"
                    else:
                        type_str = "string"  # 기본값
                    
                    # 파라미터 정의 생성
                    auto_parameters[param_name] = ParameterDefinition(
                        name=param_name,
                        description=f"Auto-generated parameter: {param_name}",
                        required=not has_default,
                        parameter_type=type_str,
                        default_value=default_value
                    )
                
                # 클래스 초기화 수정
                original_init = cls.__init__
                
                @wraps(original_init)
                def new_init(self, *args, **kwargs):
                    # 자동 생성된 파라미터 추가
                    existing_params = kwargs.setdefault('parameters', {})
                    for name, param_def in auto_parameters.items():
                        if name not in existing_params:
                            existing_params[name] = param_def
                    
                    original_init(self, *args, **kwargs)
                
                cls.__init__ = new_init
                
                logger.info(f"자동 파라미터 정의 완료: {list(auto_parameters.keys())}")
                
            except Exception as e:
                logger.warning(f"타입 힌트 분석 실패: {e}")
        
        return cls
    
    return decorator


def monitoring(enable_metrics: bool = True,
              enable_logging: bool = True,
              log_level: str = "INFO"):
    """모니터링 데코레이터
    
    에이전트 실행을 모니터링하고 메트릭을 수집합니다.
    
    Args:
        enable_metrics: 메트릭 수집 활성화
        enable_logging: 로깅 활성화
        log_level: 로그 레벨
    
    Usage:
        @monitoring(enable_metrics=True, log_level="DEBUG")
        class MyAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        import time
        from collections import defaultdict
        
        # 메트릭 저장소
        metrics = defaultdict(list)
        
        original_execute = cls.execute_with_parameters
        
        @wraps(original_execute)
        async def monitored_execute(self, query: str, parameters: Dict[str, Any]):
            start_time = time.time()
            agent_name = self.config.name if hasattr(self, 'config') else cls.__name__
            
            if enable_logging:
                logger.log(log_level, f"[{agent_name}] 실행 시작: {query}")
            
            try:
                result = await original_execute(self, query, parameters)
                
                # 성공 메트릭
                execution_time = time.time() - start_time
                if enable_metrics:
                    metrics[f"{agent_name}_execution_time"].append(execution_time)
                    metrics[f"{agent_name}_success_count"].append(1)
                
                if enable_logging:
                    logger.log(log_level, f"[{agent_name}] 실행 완료: {execution_time:.2f}초")
                
                return result
                
            except Exception as e:
                # 실패 메트릭
                execution_time = time.time() - start_time
                if enable_metrics:
                    metrics[f"{agent_name}_execution_time"].append(execution_time)
                    metrics[f"{agent_name}_error_count"].append(1)
                
                if enable_logging:
                    logger.error(f"[{agent_name}] 실행 실패: {e} ({execution_time:.2f}초)")
                
                raise
        
        # 메트릭 조회 메서드 추가
        def get_metrics(self) -> Dict[str, Any]:
            """메트릭 조회"""
            agent_name = self.config.name if hasattr(self, 'config') else cls.__name__
            
            result = {}
            for key, values in metrics.items():
                if agent_name in key:
                    if 'execution_time' in key:
                        result[key] = {
                            'count': len(values),
                            'avg': sum(values) / len(values) if values else 0,
                            'min': min(values) if values else 0,
                            'max': max(values) if values else 0
                        }
                    else:
                        result[key] = sum(values)
            
            return result
        
        cls.execute_with_parameters = monitored_execute
        cls.get_metrics = get_metrics
        
        return cls
    
    return decorator


# 조합 데코레이터
def production_ready(requests_per_minute: int = 60,
                    cache_ttl: int = 300,
                    max_retries: int = 3,
                    enable_monitoring: bool = True):
    """프로덕션 준비 데코레이터 (여러 데코레이터 조합)
    
    Args:
        requests_per_minute: 분당 요청 제한
        cache_ttl: 캐시 TTL
        max_retries: 최대 재시도 횟수
        enable_monitoring: 모니터링 활성화
    
    Usage:
        @production_ready(requests_per_minute=120, cache_ttl=600)
        class ProductionAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        # 여러 데코레이터 적용
        cls = rate_limit(requests_per_minute=requests_per_minute)(cls)
        cls = smart_caching(ttl_seconds=cache_ttl)(cls)
        cls = retry_on_failure(max_retries=max_retries)(cls)
        cls = auto_validate()(cls)
        
        if enable_monitoring:
            cls = monitoring(enable_metrics=True, enable_logging=True)(cls)
        
        return cls
    
    return decorator


# 사용 예제
if __name__ == "__main__":
    # 예제: 고급 데코레이터 사용
    
    @production_ready(requests_per_minute=120, cache_ttl=600)
    @parameter("location", "위치 정보", validation="^[가-힣a-zA-Z\\s]+$")
    @parameter("days", "일수", parameter_type="number", 
              validation=ValidationRule("range", (1, 7), "1-7일 사이의 값을 입력하세요"))
    @type_aware_parameters()
    class AdvancedWeatherAgent(ConversationalAgent):
        
        async def execute_with_parameters(self, 
                                        query: str, 
                                        parameters: Dict[str, Any],
                                        temperature_unit: str = "celsius") -> Dict[str, Any]:
            """고급 날씨 에이전트 실행"""
            return {
                "location": parameters.get("location"),
                "days": parameters.get("days"),
                "temperature_unit": temperature_unit,
                "weather_data": "예제 날씨 데이터"
            }

    logger.info("고급 데코레이터 예제 정의 완료")