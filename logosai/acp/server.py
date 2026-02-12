"""
ACP(Agent Collaboration Protocol) 서버 구현

이 모듈은 LogosAI 에이전트를 JSON-RPC를 통해 노출하는 서버를 구현합니다.
"""

import os
import json
import logging
import asyncio
import time
from typing import Dict, Any, Optional, List, Callable, Union, Tuple, Set
from datetime import datetime, timedelta
import uuid
import secrets
import hashlib
import base64
import re

try:
    import aiohttp
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logging.warning("aiohttp를 찾을 수 없습니다. HTTP 서버 기능이 제한됩니다.")

# 에이전트 관련 모듈 임포트
from ..agent_types import AgentType  
try:
    # config 모듈에서 AgentConfig 클래스 임포트 시도
    try:
        from ..config import AgentConfig
    except ImportError:
        # 실패할 경우 직접 config.py 파일에서 임포트 시도
        from .. import config
        AgentConfig = config.AgentConfig
except ImportError:
    # 이마저도 실패한 경우 AgentConfig 클래스 직접 정의
    class AgentConfig:
        """에이전트 설정 클래스"""
        def __init__(self, name, agent_type, description="", config=None, api_config=None, llm_config=None):
            self.name = name
            self.agent_type = agent_type if not isinstance(agent_type, str) else AgentType.from_string(agent_type)
            self.description = description
            self.config = config or {}
            self.api_config = api_config or {}
            self.llm_config = llm_config or {}

from ..agent import LogosAIAgent, AgentResponse, create_agent

# 로깅 설정
logger = logging.getLogger(__name__)


class ACPAuth:
    """ACP 인증 관리 클래스
    
    API 키 기반 인증을 관리합니다.
    """
    
    def __init__(self, require_auth: bool = False):
        """인증 관리자 초기화
        
        Args:
            require_auth: 인증이 필요한지 여부
        """
        self.require_auth = require_auth
        self.api_keys: Dict[str, Dict[str, Any]] = {}
        self.revoked_keys: Set[str] = set()
        self.logger = logging.getLogger(__name__)
    
    def generate_api_key(self, name: str = None, expires_in: Optional[int] = None) -> Dict[str, Any]:
        """새 API 키 생성
        
        Args:
            name: API 키 이름 (없으면 자동 생성)
            expires_in: 만료 시간(초) (없으면 만료되지 않음)
            
        Returns:
            API 키 정보 (키 ID, 키 값, 만료 시간 등)
        """
        # 키 ID 생성 (8자)
        key_id = str(uuid.uuid4())[:8]
        
        # 키 생성 (32바이트 랜덤 값, base64로 인코딩)
        key_value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii').rstrip('=')
        
        # 키 해시 생성 (저장용)
        key_hash = hashlib.sha256(key_value.encode()).hexdigest()
        
        # 만료 시간 계산
        expires_at = None
        if expires_in is not None:
            expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        # 키 정보 저장
        key_info = {
            "id": key_id,
            "name": name or f"api-key-{key_id}",
            "hash": key_hash,
            "created_at": datetime.now(),
            "expires_at": expires_at,
            "last_used": None
        }
        
        self.api_keys[key_id] = key_info
        
        # 클라이언트에 전달할 정보 (키 값 포함)
        return {
            "key_id": key_id,
            "api_key": f"{key_id}.{key_value}",
            "name": key_info["name"],
            "created_at": key_info["created_at"].isoformat(),
            "expires_at": key_info["expires_at"].isoformat() if key_info["expires_at"] else None
        }
    
    def validate_api_key(self, api_key: str) -> bool:
        """API 키 검증
        
        Args:
            api_key: 검증할 API 키
            
        Returns:
            유효한 키인지 여부
        """
        if not api_key:
            return False
        
        # 키 형식 검증
        parts = api_key.split('.')
        if len(parts) != 2:
            return False
        
        key_id, key_value = parts
        
        # 키 ID가 존재하는지 확인
        if key_id not in self.api_keys:
            return False
        
        # 키가 취소되었는지 확인
        if key_id in self.revoked_keys:
            return False
        
        # 키 해시 비교
        key_info = self.api_keys[key_id]
        key_hash = hashlib.sha256(key_value.encode()).hexdigest()
        if key_hash != key_info["hash"]:
            return False
        
        # 만료 확인
        if key_info["expires_at"] and datetime.now() > key_info["expires_at"]:
            return False
        
        # 사용 시간 업데이트
        key_info["last_used"] = datetime.now()
        
        return True
    
    def revoke_api_key(self, key_id: str) -> bool:
        """API 키 취소
        
        Args:
            key_id: 취소할 키 ID
            
        Returns:
            취소 성공 여부
        """
        if key_id not in self.api_keys:
            return False
        
        self.revoked_keys.add(key_id)
        return True
    
    def get_api_key_from_request(self, request: web.Request) -> Optional[str]:
        """HTTP 요청에서 API 키 추출
        
        Args:
            request: HTTP 요청
            
        Returns:
            추출된 API 키 (없으면 None)
        """
        # Authorization 헤더에서 API 키 추출
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            return auth_header[7:]  # 'Bearer ' 이후 부분
        
        # 쿼리 파라미터에서 API 키 추출
        api_key = request.query.get('api_key')
        if api_key:
            return api_key
        
        # 쿠키에서 API 키 추출
        api_key = request.cookies.get('api_key')
        if api_key:
            return api_key
        
        return None


