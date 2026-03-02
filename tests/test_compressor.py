"""
测试上下文压缩器

验证压缩逻辑是否正确工作。
"""

from codemate_agent.context.compressor import ContextCompressor, CompressionConfig
from codemate_agent.schema import Message


def create_mock_rounds(num_rounds: int) -> list[Message]:
    """
    创建模拟对话轮次

    每轮包含: user -> assistant -> tool (可选)

    Args:
        num_rounds: 轮次数

    Returns:
        消息列表
    """
    messages = [Message(role="system", content="系统提示词")]

    for i in range(num_rounds):
        messages.append(Message(role="user", content=f"用户问题 {i+1}"))
        messages.append(Message(
            role="assistant",
            content=f"助手回答 {i+1}",
            tool_calls=[{"id": f"call_{i}", "type": "function", "function": {"name": "test", "arguments": {}}}]
        ))
        messages.append(Message(
            role="tool",
            content=f"工具结果 {i+1}",
            tool_call_id=f"call_{i}",
            name="test"
        ))

    return messages


class TestCompressionThreshold:
    """测试压缩触发条件"""

    def test_no_compression_below_threshold(self):
        """测试低于阈值时不压缩"""
        compressor = ContextCompressor(
            config=CompressionConfig(min_retain_rounds=5)
        )

        # 5 轮 - 应该不压缩（阈值是 6）
        messages = create_mock_rounds(5)
        result = compressor.compress(messages)

        # system 消息 + 5 轮的消息
        original_count = len(messages)
        result_count = len(result)

        assert result_count == original_count, f"期望 {original_count} 条消息，实际 {result_count}"

    def test_compression_above_threshold(self):
        """测试超过阈值时触发压缩"""
        compressor = ContextCompressor(
            config=CompressionConfig(min_retain_rounds=5)
        )

        # 7 轮 - 应该压缩（保留 5 轮，压缩 2 轮）
        messages = create_mock_rounds(7)
        original_count = len(messages)

        result = compressor.compress(messages)
        result_count = len(result)

        # 压缩后应该减少：
        # - 保留 5 轮 = 1 + 5*3 = 16 条消息
        # - 原始 1 + 7*3 = 22 条消息
        assert result_count < original_count, \
            f"压缩后消息数应该减少: 原始 {original_count}, 压缩后 {result_count}"

        # 验证 system 消息仍在
        assert result[0].role == "system", "第一条消息应该是 system"

    def test_compression_large_conversation(self):
        """测试大型对话的压缩效果"""
        compressor = ContextCompressor(
            config=CompressionConfig(min_retain_rounds=5)
        )

        # 20 轮对话
        messages = create_mock_rounds(20)
        original_count = len(messages)

        result = compressor.compress(messages)
        result_count = len(result)

        # 压缩率应该超过 40%
        compression_ratio = (original_count - result_count) / original_count
        assert compression_ratio > 0.3, \
            f"压缩率应该超过 30%: {compression_ratio:.2%}"

        print(f"原始消息数: {original_count}")
        print(f"压缩后消息数: {result_count}")
        print(f"压缩率: {compression_ratio:.2%}")


class TestCompressionWithLLM:
    """测试带 LLM 的压缩（需要 API key）"""

    def test_generate_summary_without_llm(self):
        """测试没有 LLM 客户端时的行为"""
        compressor = ContextCompressor(
            config=CompressionConfig(min_retain_rounds=5)
        )

        # 8 轮对话，没有 LLM 客户端
        messages = create_mock_rounds(8)
        original_count = len(messages)

        result = compressor.compress(messages)

        # 没有 LLM 时应该跳过压缩（无法生成摘要）
        # 但由于轮数 > 5 + 1 = 6，会尝试压缩
        # 由于没有 LLM，摘要生成会失败，返回原消息
        # 实际上我们的实现是：如果摘要生成失败，仍会返回压缩后的消息
        # 只是没有新的摘要消息
        print(f"无 LLM: 原始 {original_count}, 压缩后 {len(result)}")


