"""
LogosAI Agent Development Utilities

이 모듈은 에이전트 개발을 위한 유틸리티 함수와 헬퍼 클래스를 제공합니다.
"""

import json
import re
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from loguru import logger
import aiohttp
import asyncio


class MarkdownFormatter:
    """마크다운 포맷팅 유틸리티"""
    
    @staticmethod
    def create_header(text: str, level: int = 1) -> str:
        """헤더 생성"""
        return f"{'#' * level} {text}\n\n"
    
    @staticmethod
    def create_list(items: List[str], ordered: bool = False) -> str:
        """목록 생성"""
        result = ""
        for i, item in enumerate(items, 1):
            prefix = f"{i}." if ordered else "-"
            result += f"{prefix} {item}\n"
        return result + "\n"
    
    @staticmethod
    def create_table(headers: List[str], rows: List[List[str]]) -> str:
        """테이블 생성"""
        # 헤더
        table = "| " + " | ".join(headers) + " |\n"
        table += "| " + " | ".join(["-" * len(h) for h in headers]) + " |\n"
        
        # 행
        for row in rows:
            table += "| " + " | ".join(str(cell) for cell in row) + " |\n"
        
        return table + "\n"
    
    @staticmethod
    def create_code_block(code: str, language: str = "") -> str:
        """코드 블록 생성"""
        return f"```{language}\n{code}\n```\n\n"
    
    @staticmethod
    def create_quote(text: str) -> str:
        """인용문 생성"""
        lines = text.strip().split('\n')
        return '\n'.join(f"> {line}" for line in lines) + "\n\n"
    
    @staticmethod
    def create_details(summary: str, content: str) -> str:
        """접을 수 있는 섹션 생성"""
        return f"<details>\n<summary>{summary}</summary>\n\n{content}\n</details>\n\n"
    
    @staticmethod
    def bold(text: str) -> str:
        """굵은 글씨"""
        return f"**{text}**"
    
    @staticmethod
    def italic(text: str) -> str:
        """기울임 글씨"""
        return f"*{text}*"
    
    @staticmethod
    def link(text: str, url: str) -> str:
        """링크 생성"""
        return f"[{text}]({url})"
    
    @staticmethod
    def image(alt_text: str, url: str, title: str = "") -> str:
        """이미지 생성"""
        if title:
            return f'![{alt_text}]({url} "{title}")'
        return f"![{alt_text}]({url})"


class ResponseBuilder:
    """표준화된 응답 생성 헬퍼"""
    
    def __init__(self):
        self.md = MarkdownFormatter()
        self.content = ""
    
    def add_header(self, text: str, level: int = 1) -> 'ResponseBuilder':
        """헤더 추가"""
        self.content += self.md.create_header(text, level)
        return self
    
    def add_text(self, text: str) -> 'ResponseBuilder':
        """텍스트 추가"""
        self.content += f"{text}\n\n"
        return self
    
    def add_list(self, items: List[str], ordered: bool = False) -> 'ResponseBuilder':
        """목록 추가"""
        self.content += self.md.create_list(items, ordered)
        return self
    
    def add_table(self, headers: List[str], rows: List[List[str]]) -> 'ResponseBuilder':
        """테이블 추가"""
        self.content += self.md.create_table(headers, rows)
        return self
    
    def add_code(self, code: str, language: str = "") -> 'ResponseBuilder':
        """코드 블록 추가"""
        self.content += self.md.create_code_block(code, language)
        return self
    
    def add_quote(self, text: str) -> 'ResponseBuilder':
        """인용문 추가"""
        self.content += self.md.create_quote(text)
        return self
    
    def add_separator(self) -> 'ResponseBuilder':
        """구분선 추가"""
        self.content += "---\n\n"
        return self
    
    def build(self) -> str:
        """최종 콘텐츠 반환"""
        return self.content.strip()


