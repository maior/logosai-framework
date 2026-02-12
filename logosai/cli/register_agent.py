#!/usr/bin/env python3
"""
LogosAI 에이전트 등록 CLI 도구

이 도구는 개발자가 JSON 설정 파일을 사용하여 에이전트를 Agent Market에 등록할 수 있게 합니다.
추가 코딩 없이 에이전트를 쉽게 등록할 수 있습니다.
"""

import os
import sys
import json
import argparse
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List

try:
    import httpx
except ImportError:
    print("필요한 패키지를 설치하세요: pip install httpx")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("agent-register")

# 기본 설정
DEFAULT_CONFIG_PATH = "agent_config.json"
DEFAULT_API_URL = "https://market.logosai.com/api/v1"
CONFIG_ENV_VAR = "LOGOSAI_CONFIG_PATH"
TOKEN_ENV_VAR = "LOGOSAI_API_TOKEN"


class AgentRegistrar:
    """에이전트 등록 클래스"""
    
    def __init__(
        self, 
        api_url: str = DEFAULT_API_URL,
        api_token: Optional[str] = None,
        timeout: int = 30
    ):
        """
        에이전트 등록기 초기화
        
        Args:
            api_url: API 엔드포인트 URL
            api_token: API 인증 토큰
            timeout: 요청 타임아웃(초)
        """
        self.api_url = api_url
        self.api_token = api_token
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers=self._build_headers()
        )
    
    def _build_headers(self) -> Dict[str, str]:
        """요청 헤더 생성"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
            
        return headers
    
    async def register_agent(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        에이전트를 API에 등록
        
        Args:
            config: 에이전트 설정 딕셔너리
            
        Returns:
            등록 응답
        """
        # 필수 필드 확인
        required_fields = ["name", "description", "version", "category_id"]
        missing = [field for field in required_fields if field not in config]
        
        if missing:
            raise ValueError(f"필수 필드가 누락되었습니다: {', '.join(missing)}")
        
        # API 요청
        url = f"{self.api_url}/agents"
        
        try:
            response = await self.client.post(url, json=config)
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            error_msg = f"API 오류 ({e.response.status_code}): "
            try:
                error_data = e.response.json()
                error_msg += json.dumps(error_data, ensure_ascii=False, indent=2)
            except:
                error_msg += e.response.text
                
            logger.error(error_msg)
            raise ValueError(error_msg) from e
            
        except httpx.RequestError as e:
            error_msg = f"요청 오류: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg) from e
    
    async def get_categories(self) -> List[Dict[str, Any]]:
        """
        사용 가능한 에이전트 카테고리 목록 조회
        
        Returns:
            카테고리 목록
        """
        url = f"{self.api_url}/agent-categories"
        
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            error_msg = f"카테고리 조회 중 API 오류 ({e.response.status_code}): {e.response.text}"
            logger.error(error_msg)
            return []
            
        except httpx.RequestError as e:
            error_msg = f"카테고리 조회 중 요청 오류: {str(e)}"
            logger.error(error_msg)
            return []
    
    async def get_capabilities(self) -> List[Dict[str, Any]]:
        """
        사용 가능한 에이전트 기능 태그 목록 조회
        
        Returns:
            기능 태그 목록
        """
        url = f"{self.api_url}/agent-capabilities"
        
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            error_msg = f"기능 태그 조회 중 API 오류 ({e.response.status_code}): {e.response.text}"
            logger.error(error_msg)
            return []
            
        except httpx.RequestError as e:
            error_msg = f"기능 태그 조회 중 요청 오류: {str(e)}"
            logger.error(error_msg)
            return []
    
    async def close(self):
        """리소스 정리"""
        await self.client.aclose()


