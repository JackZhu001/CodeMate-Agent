from codemate_agent.agent.agent import CodeMateAgent
from codemate_agent.commands.handler import handle_command
from codemate_agent.persistence.memory import MemoryManager
from codemate_agent.schema import LLMResponse


class DummyLLM:
    model = "dummy-model"

    def complete(self, messages, tools=None):
        return LLMResponse(content="ok", tool_calls=None, finish_reason="stop", usage=None)


def test_bm25_memory_retrieval(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    memory.save_custom_memory(
        "# 自定义记忆\n\n## 数据库\n项目使用 PostgreSQL 和 Redis 缓存。\n\n## 测试\n使用 pytest。"
    )
    result = memory.retrieve_relevant_memory("redis 缓存怎么做", top_k=2)
    assert "Redis" in result or "redis" in result


def test_init_command_creates_codemate_md(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    agent = CodeMateAgent(
        llm_client=DummyLLM(),
        tools=[],
        workspace_dir=str(workspace),
        memory_manager=memory,
        compression_enabled=False,
        planning_enabled=False,
    )
    handle_command("/init", agent, memory_manager=memory)
    codemate_path = workspace / "codemate.md"
    assert codemate_path.exists()
    assert "用户画像与偏好" in codemate_path.read_text(encoding="utf-8")


def test_system_prompt_includes_codemate_and_retrieved_memory(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    memory.save_custom_memory("# 自定义记忆\n\n## 部署\n生产环境用 Kubernetes。")
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "codemate.md").write_text("# CodeMate 项目记忆\n\n- 用户偏好：简洁回答", encoding="utf-8")

    agent = CodeMateAgent(
        llm_client=DummyLLM(),
        tools=[],
        workspace_dir=str(workspace),
        memory_manager=memory,
        compression_enabled=False,
        planning_enabled=False,
    )
    prompt = agent._get_system_prompt("kubernetes 怎么部署")
    assert "项目记忆（codemate.md）" in prompt
    assert "Kubernetes" in prompt or "kubernetes" in prompt