class ACPServer:
    """ACP 서버 클래스
    
    LogosAI 에이전트를 JSON-RPC를 통해 노출하는 서버를 구현합니다.
    """
    
    def __init__(
        self,
        agent_type: Union[AgentType, str, None] = None,
        agent_config: Optional[AgentConfig] = None,
        agent: Optional[LogosAIAgent] = None,
        host: str = "0.0.0.0",
        port: int = 8080,
        path: str = "/jsonrpc",
        logger: Optional[logging.Logger] = None,
        require_auth: bool = False
    ):
        """ACP 서버 초기화
        
        Args:
            agent_type: 에이전트 유형 (agent가 None인 경우 사용)
            agent_config: 에이전트 설정 (agent_type이 지정된 경우 사용)
            agent: 기존 에이전트 인스턴스 (직접 제공하는 경우)
            host: 서버 호스트 주소
            port: 서버 포트
            path: JSON-RPC 엔드포인트 경로
            logger: 로거 인스턴스 (없으면 기본 로거 사용)
            require_auth: API 키 인증 필요 여부
        """
        # 서버 설정
        self.host = host
        self.port = port
        self.path = path
        self.logger = logger or logging.getLogger(__name__)
        
        # 에이전트 설정
        self.agent = agent
        self.agent_type = agent_type
        self.agent_config = agent_config
        
        # 인증 관리자
        self.auth = ACPAuth(require_auth=require_auth)
        self.require_auth = require_auth
        
        # 서버 상태
        self.server = None
        self.app = None
        self.runner = None
        self.site = None
        self.running = False
        self.start_time = None
        
        # 등록된 메서드
        self.methods = {}
        
        # 서버 ID
        self.server_id = f"acp-server-{str(uuid.uuid4())[:8]}"
        
        # 통계
        self.stats = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_error": 0,
            "requests_unauthorized": 0,
            "avg_response_time": 0.0
        }
        
        # 메서드 등록
        self._register_default_methods()
    
    async def initialize(self) -> bool:
        """서버 및 에이전트 초기화
        
        Returns:
            초기화 성공 여부
        """
        try:
            # 에이전트 초기화
            if self.agent is None:
                if self.agent_type is not None:
                    # 에이전트 생성
                    if self.agent_config is None:
                        self.agent_config = AgentConfig(
                            name="ACP Agent",
                            agent_type=self.agent_type,
                            description="ACP 서버를 통해 노출된 LogosAI 에이전트"
                        )
                    
                    self.agent = create_agent(
                        agent_type=self.agent_type,
                        config=self.agent_config
                    )
                else:
                    # 기본 에이전트 생성
                    self.agent_config = AgentConfig(
                        name="Default ACP Agent",
                        agent_type=AgentType.CUSTOM,
                        description="기본 ACP 에이전트"
                    )
                    self.agent = LogosAIAgent(self.agent_config)
            
            # 에이전트 초기화
            if not self.agent.initialized:
                await self.agent.initialize()
            
            # 서버 애플리케이션 초기화
            if not AIOHTTP_AVAILABLE:
                self.logger.error("aiohttp 라이브러리가 필요합니다: pip install aiohttp")
                return False
            
            if self.app is None:
                self.app = web.Application()
                self.app.add_routes([web.post(self.path, self._handle_jsonrpc)])
                
                # CORS 설정
                try:
                    import aiohttp_cors
                    cors = aiohttp_cors.setup(self.app, defaults={
                        "*": aiohttp_cors.ResourceOptions(
                            allow_credentials=True,
                            expose_headers="*",
                            allow_headers="*"
                        )
                    })
                    for route in list(self.app.router.routes()):
                        cors.add(route)
                except ImportError:
                    self.logger.warning("aiohttp_cors를 찾을 수 없습니다. CORS 지원이 활성화되지 않습니다.")
            
            return True
            
        except Exception as e:
            self.logger.error(f"서버 초기화 중 오류: {str(e)}")
            return False
    
    async def start(self, background: bool = True) -> bool:
        """서버 시작
        
        Args:
            background: 백그라운드에서 실행 여부 (True면 비동기로 실행, False면 블로킹 모드)
            
        Returns:
            시작 성공 여부
        """
        try:
            # 서버 초기화
            if not await self.initialize():
                return False
            
            # 서버 실행
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            self.site = web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()
            
            # 상태 업데이트
            self.running = True
            self.start_time = datetime.now()
            
            self.logger.info(f"ACP 서버가 http://{self.host}:{self.port}{self.path} 에서 실행 중입니다.")
            
            # 백그라운드 모드가 아니면 계속 실행
            if not background:
                try:
                    while True:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    await self.stop()
            
            return True
            
        except Exception as e:
            self.logger.error(f"서버 시작 중 오류: {str(e)}")
            return False
    
    async def stop(self) -> bool:
        """서버 중지
        
        Returns:
            중지 성공 여부
        """
        try:
            # 서버 중지
            if self.site:
                await self.site.stop()
                self.site = None
            
            if self.runner:
                await self.runner.cleanup()
                self.runner = None
            
            # 에이전트 종료
            if self.agent and self.agent.initialized:
                await self.agent.shutdown()
            
            # 상태 업데이트
            self.running = False
            
            self.logger.info("ACP 서버가 중지되었습니다.")
            return True
            
        except Exception as e:
            self.logger.error(f"서버 중지 중 오류: {str(e)}")
            return False
    
    def register_method(self, name: str, handler: Callable) -> None:
        """JSON-RPC 메서드 등록
        
        Args:
            name: 메서드 이름
            handler: 메서드 핸들러 함수
        """
        self.methods[name] = handler
        self.logger.debug(f"메서드 '{name}' 등록됨")
    
    def _register_default_methods(self) -> None:
        """기본 메서드 등록"""
        self.register_method("query", self._handle_query)
        self.register_method("get_agent_info", self._handle_agent_info)
        self.register_method("get_server_info", self._handle_server_info)
    
    async def _handle_jsonrpc(self, request: web.Request) -> web.Response:
        """JSON-RPC 요청 처리
        
        Args:
            request: HTTP 요청 객체
            
        Returns:
            HTTP 응답 객체
        """
        start_time = time.time()
        self.stats["requests_total"] += 1
        
        try:
            # API 키 인증 확인
            if self.require_auth:
                api_key = self.auth.get_api_key_from_request(request)
                if not api_key or not self.auth.validate_api_key(api_key):
                    self.stats["requests_unauthorized"] += 1
                    return web.json_response({
                        "jsonrpc": "2.0",
                        "error": {"code": -32000, "message": "Unauthorized"},
                        "id": None
                    }, status=401)
            
            # 요청 데이터 파싱
            try:
                data = await request.json()
            except json.JSONDecodeError:
                self.stats["requests_error"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None
                })
            
            # JSON-RPC 요청 검증
            if "jsonrpc" not in data or data["jsonrpc"] != "2.0":
                self.stats["requests_error"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "Invalid Request"},
                    "id": data.get("id", None)
                })
            
            # 메서드 이름 추출
            method = data.get("method")
            if not method:
                self.stats["requests_error"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "Method is required"},
                    "id": data.get("id", None)
                })
            
            # 매개변수 추출
            params = data.get("params", {})
            request_id = data.get("id", None)
            
            # 메서드 핸들러 찾기
            if method not in self.methods:
                self.stats["requests_error"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method '{method}' not found"},
                    "id": request_id
                })
            
            # 메서드 실행
            handler = self.methods[method]
            result = await handler(params)
            
            # 통계 업데이트
            self.stats["requests_success"] += 1
            elapsed_time = time.time() - start_time
            
            # 평균 응답 시간 업데이트
            current_avg = self.stats["avg_response_time"]
            prev_count = self.stats["requests_success"] - 1
            
            if prev_count > 0:
                self.stats["avg_response_time"] = (current_avg * prev_count + elapsed_time) / self.stats["requests_success"]
            else:
                self.stats["avg_response_time"] = elapsed_time
            
            # 응답 반환
            return web.json_response({
                "jsonrpc": "2.0",
                "result": result,
                "id": request_id
            })
            
        except Exception as e:
            self.logger.error(f"요청 처리 중 오류: {str(e)}")
            self.stats["requests_error"] += 1
            
            return web.json_response({
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                "id": data.get("id") if "data" in locals() else None
            })
    
    async def _handle_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """쿼리 메서드 처리
        
        Args:
            params: 메서드 매개변수
            
        Returns:
            처리 결과
        """
        if not self.agent:
            return {"error": "에이전트가 초기화되지 않았습니다."}
        
        # 쿼리 추출
        query = params.get("query")
        if not query:
            return {"error": "쿼리가 제공되지 않았습니다."}
        
        # 컨텍스트 추출
        context = params.get("context")
        
        # 에이전트 처리
        response = await self.agent.process(query)
        
        # 응답이 AgentResponse 인스턴스인지 확인
        if isinstance(response, AgentResponse):
            return response.to_dict()
        elif isinstance(response, dict):
            return response
        else:
            return {"error": f"예상치 못한 응답 유형: {type(response).__name__}"}
    
    async def _handle_agent_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """에이전트 정보 메서드 처리
        
        Args:
            params: 메서드 매개변수
            
        Returns:
            에이전트 정보
        """
        if not self.agent:
            return {"error": "에이전트가 초기화되지 않았습니다."}
        
        # 에이전트 정보 조회
        try:
            info = self.agent.get_info()
            
            # 프로토콜 정보 추가
            info["protocol"] = "ACP/2.0"
            info["server"] = self.server_id
            info["capabilities"] = ["query", "get_agent_info", "get_server_info"]
            
            return info
            
        except Exception as e:
            self.logger.error(f"에이전트 정보 조회 중 오류: {str(e)}")
            return {"error": f"에이전트 정보 조회 오류: {str(e)}"}
    
    async def _handle_server_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """서버 정보 메서드 처리
        
        Args:
            params: 메서드 매개변수
            
        Returns:
            서버 정보
        """
        # 가동 시간 계산
        uptime = "0s"
        if self.start_time:
            delta = datetime.now() - self.start_time
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            parts = []
            if days > 0:
                parts.append(f"{days}d")
            if hours > 0:
                parts.append(f"{hours}h")
            if minutes > 0:
                parts.append(f"{minutes}m")
            
            parts.append(f"{seconds}s")
            uptime = " ".join(parts)
        
        # 서버 정보 반환
        return {
            "server_id": self.server_id,
            "protocol": "ACP/2.0",
            "version": "1.1.0",  # SDK 버전
            "uptime": uptime,
            "endpoints": {
                "jsonrpc": f"http://{self.host}:{self.port}{self.path}"
            },
            "statistics": {
                "requests_total": self.stats["requests_total"],
                "requests_success": self.stats["requests_success"],
                "requests_error": self.stats["requests_error"],
                "requests_unauthorized": self.stats["requests_unauthorized"],
                "avg_response_time": round(self.stats["avg_response_time"] * 1000, 2)  # ms 단위
            },
            "registered_methods": list(self.methods.keys())
        }
    
    def generate_api_key(self, name: str = None, expires_in: Optional[int] = None) -> Dict[str, Any]:
        """새 API 키 생성
        
        Args:
            name: API 키 이름 (없으면 자동 생성)
            expires_in: 만료 시간(초) (없으면 만료되지 않음)
            
        Returns:
            API 키 정보 (키 ID, 키 값, 만료 시간 등)
        """
        return self.auth.generate_api_key(name, expires_in)
    
    def revoke_api_key(self, key_id: str) -> bool:
        """API 키 취소
        
        Args:
            key_id: 취소할 키 ID
            
        Returns:
            취소 성공 여부
        """
        return self.auth.revoke_api_key(key_id) 