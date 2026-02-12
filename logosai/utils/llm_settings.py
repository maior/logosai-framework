"""
LLM 설정 관리를 위한 유틸리티 모듈

LLM 모델 및 설정을 쉽게 관리할 수 있는 기능을 제공합니다.
"""

import os
import logging
from typing import Dict, Any, List, Optional, Union, Tuple

# 로거 설정
logger = logging.getLogger(__name__)

# 설정 로더 임포트
from .config_loader import (
    get_config_loader,
    load_config,
    get_config_value,
    set_config_value,
    register_custom_config
)


def get_default_llm_settings() -> Dict[str, Any]:
    """기본 LLM 설정 가져오기
    
    Returns:
        기본 LLM 설정
    """
    config = load_config("sdk_config")
    return config.get("llm", {}).get("default_settings", {})


def get_provider_settings(provider: str = None) -> Dict[str, Any]:
    """LLM 제공자 설정 가져오기
    
    Args:
        provider: 제공자 이름 (None이면 기본 제공자 사용)
        
    Returns:
        LLM 제공자 설정
    """
    config = load_config("sdk_config")
    llm_config = config.get("llm", {})
    
    # 제공자가 지정되지 않으면 기본 제공자 사용
    if not provider:
        provider = llm_config.get("default_provider", "openai")
        
    providers = llm_config.get("providers", {})
    return providers.get(provider, {})


def get_api_key(provider: str = None) -> Optional[str]:
    """LLM 제공자의 API 키 가져오기
    
    Args:
        provider: 제공자 이름 (None이면 기본 제공자 사용)
        
    Returns:
        API 키 (환경 변수에서 가져옴)
    """
    provider_settings = get_provider_settings(provider)
    api_key_env = provider_settings.get("api_key_env")
    
    if not api_key_env:
        logger.warning(f"LLM 제공자 {provider}의 API 키 환경 변수가 설정되지 않았습니다.")
        return None
        
    api_key = os.environ.get(api_key_env)
    
    if not api_key:
        logger.warning(f"환경 변수 {api_key_env}가 설정되지 않았습니다.")
        
    return api_key


def register_provider(
    provider_name: str,
    api_key_env: str,
    default_model: str,
    fallback_model: Optional[str] = None,
    api_base_env: Optional[str] = None,
    organization_env: Optional[str] = None
) -> bool:
    """LLM 제공자 등록
    
    Args:
        provider_name: 제공자 이름
        api_key_env: API 키 환경 변수 이름
        default_model: 기본 모델 이름
        fallback_model: 폴백 모델 이름 (선택적)
        api_base_env: API 기본 URL 환경 변수 이름 (선택적)
        organization_env: 조직 ID 환경 변수 이름 (선택적)
        
    Returns:
        등록 성공 여부
    """
    try:
        # 설정 로드
        config = load_config("sdk_config")
        
        # llm 섹션이 없으면 생성
        if "llm" not in config:
            config["llm"] = {
                "default_provider": "openai",
                "default_model": "gpt-4.1-mini",
                "default_settings": {
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "max_tokens": 2000,
                    "streaming": True,
                    "timeout": 60
                },
                "providers": {}
            }
        
        # providers 섹션이 없으면 생성
        if "providers" not in config["llm"]:
            config["llm"]["providers"] = {}
            
        # 제공자 정보 추가
        provider_settings = {
            "api_key_env": api_key_env,
            "default_model": default_model
        }
        
        if fallback_model:
            provider_settings["fallback_model"] = fallback_model
            
        if api_base_env:
            provider_settings["api_base_env"] = api_base_env
            
        if organization_env:
            provider_settings["organization_env"] = organization_env
            
        config["llm"]["providers"][provider_name] = provider_settings
        
        # 설정 등록 (메모리에만 저장)
        register_custom_config("sdk_config", config)
        
        logger.info(f"LLM 제공자 등록 완료: {provider_name}")
        return True
    except Exception as e:
        logger.error(f"LLM 제공자 등록 중 오류: {str(e)}")
        return False


def set_default_provider(provider_name: str) -> bool:
    """기본 LLM 제공자 설정
    
    Args:
        provider_name: 제공자 이름
        
    Returns:
        설정 성공 여부
    """
    try:
        # 설정 로드
        config = load_config("sdk_config")
        
        # 제공자가 존재하는지 확인
        providers = config.get("llm", {}).get("providers", {})
        if provider_name not in providers:
            logger.warning(f"LLM 제공자 {provider_name}가 등록되지 않았습니다.")
            return False
            
        # 기본 제공자 설정
        set_config_value("sdk_config", "llm.default_provider", provider_name, auto_save=False)
        
        logger.info(f"기본 LLM 제공자를 {provider_name}로 설정했습니다.")
        return True
    except Exception as e:
        logger.error(f"기본 LLM 제공자 설정 중 오류: {str(e)}")
        return False


def update_default_llm_settings(
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
    streaming: Optional[bool] = None,
    timeout: Optional[int] = None,
    other_settings: Optional[Dict[str, Any]] = None
) -> bool:
    """기본 LLM 설정 업데이트
    
    Args:
        temperature: 온도 (창의성 조절)
        top_p: Top-p 샘플링
        max_tokens: 최대 토큰 수
        streaming: 스트리밍 활성화 여부
        timeout: 타임아웃 (초)
        other_settings: 기타 설정
        
    Returns:
        업데이트 성공 여부
    """
    try:
        # 현재 설정 로드
        current_settings = get_default_llm_settings()
        
        # 새 설정 병합
        new_settings = current_settings.copy()
        
        if temperature is not None:
            new_settings["temperature"] = temperature
            
        if top_p is not None:
            new_settings["top_p"] = top_p
            
        if max_tokens is not None:
            new_settings["max_tokens"] = max_tokens
            
        if streaming is not None:
            new_settings["streaming"] = streaming
            
        if timeout is not None:
            new_settings["timeout"] = timeout
            
        if other_settings:
            new_settings.update(other_settings)
            
        # 설정 업데이트
        set_config_value("sdk_config", "llm.default_settings", new_settings, auto_save=False)
        
        logger.info("기본 LLM 설정이 업데이트되었습니다.")
        return True
    except Exception as e:
        logger.error(f"LLM 설정 업데이트 중 오류: {str(e)}")
        return False


def get_model_info() -> Tuple[str, Dict[str, Any]]:
    """현재 LLM 모델 정보 가져오기
    
    Returns:
        기본 모델 이름과 설정 튜플
    """
    config = load_config("sdk_config")
    llm_config = config.get("llm", {})
    
    # 기본 제공자 확인
    provider = llm_config.get("default_provider", "openai")
    
    # 제공자 설정 가져오기
    provider_settings = get_provider_settings(provider)
    
    # 기본 모델 확인
    model = provider_settings.get("default_model") or llm_config.get("default_model", "gpt-4-turbo")
    
    # 모델 설정 가져오기
    settings = llm_config.get("default_settings", {})
    
    return model, settings


def get_available_llm_providers() -> List[Dict[str, Any]]:
    """사용 가능한 LLM 제공자 목록 가져오기
    
    Returns:
        제공자 목록 (이름, 기본 모델 등)
    """
    config = load_config("sdk_config")
    llm_config = config.get("llm", {})
    providers = llm_config.get("providers", {})
    
    result = []
    for name, settings in providers.items():
        result.append({
            "name": name,
            "default_model": settings.get("default_model", ""),
            "api_key_available": os.environ.get(settings.get("api_key_env", "")) is not None,
            "is_default": name == llm_config.get("default_provider")
        })
        
    return result 