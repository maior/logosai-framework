# -*- coding: utf-8 -*-
"""
LogosAI Agent Bundler Module

This module helps you create and package LogosAI agents in various ways so that they can be registered on the agent market.
"""

import os
import json
import shutil
import zipfile
import tempfile
import logging
import importlib.util
import inspect
from enum import Enum
from typing import Dict, Any, List, Optional, Union, Callable, Type
from dataclasses import dataclass

from .agent import LogosAIAgent
from .config import AgentConfig
from .agent_types import AgentType, AgentResponseType
from .types import AgentResponse

# 로깅 설정
logger = logging.getLogger(__name__)


class BundleType(Enum):
    """번들 유형 정의"""
    MANAGED_SOURCE = "managed_source"  # 소스코드 업로드 방식 (Managed Service)
    SELF_HOSTED = "self_hosted"        # JSON-RPC 원격 접속 방식 (Self-hosted)
    LLM_INTEGRATION = "llm_integration" # LLM 통합 방식 (LLM Integration)


@dataclass
class BundleConfig:
    """에이전트 번들 설정"""
    name: str                      # 에이전트 이름
    version: str                   # 버전
    description: str               # 설명
    author: str                    # 작성자
    bundle_type: BundleType        # 번들 유형
    agent_type: AgentType          # 에이전트 유형
    entry_point: str = ""          # 진입점 (소스코드 방식)
    api_endpoint: str = ""         # API 엔드포인트 (Self-hosted 방식)
    llm_provider: str = ""         # LLM 제공자 (LLM 통합 방식)
    llm_model: str = ""            # LLM 모델 (LLM 통합 방식)
    readme: str = ""               # README 내용
    requirements: List[str] = None # 필요 패키지 목록
    metadata: Dict[str, Any] = None  # 추가 메타데이터
    
    def __post_init__(self):
        if self.requirements is None:
            self.requirements = []
        if self.metadata is None:
            self.metadata = {}
            
    def validate(self) -> bool:
        """설정 유효성 검사"""
        if not self.name or not self.version or not self.description:
            logger.error("필수 필드(이름, 버전, 설명)가 누락되었습니다.")
            return False
            
        # 번들 유형별 필수 필드 검사
        if self.bundle_type == BundleType.MANAGED_SOURCE:
            if not self.entry_point:
                logger.error("소스코드 방식에는 entry_point가 필수입니다.")
                return False
        elif self.bundle_type == BundleType.SELF_HOSTED:
            if not self.api_endpoint:
                logger.error("원격 접속 방식에는 api_endpoint가 필수입니다.")
                return False
        elif self.bundle_type == BundleType.LLM_INTEGRATION:
            if not self.llm_provider or not self.llm_model:
                logger.error("LLM 통합 방식에는 llm_provider와 llm_model이 필수입니다.")
                return False
                
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """설정을 딕셔너리로 변환"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "bundle_type": self.bundle_type.value,
            "agent_type": str(self.agent_type),
            "entry_point": self.entry_point,
            "api_endpoint": self.api_endpoint,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "requirements": self.requirements,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BundleConfig':
        """딕셔너리에서 설정 객체 생성"""
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            bundle_type=BundleType(data.get("bundle_type", BundleType.MANAGED_SOURCE.value)),
            agent_type=AgentType.from_string(data.get("agent_type", "CUSTOM")),
            entry_point=data.get("entry_point", ""),
            api_endpoint=data.get("api_endpoint", ""),
            llm_provider=data.get("llm_provider", ""),
            llm_model=data.get("llm_model", ""),
            readme=data.get("readme", ""),
            requirements=data.get("requirements", []),
            metadata=data.get("metadata", {})
        )


class AgentBundler:
    """에이전트 번들링 도구"""
    
    def __init__(self, config: BundleConfig):
        """
        번들러 초기화
        
        Args:
            config: 번들 설정
        """
        self.config = config
        
    def validate_agent_class(self, agent_class: Type[LogosAIAgent]) -> bool:
        """에이전트 클래스 유효성 검사"""
        if not issubclass(agent_class, LogosAIAgent):
            logger.error(f"제공된 클래스가 LogosAIAgent를 상속받지 않았습니다: {agent_class.__name__}")
            return False
            
        # 필수 메서드 구현 확인
        required_methods = ["process_query", "initialize"]
        for method in required_methods:
            if not hasattr(agent_class, method):
                logger.error(f"에이전트 클래스에 필수 메서드가 없습니다: {method}")
                return False
                
        return True
        
    def create_managed_bundle(self, source_dir: str, output_path: str) -> str:
        """
        소스코드 업로드 방식 번들 생성
        
        Args:
            source_dir: 소스코드 디렉토리 경로
            output_path: 출력 파일 경로
            
        Returns:
            생성된 번들 파일 경로
        """
        if not self.config.validate():
            raise ValueError("번들 설정이 유효하지 않습니다.")
            
        if not os.path.exists(source_dir):
            raise ValueError(f"소스 디렉토리가 존재하지 않습니다: {source_dir}")
            
        # 임시 디렉토리 생성
        with tempfile.TemporaryDirectory() as temp_dir:
            # 소스 파일 복사
            agent_dir = os.path.join(temp_dir, "agent")
            shutil.copytree(source_dir, agent_dir)
            
            # 설정 파일 생성
            config_file = os.path.join(temp_dir, "bundle.json")
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config.to_dict(), f, indent=2)
                
            # README 생성
            if self.config.readme:
                readme_file = os.path.join(temp_dir, "README.md")
                with open(readme_file, 'w', encoding='utf-8') as f:
                    f.write(self.config.readme)
                    
            # requirements.txt 생성
            if self.config.requirements:
                req_file = os.path.join(temp_dir, "requirements.txt")
                with open(req_file, 'w', encoding='utf-8') as f:
                    f.write("\n".join(self.config.requirements))
                    
            # 번들 압축
            if not output_path.endswith('.zip'):
                output_path += '.zip'
                
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
                        
            logger.info(f"Managed 방식 에이전트 번들이 생성되었습니다: {output_path}")
            return output_path
            
    def create_self_hosted_bundle(self, output_path: str) -> str:
        """
        JSON-RPC 원격 접속 방식 번들 생성
        
        Args:
            output_path: 출력 파일 경로
            
        Returns:
            생성된 번들 파일 경로
        """
        if not self.config.validate():
            raise ValueError("번들 설정이 유효하지 않습니다.")
            
        if not self.config.api_endpoint:
            raise ValueError("API 엔드포인트가 지정되지 않았습니다.")
            
        # 임시 디렉토리 생성
        with tempfile.TemporaryDirectory() as temp_dir:
            # 설정 파일 생성
            config_file = os.path.join(temp_dir, "bundle.json")
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config.to_dict(), f, indent=2)
                
            # README 생성
            if self.config.readme:
                readme_file = os.path.join(temp_dir, "README.md")
                with open(readme_file, 'w', encoding='utf-8') as f:
                    f.write(self.config.readme)
                    
            # 프록시 클라이언트 생성 (Self-hosted 에이전트 연결용)
            proxy_file = os.path.join(temp_dir, "proxy_client.py")
            with open(proxy_file, 'w', encoding='utf-8') as f:
                f.write(self._generate_proxy_client())
                
            # 번들 압축
            if not output_path.endswith('.zip'):
                output_path += '.zip'
                
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
                        
            logger.info(f"Self-hosted 방식 에이전트 번들이 생성되었습니다: {output_path}")
            return output_path
            
    def create_llm_integration_bundle(self, output_path: str) -> str:
        """
        LLM 통합 방식 번들 생성
        
        Args:
            output_path: 출력 파일 경로
            
        Returns:
            생성된 번들 파일 경로
        """
        if not self.config.validate():
            raise ValueError("번들 설정이 유효하지 않습니다.")
            
        if not self.config.llm_provider or not self.config.llm_model:
            raise ValueError("LLM 제공자와 모델이 지정되지 않았습니다.")
            
        # 임시 디렉토리 생성
        with tempfile.TemporaryDirectory() as temp_dir:
            # 설정 파일 생성
            config_file = os.path.join(temp_dir, "bundle.json")
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config.to_dict(), f, indent=2)
                
            # README 생성
            if self.config.readme:
                readme_file = os.path.join(temp_dir, "README.md")
                with open(readme_file, 'w', encoding='utf-8') as f:
                    f.write(self.config.readme)
                    
            # LLM 통합 어댑터 생성
            adapter_file = os.path.join(temp_dir, "llm_adapter.py")
            with open(adapter_file, 'w', encoding='utf-8') as f:
                f.write(self._generate_llm_adapter())
                
            # 번들 압축
            if not output_path.endswith('.zip'):
                output_path += '.zip'
                
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
                        
            logger.info(f"LLM 통합 방식 에이전트 번들이 생성되었습니다: {output_path}")
            return output_path
    
    def _generate_proxy_client(self) -> str:
        """JSON-RPC 프록시 클라이언트 코드 생성"""
        return '''
import json
import aiohttp
import logging
from typing import Dict, Any, Optional

from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig
from logosai.types import AgentResponse, AgentResponseType

logger = logging.getLogger(__name__)

class RemoteAgentProxy(LogosAIAgent):
    """Proxy agent that communicates with remote agents through JSON-RPC."""
    
    def __init__(self, agent_id: str, endpoint: str):
        self.agent_id = agent_id
        self.endpoint = endpoint
        
    async def initialize(self) -> bool:
        """에이전트 초기화"""
        await super().initialize()
        self.session = aiohttp.ClientSession()
        return True
        
    async def shutdown(self) -> None:
        """에이전트 종료"""
        if self.session:
            await self.session.close()
            self.session = None
        await super().shutdown()
        
    async def process_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """원격 에이전트에 쿼리 전송"""
        if not self.session:
            await self.initialize()
            
        try:
            # JSON-RPC 요청 생성
            payload = {
                "jsonrpc": "2.0",
                "method": "process_query",
                "params": {
                    "query": query,
                    "context": context or {}
                },
                "id": 1
            }
            
            # 요청 전송
            async with self.session.post(
                self.endpoint, 
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return AgentResponse.error(f"원격 에이전트 오류 (상태 코드: {response.status}): {error_text}")
                    
                # 응답 처리
                result = await response.json()
                
                # 오류 검사
                if "error" in result:
                    return AgentResponse.error(
                        f"JSON-RPC 오류: {result['error'].get('message', '알 수 없는 오류')}"
                    )
                    
                # 결과 반환
                if "result" in result:
                    response_data = result["result"]
                    return AgentResponse.from_dict(response_data) if isinstance(response_data, dict) else AgentResponse.success("성공", response_data)
                    
                return AgentResponse.error("응답에 결과가 없습니다")
                
        except Exception as e:
            logger.exception("JSON-RPC 요청 중 오류 발생")
            return AgentResponse.error(f"원격 에이전트 통신 오류: {str(e)}")
'''

    def _generate_llm_adapter(self) -> str:
        """LLM 통합 어댑터 코드 생성"""
        return '''
import json
import logging
from typing import Dict, Any, Optional, List

from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig
from logosai.types import AgentResponse, AgentResponseType

logger = logging.getLogger(__name__)

class LLMIntegrationAgent(LogosAIAgent):
    """LLM을 활용한 통합 에이전트"""
    
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.llm_provider = config.api_config.get("llm_provider", "")
        self.llm_model = config.api_config.get("llm_model", "")
        self.llm_client = None
        
    async def initialize(self) -> bool:
        """에이전트 초기화"""
        await super().initialize()
        
        # LLM 클라이언트 초기화
        try:
            if self.llm_provider.lower() == "openai":
                from openai import AsyncOpenAI
                api_key = self.api_config.get("api_key")
                self.llm_client = AsyncOpenAI(api_key=api_key)
            elif self.llm_provider.lower() == "anthropic":
                from anthropic import AsyncAnthropic
                api_key = self.api_config.get("api_key")
                self.llm_client = AsyncAnthropic(api_key=api_key)
            elif self.llm_provider.lower() == "google":
                import google.generativeai as genai
                api_key = self.api_config.get("api_key")
                genai.configure(api_key=api_key)
                self.llm_client = genai
            else:
                logger.error(f"지원되지 않는 LLM 제공자: {self.llm_provider}")
                return False
                
            return True
        except Exception as e:
            logger.exception(f"LLM 클라이언트 초기화 중 오류: {str(e)}")
            return False
            
    async def process_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """LLM을 사용하여 쿼리 처리"""
        if not self.llm_client:
            if not await self.initialize():
                return AgentResponse.error("LLM 클라이언트 초기화 실패")
                
        try:
            # 컨텍스트 처리
            system_prompt = self.api_config.get("system_prompt", "")
            
            # 제공자별 API 호출
            if self.llm_provider.lower() == "openai":
                response = await self._call_openai(query, system_prompt, context)
            elif self.llm_provider.lower() == "anthropic":
                response = await self._call_anthropic(query, system_prompt, context)
            elif self.llm_provider.lower() == "google":
                response = await self._call_google(query, system_prompt, context)
            else:
                return AgentResponse.error(f"지원되지 않는 LLM 제공자: {self.llm_provider}")
                
            return response
            
        except Exception as e:
            logger.exception(f"LLM 처리 중 오류: {str(e)}")
            return AgentResponse.error(f"LLM 처리 오류: {str(e)}")
            
    async def _call_openai(self, query: str, system_prompt: str, context: Optional[Dict[str, Any]]) -> AgentResponse:
        """OpenAI API 호출"""
        messages = []
        
        # 시스템 프롬프트 추가
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
            
        # 컨텍스트 추가
        if context and "messages" in context:
            messages.extend(context["messages"])
            
        # 사용자 쿼리 추가
        messages.append({"role": "user", "content": query})
        
        # API 호출
        response = await self.llm_client.chat.completions.create(
            model=self.llm_model,
            messages=messages,
            temperature=self.api_config.get("temperature", 0.7),
            max_tokens=self.api_config.get("max_tokens", 1000)
        )
        
        # 응답 처리
        content = response.choices[0].message.content
        
        # JSON 형식인지 확인
        try:
            json_content = json.loads(content)
            return AgentResponse(
                type=AgentResponseType.JSON,
                content=json_content,
                message=json_content.get("message", "")
            )
        except:
            # 일반 텍스트 응답
            return AgentResponse(
                type=AgentResponseType.TEXT,
                content={"result": content},
                message=content[:100] + "..." if len(content) > 100 else content
            )
            
    async def _call_anthropic(self, query: str, system_prompt: str, context: Optional[Dict[str, Any]]) -> AgentResponse:
        """Anthropic API 호출"""
        # 메시지 준비
        system = system_prompt if system_prompt else None
        
        # API 호출
        response = await self.llm_client.messages.create(
            model=self.llm_model,
            system=system,
            messages=[{"role": "user", "content": query}],
            max_tokens=self.api_config.get("max_tokens", 1000)
        )
        
        # 응답 처리
        content = response.content[0].text
        
        # JSON 형식인지 확인
        try:
            json_content = json.loads(content)
            return AgentResponse(
                type=AgentResponseType.JSON,
                content=json_content,
                message=json_content.get("message", "")
            )
        except:
            # 일반 텍스트 응답
            return AgentResponse(
                type=AgentResponseType.TEXT,
                content={"result": content},
                message=content[:100] + "..." if len(content) > 100 else content
            )
            
    async def _call_google(self, query: str, system_prompt: str, context: Optional[Dict[str, Any]]) -> AgentResponse:
        """Google Generative AI API 호출"""
        # 프롬프트 준비
        if system_prompt:
            full_prompt = f"{system_prompt}\\n\\n{query}"
        else:
            full_prompt = query
            
        # API 호출
        response = await self.llm_client.generate_content_async(
            model=self.llm_model,
            contents=full_prompt
        )
        
        # 응답 처리
        content = response.text
        
        # JSON 형식인지 확인
        try:
            json_content = json.loads(content)
            return AgentResponse(
                type=AgentResponseType.JSON,
                content=json_content,
                message=json_content.get("message", "")
            )
        except:
            # 일반 텍스트 응답
            return AgentResponse(
                type=AgentResponseType.TEXT,
                content={"result": content},
                message=content[:100] + "..." if len(content) > 100 else content
            )
'''

def create_agent_bundle(
    name: str,
    version: str,
    description: str,
    author: str,
    agent_type: Union[AgentType, str],
    bundle_type: BundleType,
    source_dir: str = None,
    api_endpoint: str = None,
    llm_provider: str = None,
    llm_model: str = None,
    readme: str = "",
    requirements: List[str] = None,
    metadata: Dict[str, Any] = None,
    output_path: str = "./agent_bundle.zip"
) -> str:
    """
    에이전트 번들 생성 도우미 함수
    
    Args:
        name: 에이전트 이름
        version: 버전
        description: 설명
        author: 작성자
        agent_type: 에이전트 유형 (AgentType 또는 문자열)
        bundle_type: 번들 유형 (BundleType)
        source_dir: 소스코드 디렉토리 경로 (소스코드 방식)
        api_endpoint: API 엔드포인트 (원격 접속 방식)
        llm_provider: LLM 제공자 (LLM 통합 방식)
        llm_model: LLM 모델 (LLM 통합 방식)
        readme: README 내용
        requirements: 필요 패키지 목록
        metadata: 추가 메타데이터
        output_path: 출력 파일 경로
        
    Returns:
        생성된 번들 파일 경로
    """
    # 에이전트 유형 변환
    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)
        
    # 설정 생성
    config = BundleConfig(
        name=name,
        version=version,
        description=description,
        author=author,
        bundle_type=bundle_type,
        agent_type=agent_type,
        entry_point="agent/__init__.py" if bundle_type == BundleType.MANAGED_SOURCE else "",
        api_endpoint=api_endpoint or "",
        llm_provider=llm_provider or "",
        llm_model=llm_model or "",
        readme=readme,
        requirements=requirements or [],
        metadata=metadata or {}
    )
    
    # 번들러 생성
    bundler = AgentBundler(config)
    
    # 번들 유형에 따라 처리
    if bundle_type == BundleType.MANAGED_SOURCE:
        if not source_dir:
            raise ValueError("소스코드 방식에는 source_dir가 필수입니다.")
        return bundler.create_managed_bundle(source_dir, output_path)
    elif bundle_type == BundleType.SELF_HOSTED:
        if not api_endpoint:
            raise ValueError("원격 접속 방식에는 api_endpoint가 필수입니다.")
        return bundler.create_self_hosted_bundle(output_path)
    elif bundle_type == BundleType.LLM_INTEGRATION:
        if not llm_provider or not llm_model:
            raise ValueError("LLM 통합 방식에는 llm_provider와 llm_model이 필수입니다.")
        return bundler.create_llm_integration_bundle(output_path)
    else:
        raise ValueError(f"지원되지 않는 번들 유형: {bundle_type}") 