"""
子代理模块（向后兼容）

已移动到 codemate_agent.tools.task，这里保留导出以保持兼容性。
"""

# 从新位置导入
from codemate_agent.tools.task import (
    TaskTool,
    SubagentRunner,
    SubagentResult,
    TaskResponse,
    SUBAGENT_TYPES,
    ALLOWED_TOOLS,
    DENIED_TOOLS,
)

__all__ = [
    "TaskTool",
    "SubagentRunner",
    "SubagentResult",
    "TaskResponse",
    "SUBAGENT_TYPES",
    "ALLOWED_TOOLS",
    "DENIED_TOOLS",
]
