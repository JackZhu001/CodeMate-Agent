from codemate_agent.agent.agent import CodeMateAgent
from codemate_agent.schema import LLMResponse, ToolCall, FunctionCall


class DummyLLM:
    model = "dummy-model"

    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="<think>继续思考中</think>",
                tool_calls=None,
                finish_reason="stop",
                usage=None,
            )
        return LLMResponse(
            content="已生成文件：docs/index.html",
            tool_calls=None,
            finish_reason="stop",
            usage=None,
        )


class NagTriggerLLM:
    model = "dummy-model"

    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(name="missing_tool", arguments={}),
                    )
                ],
                finish_reason="tool_calls",
                usage=None,
            )
        return LLMResponse(content="done", tool_calls=None, finish_reason="stop", usage=None)


def _has_todo_nag(messages) -> bool:
    return any(
        msg.role == "system" and "请更新你的任务进度" in (msg.content or "")
        for msg in messages
    )


def test_prevent_premature_finish_when_plan_not_done(monkeypatch, tmp_path):
    monkeypatch.setenv("HEARTBEAT_ENABLED", "false")
    llm = DummyLLM()
    agent = CodeMateAgent(
        llm_client=llm,
        tools=[],
        workspace_dir=str(tmp_path),
        compression_enabled=False,
        planning_enabled=True,
    )
    # 模拟已有计划但未完成
    agent.planner.current_plan = object()
    agent._todo_all_completed = False

    result = agent.run("生成网页")
    assert "已生成文件" in result
    assert llm.calls == 2


def test_todo_nag_triggers_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("HEARTBEAT_ENABLED", "false")
    monkeypatch.setenv("TODO_NAG_INTERVAL", "1")
    monkeypatch.setenv("TODO_NAG_ENABLED", "true")

    agent = CodeMateAgent(
        llm_client=NagTriggerLLM(),
        tools=[],
        workspace_dir=str(tmp_path),
        compression_enabled=False,
        planning_enabled=False,
    )
    result = agent.run("run")
    assert result == "done"
    assert _has_todo_nag(agent.messages)


def test_todo_nag_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("HEARTBEAT_ENABLED", "false")
    monkeypatch.setenv("TODO_NAG_INTERVAL", "1")
    monkeypatch.setenv("TODO_NAG_ENABLED", "false")

    agent = CodeMateAgent(
        llm_client=NagTriggerLLM(),
        tools=[],
        workspace_dir=str(tmp_path),
        compression_enabled=False,
        planning_enabled=False,
    )
    result = agent.run("run")
    assert result == "done"
    assert not _has_todo_nag(agent.messages)
