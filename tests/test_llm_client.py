from codemate_agent.llm.client import LLMClient
from codemate_agent.schema import Message


def _build_client(provider: str) -> LLMClient:
    client = object.__new__(LLMClient)
    client.provider = provider
    return client


def test_minimax_keep_recent_two_tool_rounds_structured():
    client = _build_client("minimax")
    messages = [
        Message(role="system", content="base system"),
        Message(role="user", content="q1"),
        Message(role="assistant", content="", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": {"file_path": "a.py"}}}]),
        Message(role="tool", content="r1", tool_call_id="c1", name="read_file"),
        Message(role="user", content="q2"),
        Message(role="assistant", content="", tool_calls=[{"id": "c2", "type": "function", "function": {"name": "read_file", "arguments": {"file_path": "b.py"}}}]),
        Message(role="tool", content="r2", tool_call_id="c2", name="read_file"),
        Message(role="user", content="q3"),
        Message(role="assistant", content="", tool_calls=[{"id": "c3", "type": "function", "function": {"name": "read_file", "arguments": {"file_path": "c.py"}}}]),
        Message(role="tool", content="r3", tool_call_id="c3", name="read_file"),
    ]

    converted = client._convert_messages(messages)

    # 老轮次 c1 被降级为文本，不保留结构化 tool 协议
    assert converted[2]["role"] == "assistant"
    assert "tool_calls" not in converted[2]
    assert converted[3]["role"] == "assistant"
    assert "tool_call_id" not in converted[3]

    # 最近两轮 c2/c3 保持结构化，继续支持 function calling 交互
    assert converted[5]["tool_calls"][0]["id"] == "c2"
    assert converted[6]["role"] == "tool"
    assert converted[6]["tool_call_id"] == "c2"
    assert converted[8]["tool_calls"][0]["id"] == "c3"
    assert converted[9]["role"] == "tool"
    assert converted[9]["tool_call_id"] == "c3"


def test_minimax_only_first_system_kept():
    client = _build_client("minimax")
    messages = [
        Message(role="system", content="s1"),
        Message(role="system", content="s2"),
        Message(role="user", content="hello"),
    ]

    converted = client._convert_messages(messages)
    assert converted[0]["role"] == "system"
    assert converted[1]["role"] == "user"
    assert converted[1]["content"].startswith("[System note]")


def test_parse_minimax_xml_tool_call_from_content():
    client = _build_client("minimax")
    content = """
<think>internal</think>
先执行命令
<minimax:tool_call>
<invoke name="run_shell">
<parameter name="command">pwd</parameter>
</invoke>
</minimax:tool_call>
"""
    cleaned, tool_calls = client._parse_minimax_tool_calls_from_content(content)
    assert tool_calls is not None
    assert tool_calls[0].function.name == "run_shell"
    assert tool_calls[0].function.arguments["command"] == "pwd"
    assert "<minimax:tool_call>" not in cleaned
