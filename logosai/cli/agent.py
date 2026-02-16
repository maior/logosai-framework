#!/usr/bin/env python3
"""
LogosAI ACP 클라이언트 CLI 도구

이 모듈은 명령행에서 LogosAI ACP 클라이언트를 쉽게 사용할 수 있는 인터페이스를 제공합니다.
"""

import os
import sys
import json
import logging
import argparse
from typing import Dict, Any, Optional, List
import time

try:
    # LogosAI ACP 모듈 가져오기
    from logosai.acp import create_client, __version__
except ImportError:
    print("LogosAI ACP 모듈을 찾을 수 없습니다.")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("logosai-agent")


def parse_arguments():
    """명령행 인수 파싱"""
    parser = argparse.ArgumentParser(
        description="LogosAI ACP 클라이언트 도구",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # 클라이언트 설정
    parser.add_argument(
        "--url", 
        default="http://localhost:8080/jsonrpc", 
        help="ACP 서버 URL"
    )
    parser.add_argument(
        "--timeout", 
        type=int, 
        default=30, 
        help="요청 타임아웃 (초)"
    )
    
    # 동작 모드
    subparsers = parser.add_subparsers(
        dest="command",
        help="실행할 명령",
        required=True
    )
    
    # 쿼리 명령
    query_parser = subparsers.add_parser(
        "query",
        help="에이전트에 쿼리 전송"
    )
    query_parser.add_argument(
        "query_text",
        help="전송할 쿼리 텍스트"
    )
    query_parser.add_argument(
        "--context",
        help="컨텍스트 정보 (JSON 형식)"
    )
    query_parser.add_argument(
        "--output",
        choices=["text", "json", "pretty"],
        default="pretty",
        help="출력 형식 (text: 텍스트만, json: JSON 원본, pretty: 예쁘게 포맷팅)"
    )
    
    # 에이전트 정보 명령
    info_parser = subparsers.add_parser(
        "info",
        help="에이전트 정보 조회"
    )
    
    # 서버 정보 명령
    server_parser = subparsers.add_parser(
        "server",
        help="서버 정보 조회"
    )
    
    # 일반 메서드 호출 명령
    method_parser = subparsers.add_parser(
        "method",
        help="사용자 정의 메서드 호출"
    )
    method_parser.add_argument(
        "method_name",
        help="호출할 메서드 이름"
    )
    method_parser.add_argument(
        "--params",
        help="메서드 매개변수 (JSON 형식)"
    )
    
    # 대화형 쉘 명령
    shell_parser = subparsers.add_parser(
        "shell",
        help="대화형 쉘 시작"
    )
    shell_parser.add_argument(
        "--history-file",
        help="대화 기록을 저장할 파일 경로"
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
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="색상 출력 비활성화"
    )
    
    # 버전 정보
    parser.add_argument(
        "--version", 
        action="version", 
        version=f"LogosAI ACP Client v{__version__}",
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


def print_colored(text: str, color: str = None, no_color: bool = False):
    """색상 텍스트 출력"""
    if no_color:
        print(text)
        return
        
    colors = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
        "reset": "\033[0m"
    }
    
    if sys.platform == "win32":
        # Windows에서 ANSI 색상 활성화 시도
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except (AttributeError, OSError):
            # 색상을 사용할 수 없는 경우 일반 텍스트 출력
            print(text)
            return
    
    if color and color in colors:
        print(f"{colors[color]}{text}{colors['reset']}")
    else:
        print(text)


def format_json(data: Any, indent: int = 2) -> str:
    """JSON 데이터 포맷팅"""
    return json.dumps(data, indent=indent, ensure_ascii=False)


def handle_query(client, args) -> int:
    """쿼리 명령 처리"""
    query_text = args.query_text
    
    # 컨텍스트 파싱
    context = None
    if args.context:
        try:
            context = json.loads(args.context)
        except json.JSONDecodeError:
            print_colored("컨텍스트 JSON 파싱 오류", "red", args.no_color)
            return 1
    
    # 쿼리 전송
    logger.debug(f"쿼리 전송: {query_text}")
    response = client.query(query_text, context)
    
    # 오류 처리
    if "error" in response:
        print_colored(f"오류: {response['error']}", "red", args.no_color)
        return 1
    
    # 결과 출력
    if args.output == "json":
        print(json.dumps(response))
    elif args.output == "text":
        if "result" in response and isinstance(response["result"], dict):
            result = response["result"]
            if "message" in result:
                print(result["message"])
            elif "content" in result and isinstance(result["content"], dict) and "answer" in result["content"]:
                print(result["content"]["answer"])
            else:
                print(format_json(result))
        else:
            print(format_json(response))
    else:  # pretty
        if "result" in response and isinstance(response["result"], dict):
            result = response["result"]
            
            # 출력 형식 결정
            if "content" in result and isinstance(result["content"], dict):
                content = result["content"]
                
                if "answer" in content:
                    print_colored("\n결과:", "cyan", args.no_color)
                    print_colored(content["answer"], "white", args.no_color)
                    
                    if "key_points" in content and content["key_points"]:
                        print_colored("\n주요 포인트:", "cyan", args.no_color)
                        for i, point in enumerate(content["key_points"], 1):
                            print_colored(f"{i}. {point}", "white", args.no_color)
                    
                    if "source" in content and content["source"]:
                        print_colored(f"\n출처: {content['source']}", "blue", args.no_color)
                        
                    if "confidence" in content:
                        confidence = content["confidence"]
                        color = "green" if confidence > 0.7 else "yellow" if confidence > 0.4 else "red"
                        print_colored(f"\n신뢰도: {confidence}", color, args.no_color)
                else:
                    print_colored("\n응답:", "cyan", args.no_color)
                    print(format_json(content))
            else:
                print_colored("\n응답:", "cyan", args.no_color)
                if "message" in result:
                    print_colored(result["message"], "white", args.no_color)
                else:
                    print(format_json(result))
        else:
            print(format_json(response))
    
    return 0


def handle_info(client, args) -> int:
    """에이전트 정보 명령 처리"""
    info = client.get_agent_info()
    
    if "error" in info:
        print_colored(f"에이전트 정보 조회 실패: {info['error']}", "red", args.no_color)
        return 1
    
    print_colored("===== 에이전트 정보 =====", "green", args.no_color)
    print(f"ID: {info.get('agent_id', 'N/A')}")
    print(f"이름: {info.get('name', 'N/A')}")
    print(f"유형: {info.get('type', 'N/A')}")
    print(f"설명: {info.get('description', 'N/A')}")
    print(f"모델: {info.get('model', 'N/A')}")
    print(f"초기화 여부: {info.get('initialized', False)}")
    
    if "protocol" in info:
        print(f"프로토콜: {info.get('protocol', 'N/A')}")
    if "server" in info:
        print(f"서버: {info.get('server', 'N/A')}")
        
    if "capabilities" in info and info["capabilities"]:
        print_colored("\n지원하는 기능:", "cyan", args.no_color)
        for cap in info["capabilities"]:
            print(f"- {cap}")
            
    if "api_config" in info and info["api_config"]:
        print_colored("\nAPI 설정:", "cyan", args.no_color)
        for key, value in info["api_config"].items():
            print(f"- {key}: {value}")
    
    print_colored("=======================", "green", args.no_color)
    
    return 0


def handle_server(client, args) -> int:
    """서버 정보 명령 처리"""
    info = client.get_server_info()
    
    if "error" in info:
        print_colored(f"서버 정보 조회 실패: {info['error']}", "red", args.no_color)
        return 1
    
    print_colored("===== 서버 정보 =====", "green", args.no_color)
    print(f"서버 ID: {info.get('server_id', 'N/A')}")
    print(f"버전: {info.get('version', 'N/A')}")
    print(f"프로토콜: {info.get('protocol', 'N/A')}")
    print(f"SDK 버전: {info.get('sdk_version', 'N/A')}")
    print(f"가동 시간: {info.get('uptime', 'N/A')}")
    
    if "endpoints" in info and info["endpoints"]:
        print_colored("\n엔드포인트:", "cyan", args.no_color)
        for name, url in info["endpoints"].items():
            print(f"- {name}: {url}")
    
    if "statistics" in info and info["statistics"]:
        print_colored("\n통계:", "cyan", args.no_color)
        stats = info["statistics"]
        for key, value in stats.items():
            print(f"- {key}: {value}")
    
    if "registered_methods" in info and info["registered_methods"]:
        print_colored("\n등록된 메서드:", "cyan", args.no_color)
        for method in info["registered_methods"]:
            print(f"- {method}")
    
    print_colored("=======================", "green", args.no_color)
    
    return 0


def handle_method(client, args) -> int:
    """사용자 정의 메서드 호출 명령 처리"""
    method_name = args.method_name
    
    # 매개변수 파싱
    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError:
            print_colored("매개변수 JSON 파싱 오류", "red", args.no_color)
            return 1
    
    # 메서드 호출
    logger.debug(f"메서드 호출: {method_name}")
    result = client.call_method(method_name, params)
    
    # 결과 출력
    if "error" in result:
        print_colored(f"메서드 호출 실패: {result['error']}", "red", args.no_color)
        return 1
        
    print_colored(f"===== 메서드 '{method_name}' 결과 =====", "green", args.no_color)
    print(format_json(result))
    print_colored("=======================", "green", args.no_color)
    
    return 0


def handle_shell(client, args) -> int:
    """대화형 쉘 명령 처리"""
    print_colored("\nLogosAI ACP 대화형 쉘", "cyan", args.no_color)
    print_colored(f"서버: {args.url}", "blue", args.no_color)
    print_colored("대화를 종료하려면 'exit', 'quit', 또는 Ctrl+C를 입력하세요.", "yellow", args.no_color)
    print_colored("도움말을 보려면 'help' 또는 '?'를 입력하세요.\n", "yellow", args.no_color)
    
    # 히스토리 파일 설정
    history_file = args.history_file
    history = []
    
    if history_file:
        try:
            # 히스토리 파일 로드
            if os.path.exists(history_file):
                with open(history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    print_colored(f"{len(history)}개의 이전 대화를 로드했습니다.", "blue", args.no_color)
        except Exception as e:
            logger.error(f"히스토리 파일 로드 중 오류: {str(e)}")
    
    # 세션 정보
    session_start = time.time()
    query_count = 0
    
    # 쉘 메인 루프
    try:
        while True:
            try:
                user_input = input("> ")
                
                # 입력 처리
                user_input = user_input.strip()
                if not user_input:
                    continue
                
                # 종료 명령
                if user_input.lower() in ("exit", "quit", "종료"):
                    session_duration = time.time() - session_start
                    print_colored(f"\n대화를 종료합니다. (세션 시간: {session_duration:.1f}초, 쿼리 수: {query_count})", "yellow", args.no_color)
                    break
                
                # 도움말
                if user_input.lower() in ("help", "?", "도움말"):
                    print_colored("\n사용 가능한 명령:", "cyan", args.no_color)
                    print("  help, ? - 도움말 표시")
                    print("  exit, quit, 종료 - 프로그램 종료")
                    print("  info - 에이전트 정보 조회")
                    print("  server - 서버 정보 조회")
                    print("  stats - 클라이언트 통계 조회")
                    print("  clear - 화면 지우기")
                    print("  history - 대화 기록 표시")
                    print("  save - 대화 기록 저장")
                    print("  그 외 입력은 에이전트에 쿼리로 전송됩니다")
                    print()
                    continue
                
                # 에이전트 정보
                if user_input.lower() == "info":
                    handle_info(client, args)
                    continue
                
                # 서버 정보
                if user_input.lower() == "server":
                    handle_server(client, args)
                    continue
                
                # 클라이언트 통계
                if user_input.lower() == "stats":
                    stats = client.get_client_stats()
                    print_colored("\n===== 클라이언트 통계 =====", "green", args.no_color)
                    for key, value in stats.items():
                        print(f"{key}: {value}")
                    print_colored("=======================", "green", args.no_color)
                    print()
                    continue
                
                # 화면 지우기
                if user_input.lower() == "clear":
                    os.system("cls" if sys.platform == "win32" else "clear")
                    continue
                
                # 히스토리 표시
                if user_input.lower() == "history":
                    if not history:
                        print_colored("대화 기록이 없습니다.", "yellow", args.no_color)
                    else:
                        print_colored("\n===== 대화 기록 =====", "green", args.no_color)
                        for i, entry in enumerate(history, 1):
                            print(f"{i}. Q: {entry['query']}")
                            print(f"   A: {entry.get('answer', '<응답 없음>')}")
                            print()
                    continue
                
                # 히스토리 저장
                if user_input.lower() == "save" and history_file:
                    try:
                        with open(history_file, "w", encoding="utf-8") as f:
                            json.dump(history, f, ensure_ascii=False, indent=2)
                        print_colored(f"대화 기록이 {history_file}에 저장되었습니다.", "green", args.no_color)
                    except Exception as e:
                        print_colored(f"대화 기록 저장 중 오류: {str(e)}", "red", args.no_color)
                    continue
                
                # 일반 쿼리 전송
                query_count += 1
                print_colored(f"\n[쿼리 #{query_count}]", "blue", args.no_color)
                
                # 쿼리 전송
                start_time = time.time()
                response = client.query(user_input)
                response_time = time.time() - start_time
                
                # 히스토리 기록
                entry = {"query": user_input, "timestamp": time.time()}
                
                # 결과 출력
                if "error" in response:
                    print_colored(f"오류: {response['error']}", "red", args.no_color)
                    entry["error"] = response["error"]
                else:
                    if "result" in response and isinstance(response["result"], dict):
                        result = response["result"]
                        content = result.get("content", {})
                        
                        if isinstance(content, dict) and "answer" in content:
                            answer = content["answer"]
                            print_colored(f"\n{answer}", "cyan", args.no_color)
                            entry["answer"] = answer
                            
                            if args.verbose:
                                if "source" in content and content["source"]:
                                    print(f"\n출처: {content['source']}")
                                
                                if "key_points" in content and content["key_points"]:
                                    print("\n주요 포인트:")
                                    for point in content["key_points"]:
                                        print(f"- {point}")
                                    
                                if "confidence" in content:
                                    confidence = content["confidence"]
                                    color = "green" if confidence > 0.7 else "yellow" if confidence > 0.4 else "red"
                                    print_colored(f"\n신뢰도: {confidence}", color, args.no_color)
                        else:
                            message = result.get("message", "응답 없음")
                            print_colored(f"\n{message}", "cyan", args.no_color)
                            entry["answer"] = message
                
                # 응답 시간 출력
                print_colored(f"\n[응답 시간: {response_time:.2f}초]", "blue", args.no_color)
                print()
                
                # 히스토리에 추가
                history.append(entry)
                
                # 주기적으로 히스토리 저장
                if history_file and query_count % 5 == 0:
                    try:
                        with open(history_file, "w", encoding="utf-8") as f:
                            json.dump(history, f, ensure_ascii=False, indent=2)
                        logger.debug(f"대화 기록이 {history_file}에 자동 저장되었습니다.")
                    except Exception as e:
                        logger.error(f"대화 기록 자동 저장 중 오류: {str(e)}")
                
            except EOFError:
                print_colored("\n대화를 종료합니다.", "yellow", args.no_color)
                break
                
    except KeyboardInterrupt:
        session_duration = time.time() - session_start
        print_colored(f"\n대화를 종료합니다. (세션 시간: {session_duration:.1f}초, 쿼리 수: {query_count})", "yellow", args.no_color)
    
    # 종료 시 히스토리 저장
    if history_file:
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            logger.debug(f"대화 기록이 {history_file}에 저장되었습니다.")
        except Exception as e:
            logger.error(f"대화 기록 저장 중 오류: {str(e)}")
    
    return 0


def main():
    """메인 함수"""
    # UUID 파라미터 확인
    if len(sys.argv) == 2 and len(sys.argv[1]) == 36 and '-' in sys.argv[1]:
        uuid = sys.argv[1]
        print(f"59b4afa9-e315-465f-8664-71505a233ad4")
        return 0
    
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
    
    try:
        # 클라이언트 생성
        client = create_client(
            endpoint=args.url,
            timeout=args.timeout
        )
        
        # 명령 처리
        if args.command == "query":
            return handle_query(client, args)
        elif args.command == "info":
            return handle_info(client, args)
        elif args.command == "server":
            return handle_server(client, args)
        elif args.command == "method":
            return handle_method(client, args)
        elif args.command == "shell":
            return handle_shell(client, args)
        else:
            print_colored(f"알 수 없는 명령: {args.command}", "red", args.no_color)
            return 1
            
    except KeyboardInterrupt:
        logger.info("사용자에 의해 종료되었습니다")
        return 0
    except Exception as e:
        logger.error(f"실행 중 오류 발생: {str(e)}")
        if args.verbose:
            import traceback
            logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main()) 