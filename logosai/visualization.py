"""
LogosAI 시각화 시스템

에이전트 결과를 자동으로 시각화하는 고급 시스템을 제공합니다.
"""

import re
import json
from typing import Dict, Any, Optional, List, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from loguru import logger


@dataclass
class ChartConfig:
    """차트 설정"""
    chart_type: str = "line"  # line, bar, pie, scatter, radar, doughnut
    title: Optional[str] = None
    x_axis_label: Optional[str] = None
    y_axis_label: Optional[str] = None
    color_scheme: str = "default"  # default, blue, green, red, rainbow
    responsive: bool = True
    animation: bool = True
    legend_position: str = "top"  # top, bottom, left, right
    custom_options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DataPattern:
    """데이터 패턴 정의"""
    pattern_type: str  # time_series, categorical, numeric, key_value
    confidence: float
    detected_fields: Dict[str, str]
    suggested_chart_type: str
    data_format: str


class DataAnalyzer:
    """데이터 분석기"""
    
    @staticmethod
    def analyze_data_structure(data: Any) -> DataPattern:
        """데이터 구조 분석"""
        try:
            if isinstance(data, dict):
                return DataAnalyzer._analyze_dict_data(data)
            elif isinstance(data, list):
                return DataAnalyzer._analyze_list_data(data)
            else:
                return DataPattern(
                    pattern_type="simple",
                    confidence=0.3,
                    detected_fields={},
                    suggested_chart_type="bar",
                    data_format="unknown"
                )
        except Exception as e:
            logger.error(f"데이터 구조 분석 실패: {e}")
            return DataPattern(
                pattern_type="unknown",
                confidence=0.0,
                detected_fields={},
                suggested_chart_type="bar",
                data_format="error"
            )
    
    @staticmethod
    def _analyze_dict_data(data: Dict[str, Any]) -> DataPattern:
        """딕셔너리 데이터 분석"""
        # 이미 Chart.js 형식인지 확인
        if 'labels' in data and 'datasets' in data:
            return DataPattern(
                pattern_type="chart_ready",
                confidence=1.0,
                detected_fields={"labels": "x_axis", "datasets": "y_data"},
                suggested_chart_type="line",
                data_format="chartjs"
            )
        
        # 시계열 데이터 패턴 확인
        time_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}',  # ISO datetime
            r'(월|화|수|목|금|토|일)요일',  # 요일 (한글)
            r'(January|February|March|April|May|June|July|August|September|October|November|December)',  # 월 (영문)
            r'(1월|2월|3월|4월|5월|6월|7월|8월|9월|10월|11월|12월)',  # 월 (한글)
        ]
        
        # 키-값 분석
        keys = list(data.keys())
        values = list(data.values())
        
        # 시간 관련 키 확인
        time_key_count = 0
        numeric_value_count = 0
        
        for key in keys:
            key_str = str(key).lower()
            if any(pattern in key_str for pattern in ['time', 'date', '시간', '날짜', 'day', 'month', 'year']):
                time_key_count += 1
            
            # 시간 패턴 매칭
            for pattern in time_patterns:
                if re.search(pattern, str(key)):
                    time_key_count += 1
                    break
        
        # 숫자 값 개수 확인
        for value in values:
            try:
                float(value)
                numeric_value_count += 1
            except (ValueError, TypeError):
                pass
        
        # 패턴 판별
        if time_key_count > 0 and numeric_value_count > len(values) * 0.7:
            return DataPattern(
                pattern_type="time_series",
                confidence=0.8 + (time_key_count / len(keys)) * 0.2,
                detected_fields={"time": "x_axis", "values": "y_axis"},
                suggested_chart_type="line",
                data_format="key_value"
            )
        
        # 온도 관련 데이터 확인
        temperature_keywords = ['온도', 'temperature', '기온', '체감온도', 'temp']
        temp_score = sum(1 for key in keys if any(kw in str(key).lower() for kw in temperature_keywords))
        
        if temp_score > 0:
            return DataPattern(
                pattern_type="temperature",
                confidence=0.9,
                detected_fields={"temperature": "y_axis"},
                suggested_chart_type="line",
                data_format="weather_data"
            )
        
        # 일반 카테고리 데이터
        if len(keys) > 1 and numeric_value_count > 0:
            return DataPattern(
                pattern_type="categorical",
                confidence=0.6,
                detected_fields={"categories": "x_axis", "values": "y_axis"},
                suggested_chart_type="bar",
                data_format="key_value"
            )
        
        return DataPattern(
            pattern_type="simple",
            confidence=0.4,
            detected_fields={},
            suggested_chart_type="bar",
            data_format="dict"
        )
    
    @staticmethod
    def _analyze_list_data(data: List[Any]) -> DataPattern:
        """리스트 데이터 분석"""
        if not data:
            return DataPattern(
                pattern_type="empty",
                confidence=0.0,
                detected_fields={},
                suggested_chart_type="bar",
                data_format="empty"
            )
        
        # 첫 번째 요소로 구조 판단
        first_item = data[0]
        
        if isinstance(first_item, dict):
            # 객체 배열
            keys = list(first_item.keys())
            
            # 시계열 데이터 확인
            time_fields = []
            numeric_fields = []
            
            for key in keys:
                if any(time_word in str(key).lower() for time_word in ['time', 'date', '시간', '날짜', 'day']):
                    time_fields.append(key)
                
                # 모든 항목에서 숫자인지 확인
                try:
                    all_numeric = all(isinstance(item.get(key), (int, float)) or 
                                    (isinstance(item.get(key), str) and item.get(key).replace('.', '').isdigit())
                                    for item in data)
                    if all_numeric:
                        numeric_fields.append(key)
                except (TypeError, ValueError):
                    pass
            
            if time_fields and numeric_fields:
                return DataPattern(
                    pattern_type="time_series",
                    confidence=0.9,
                    detected_fields={"time": time_fields[0], "values": numeric_fields},
                    suggested_chart_type="line",
                    data_format="object_array"
                )
            
            elif numeric_fields:
                return DataPattern(
                    pattern_type="categorical",
                    confidence=0.7,
                    detected_fields={"categories": keys[0], "values": numeric_fields},
                    suggested_chart_type="bar",
                    data_format="object_array"
                )
        
        elif isinstance(first_item, (int, float)):
            # 숫자 배열
            return DataPattern(
                pattern_type="numeric_sequence",
                confidence=0.8,
                detected_fields={"values": "y_axis"},
                suggested_chart_type="line",
                data_format="number_array"
            )
        
        return DataPattern(
            pattern_type="simple",
            confidence=0.3,
            detected_fields={},
            suggested_chart_type="bar",
            data_format="array"
        )