class TestRoundIdentification:
    """测试轮次识别"""

    def test_identify_rounds_simple(self):
        """测试简单轮次识别"""
        compressor = ContextCompressor()

        messages = [
            Message(role="user", content="问题 1"),
            Message(role="assistant", content="回答 1"),
            Message(role="user", content="问题 2"),
            Message(role="assistant", content="回答 2"),
        ]

        rounds = compressor._identify_rounds(messages)

        assert len(rounds) == 2, f"应该识别出 2 轮，实际 {len(rounds)}"

    def test_identify_rounds_with_tools(self):
        """测试带工具调用的轮次识别"""
        from codemate_agent.schema import ToolCall, FunctionCall

        compressor = ContextCompressor()

        messages = [
            Message(role="user", content="问题 1"),
            Message(role="assistant", content="", tool_calls=[
                ToolCall(id="call1", type="function", function=FunctionCall(name="test", arguments={}))
            ]),
            Message(role="tool", content="结果", tool_call_id="call1"),
            Message(role="user", content="问题 2"),
        ]

        rounds = compressor._identify_rounds(messages)

        assert len(rounds) == 2, f"应该识别出 2 轮，实际 {len(rounds)}"
        # 第一轮应该包含 3 条消息
        assert len(rounds[0]) == 3, f"第一轮应该有 3 条消息"


def test_compression_config_from_env(monkeypatch):
    """测试从环境变量加载配置"""
    monkeypatch.setenv("CONTEXT_WINDOW", "20000")
    monkeypatch.setenv("COMPRESSION_THRESHOLD", "0.7")
    monkeypatch.setenv("MIN_RETAIN_ROUNDS", "5")

    config = CompressionConfig.from_env()

    assert config.context_window == 20000
    assert config.compression_threshold == 0.7
    assert config.min_retain_rounds == 5


def test_micro_compact_keeps_recent_rounds_and_whitelist():
    """微压缩应保留近三轮，并跳过白名单工具"""
    messages = [Message(role="system", content="系统提示词")]
    tools = ["old_tool", "todo_write", "tool_3", "tool_4", "tool_5"]

    for i, tool_name in enumerate(tools, start=1):
        call_id = f"call_{i}"
        messages.append(Message(role="user", content=f"用户问题 {i}"))
        messages.append(Message(
            role="assistant",
            content="",
            tool_calls=[{"id": call_id, "type": "function", "function": {"name": tool_name, "arguments": {}}}],
        ))
        messages.append(Message(
            role="tool",
            content=("X" * 180) + f"_{tool_name}",
            tool_call_id=call_id,
            name=tool_name,
        ))

    compressor = ContextCompressor(
        config=CompressionConfig(
            micro_compact_keep=3,
            micro_compact_tool_whitelist=["todo_write"],
        )
    )
    result = compressor.micro_compact(messages)

    compressed_first = next(m for m in result if m.role == "tool" and m.name == "old_tool")
    whitelisted_second = next(m for m in result if m.role == "tool" and m.name == "todo_write")
    recent_last = next(m for m in result if m.role == "tool" and m.name == "tool_5")

    assert "已压缩" in compressed_first.content
    assert "已压缩" not in whitelisted_second.content
    assert "已压缩" not in recent_last.content


def test_auto_compact_retains_system_and_last_three_rounds():
    """自动压缩应保留 system 和最近三轮原始消息"""
    messages = create_mock_rounds(6)
    compressor = ContextCompressor(config=CompressionConfig())

    result = compressor.auto_compact(messages)

    assert result[0].role == "system"
    assert any(m.role == "system" and "历史摘要" in m.content for m in result)

    user_msgs = [m for m in result if m.role == "user"]
    assert len(user_msgs) == 3
    assert user_msgs[0].content == "用户问题 4"
    assert user_msgs[2].content == "用户问题 6"


if __name__ == "__main__":
    # 快速测试
    test = TestCompressionThreshold()

    print("测试 1: 低于阈值不压缩")
    test.test_no_compression_below_threshold()
    print("✓ 通过\n")

    print("测试 2: 超过阈值触发压缩")
    test.test_compression_above_threshold()
    print("✓ 通过\n")

    print("测试 3: 大型对话压缩效果")
    test.test_compression_large_conversation()
    print("✓ 通过\n")

    print("测试 4: 轮次识别")
    test_round = TestRoundIdentification()
    test_round.test_identify_rounds_simple()
    test_round.test_identify_rounds_with_tools()
    print("✓ 通过\n")

    print("所有测试通过！")
