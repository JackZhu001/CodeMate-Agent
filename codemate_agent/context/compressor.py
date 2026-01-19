"""
上下文压缩器

当对话历史过长时，自动压缩旧消息为摘要。
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from ..schema import Message
from ..logging import setup_logger
from ..tools.todo.todo_write import TodoWriteTool


# 默认配置
DEFAULT_CONTEXT_WINDOW = 10000  # GLM-4 上下文窗口
DEFAULT_COMPRESSION_THRESHOLD = 0.8  # 80% 触发压缩
DEFAULT_MIN_RETAIN_ROUNDS = 5  # 最少保留轮次（降低以便更早触发压缩）


@dataclass
class CompressionConfig:
    """压缩配置"""

    context_window: int = DEFAULT_CONTEXT_WINDOW
    compression_threshold: float = DEFAULT_COMPRESSION_THRESHOLD
    min_retain_rounds: int = DEFAULT_MIN_RETAIN_ROUNDS

    @classmethod
    def from_env(cls) -> "CompressionConfig":
        """从环境变量加载配置"""
        return cls(
            context_window=int(os.getenv("CONTEXT_WINDOW", str(DEFAULT_CONTEXT_WINDOW))),
            compression_threshold=float(os.getenv("COMPRESSION_THRESHOLD", str(DEFAULT_COMPRESSION_THRESHOLD))),
            min_retain_rounds=int(os.getenv("MIN_RETAIN_ROUNDS", str(DEFAULT_MIN_RETAIN_ROUNDS))),
        )


@dataclass
class CompressionRecord:
    """压缩操作记录"""

    timestamp: datetime = field(default_factory=datetime.now)
    total_messages: int = 0
    rounds_compressed: int = 0
    rounds_retained: int = 0
    summary_length: int = 0
    compression_ratio: float = 0.0
    summary_preview: str = ""

    def __str__(self) -> str:
        time_str = self.timestamp.strftime("%H:%M:%S")
        return (
            f"[{time_str}] 压缩记录: {self.total_messages} → "
            f"{self.total_messages - self.rounds_compressed * 3} 条消息 "
            f"({self.rounds_compressed} 轮), 压缩率 {self.compression_ratio:.1%}"
        )


class ContextCompressor:
    """
    上下文压缩器

    当对话历史超过阈值时，将旧消息压缩为摘要。
    """

    # 摘要提示词模板
    SUMMARY_PROMPT = """请将以下对话历史压缩为简洁的摘要。

要求：
1. 保留用户的主要意图和需求
2. 记录已完成的关键操作和结果
3. 省略细节过程
4. 使用 Markdown 格式

对话历史：
{history}