class ChartGenerator:
    """차트 생성기"""
    
    @staticmethod
    def generate_chart_data(data: Any, 
                          config: Optional[ChartConfig] = None,
                          pattern: Optional[DataPattern] = None) -> Dict[str, Any]:
        """Chart.js 호환 차트 데이터 생성"""
        
        if config is None:
            config = ChartConfig()
        
        if pattern is None:
            pattern = DataAnalyzer.analyze_data_structure(data)
        
        try:
            # 패턴에 따른 차트 생성
            if pattern.pattern_type == "chart_ready":
                return ChartGenerator._format_existing_chart(data, config)
            
            elif pattern.pattern_type == "time_series":
                return ChartGenerator._create_time_series_chart(data, config, pattern)
            
            elif pattern.pattern_type == "temperature":
                return ChartGenerator._create_temperature_chart(data, config, pattern)
            
            elif pattern.pattern_type == "categorical":
                return ChartGenerator._create_categorical_chart(data, config, pattern)
            
            elif pattern.pattern_type == "numeric_sequence":
                return ChartGenerator._create_sequence_chart(data, config, pattern)
            
            else:
                return ChartGenerator._create_generic_chart(data, config, pattern)
                
        except Exception as e:
            logger.error(f"차트 생성 실패: {e}")
            return ChartGenerator._create_fallback_chart(data, config)
    
    @staticmethod
    def _format_existing_chart(data: Dict[str, Any], config: ChartConfig) -> Dict[str, Any]:
        """기존 차트 데이터 포맷팅"""
        chart_data = {
            "type": config.chart_type,
            "data": data,
            "options": ChartGenerator._get_chart_options(config)
        }
        
        # 제목 추가
        if config.title:
            chart_data["options"]["plugins"]["title"] = {
                "display": True,
                "text": config.title
            }
        
        return chart_data
    
    @staticmethod
    def _create_time_series_chart(data: Any, config: ChartConfig, pattern: DataPattern) -> Dict[str, Any]:
        """시계열 차트 생성"""
        labels = []
        datasets = []
        
        if isinstance(data, dict):
            # 키-값 딕셔너리
            labels = list(data.keys())
            values = list(data.values())
            
            datasets.append({
                "label": config.y_axis_label or "Values",
                "data": values,
                "borderColor": ChartGenerator._get_color(0, config.color_scheme),
                "backgroundColor": ChartGenerator._get_background_color(0, config.color_scheme),
                "tension": 0.4
            })
        
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            # 객체 배열
            time_field = pattern.detected_fields.get("time")
            value_fields = pattern.detected_fields.get("values", [])
            
            if time_field:
                labels = [item.get(time_field) for item in data]
                
                for i, field in enumerate(value_fields[:5]):  # 최대 5개 시리즈
                    values = [item.get(field) for item in data]
                    datasets.append({
                        "label": field.replace('_', ' ').title(),
                        "data": values,
                        "borderColor": ChartGenerator._get_color(i, config.color_scheme),
                        "backgroundColor": ChartGenerator._get_background_color(i, config.color_scheme),
                        "tension": 0.4
                    })
        
        return {
            "type": "line",
            "data": {
                "labels": labels,
                "datasets": datasets
            },
            "options": ChartGenerator._get_time_series_options(config)
        }
    
    @staticmethod
    def _create_temperature_chart(data: Any, config: ChartConfig, pattern: DataPattern) -> Dict[str, Any]:
        """온도 차트 생성 (특화)"""
        if isinstance(data, dict):
            # 날씨 데이터 특별 처리
            chart_data = ChartGenerator._create_time_series_chart(data, config, pattern)
            
            # 온도 차트 특별 옵션
            chart_data["options"]["scales"]["y"]["title"] = {
                "display": True,
                "text": "온도 (°C)"
            }
            
            # 온도 범위에 따른 색상
            for dataset in chart_data["data"]["datasets"]:
                if "온도" in dataset["label"] or "temperature" in dataset["label"].lower():
                    dataset["borderColor"] = "rgb(255, 99, 132)"
                    dataset["backgroundColor"] = "rgba(255, 99, 132, 0.2)"
                elif "체감" in dataset["label"] or "apparent" in dataset["label"].lower():
                    dataset["borderColor"] = "rgb(54, 162, 235)"
                    dataset["backgroundColor"] = "rgba(54, 162, 235, 0.2)"
            
            return chart_data
        
        return ChartGenerator._create_time_series_chart(data, config, pattern)
    
    @staticmethod
    def _create_categorical_chart(data: Any, config: ChartConfig, pattern: DataPattern) -> Dict[str, Any]:
        """카테고리 차트 생성"""
        labels = []
        values = []
        
        if isinstance(data, dict):
            labels = list(data.keys())
            values = list(data.values())
        
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            # 객체 배열에서 첫 번째 필드를 라벨로, 숫자 필드를 값으로
            category_field = list(data[0].keys())[0]
            value_fields = pattern.detected_fields.get("values", [])
            
            if value_fields:
                labels = [item.get(category_field) for item in data]
                values = [item.get(value_fields[0]) for item in data]
        
        return {
            "type": config.chart_type or "bar",
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": config.y_axis_label or "Values",
                    "data": values,
                    "backgroundColor": [
                        ChartGenerator._get_background_color(i, config.color_scheme) 
                        for i in range(len(values))
                    ],
                    "borderColor": [
                        ChartGenerator._get_color(i, config.color_scheme) 
                        for i in range(len(values))
                    ],
                    "borderWidth": 1
                }]
            },
            "options": ChartGenerator._get_chart_options(config)
        }
    
    @staticmethod
    def _create_sequence_chart(data: List[Union[int, float]], config: ChartConfig, pattern: DataPattern) -> Dict[str, Any]:
        """수치 시퀀스 차트 생성"""
        labels = [f"Point {i+1}" for i in range(len(data))]
        
        return {
            "type": "line",
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": config.y_axis_label or "Values",
                    "data": data,
                    "borderColor": ChartGenerator._get_color(0, config.color_scheme),
                    "backgroundColor": ChartGenerator._get_background_color(0, config.color_scheme),
                    "tension": 0.4
                }]
            },
            "options": ChartGenerator._get_chart_options(config)
        }
    
    @staticmethod
    def _create_generic_chart(data: Any, config: ChartConfig, pattern: DataPattern) -> Dict[str, Any]:
        """일반 차트 생성"""
        return {
            "type": config.chart_type,
            "data": {
                "labels": ["Data"],
                "datasets": [{
                    "label": "Values",
                    "data": [1],
                    "backgroundColor": ChartGenerator._get_background_color(0, config.color_scheme)
                }]
            },
            "options": ChartGenerator._get_chart_options(config)
        }
    
    @staticmethod
    def _create_fallback_chart(data: Any, config: ChartConfig) -> Dict[str, Any]:
        """폴백 차트 생성"""
        return {
            "type": "bar",
            "data": {
                "labels": ["Error"],
                "datasets": [{
                    "label": "Chart Generation Error",
                    "data": [0],
                    "backgroundColor": "rgba(255, 0, 0, 0.2)",
                    "borderColor": "rgba(255, 0, 0, 1)"
                }]
            },
            "options": {
                "responsive": True,
                "plugins": {
                    "title": {
                        "display": True,
                        "text": "차트 생성 오류"
                    }
                }
            }
        }
    
    @staticmethod
    def _get_chart_options(config: ChartConfig) -> Dict[str, Any]:
        """기본 차트 옵션"""
        options = {
            "responsive": config.responsive,
            "animation": {
                "duration": 1000 if config.animation else 0
            },
            "plugins": {
                "legend": {
                    "position": config.legend_position
                }
            }
        }
        
        if config.title:
            options["plugins"]["title"] = {
                "display": True,
                "text": config.title
            }
        
        # 축 레이블
        if config.x_axis_label or config.y_axis_label:
            options["scales"] = {}
            
            if config.x_axis_label:
                options["scales"]["x"] = {
                    "title": {
                        "display": True,
                        "text": config.x_axis_label
                    }
                }
            
            if config.y_axis_label:
                options["scales"]["y"] = {
                    "title": {
                        "display": True,
                        "text": config.y_axis_label
                    }
                }
        
        # 커스텀 옵션 병합
        if config.custom_options:
            options.update(config.custom_options)
        
        return options
    
    @staticmethod
    def _get_time_series_options(config: ChartConfig) -> Dict[str, Any]:
        """시계열 차트 전용 옵션"""
        options = ChartGenerator._get_chart_options(config)
        
        # 시간 축 설정 (필요한 경우)
        if "scales" not in options:
            options["scales"] = {}
        
        options["scales"]["x"] = {
            "title": {
                "display": True,
                "text": config.x_axis_label or "Time"
            }
        }
        
        return options
    
    @staticmethod
    def _get_color(index: int, scheme: str) -> str:
        """색상 스키마에 따른 색상 반환"""
        colors = {
            "default": [
                "rgb(75, 192, 192)",
                "rgb(255, 99, 132)", 
                "rgb(54, 162, 235)",
                "rgb(255, 205, 86)",
                "rgb(153, 102, 255)"
            ],
            "blue": [
                "rgb(54, 162, 235)",
                "rgb(28, 120, 200)", 
                "rgb(100, 180, 255)",
                "rgb(0, 100, 180)",
                "rgb(150, 200, 255)"
            ],
            "green": [
                "rgb(75, 192, 192)",
                "rgb(40, 160, 140)",
                "rgb(100, 220, 200)",
                "rgb(50, 150, 120)",
                "rgb(120, 240, 220)"
            ],
            "red": [
                "rgb(255, 99, 132)",
                "rgb(220, 60, 100)",
                "rgb(255, 130, 160)",
                "rgb(200, 40, 80)",
                "rgb(255, 160, 180)"
            ],
            "rainbow": [
                "rgb(255, 99, 132)",  # 빨강
                "rgb(255, 159, 64)",  # 주황
                "rgb(255, 205, 86)",  # 노랑
                "rgb(75, 192, 192)",  # 청록
                "rgb(54, 162, 235)",  # 파랑
                "rgb(153, 102, 255)", # 보라
                "rgb(201, 203, 207)"  # 회색
            ]
        }
        
        color_list = colors.get(scheme, colors["default"])
        return color_list[index % len(color_list)]
    
    @staticmethod
    def _get_background_color(index: int, scheme: str) -> str:
        """반투명 배경 색상 반환"""
        color = ChartGenerator._get_color(index, scheme)
        # rgb(r, g, b)를 rgba(r, g, b, 0.2)로 변환
        return color.replace("rgb(", "rgba(").replace(")", ", 0.2)")


