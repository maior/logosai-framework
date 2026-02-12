"""
LogosAI ACP (Agent Collaboration Protocol) 모듈

이 모듈은 LogosAI 에이전트들 간의 통신을 위한 프로토콜을 구현합니다.
"""

from .server import ACPServer
from .client import ACPClient

__all__ = ['ACPServer', 'ACPClient']

__version__ = "1.0.0"

import logging
import os
import sys
from typing import List, Dict, Any, Optional, Union, Callable

# 로깅 설정
logger = logging.getLogger(__name__)

# 공개할 심볼 목록
__all__ = ["ACPServer", "ACPClient", "create_client", "__version__"]

try:
    # 주 모듈에서 클래스 임포트 시도
    from .server import ACPServer
    from .client import ACPClient, create_client
    logger.debug("ACP 모듈을 성공적으로 로드했습니다.")
except ImportError as e:
    logger.warning(f"기본 ACP 모듈 로드 실패: {e}")
    
    try:
        # 예제 파일에서 임포트 시도
        sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples"))
        from acp_server_example import ACPServer
        from acp_client_example import ACPClient
        logger.info("ACP 예제 모듈을 대신 로드했습니다.")
        
        # create_client 함수 대체 구현
        def create_client(*args, **kwargs):
            return ACPClient(*args, **kwargs)
    except ImportError as e2:
        logger.error(f"ACP 예제 모듈 로드 실패: {e2}")
        
        # 실패 시 빈 클래스 정의
        class ACPServer:
            """
            ACPServer 클래스의 스텁 구현.
            
            실제 구현은 logosai.acp.server 모듈이 설치되어 있어야 합니다.
            """
            def __init__(self, *args, **kwargs):
                raise NotImplementedError("ACP 모듈이 설치되지 않았습니다. LogosAI의 전체 버전을 설치하세요.")
        
        class ACPClient:
            """
            ACPClient 클래스의 스텁 구현.
            
            실제 구현은 logosai.acp.client 모듈이 설치되어 있어야 합니다.
            """
            def __init__(self, *args, **kwargs):
                raise NotImplementedError("ACP 모듈이 설치되지 않았습니다. LogosAI의 전체 버전을 설치하세요.")

# 버전 체크 및 호환성 검사
def check_version():
    """
    ACP 모듈의 버전 호환성을 확인합니다.
    """
    from .. import __version__ as logosai_version
    
    if logosai_version < "1.1.0":
        logger.warning(f"ACP 모듈은 LogosAI 버전 1.1.0 이상에서 가장 잘 작동합니다. 현재 버전: {logosai_version}")
    
    return __version__

# 초기화 시 버전 체크 실행
try:
    version_info = check_version()
    logger.debug(f"ACP 모듈 버전: {version_info}")
except ImportError:
    logger.debug("LogosAI 기본 모듈을 찾을 수 없어 버전 검사를 건너뜁니다.") 