"""
LogosAI Code Generation Module

This module provides code generation capabilities for the LogosAI framework,
supporting both agent class generation and standalone function generation.

Part of the Self-Growing capability in the Agent Self-Evolution System.

Usage:
    # Traditional mode (requires pre-defined rules)
    from logosai.generation import FunctionGenerator
    generator = FunctionGenerator()
    code = generator.generate(...)

    # LLM mode (infers everything from natural language)
    from logosai.generation import FunctionGenerator, LLMAnalyzer
    generator = FunctionGenerator(use_llm=True)
    code = await generator.generate_from_query("고객 이탈 확률 계산 에이전트")
"""

from .function_generator import FunctionGenerator
from .llm_analyzer import LLMAnalyzer, FunctionSpec

__all__ = ['FunctionGenerator', 'LLMAnalyzer', 'FunctionSpec']