class VisualizationEngine:
    """시각화 엔진 (메인 인터페이스)"""
    
    def __init__(self):
        self.analyzer = DataAnalyzer()
        self.generator = ChartGenerator()
    
    def auto_visualize(self, 
                      data: Any,
                      title: Optional[str] = None,
                      chart_type: Optional[str] = None,
                      **config_kwargs) -> Optional[Dict[str, Any]]:
        """자동 시각화
        
        Args:
            data: 시각화할 데이터
            title: 차트 제목
            chart_type: 강제 차트 타입
            **config_kwargs: 추가 설정
        
        Returns:
            Chart.js 호환 차트 데이터
        """
        try:
            # 데이터 패턴 분석
            pattern = self.analyzer.analyze_data_structure(data)
            
            # 차트 설정 구성
            config = ChartConfig(
                chart_type=chart_type or pattern.suggested_chart_type,
                title=title,
                **config_kwargs
            )
            
            # 차트 생성
            chart_data = self.generator.generate_chart_data(data, config, pattern)
            
            # 메타데이터 추가
            chart_data["metadata"] = {
                "pattern_detected": pattern.pattern_type,
                "confidence": pattern.confidence,
                "auto_generated": True,
                "generation_time": datetime.now().isoformat()
            }
            
            logger.info(f"자동 시각화 완료: {pattern.pattern_type} -> {config.chart_type}")
            return chart_data
            
        except Exception as e:
            logger.error(f"자동 시각화 실패: {e}")
            return None
    
    def create_weather_chart(self, weather_data: Dict[str, Any], location: str) -> Optional[Dict[str, Any]]:
        """날씨 전용 차트 생성"""
        config = ChartConfig(
            chart_type="line",
            title=f"{location} 온도 변화",
            x_axis_label="시간",
            y_axis_label="온도 (°C)",
            color_scheme="blue"
        )
        
        pattern = DataPattern(
            pattern_type="temperature",
            confidence=1.0,
            detected_fields={"temperature": "y_axis"},
            suggested_chart_type="line",
            data_format="weather_data"
        )
        
        return self.generator.generate_chart_data(weather_data, config, pattern)
    
    def create_comparison_chart(self, 
                               data: Dict[str, List[float]],
                               title: str = "비교 차트") -> Optional[Dict[str, Any]]:
        """비교 차트 생성"""
        config = ChartConfig(
            chart_type="bar",
            title=title,
            color_scheme="rainbow"
        )
        
        try:
            labels = list(data.keys())
            max_length = max(len(values) for values in data.values())
            chart_labels = [f"항목 {i+1}" for i in range(max_length)]
            
            datasets = []
            for i, (label, values) in enumerate(data.items()):
                datasets.append({
                    "label": label,
                    "data": values,
                    "backgroundColor": ChartGenerator._get_background_color(i, "rainbow"),
                    "borderColor": ChartGenerator._get_color(i, "rainbow"),
                    "borderWidth": 1
                })
            
            return {
                "type": "bar",
                "data": {
                    "labels": chart_labels,
                    "datasets": datasets
                },
                "options": ChartGenerator._get_chart_options(config)
            }
            
        except Exception as e:
            logger.error(f"비교 차트 생성 실패: {e}")
            return None


