#!/usr/bin/env python3
"""
LogosAI ACP 서버 실행 CLI 도구

이 모듈은 명령행에서 LogosAI ACP 서버를 쉽게 실행할 수 있는 인터페이스를 제공합니다.
"""

import os
import sys
import logging
import argparse
from typing import Dict, Any, Optional

try:
    # LogosAI ACP 모듈 가져오기
    from logosai.acp import ACPServer, __version__
    from logosai import AgentConfig, AgentType
except ImportError as e:
    print(f"LogosAI ACP 모듈을 가져올 수 없습니다: {str(e)}")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("logosai-serve")


def parse_arguments():
    """명령행 인수 파싱"""
    parser = argparse.ArgumentParser(
        description="LogosAI ACP 서버 실행 도구",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # 서버 설정
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="서버 바인딩 호스트 주소"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8080, 
        help="서버 포트"
    )
    parser.add_argument(
        "--path", 
        default="/jsonrpc", 
        help="JSON-RPC 엔드포인트 경로"
    )
    
    # 에이전트 설정
    parser.add_argument(
        "--agent-type", 
        default="llm_search", 
        help="사용할 에이전트 타입 (llm_search, internet_search, custom 등)"
    )
    parser.add_argument(
        "--agent-name", 
        default="ACP Agent", 
        help="에이전트 이름"
    )
    parser.add_argument(
        "--agent-description", 
        default="ACP 서버를 통해 노출된 LogosAI 에이전트", 
        help="에이전트 설명"
    )
    parser.add_argument(
        "--model", 
        default="gpt-3.5-turbo", 
        help="사용할 LLM 모델 (LLM 에이전트인 경우)"
    )
    parser.add_argument(
        "--temperature", 
        type=float,
        default=0.7, 
        help="LLM 모델 temperature 값"
    )
    
    # 로깅 설정
    parser.add_argument(
        "--verbose", 
        "-v", 
        action="store_true", 
        help="상세 로깅 활성화"
    )
    parser.add_argument(
        "--quiet", 
        "-q", 
        action="store_true", 
        help="로깅 비활성화"
    )
    
    # 버전 정보
    parser.add_argument(
        "--version", 
        action="version", 
        version=f"LogosAI ACP Server v{__version__}",
        help="버전 정보 출력 후 종료"
    )
    
    return parser.parse_args()


def configure_logging(verbose: bool, quiet: bool) -> None:
    """로깅 레벨 설정"""
    if quiet:
        logger.setLevel(logging.WARNING)
    elif verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)


def get_agent_type(type_name: str) -> AgentType:
    """
    에이전트 타입 문자열을 AgentType Enum으로 변환
    
    Args:
        type_name: 에이전트 타입 이름
        
    Returns:
        AgentType: 해당하는 AgentType Enum 값
    """
    type_mapping = {
        "llm_search": AgentType.LLM_SEARCH,
        "internet_search": AgentType.INTERNET_SEARCH,
        "task_classifier": AgentType.TASK_CLASSIFIER,
        "rag_search": AgentType.RAG_SEARCH,
        "shopping": AgentType.SHOPPING,
        "analysis": AgentType.ANALYSIS,
        "custom": AgentType.CUSTOM
    }
    
    return type_mapping.get(type_name.lower(), AgentType.CUSTOM)


def create_agent_config(args) -> AgentConfig:
    """
    명령행 인수에서 에이전트 설정 생성
    
    Args:
        args: 파싱된 명령행 인수
        
    Returns:
        AgentConfig: 에이전트 설정 객체
    """
    agent_type = get_agent_type(args.agent_type)
    
    # 에이전트 설정
    config = AgentConfig(
        name=args.agent_name,
        agent_type=agent_type,
        description=args.agent_description,
        config={
            "model": args.model,
            "temperature": args.temperature
        }
    )
    
    return config


def main():
    """메인 함수"""
    # 명령행 인수 파싱
    args = parse_arguments()
    
    # 로깅 설정
    configure_logging(args.verbose, args.quiet)
    
    # 환경 변수 출력 (디버깅용)
    if args.verbose:
        for key, value in sorted(os.environ.items()):
            if key.startswith(("LOGOSAI_", "OPENAI_")):
                safe_value = value[:3] + "****" if key.endswith(("KEY", "SECRET", "TOKEN")) else value
                logger.debug(f"환경 변수: {key}={safe_value}")
    
    # 시작 메시지
    logger.info(f"LogosAI ACP 서버 v{__version__} 시작 중...")
    
    try:
        # 에이전트 설정 생성
        agent_config = create_agent_config(args)
        
        # 서버 생성
        server = ACPServer(
            agent_type=args.agent_type,
            agent_config=agent_config,
            host=args.host,
            port=args.port,
            path=args.path,
            logger=logger
        )
        
        # 서버 시작 메시지
        logger.info(f"ACP 서버가 http://{args.host}:{args.port}{args.path} 에서 실행됩니다")
        logger.info(f"에이전트: {args.agent_name} ({args.agent_type})")
        
        if args.host == "0.0.0.0":
            logger.info("접근 URL: http://localhost:{port}{path} 또는 http://<IP 주소>:{port}{path}".format(
                port=args.port, path=args.path
            ))
        
        logger.info("서버를 종료하려면 Ctrl+C를 누르세요")
        
        # 서버 시작 (포그라운드 모드)
        server.start(background=False)
        
    except KeyboardInterrupt:
        logger.info("사용자에 의해 서버가 종료되었습니다")
    except Exception as e:
        logger.error(f"서버 실행 중 오류 발생: {str(e)}")
        if args.verbose:
            import traceback
            logger.debug(traceback.format_exc())
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main()) 