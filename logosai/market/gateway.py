"""
LogosAI Agent Market 게이트웨이 모듈

Agent Market의 ACP 게이트웨이 구현부입니다. 이 모듈은 LLM과 에이전트 간의 통신을 중계합니다.
"""

import os
import json
import asyncio
import logging
import importlib
from typing import Dict, List, Any, Optional, Callable, Union, Tuple
from datetime import datetime

# 로깅 설정
logger = logging.getLogger(__name__)

try:
    import aiohttp
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.warning("aiohttp를 찾을 수 없습니다. HTTP 게이트웨이 기능이 제한됩니다.")

# 기본 에이전트 마켓 엔드포인트
DEFAULT_MARKET_ENDPOINT = "https://market.logosai.com"


class ACPGateway:
    """Agent Collaboration Protocol 게이트웨이
    
    LLM과 LogosAI 에이전트 간의 통신을 중계하는 게이트웨이입니다.
    JSON-RPC 기반의 통신 프로토콜을 사용합니다.
    """
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8090,
        market_endpoint: str = DEFAULT_MARKET_ENDPOINT,
        api_key: Optional[str] = None,
        path: str = "/gateway",
        require_auth: bool = False
    ):
        """
        ACP 게이트웨이 초기화
        
        Args:
            host: 게이트웨이 호스트 주소
            port: 게이트웨이 포트
            market_endpoint: Agent Market API 엔드포인트
            api_key: API 키 (선택 사항)
            path: 게이트웨이 엔드포인트 경로
            require_auth: 인증 필요 여부
        """
        self.host = host
        self.port = port
        self.path = path
        self.require_auth = require_auth
        self.api_key = api_key or os.environ.get("LOGOSAI_API_KEY")
        self.market_endpoint = market_endpoint
        
        # 내부 상태
        self.app = None
        self.runner = None
        self.site = None
        self.is_running = False
        self._agent_cache = {}
        self._client_cache = {}
        self._session = None
        
        # 통계
        self.stats = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_error": 0,
            "start_time": None
        }
    
    async def _ensure_session(self):
        """HTTP 세션이 초기화되었는지 확인"""
        if self._session is None:
            if not AIOHTTP_AVAILABLE:
                raise ImportError("aiohttp 라이브러리를 설치해야 합니다: pip install aiohttp")
                
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                
            self._session = aiohttp.ClientSession(headers=headers)
            
        return self._session
    
    async def _get_agent_client(self, agent_id: str, options: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """
        에이전트 클라이언트 가져오기
        
        Args:
            agent_id: 에이전트 ID
            options: 에이전트 옵션
            
        Returns:
            ACP 클라이언트 인스턴스
        """
        cache_key = f"{agent_id}_{json.dumps(options or {})}"
        
        # 캐시 확인
        if cache_key in self._client_cache:
            return self._client_cache[cache_key]
        
        # Agent Market에서 에이전트 정보 조회
        try:
            # Agent Market 모듈 동적 임포트
            from .. import market
            
            # 에이전트 인스턴스 프로비저닝
            agent_instance = await market.get_market(
                endpoint=self.market_endpoint,
                api_key=self.api_key
            ).provision_agent(agent_id, options)
            
            if not agent_instance:
                logger.error(f"에이전트 '{agent_id}' 프로비저닝 실패")
                return None
            
            # ACP 클라이언트 생성
            from ..acp import ACPClient
            client = ACPClient(endpoint=agent_instance.endpoint)
            
            # 캐시에 저장
            self._client_cache[cache_key] = (client, agent_instance)
            return client, agent_instance
            
        except Exception as e:
            logger.error(f"에이전트 클라이언트 생성 중 오류: {str(e)}")
            return None
    
    async def _handle_gateway_request(self, request: web.Request) -> web.Response:
        """
        게이트웨이 요청 처리 핸들러
        
        Args:
            request: HTTP 요청
            
        Returns:
            HTTP 응답
        """
        self.stats["requests_total"] += 1
        
        # 인증 확인
        if self.require_auth:
            # 여기에 인증 로직 구현
            pass
        
        try:
            # 요청 본문 파싱
            request_data = await request.json()
            
            # JSON-RPC 요청 형식 확인
            if not isinstance(request_data, dict):
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "잘못된 요청 형식"},
                    "id": None
                }, status=400)
            
            # JSON-RPC 버전 확인
            if request_data.get("jsonrpc") != "2.0":
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "지원되지 않는 JSON-RPC 버전"},
                    "id": None
                }, status=400)
            
            # 요청 ID 추출
            request_id = request_data.get("id")
            
            # 메서드 및 파라미터 추출
            method = request_data.get("method")
            params = request_data.get("params", {})
            
            if not method:
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "메서드가 지정되지 않았습니다"},
                    "id": request_id
                }, status=400)
            
            # 리스트 메서드 처리
            if method == "list_agents":
                result = await self._handle_list_agents(params)
                self.stats["requests_success"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": request_id
                })
            
            # 에이전트 쿼리 메서드 처리
            elif method == "query_agent":
                result = await self._handle_query_agent(params)
                self.stats["requests_success"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": request_id
                })
            
            # 게이트웨이 정보 메서드 처리
            elif method == "get_gateway_info":
                result = await self._handle_get_gateway_info(params)
                self.stats["requests_success"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": request_id
                })
            
            # 지원하지 않는 메서드
            else:
                self.stats["requests_error"] += 1
                return web.json_response({
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"지원하지 않는 메서드: {method}"},
                    "id": request_id
                }, status=400)
                
        except json.JSONDecodeError:
            self.stats["requests_error"] += 1
            return web.json_response({
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "잘못된 JSON 형식"},
                "id": None
            }, status=400)
            
        except Exception as e:
            self.stats["requests_error"] += 1
            logger.error(f"요청 처리 중 오류: {str(e)}")
            return web.json_response({
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": f"내부 오류: {str(e)}"},
                "id": request_id if 'request_id' in locals() else None
            }, status=500)
    
    async def _handle_list_agents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        사용 가능한 에이전트 목록 조회 처리
        
        Args:
            params: 요청 파라미터
            
        Returns:
            결과 딕셔너리
        """
        try:
            # Agent Market 모듈 동적 임포트
            from .. import market
            
            # 파라미터 추출
            category = params.get("category")
            query = params.get("query")
            
            # Agent Market에서 에이전트 목록 조회
            agents = await market.get_market(
                endpoint=self.market_endpoint,
                api_key=self.api_key
            ).list_agents(category=category, query=query)
            
            return {
                "agents": agents,
                "count": len(agents),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"에이전트 목록 조회 중 오류: {str(e)}")
            return {"error": str(e), "agents": []}
    
    async def _handle_query_agent(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        에이전트 쿼리 처리
        
        Args:
            params: 요청 파라미터
            
        Returns:
            결과 딕셔너리
        """
        agent_id = params.get("agent_id")
        query = params.get("query")
        options = params.get("options", {})
        
        if not agent_id:
            return {"error": "에이전트 ID가 지정되지 않았습니다"}
        
        if not query:
            return {"error": "쿼리가 지정되지 않았습니다"}
        
        try:
            # 에이전트 클라이언트 가져오기
            client_info = await self._get_agent_client(agent_id, options)
            if not client_info:
                return {"error": f"에이전트 '{agent_id}'를 사용할 수 없습니다"}
            
            client, agent_instance = client_info
            
            # 에이전트에 쿼리 전송
            result = await client.query(query)
            
            # 메타데이터 추가
            result["_meta"] = {
                "agent_id": agent_id,
                "timestamp": datetime.now().isoformat(),
                "gateway_id": id(self)
            }
            
            return result
            
        except Exception as e:
            logger.error(f"에이전트 쿼리 중 오류: {str(e)}")
            return {"error": str(e)}
    
    async def _handle_get_gateway_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        게이트웨이 정보 조회 처리
        
        Args:
            params: 요청 파라미터
            
        Returns:
            결과 딕셔너리
        """
        uptime = (datetime.now() - self.stats["start_time"]).total_seconds() if self.stats["start_time"] else 0
        
        return {
            "gateway_id": id(self),
            "version": "1.0.0",
            "stats": {
                "requests_total": self.stats["requests_total"],
                "requests_success": self.stats["requests_success"],
                "requests_error": self.stats["requests_error"],
                "uptime_seconds": uptime
            },
            "market_endpoint": self.market_endpoint,
            "timestamp": datetime.now().isoformat()
        }
    
    async def start(self) -> bool:
        """
        게이트웨이 시작
        
        Returns:
            성공 여부
        """
        if not AIOHTTP_AVAILABLE:
            logger.error("aiohttp 라이브러리를 설치해야 합니다: pip install aiohttp")
            return False
        
        if self.is_running:
            logger.warning("게이트웨이가 이미 실행 중입니다")
            return True
        
        try:
            # 웹 애플리케이션 생성
            self.app = web.Application()
            
            # 라우트 설정
            self.app.add_routes([
                web.post(self.path, self._handle_gateway_request),
                web.get(self.path, lambda req: web.json_response({
                    "name": "LogosAI ACP Gateway",
                    "version": "1.0.0",
                    "status": "running"
                }))
            ])
            
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
                logger.warning("aiohttp_cors를 설치하면 CORS 지원이 활성화됩니다: pip install aiohttp_cors")
            
            # 서버 실행
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            self.site = web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()
            
            # 상태 업데이트
            self.is_running = True
            self.stats["start_time"] = datetime.now()
            
            logger.info(f"ACP 게이트웨이가 http://{self.host}:{self.port}{self.path}에서 실행 중입니다")
            return True
            
        except Exception as e:
            logger.error(f"게이트웨이 시작 중 오류: {str(e)}")
            await self.stop()
            return False
    
    async def stop(self):
        """게이트웨이 종료"""
        # 클라이언트 캐시 정리
        for cache_key, (client, agent_instance) in self._client_cache.items():
            try:
                # 클라이언트 종료
                await client.close()
                
                # 에이전트 인스턴스 해제
                from .. import market
                await market.get_market().release_agent(agent_instance.id)
                
            except Exception as e:
                logger.error(f"에이전트 클라이언트 정리 중 오류: {str(e)}")
        
        self._client_cache.clear()
        
        # 세션 정리
        if self._session:
            await self._session.close()
            self._session = None
        
        # 웹 서버 정리
        if self.site:
            await self.site.stop()
            self.site = None
            
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            
        self.app = None
        self.is_running = False
        logger.info("ACP 게이트웨이가 종료되었습니다")
    
    async def run_forever(self):
        """게이트웨이를 영구적으로 실행"""
        if not await self.start():
            return
            
        try:
            # 종료될 때까지 대기
            while self.is_running:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logger.info("게이트웨이 태스크가 취소되었습니다")
            
        finally:
            await self.stop()


async def main():
    """게이트웨이 실행 예제"""
    gateway = ACPGateway(host="0.0.0.0", port=8090)
    
    try:
        await gateway.run_forever()
    except KeyboardInterrupt:
        logger.info("사용자에 의해 게이트웨이가 종료되었습니다")
    finally:
        await gateway.stop()


if __name__ == "__main__":
    asyncio.run(main()) 