# 싱글톤 인스턴스
_visualization_engine: Optional[VisualizationEngine] = None


def get_visualization_engine() -> VisualizationEngine:
    """시각화 엔진 싱글톤 반환"""
    global _visualization_engine
    if _visualization_engine is None:
        _visualization_engine = VisualizationEngine()
    return _visualization_engine


# 편의 함수들
def auto_chart(data: Any, **kwargs) -> Optional[Dict[str, Any]]:
    """빠른 자동 차트 생성"""
    engine = get_visualization_engine()
    return engine.auto_visualize(data, **kwargs)


def weather_chart(weather_data: Dict[str, Any], location: str) -> Optional[Dict[str, Any]]:
    """날씨 차트 빠른 생성"""
    engine = get_visualization_engine()
    return engine.create_weather_chart(weather_data, location)


def comparison_chart(data: Dict[str, List[float]], title: str = "비교") -> Optional[Dict[str, Any]]:
    """비교 차트 빠른 생성"""
    engine = get_visualization_engine()
    return engine.create_comparison_chart(data, title)


# 사용 예제
if __name__ == "__main__":
    # 예제 데이터
    sample_weather_data = {
        "2023-07-01": 25.5,
        "2023-07-02": 27.2,
        "2023-07-03": 26.8,
        "2023-07-04": 24.9,
        "2023-07-05": 23.1,
        "2023-07-06": 22.8,
        "2023-07-07": 24.3
    }
    
    # 자동 시각화 테스트
    chart = auto_chart(
        data=sample_weather_data,
        title="서울 일주일 온도",
        chart_type="line"
    )
    
    if chart:
        logger.info("차트 생성 성공!")
        logger.info(f"타입: {chart['type']}")
        logger.info(f"라벨 수: {len(chart['data']['labels'])}")
        logger.info(f"데이터셋 수: {len(chart['data']['datasets'])}")
    else:
        logger.error("차트 생성 실패")