请生成摘要："""

    def __init__(
        self,
        config: Optional[CompressionConfig] = None,
        llm_client=None,
    ):
        """
        初始化压缩器

        Args:
            config: 压缩配置
            llm_client: LLM 客户端（用于生成摘要）
        """
        self.config = config or CompressionConfig.from_env()
        self.llm = llm_client
        self.logger = setup_logger("codemate.compressor")
        # 压缩历史记录
        self.compression_history: List[CompressionRecord] = []
        # 最大历史记录数
        self.max_history_size = 20

    def get_compression_history(self) -> List[CompressionRecord]:
        """获取压缩历史记录"""
        return self.compression_history.copy()

    def print_compression_history(self) -> None:
        """打印压缩历史"""
        if not self.compression_history:
            self.logger.info("暂无压缩历史记录")
            return

        self.logger.info(f"=== 压缩历史 (共 {len(self.compression_history)} 次) ===")
        for record in self.compression_history:
            self.logger.info(str(record))

    def _record_compression(
        self,
        total_messages: int,
        rounds_compressed: int,
        rounds_retained: int,
        summary_length: int,
        result_count: int,
    ) -> None:
        """
        记录压缩操作

        Args:
            total_messages: 压缩前的消息总数
            rounds_compressed: 压缩的轮次数
            rounds_retained: 保留的轮次数
            summary_length: 摘要长度
            result_count: 压缩后的消息数
        """
        # 计算压缩率
        compression_ratio = (total_messages - result_count) / total_messages if total_messages > 0 else 0

        # 获取摘要预览（前 100 字符）
        summary_preview = ""
        if summary_length > 0:
            # 这里无法访问实际摘要内容，只记录长度
            summary_preview = f"摘要长度: {summary_length} 字符"

        record = CompressionRecord(
            total_messages=total_messages,
            rounds_compressed=rounds_compressed,
            rounds_retained=rounds_retained,
            summary_length=summary_length,
            compression_ratio=compression_ratio,
            summary_preview=summary_preview,
        )

        self.compression_history.append(record)

        # 限制历史记录大小
        if len(self.compression_history) > self.max_history_size:
            self.compression_history.pop(0)

        self.logger.debug(f"已记录压缩历史: {record}")

    def should_compress(
        self,
        messages: List[Message],
        last_usage_tokens: int = 0,
        pending_input: str = "",
    ) -> bool:
        """
        判断是否需要压缩

        Args:
            messages: 当前消息列表
            last_usage_tokens: 上一次 API 调用的 token 数
            pending_input: 待发送的用户输入

        Returns:
            是否需要压缩
        """
        # 至少需要一定数量的消息才考虑压缩
        if len(messages) < 3:
            return False

        # 估算输入 token 数（粗略：1 字符 ≈ 1/3 token）
        input_estimate = len(pending_input) // 3

        # 估算总 token 数
        estimated_total = last_usage_tokens + input_estimate

        # 检查是否超过阈值
        threshold = int(self.config.context_window * self.config.compression_threshold)

        return estimated_total >= threshold

    def compress(self, messages: List[Message]) -> List[Message]:
        """
        压缩消息列表

        Args:
            messages: 原始消息列表

        Returns:
            压缩后的消息列表
        """
        if len(messages) < 3:
            return messages

        # 1. 分离 system 消息
        system_msg = None
        other_messages = []
        for msg in messages:
            if msg.role == "system":
                system_msg = msg
            else:
                other_messages.append(msg)

        # 2. 识别轮次和现有摘要
        rounds = self._identify_rounds(other_messages)
        existing_summaries = self._extract_summaries(other_messages)

        # 添加调试日志
        self.logger.info(
            f"压缩检查: 总消息数={len(messages)}, 识别轮数={len(rounds)}, "
            f"min_retain={self.config.min_retain_rounds}"
        )

        # 3. 计算保留区
        # 只有当轮次明显多于保留轮数时才压缩（至少保留 min_retain_rounds + 1 轮）
        threshold = self.config.min_retain_rounds + 1
        if len(rounds) <= threshold:
            # 轮次太少，不压缩
            self.logger.info(
                f"跳过压缩: 轮数({len(rounds)}) <= 阈值({threshold})"
            )
            return messages

        # 确保保留至少 min_retain_rounds 轮，但至少留 1 轮用于压缩
        min_rounds = min(self.config.min_retain_rounds, len(rounds) - 1)

        retain_start_idx = len(rounds) - min_rounds
        compress_rounds = rounds[:retain_start_idx]

        self.logger.info(
            f"执行压缩: 保留 {min_rounds} 轮 (索引 {retain_start_idx}-{len(rounds)-1}), "
            f"压缩 {len(compress_rounds)} 轮 (索引 0-{retain_start_idx-1})"
        )

        # 4. 获取压缩区的消息（上面已定义 compress_rounds）
        retain_messages = self._rounds_to_messages(rounds[retain_start_idx:])

        # 5. 生成摘要
        summary_content = self._generate_summary(compress_rounds, existing_summaries)

        # 6. 重建消息列表
        result = []
        if system_msg:
            result.append(system_msg)

        # 添加旧摘要
        for summary in existing_summaries:
            result.append(summary)

        # 添加新摘要（如果生成成功）
        if summary_content:
            result.append(Message(role="system", content=f"[历史摘要]\n{summary_content}"))
            self.logger.info(f"已压缩 {len(compress_rounds)} 轮对话为摘要")
        else:
            self.logger.info(f"已压缩 {len(compress_rounds)} 轮对话（未生成摘要）")

        # 注入当前 TODO 状态（如果有）
        todo_state = TodoWriteTool.get_current_state()
        if todo_state:
            result.append(Message(
                role="system",
                content=f"[当前任务进度]\n{todo_state['formatted']}"
            ))
            self.logger.info("已注入当前 TODO 状态到压缩上下文")

        # 记录压缩历史（无论是否生成摘要）
        self._record_compression(
            total_messages=len(messages),
            rounds_compressed=len(compress_rounds),
            rounds_retained=min_rounds,
            summary_length=len(summary_content) if summary_content else 0,
            result_count=len(result),
        )

        # 添加保留的消息
        result.extend(retain_messages)

        return result

    def _identify_rounds(self, messages: List[Message]) -> List[List[Message]]:
        """
        识别对话轮次

        一轮 = 从 user 消息开始，到下一个 user 消息之前结束

        Args:
            messages: 消息列表（不含 system）

        Returns:
            轮次列表
        """
        rounds = []
        current_round = []

        for msg in messages:
            if msg.role == "user":
                # 保存上一轮
                if current_round:
                    rounds.append(current_round)
                # 开始新一轮
                current_round = [msg]
            elif msg.role == "summary":
                # 摘要消息不属于任何轮次
                if current_round:
                    rounds.append(current_round)
                rounds.append([msg])  # 单独一轮
                current_round = []
            else:
                # assistant, tool 消息加入当前轮
                if current_round or msg.role == "assistant":
                    current_round.append(msg)

        # 最后一轮
        if current_round:
            rounds.append(current_round)

        return rounds

    def _extract_summaries(self, messages: List[Message]) -> List[Message]:
        """提取现有的摘要消息"""
        return [m for m in messages if m.role == "summary"]

    def _rounds_to_messages(self, rounds: List[List[Message]]) -> List[Message]:
        """将轮次转换为扁平消息列表"""
        result = []
        for round_msg in rounds:
            result.extend(round_msg)
        return result

    def _generate_summary(
        self,
        rounds: List[List[Message]],
        existing_summaries: List[Message],
    ) -> Optional[str]:
        """
        生成摘要

        Args:
            rounds: 要压缩的轮次
            existing_summaries: 现有摘要

        Returns:
            生成的摘要内容，失败返回 None
        """
        if not rounds:
            return None

        # 如果没有 LLM 客户端，返回 None
        if not self.llm:
            self.logger.warning("LLM 客户端未配置，跳过摘要生成")
            return None

        # 构建历史文本
        history_parts = []

        # 添加现有摘要
        for summary in existing_summaries:
            history_parts.append(f"[旧摘要] {summary.content}")

        # 添加轮次内容
        for i, round_msg in enumerate(rounds):
            round_text = self._format_round(round_msg)
            history_parts.append(f"[轮次 {i + 1}]\n{round_text}")

        history_text = "\n\n".join(history_parts)

        try:
            # 调用 LLM 生成摘要
            prompt = self.SUMMARY_PROMPT.format(history=history_text[:8000])  # 限制输入长度

            response = self.llm.complete(
                messages=[Message(role="user", content=prompt)],
                tools=None,
            )

            summary = response.content.strip() if response.content else None

            if summary:
                self.logger.info(f"摘要生成成功，长度: {len(summary)}")
            else:
                self.logger.warning("摘要生成失败：返回内容为空")

            return summary

        except Exception as e:
            self.logger.error(f"摘要生成失败: {e}")
            return None

    def _format_round(self, round_msg: List[Message]) -> str:
        """格式化轮次内容"""
        parts = []
        for msg in round_msg:
            if msg.role == "user":
                parts.append(f"用户: {msg.content}")
            elif msg.role == "assistant":
                content = msg.content or ""
                if msg.tool_calls:
                    tool_names = [t.function.name for t in msg.tool_calls]
                    content = f"[调用工具: {', '.join(tool_names)}]"
                parts.append(f"助手: {content}")
            elif msg.role == "tool":
                parts.append(f"[工具: {msg.name or 'unknown'}] 结果已返回")

        return "\n".join(parts)
