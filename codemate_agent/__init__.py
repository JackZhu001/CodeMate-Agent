"""
CodeMate AI - 基于 Function Calling 范式的代码分析 Agent

使用 GLM/MiniMax API 实现智能代码分析、项目理解和重构建议。
"""

__version__ = "0.3.0"

from codemate_agent.agent import CodeMateAgent
from codemate_agent.llm import LLMClient, GLMClient
from codemate_agent.tools import get_all_tools

__all__ = [
    "CodeMateAgent",
    "LLMClient",
    "GLMClient",
    "get_all_tools",
]

# 保留旧名称以兼容
ReActAgent = CodeMateAgent
