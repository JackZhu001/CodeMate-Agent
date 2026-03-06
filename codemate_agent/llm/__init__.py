"""
LLM 客户端模块

支持多种 LLM API 提供商：MiniMax、OpenAI、Anthropic、GLM 等。
"""

from codemate_agent.llm.client import LLMClient

# 保留 GLMClient 别名以兼容旧代码
GLMClient = LLMClient

__all__ = ["LLMClient", "GLMClient"]
