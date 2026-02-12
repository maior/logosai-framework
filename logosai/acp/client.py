"""
ACP(Agent Collaboration Protocol) 클라이언트 구현

이 모듈은 LogosAI 에이전트와 통신하기 위한 ACP 클라이언트를 구현합니다.
JSON-RPC 프로토콜을 사용하여 에이전트에 쿼리를 보내고 응답을 받을 수 있습니다.
"""

import os
import json
import sys
import urllib.request
import urllib.error
import socket
import uuid
import logging
import time
import asyncio
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

# 로깅 설정
logger = logging.getLogger(__name__)

class ACPClient:
    """Client for interacting with ACP server via JSON-RPC."""
    
    def __init__(self, server_url: str = "http://localhost:8888/jsonrpc"):
        """Initialize the ACP client with server URL."""
        self.server_url = server_url
        self.request_id = 1
        self.agents = {}
        self.connection_retries = 3  # 연결 재시도 횟수
        self.connection_retry_delay = 1  # 재시도 간 지연 시간(초)
        logger.info(f"ACP 클라이언트 초기화: 서버 URL={server_url}")

    def check_server_connection(self) -> bool:
        """서버 연결 상태 확인"""
        logger.info(f"서버 연결 확인 중: {self.server_url}")
        try:
            # URL에서 호스트와 포트 추출
            from urllib.parse import urlparse
            parsed_url = urlparse(self.server_url)
            host = parsed_url.hostname or 'localhost'
            port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
            
            # 소켓 연결 시도
            with socket.create_connection((host, port), timeout=5) as sock:
                logger.info(f"서버 연결 성공: {host}:{port}")
                return True
        except socket.error as e:
            logger.error(f"서버 연결 실패: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"서버 연결 확인 중 오류: {str(e)}")
            return False

    def load_agents(self, agent_file: str) -> None:
        """Load agents from a JSON file.
        
        Args:
            agent_file: 에이전트 설정 파일의 경로
        """
        try:
            if os.path.exists(agent_file):
                logger.info(f"에이전트 파일 로드 중: {agent_file}")
                with open(agent_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'agents' in data and isinstance(data['agents'], list):
                        for agent in data['agents']:
                            if 'agent_id' in agent:
                                self.agents[agent['agent_id']] = agent
                                logger.debug(f"에이전트 로드됨: {agent['agent_id']} - {agent.get('name', 'Unknown')}")
                        logger.info(f"로드된 에이전트 수: {len(self.agents)}")
                    else:
                        logger.warning("경고: 에이전트 파일에 'agents' 배열이 없습니다.")
            else:
                logger.warning(f"경고: 에이전트 파일을 찾을 수 없습니다: {agent_file}")
        except Exception as e:
            logger.error(f"에이전트 파일 로드 중 오류 발생: {str(e)}")

    def _make_jsonrpc_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a JSON-RPC request to the server."""
        headers = {
            'Content-Type': 'application/json',
        }
        
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': self.request_id
        }
        
        self.request_id += 1
        logger.info(f"JSON-RPC 요청 시작: 메서드={method}, ID={payload['id']}")
        logger.debug(f"요청 파라미터: {json.dumps(params)}")
        
        for retry in range(self.connection_retries):
            try:
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(self.server_url, data=data, headers=headers)
                logger.debug(f"서버 요청 중: {self.server_url}")
                
                with urllib.request.urlopen(req) as response:
                    response_data = json.loads(response.read().decode('utf-8'))
                    
                    if 'error' in response_data:
                        logger.error(f"서버 오류 응답: {response_data['error']}")
                        return response_data
                    
                    logger.info(f"서버 응답 성공: ID={response_data.get('id')}")
                    return response_data.get('result', {})
                    
            except (urllib.error.URLError, socket.error) as e:
                if retry < self.connection_retries - 1:
                    logger.warning(f"연결 실패, {self.connection_retry_delay}초 후 재시도 ({retry + 1}/{self.connection_retries}): {str(e)}")
                    time.sleep(self.connection_retry_delay)
                else:
                    logger.error(f"최대 재시도 횟수 초과: {str(e)}")
                    raise
    
    def get_server_info(self) -> Dict[str, Any]:
        """Get server information."""
        return self._make_jsonrpc_request('get_server_info', {})
    
    def query(self, agent_id: str, query: str, **params) -> Dict[str, Any]:
        """Send a query to an agent."""
        request_params = {
            'agent_id': agent_id,
            'query': query,
            **params
        }
        return self._make_jsonrpc_request('query', request_params)

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all available agents."""
        if self.agents:
            return list(self.agents.values())
        return self.query('list_agents', {})

    def get_local_agents(self) -> List[Dict[str, Any]]:
        """Get list of locally loaded agents."""
        return list(self.agents.values())

    def execute_agent(self, agent_id: str, query: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute an agent with the given query and parameters."""
        if params is None:
            params = {}
            
        # Add any default parameters from the agent configuration
        if agent_id in self.agents and 'parameters' in self.agents[agent_id]:
            default_params = self.agents[agent_id]['parameters']
            # Only add default parameters that are not already specified
            for key, value in default_params.items():
                if key not in params:
                    params[key] = value
        
        logger.info(f"에이전트 실행 요청: agent_id={agent_id}, query='{query}'")
        
        try:
            # 서버로 JSON-RPC 호출
            response = self.query('execute_agent', {
                'agent_id': agent_id,
                'query': query,
                'parameters': params
            })
            
            if not response:
                logger.warning(f"에이전트 {agent_id}로부터 응답을 받지 못했습니다.")
                return {}
            
            return response
            
        except Exception as e:
            logger.error(f"에이전트 실행 중 오류: {str(e)}")
            
            # 서버 연결 실패 시 로컬에서 간단한 응답 생성
            if agent_id == "task_classifier_agent":
                return {
                    "recommended_agent": "llm_search_agent",
                    "task_type": "llm_search",
                    "confidence": 0.0,
                    "reasoning": "분류 결과 없음",
                    "requires_analysis": False
                }
            elif agent_id == "llm_search_agent":
                return {
                    "result": "llm_search_completed",
                    "content": f"'{query}'에 대한 LLM 검색 결과입니다.",
                    "message": "로컬 처리: 서버 연결 없이 생성된 LLM 검색 응답입니다.",
                    "metadata": {"processed_locally": True, "agent_id": agent_id}
                }
            else:
                return {
                    "result": "generic_response",
                    "content": f"'{query}'에 대한 응답입니다.",
                    "message": f"로컬 처리: 서버 연결 없이 생성된 '{agent_id}' 에이전트 응답입니다.",
                    "metadata": {"processed_locally": True, "agent_id": agent_id}
                }

    def get_agent_info(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific agent."""
        if agent_id in self.agents:
            return self.agents[agent_id]
        return None

def create_client(*args, **kwargs) -> ACPClient:
    """
    ACPClient 생성 유틸리티 함수
    
    Args:
        server_url: ACP 서버 URL
        
    Returns:
        생성된 클라이언트 인스턴스
    """
    return ACPClient(*args, **kwargs) 