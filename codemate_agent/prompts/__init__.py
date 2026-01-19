"""
Prompt 管理模块

集中管理所有系统提示词。
"""

from .system_prompt import SYSTEM_PROMPT
from .agents_prompts import (
    SUBAGENT_GENERAL_PROMPT,
    SUBAGENT_EXPLORE_PROMPT,
    SUBAGENT_PLAN_PROMPT,
    SUBAGENT_SUMMARY_PROMPT,
    get_subagent_prompt,
)

__all__ = [
    "SYSTEM_PROMPT",
    "SUBAGENT_GENERAL_PROMPT",
    "SUBAGENT_EXPLORE_PROMPT",
    "SUBAGENT_PLAN_PROMPT",
    "SUBAGENT_SUMMARY_PROMPT",
    "get_subagent_prompt",
]
