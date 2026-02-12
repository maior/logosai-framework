"""
설정 파일 로더 모듈

JSON 설정 파일을 로드하고 관리하기 위한 유틸리티 모듈입니다.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Union, TypeVar, cast
from pathlib import Path
from functools import lru_cache
from loguru import logger


# 타입 정의
T = TypeVar('T')
ConfigDict = Dict[str, Any]


class ConfigLoader:
    """설정 파일 로더 클래스
    
    JSON 설정 파일을 로드하고 관리하기 위한 싱글톤 클래스
    """
    _instance = None
    _configs: Dict[str, ConfigDict] = {}
    _config_dir: str = ""
    _user_config_dir: Optional[str] = None
    _custom_configs: Dict[str, ConfigDict] = {}
    
    def __new__(cls, *args, **kwargs):
        """싱글톤 패턴 구현"""
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_dir: Optional[str] = None, user_config_dir: Optional[str] = None):
        """설정 로더 초기화
        
        Args:
            config_dir: 설정 파일이 위치한 디렉토리 경로
            user_config_dir: 사용자 정의 설정 파일이 위치한 디렉토리 경로
        """
        if self._initialized:
            return
            
        self._config_dir = self._get_config_dir(config_dir)
        self._user_config_dir = user_config_dir
        self._configs = {}
        self._custom_configs = {}
        self._initialized = True
        
        logger.debug(f"ConfigLoader 초기화 완료: {self._config_dir}, 사용자 설정: {self._user_config_dir}")
    
    def _get_config_dir(self, config_dir: Optional[str] = None) -> str:
        """설정 디렉토리 경로 가져오기
        
        Args:
            config_dir: 외부에서 지정한 설정 디렉토리 경로
            
        Returns:
            설정 디렉토리 경로
        """
        if config_dir:
            return config_dir
            
        # 패키지 설정 디렉토리 기본 경로
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_config_dir = os.path.join(package_dir, "config")
        
        # 환경 변수로 설정 디렉토리 지정 가능
        env_config_dir = os.environ.get("LOGOSAI_CONFIG_DIR")
        
        return env_config_dir or default_config_dir
    
    def set_user_config_dir(self, user_config_dir: str) -> bool:
        """사용자 정의 설정 디렉토리 설정
        
        Args:
            user_config_dir: 사용자 정의 설정 디렉토리 경로
            
        Returns:
            성공 여부
        """
        # 디렉토리 존재 확인
        if not os.path.exists(user_config_dir):
            logger.warning(f"사용자 설정 디렉토리가 존재하지 않습니다: {user_config_dir}")
            try:
                os.makedirs(user_config_dir, exist_ok=True)
                logger.info(f"사용자 설정 디렉토리를 생성했습니다: {user_config_dir}")
            except Exception as e:
                logger.error(f"사용자 설정 디렉토리 생성 실패: {str(e)}")
                return False
        
        self._user_config_dir = user_config_dir
        logger.info(f"사용자 설정 디렉토리를 설정했습니다: {user_config_dir}")
        
        # 캐시 초기화
        self._configs = {}
        
        return True
        
    def load_config(self, config_name: str, reload: bool = False) -> ConfigDict:
        """설정 파일 로드
        
        Args:
            config_name: 설정 파일 이름 (확장자 없이)
            reload: 캐시된 설정을 무시하고 다시 로드할지 여부
            
        Returns:
            설정 데이터 딕셔너리
        """
        # 사용자 정의 메모리 설정이 있는 경우
        if config_name in self._custom_configs and not reload:
            return self._custom_configs[config_name]
            
        # 이미 로드된 설정이 있고, 강제 리로드가 아니면 캐시 반환
        if not reload and config_name in self._configs:
            return self._configs[config_name]
            
        # .json 확장자 추가
        if not config_name.endswith('.json'):
            config_file = f"{config_name}.json"
        else:
            config_file = config_name
            config_name = config_name[:-5]  # .json 제거
            
        # 설정 파일 경로 확인 (사용자 정의 경로 우선)
        config_data = {}
        
        # 1. 사용자 정의 경로에서 파일 확인
        if self._user_config_dir:
            user_config_path = os.path.join(self._user_config_dir, config_file)
            if os.path.exists(user_config_path):
                try:
                    with open(user_config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    logger.debug(f"사용자 설정 파일 로드 완료: {user_config_path}")
                except Exception as e:
                    logger.error(f"사용자 설정 파일 로드 오류: {user_config_path} - {str(e)}")
        
        # 2. 기본 경로에서 파일 확인 (사용자 설정이 없거나 병합 필요)
        default_config_path = os.path.join(self._config_dir, config_file)
        if os.path.exists(default_config_path):
            try:
                with open(default_config_path, 'r', encoding='utf-8') as f:
                    default_config = json.load(f)
                    
                # 사용자 설정이 없으면 기본 설정 사용, 있으면 기본 설정 깊은 병합
                if not config_data:
                    config_data = default_config
                else:
                    # 기본 설정과 사용자 설정 병합 (깊은 병합)
                    config_data = self._deep_merge(default_config, config_data)
                    
                logger.debug(f"기본 설정 파일 로드 완료: {default_config_path}")
            except Exception as e:
                logger.error(f"기본 설정 파일 로드 오류: {default_config_path} - {str(e)}")
                if not config_data:  # 사용자 설정도 없는 경우
                    config_data = {}
        
        # 파일이 없거나 오류가 발생하면 빈 딕셔너리 반환
        if not config_data:
            logger.warning(f"설정 파일을 찾을 수 없거나 로드할 수 없습니다: {config_name}")
            self._configs[config_name] = {}
            return {}
        
        # 캐시에 저장
        self._configs[config_name] = config_data
        logger.debug(f"설정 파일 로드 완료: {config_name}")
        
        return config_data
    
    def _deep_merge(self, dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
        """두 딕셔너리를 깊게 병합
        
        Args:
            dict1: 기본 딕셔너리
            dict2: 우선 적용할 딕셔너리
            
        Returns:
            병합된 딕셔너리
        """
        result = dict1.copy()
        
        for key, value in dict2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
                
        return result
    
    def register_custom_config(self, config_name: str, config_data: ConfigDict) -> bool:
        """사용자 정의 설정 등록 (메모리에만 저장)
        
        Args:
            config_name: 설정 이름
            config_data: 설정 데이터
            
        Returns:
            성공 여부
        """
        try:
            # 기존 설정이 있는 경우 병합
            if config_name in self._configs:
                existing_config = self._configs[config_name]
                merged_config = self._deep_merge(existing_config, config_data)
                self._custom_configs[config_name] = merged_config
            else:
                self._custom_configs[config_name] = config_data
            
            logger.info(f"사용자 정의 설정 등록 완료: {config_name}")
            return True
        except Exception as e:
            logger.error(f"사용자 정의 설정 등록 오류: {config_name} - {str(e)}")
            return False
            
    def save_config(self, config_name: str, config_data: ConfigDict, to_user_config: bool = True) -> bool:
        """설정 파일 저장
        
        Args:
            config_name: 설정 파일 이름 (확장자 없이)
            config_data: 저장할 설정 데이터
            to_user_config: 사용자 설정 디렉토리에 저장할지 여부
            
        Returns:
            저장 성공 여부
        """
        # .json 확장자 추가
        if not config_name.endswith('.json'):
            config_file = f"{config_name}.json"
        else:
            config_file = config_name
            config_name = config_name[:-5]  # .json 제거
            
        # 저장 경로 결정
        if to_user_config and self._user_config_dir:
            config_dir = self._user_config_dir
        else:
            config_dir = self._config_dir
            
        # 파일 경로 생성
        config_path = os.path.join(config_dir, config_file)
        
        try:
            # 디렉토리 확인 및 생성
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            
            # JSON 파일 저장
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
                
            # 캐시 갱신
            self._configs[config_name] = config_data
            
            # 사용자 정의 메모리 설정도 갱신
            if config_name in self._custom_configs:
                self._custom_configs[config_name] = config_data
                
            logger.debug(f"설정 파일 저장 완료: {config_path}")
            
            return True
        except Exception as e:
            logger.error(f"설정 파일 저장 오류: {config_name} - {str(e)}")
            return False
            
    def get_config_value(self, config_name: str, path: str, default: T = None) -> Union[Any, T]:
        """설정 값 가져오기
        
        Args:
            config_name: 설정 파일 이름
            path: 설정 경로 (예: "logging.level")
            default: 값이 없을 경우 반환할 기본값
            
        Returns:
            설정 값 또는 기본값
        """
        # 설정 로드
        config = self.load_config(config_name)
        
        # 빈 설정이면 기본값 반환
        if not config:
            return default
            
        # 경로 분할
        path_parts = path.split('.')
        
        # 경로 따라가기
        current = config
        for part in path_parts:
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
            
        return current
        
    def set_config_value(self, config_name: str, path: str, value: Any, auto_save: bool = True, to_user_config: bool = True) -> bool:
        """설정 값 설정
        
        Args:
            config_name: 설정 파일 이름
            path: 설정 경로 (예: "logging.level")
            value: 설정할 값
            auto_save: 자동 저장 여부
            to_user_config: 사용자 설정에 저장할지 여부
            
        Returns:
            성공 여부
        """
        # 설정 로드
        config = self.load_config(config_name)
        
        # 빈 설정이면 새로 생성
        if not config:
            config = {}
            
        # 경로 분할
        path_parts = path.split('.')
        
        # 마지막 부분을 제외한 경로 생성
        current = config
        for i, part in enumerate(path_parts[:-1]):
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
            
        # 값 설정
        current[path_parts[-1]] = value
        
        # 캐시 갱신
        self._configs[config_name] = config
        
        # 메모리 사용자 정의 설정이 있으면 갱신
        if config_name in self._custom_configs:
            temp_config = self._custom_configs[config_name].copy()
            
            # 경로를 따라 딕셔너리 생성
            current = temp_config
            for i, part in enumerate(path_parts[:-1]):
                if part not in current:
                    current[part] = {}
                current = current[part]
                
            # 값 설정
            current[path_parts[-1]] = value
            self._custom_configs[config_name] = temp_config
        
        # 자동 저장
        if auto_save:
            return self.save_config(config_name, config, to_user_config)
            
        return True
        
    def list_configs(self) -> List[str]:
        """사용 가능한 설정 파일 목록 반환
        
        Returns:
            설정 파일 이름 목록
        """
        configs = set()
        
        # 기본 설정 디렉토리에서 파일 목록 가져오기
        try:
            if os.path.exists(self._config_dir):
                configs.update([f[:-5] for f in os.listdir(self._config_dir) if f.endswith('.json')])
        except Exception as e:
            logger.error(f"기본 설정 파일 목록 조회 오류: {str(e)}")
        
        # 사용자 설정 디렉토리에서 파일 목록 가져오기
        try:
            if self._user_config_dir and os.path.exists(self._user_config_dir):
                configs.update([f[:-5] for f in os.listdir(self._user_config_dir) if f.endswith('.json')])
        except Exception as e:
            logger.error(f"사용자 설정 파일 목록 조회 오류: {str(e)}")
        
        # 메모리 내 사용자 정의 설정 추가
        configs.update(self._custom_configs.keys())
        
        return list(configs)
    
    def reset_custom_configs(self) -> None:
        """사용자 정의 설정 초기화"""
        self._custom_configs = {}
        logger.info("사용자 정의 설정 초기화 완료")


# 싱글톤 인스턴스 가져오기
def get_config_loader(config_dir: Optional[str] = None, user_config_dir: Optional[str] = None) -> ConfigLoader:
    """설정 로더 인스턴스 가져오기
    
    Args:
        config_dir: 설정 파일 디렉토리 경로
        user_config_dir: 사용자 설정 파일 디렉토리 경로
        
    Returns:
        ConfigLoader 인스턴스
    """
    loader = ConfigLoader(config_dir, user_config_dir)
    return loader


# 편의 함수
def load_config(config_name: str, reload: bool = False) -> ConfigDict:
    """설정 파일 로드
    
    Args:
        config_name: 설정 파일 이름
        reload: 캐시된 설정을 무시하고 다시 로드할지 여부
        
    Returns:
        설정 데이터
    """
    return get_config_loader().load_config(config_name, reload)


def get_config_value(config_name: str, path: str, default: T = None) -> Union[Any, T]:
    """설정 값 가져오기
    
    Args:
        config_name: 설정 파일 이름
        path: 설정 경로
        default: 기본값
        
    Returns:
        설정 값
    """
    return get_config_loader().get_config_value(config_name, path, default)


def set_config_value(config_name: str, path: str, value: Any, auto_save: bool = True, to_user_config: bool = True) -> bool:
    """설정 값 설정
    
    Args:
        config_name: 설정 파일 이름
        path: 설정 경로
        value: 설정 값
        auto_save: 자동 저장 여부
        to_user_config: 사용자 설정에 저장할지 여부
        
    Returns:
        성공 여부
    """
    return get_config_loader().set_config_value(config_name, path, value, auto_save, to_user_config)


def register_custom_config(config_name: str, config_data: ConfigDict) -> bool:
    """사용자 정의 설정 등록
    
    Args:
        config_name: 설정 이름
        config_data: 설정 데이터
        
    Returns:
        성공 여부
    """
    return get_config_loader().register_custom_config(config_name, config_data)


def set_user_config_dir(user_config_dir: str) -> bool:
    """사용자 설정 디렉토리 설정
    
    Args:
        user_config_dir: 사용자 설정 디렉토리 경로
        
    Returns:
        성공 여부
    """
    return get_config_loader().set_user_config_dir(user_config_dir)


# 특정 설정 파일 로드 유틸리티 함수
def get_agent_type_config(agent_type: str) -> Dict[str, Any]:
    """에이전트 유형 설정 가져오기
    
    Args:
        agent_type: 에이전트 유형
        
    Returns:
        에이전트 유형 설정
    """
    config = load_config("agent_types")
    types = config.get("types", {})
    return types.get(agent_type.upper(), {})


def get_response_type_config(response_type: str) -> Dict[str, Any]:
    """응답 유형 설정 가져오기
    
    Args:
        response_type: 응답 유형
        
    Returns:
        응답 유형 설정
    """
    config = load_config("response_types")
    types = config.get("types", {})
    return types.get(response_type.upper(), {})


def get_agent_config_template(template_name: str) -> Dict[str, Any]:
    """에이전트 설정 템플릿 가져오기
    
    Args:
        template_name: 템플릿 이름
        
    Returns:
        에이전트 설정 템플릿
    """
    config = load_config("agent_config_templates")
    templates = config.get("templates", {})
    
    # 템플릿이 없으면 기본 설정 반환
    if template_name not in templates:
        return config.get("default", {})
        
    return templates.get(template_name, {})


def load_agent_types() -> Dict[str, Dict[str, Any]]:
    """에이전트 타입 설정 로드
    
    Returns:
        에이전트 타입 설정 딕셔너리
    """
    try:
        config_data = load_config("agents")
        if not config_data or not isinstance(config_data, dict):
            logger.error("에이전트 설정 파일이 비어있거나 올바른 형식이 아닙니다.")
            return {}
            
        agent_types = {}
        for agent_type, config in config_data.items():
            if isinstance(config, dict):
                agent_types[agent_type] = config
            
        return agent_types
        
    except Exception as e:
        logger.error(f"에이전트 설정 파일 로드 중 오류: {str(e)}")
        return {} 