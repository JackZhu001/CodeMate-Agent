"""
Compact 工具 - 手动触发对话压缩

参考 s06 设计：
- 允许 Agent 主动触发对话压缩
- 调用 ContextCompressor 的 auto_compact 方法
- 返回压缩结果
"""

from typing import Any, Dict, ClassVar

from codemate_agent.tools.base import Tool
from codemate_agent.context import ContextCompressor
from codemate_agent.schema import Message


class CompactTool(Tool):
    """
    手动触发对话压缩工具

    当 Agent 认为上下文过长时，可以主动调用此工具触发压缩。
    压缩会保存完整对话记录到文件，并生成摘要替换对话历史。
    """

    # 类级别引用，用于跨工具访问 compressor
    _compressor: ClassVar[ContextCompressor] = None
    _messages_ref: ClassVar[list] = None

    @classmethod
    def set_dependencies(cls, compressor: ContextCompressor, messages: list):
        """
        设置依赖

        Args:
            compressor: 上下文压缩器实例
            messages: 消息列表引用
        """
        cls._compressor = compressor
        cls._messages_ref = messages

    @property
    def name(self) -> str:
        return "compact"

    @property
    def description(self) -> str:
        return """手动触发对话上下文压缩。

当对话历史过长时使用此工具。压缩会：
1. 保存完整对话到 .transcripts/ 目录
2. 调用 LLM 生成摘要
3. 用摘要替换对话历史，释放 token 空间

参数：
- focus: 可选，指定压缩时需要保留的重点内容

注意：频繁压缩可能导致信息丢失，建议只在必要时使用。"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "压缩时需要保留的重点内容（如任务目标、关键决策等）"
                }
            },
            "required": []
        }

    def run(self, **kwargs) -> str:
        """
        执行压缩

        Args:
            focus: 压缩时需要保留的重点内容

        Returns:
            压缩结果描述
        """
        focus = kwargs.get("focus", "")

        # 检查依赖是否设置
        if not CompactTool._compressor or not CompactTool._messages_ref:
            return "错误：压缩工具未正确初始化"

        try:
            # 获取当前消息列表
            messages = CompactTool._messages_ref

            if not messages or len(messages) < 5:
                return "对话历史过短，无需压缩"

            # 执行自动压缩
            original_count = len(messages)
            compressed_messages = CompactTool._compressor.auto_compact(messages)

            # 更新消息列表引用
            CompactTool._messages_ref[:] = compressed_messages

            # 统计信息
            new_count = len(compressed_messages)
            saved = original_count - new_count

            return f"""✅ 对话压缩完成！

压缩前: {original_count} 条消息
压缩后: {new_count} 条消息
节省: {saved} 条

完整对话已保存到 .transcripts/ 目录，LLM 已生成摘要继续执行。"""

        except Exception as e:
            return f"压缩失败: {str(e)}"
