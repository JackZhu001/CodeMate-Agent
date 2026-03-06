import time

from codemate_agent.agent.agent import CodeMateAgent
from codemate_agent.commands.handler import handle_command
from codemate_agent.schema import LLMResponse
from codemate_agent.tools.todo.todo_write import TodoWriteTool


class DummyLLM:
    model = "dummy-model"

    def complete(self, messages, tools=None):
        return LLMResponse(content="ok", tool_calls=None, finish_reason="stop", usage=None)


class SlowDummyLLM:
    model = "dummy-model"

    def complete(self, messages, tools=None):
        time.sleep(1.1)
        return LLMResponse(content="ok", tool_calls=None, finish_reason="stop", usage=None)


def test_heartbeat_updates_and_command(monkeypatch, tmp_path):
    monkeypatch.setenv("HEARTBEAT_ENABLED", "true")
    monkeypatch.setenv("HEARTBEAT_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))

    agent = CodeMateAgent(
        llm_client=DummyLLM(),
        tools=[],
        compression_enabled=False,
        planning_enabled=False,
    )
    result = agent.run("hello")
    assert result == "ok"

    status = agent.get_heartbeat_status()
    assert status["phase"] == "completed"
    assert status["beats"] > 0
    assert (tmp_path / f"heartbeat-{status['session_id']}.jsonl").exists()

    # /heartbeat 命令可执行（不抛异常）
    handle_command("/heartbeat", agent)


def test_heartbeat_watchdog_alert(monkeypatch, tmp_path):
    monkeypatch.setenv("HEARTBEAT_ENABLED", "true")
    monkeypatch.setenv("HEARTBEAT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))

    agent = CodeMateAgent(
        llm_client=SlowDummyLLM(),
        tools=[],
        compression_enabled=False,
        planning_enabled=False,
    )
    result = agent.run("hello")
    assert result == "ok"

    status = agent.get_heartbeat_status()
    assert status["stalled"] is True


def test_heartbeat_pending_todo_check(monkeypatch, tmp_path):
    monkeypatch.setenv("HEARTBEAT_ENABLED", "true")
    monkeypatch.setenv("HEARTBEAT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("HEARTBEAT_POLL_SECONDS", "60")
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))

    TodoWriteTool._current_summary = "test"
    TodoWriteTool._current_todos = [{"content": "do x", "status": "pending"}]

    agent = CodeMateAgent(
        llm_client=DummyLLM(),
        tools=[],
        compression_enabled=False,
        planning_enabled=False,
    )
    # 人工模拟长时间空闲
    agent._last_activity_ts = time.time() - 2
    agent._heartbeat_pending_check_once()
    status = agent.get_heartbeat_status()
    assert status["pending_todos"] >= 1
    TodoWriteTool.clear()