async def init_config(output_path: str, force: bool = False) -> None:
    """
    새 에이전트 설정 템플릿 생성
    
    Args:
        output_path: 출력 파일 경로
        force: 기존 파일 덮어쓰기 여부
    """
    output_path = Path(output_path)
    
    if output_path.exists() and not force:
        logger.error(f"파일이 이미 존재합니다: {output_path}")
        print(f"파일을 덮어쓰려면 --force 옵션을 사용하세요.")
        return
    
    # 에이전트 카테고리 및 기능 가져오기
    registrar = AgentRegistrar()
    
    try:
        categories = await registrar.get_categories()
        capabilities = await registrar.get_capabilities()
    finally:
        await registrar.close()
    
    # 템플릿 생성
    template = {
        "name": "내 멋진 에이전트",
        "agent_id": "my-awesome-agent",
        "description": "에이전트 설명을 여기에 작성하세요.",
        "version": "1.0.0",
        "category_id": categories[0]["id"] if categories else 1,
        "available_categories": [
            {"id": cat["id"], "name": cat["name"], "slug": cat["slug"]}
            for cat in categories
        ],
        "capabilities": [cap["id"] for cap in capabilities[:2]] if capabilities else [],
        "available_capabilities": [
            {"id": cap["id"], "name": cap["name"], "slug": cap["slug"]}
            for cap in capabilities
        ],
        "implementation_type": "python",
        "repository_url": "https://github.com/yourusername/agent-repo",
        "documentation_url": "https://docs.yourdomain.com/agent",
        "is_public": True,
        "api_schema": {
            "openapi": "3.0.0",
            "info": {
                "title": "내 에이전트 API",
                "version": "1.0.0"
            },
            "paths": {
                "/query": {
                    "post": {
                        "summary": "에이전트에 쿼리 전송",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "query": {
                                                "type": "string"
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "성공적인 응답"
                            }
                        }
                    }
                }
            }
        },
        "config_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "반환할 최대 결과 수"
                },
                "api_key": {
                    "type": "string",
                    "description": "외부 API 키 (필요한 경우)"
                }
            }
        },
        "default_config": {
            "max_results": 5
        },
        "required_resources": {
            "memory": "512Mi",
            "cpu": "0.5",
            "gpu": None
        }
    }
    
    # 파일 저장
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    
    logger.info(f"템플릿 설정 파일이 생성되었습니다: {output_path}")
    print(f"이 파일을 편집한 후 등록하세요: register-agent {output_path}")


async def register_from_file(config_path: str, api_url: str, api_token: str) -> None:
    """
    파일에서 에이전트 설정을 로드하고 등록
    
    Args:
        config_path: 설정 파일 경로
        api_url: API URL
        api_token: API 토큰
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        logger.error(f"설정 파일을 찾을 수 없습니다: {config_path}")
        return
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 오류: {str(e)}")
        return
    except Exception as e:
        logger.error(f"파일 읽기 오류: {str(e)}")
        return
    
    # 메타 필드 제거
    if "available_categories" in config:
        del config["available_categories"]
    if "available_capabilities" in config:
        del config["available_capabilities"]
    
    # 등록 처리
    registrar = AgentRegistrar(api_url=api_url, api_token=api_token)
    
    try:
        result = await registrar.register_agent(config)
        logger.info("에이전트가 성공적으로 등록되었습니다!")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
    except ValueError as e:
        logger.error(f"등록 오류: {str(e)}")
        
    finally:
        await registrar.close()


def main():
    """메인 함수: 명령행 인터페이스 처리"""
    parser = argparse.ArgumentParser(description="LogosAI 에이전트 등록 도구")
    
    subparsers = parser.add_subparsers(dest="command", help="명령")
    
    # 초기화 명령
    init_parser = subparsers.add_parser("init", help="새 에이전트 설정 템플릿 생성")
    init_parser.add_argument("--output", "-o", default=DEFAULT_CONFIG_PATH, help="출력 파일 경로")
    init_parser.add_argument("--force", "-f", action="store_true", help="기존 파일 덮어쓰기")
    
    # 등록 명령
    register_parser = subparsers.add_parser("register", help="에이전트 등록")
    register_parser.add_argument("config", nargs="?", default=DEFAULT_CONFIG_PATH, help="설정 파일 경로")
    register_parser.add_argument("--api-url", "-u", default=DEFAULT_API_URL, help="API URL")
    register_parser.add_argument("--token", "-t", help="API 토큰")
    
    args = parser.parse_args()
    
    # 환경 변수에서 설정 로드
    config_path = os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)
    api_token = os.getenv(TOKEN_ENV_VAR)
    
    # 인수 우선 처리
    if args.command == "init":
        output_path = args.output
        asyncio.run(init_config(output_path, args.force))
        
    elif args.command == "register":
        config_path = args.config or config_path
        api_url = args.api_url
        token = args.token or api_token
        
        if not token:
            logger.error(f"API 토큰이 필요합니다. --token 옵션을 사용하거나 {TOKEN_ENV_VAR} 환경 변수를 설정하세요.")
            return
            
        asyncio.run(register_from_file(config_path, api_url, token))
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main() 