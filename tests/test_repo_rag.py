from codemate_agent.persistence.memory import MemoryManager
from codemate_agent.retrieval import RepoRAG


def test_repo_rag_retrieves_workspace_docs_and_codemate(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "codemate.md").write_text(
        "# Oh-My-Claw 项目记忆\n\n## 关键约定\n- 部署方式：Kubernetes\n",
        encoding="utf-8",
    )
    docs_dir = workspace / "docs"
    docs_dir.mkdir()
    (docs_dir / "memory.md").write_text(
        "# 记忆系统\n\n## 检索\n项目通过 BM25 召回长期记忆片段。",
        encoding="utf-8",
    )

    repo_rag = RepoRAG(workspace_dir=workspace, memory_manager=memory)
    result = repo_rag.retrieve("kubernetes 部署约定")

    assert not result.is_empty()
    prompt_text = result.to_prompt_text()
    assert "codemate.md" in prompt_text
    assert "Kubernetes" in prompt_text or "kubernetes" in prompt_text


def test_repo_rag_enforces_char_budget(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docs_dir = workspace / "docs"
    docs_dir.mkdir()
    large_text = "# 设计\n\n## 检索\n" + ("检索增强上下文 " * 200)
    (docs_dir / "design.md").write_text(large_text, encoding="utf-8")

    repo_rag = RepoRAG(
        workspace_dir=workspace,
        memory_manager=memory,
        top_k=5,
        char_budget=600,
    )
    result = repo_rag.retrieve("检索增强上下文")

    assert not result.is_empty()
    assert result.total_chars <= 600


def test_repo_rag_limits_chunks_from_same_source(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docs_dir = workspace / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text(
        "# 指南\n\n## 一\nKubernetes 部署\n\n## 二\nKubernetes 检查\n\n## 三\nKubernetes 回滚",
        encoding="utf-8",
    )

    repo_rag = RepoRAG(
        workspace_dir=workspace,
        memory_manager=memory,
        top_k=5,
        char_budget=2000,
        per_source_limit=2,
    )
    result = repo_rag.retrieve("kubernetes")

    sources = [chunk.path for chunk in result.chunks]
    assert sources.count("docs/guide.md") <= 2


def test_repo_rag_retrieves_code_facts_from_workspace(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package_dir = workspace / "codemate_agent" / "team"
    package_dir.mkdir(parents=True)
    (package_dir / "coordinator.py").write_text(
        "def enforce_strict_stage_order(tasks):\n"
        "    return 'researcher -> builder -> reviewer'\n",
        encoding="utf-8",
    )

    repo_rag = RepoRAG(workspace_dir=workspace, memory_manager=memory)
    result = repo_rag.retrieve("strict_stage_order researcher builder reviewer")

    assert not result.is_empty()
    assert any(chunk.path == "codemate_agent/team/coordinator.py" for chunk in result.chunks)


def test_repo_rag_includes_repo_map_summary(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package_dir = workspace / "codemate_agent" / "team"
    package_dir.mkdir(parents=True)
    (package_dir / "coordinator.py").write_text(
        '"""Team coordination helpers."""\n\n'
        "class TeamCoordinator:\n"
        "    def dispatch_task(self, task):\n"
        "        return task\n",
        encoding="utf-8",
    )

    repo_rag = RepoRAG(workspace_dir=workspace, memory_manager=memory)
    result = repo_rag.retrieve("team coordinator dispatch task")

    prompt_text = result.to_prompt_text()
    assert result.plan is not None
    assert result.plan.mode == "concept_lookup"
    assert "## Repo Map" in prompt_text
    assert "codemate_agent/team/coordinator.py" in prompt_text
    assert "TeamCoordinator" in prompt_text


def test_repo_rag_python_code_chunking_is_symbol_first(tmp_path):
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package_dir = workspace / "codemate_agent"
    package_dir.mkdir(parents=True)
    (package_dir / "runtime.py").write_text(
        "def helper(value):\n"
        "    return value\n\n"
        "class TeamRuntime:\n"
        "    def boot(self):\n"
        "        return True\n",
        encoding="utf-8",
    )

    repo_rag = RepoRAG(workspace_dir=workspace, memory_manager=memory)
    result = repo_rag.retrieve("TeamRuntime boot")

    assert result.plan is not None
    assert result.plan.mode == "symbol_lookup"
    assert any(chunk.chunk_type in {"class", "function"} for chunk in result.chunks)
    assert any(chunk.symbol_name == "TeamRuntime.boot" for chunk in result.chunks)


def test_repo_rag_can_disable_code_channel(monkeypatch, tmp_path):
    monkeypatch.setenv("REPO_RAG_CODE_ENABLED", "false")
    memory = MemoryManager(tmp_path / "memory")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package_dir = workspace / "codemate_agent"
    package_dir.mkdir()
    (package_dir / "runtime.py").write_text(
        "def agent_team_runtime_ready():\n"
        "    return True\n",
        encoding="utf-8",
    )

    repo_rag = RepoRAG(workspace_dir=workspace, memory_manager=memory)
    result = repo_rag.retrieve("agent_team_runtime_ready")

    assert result.is_empty()