class QueryParser:
    """쿼리 파싱 유틸리티"""
    
    @staticmethod
    def extract_numbers(text: str) -> List[float]:
        """텍스트에서 숫자 추출"""
        # 정수와 소수 모두 추출
        pattern = r'-?\d+\.?\d*'
        matches = re.findall(pattern, text)
        return [float(m) for m in matches]
    
    @staticmethod
    def extract_dates(text: str) -> List[str]:
        """텍스트에서 날짜 추출"""
        # 다양한 날짜 형식 지원
        patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
            r'\d{2}\.\d{2}\.\d{4}',  # DD.MM.YYYY
            r'\d{4}년 \d{1,2}월 \d{1,2}일',  # Korean format
        ]
        
        dates = []
        for pattern in patterns:
            dates.extend(re.findall(pattern, text))
        return dates
    
    @staticmethod
    def extract_urls(text: str) -> List[str]:
        """텍스트에서 URL 추출"""
        pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        return re.findall(pattern, text)
    
    @staticmethod
    def extract_emails(text: str) -> List[str]:
        """텍스트에서 이메일 추출"""
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return re.findall(pattern, text)
    
    @staticmethod
    def extract_keywords(text: str, stopwords: List[str] = None) -> List[str]:
        """텍스트에서 키워드 추출"""
        if stopwords is None:
            stopwords = ['의', '를', '을', '은', '는', '이', '가', '에', '에서', '으로', '와', '과']
        
        # 단어 분리
        words = re.findall(r'\w+', text.lower())
        
        # 불용어 제거 및 중복 제거
        keywords = []
        seen = set()
        for word in words:
            if word not in stopwords and word not in seen and len(word) > 1:
                keywords.append(word)
                seen.add(word)
        
        return keywords


class APIClient:
    """비동기 API 클라이언트 헬퍼"""
    
    def __init__(self, base_url: str = "", timeout: int = 30):
        self.base_url = base_url
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def request(
        self,
        method: str,
        endpoint: str,
        headers: Dict[str, str] = None,
        params: Dict[str, Any] = None,
        json_data: Dict[str, Any] = None,
        retry_count: int = 3
    ) -> Union[Dict[str, Any], List[Any]]:
        """API 요청 실행"""
        if not self.session:
            raise RuntimeError("APIClient를 async with 문과 함께 사용하세요")
        
        url = f"{self.base_url}{endpoint}" if self.base_url else endpoint
        
        for attempt in range(retry_count):
            try:
                async with self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data
                ) as response:
                    response.raise_for_status()
                    
                    # JSON 응답 시도
                    try:
                        return await response.json()
                    except (json.JSONDecodeError, ValueError):
                        # JSON이 아닌 경우 텍스트 반환
                        return {"text": await response.text()}
                        
            except aiohttp.ClientError as e:
                if attempt == retry_count - 1:
                    logger.error(f"API 요청 실패: {str(e)}")
                    raise
                await asyncio.sleep(2 ** attempt)


class ConfigValidator:
    """에이전트 설정 검증 유틸리티"""
    
    @staticmethod
    def validate_config(config: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
        """설정 검증
        
        Args:
            config: 검증할 설정
            schema: 스키마 정의
            
        Returns:
            오류 메시지 리스트 (비어있으면 검증 성공)
        """
        errors = []
        
        for key, spec in schema.items():
            # 필수 필드 검사
            if spec.get("required", False) and key not in config:
                errors.append(f"필수 필드 '{key}'가 없습니다")
                continue
            
            if key not in config:
                continue
            
            value = config[key]
            
            # 타입 검사
            if "type" in spec:
                expected_type = spec["type"]
                if expected_type == "string" and not isinstance(value, str):
                    errors.append(f"'{key}'는 문자열이어야 합니다")
                elif expected_type == "integer" and not isinstance(value, int):
                    errors.append(f"'{key}'는 정수여야 합니다")
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    errors.append(f"'{key}'는 숫자여야 합니다")
                elif expected_type == "boolean" and not isinstance(value, bool):
                    errors.append(f"'{key}'는 불리언이어야 합니다")
                elif expected_type == "array" and not isinstance(value, list):
                    errors.append(f"'{key}'는 배열이어야 합니다")
                elif expected_type == "object" and not isinstance(value, dict):
                    errors.append(f"'{key}'는 객체여야 합니다")
            
            # 값 범위 검사
            if "min" in spec and isinstance(value, (int, float)) and value < spec["min"]:
                errors.append(f"'{key}'는 {spec['min']} 이상이어야 합니다")
            if "max" in spec and isinstance(value, (int, float)) and value > spec["max"]:
                errors.append(f"'{key}'는 {spec['max']} 이하여야 합니다")
            
            # 선택 옵션 검사
            if "enum" in spec and value not in spec["enum"]:
                errors.append(f"'{key}'는 다음 중 하나여야 합니다: {spec['enum']}")
        
        return errors


class PerformanceMonitor:
    """성능 모니터링 유틸리티"""
    
    def __init__(self):
        self.metrics = {
            "request_count": 0,
            "total_time": 0.0,
            "min_time": float('inf'),
            "max_time": 0.0,
            "errors": 0
        }
    
    def record_request(self, duration: float, success: bool = True):
        """요청 기록"""
        self.metrics["request_count"] += 1
        self.metrics["total_time"] += duration
        self.metrics["min_time"] = min(self.metrics["min_time"], duration)
        self.metrics["max_time"] = max(self.metrics["max_time"], duration)
        
        if not success:
            self.metrics["errors"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """통계 반환"""
        count = self.metrics["request_count"]
        if count == 0:
            return {
                "request_count": 0,
                "average_time": 0.0,
                "min_time": 0.0,
                "max_time": 0.0,
                "error_rate": 0.0
            }
        
        return {
            "request_count": count,
            "average_time": self.metrics["total_time"] / count,
            "min_time": self.metrics["min_time"],
            "max_time": self.metrics["max_time"],
            "error_rate": self.metrics["errors"] / count
        }
    
    def reset(self):
        """메트릭 초기화"""
        self.__init__()


def create_test_harness(agent_class, test_queries: List[Union[str, Dict[str, Any]]]):
    """에이전트 테스트 하네스 생성"""
    
    async def run_tests():
        """테스트 실행"""
        agent = agent_class()
        monitor = PerformanceMonitor()
        
        try:
            # 초기화
            logger.info(f"🚀 {agent.name} 초기화 중...")
            await agent.initialize()
            
            # 각 쿼리 테스트
            for i, query in enumerate(test_queries, 1):
                logger.info(f"\n{'='*50}")
                logger.info(f"테스트 {i}: {query if isinstance(query, str) else query.get('query', query)}")
                logger.info(f"{'='*50}")
                
                start_time = asyncio.get_event_loop().time()
                try:
                    response = await agent.process(query)
                    duration = asyncio.get_event_loop().time() - start_time
                    
                    logger.info(f"✅ 성공 (처리 시간: {duration:.2f}초)")
                    logger.info(f"응답 타입: {response.type}")
                    
                    # 응답 내용 출력 (길면 잘라서)
                    content_str = json.dumps(response.content, ensure_ascii=False, indent=2)
                    if len(content_str) > 500:
                        content_str = content_str[:500] + "..."
                    logger.info(f"응답 내용:\n{content_str}")
                    
                    monitor.record_request(duration, True)
                    
                except Exception as e:
                    duration = asyncio.get_event_loop().time() - start_time
                    logger.error(f"❌ 실패: {str(e)}")
                    monitor.record_request(duration, False)
            
            # 통계 출력
            stats = monitor.get_stats()
            logger.info(f"\n{'='*50}")
            logger.info("📊 테스트 통계")
            logger.info(f"{'='*50}")
            logger.info(f"총 요청 수: {stats['request_count']}")
            logger.info(f"평균 처리 시간: {stats['average_time']:.2f}초")
            logger.info(f"최소 처리 시간: {stats['min_time']:.2f}초")
            logger.info(f"최대 처리 시간: {stats['max_time']:.2f}초")
            logger.info(f"오류율: {stats['error_rate']:.1%}")
            
        finally:
            # 정리
            await agent.shutdown()
    
    return run_tests