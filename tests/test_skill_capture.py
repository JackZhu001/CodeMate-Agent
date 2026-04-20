import json

from codemate_agent.skill import SkillCaptureManager, SkillManager
from codemate_agent.tools.base import Tool
from codemate_agent.tools.registry import ToolRegistry


class DummyTool(Tool):
    def __init__(self, tool_name: str):
        self._tool_name = tool_name

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return f"dummy tool: {self._tool_name}"

    def run(self, **kwargs) -> str:
        return "ok"


def test_skill_manager_prefers_workspace_skill_over_fallback(tmp_path):
    workspace_skills = tmp_path / "skills"
    fallback_skills = tmp_path / "fallback-skills"
    (workspace_skills / "demo").mkdir(parents=True)
    (fallback_skills / "demo").mkdir(parents=True)

    (workspace_skills / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: workspace version\n---\n# demo\n",
        encoding="utf-8",
    )
    (fallback_skills / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: fallback version\n---\n# demo\n",
        encoding="utf-8",
    )

    manager = SkillManager(skills_dir=workspace_skills, extra_skills_dirs=[fallback_skills])

    assert manager.get_description("demo") == "workspace version"


def test_capture_manager_generates_draft_after_three_similar_runs(tmp_path):
    registry = ToolRegistry()
    registry.register(DummyTool("read_file"))
    registry.register(DummyTool("write_file"))

    manager = SkillCaptureManager(workspace_dir=tmp_path, tool_registry=registry)

    draft_path = None
    for index in range(3):
        draft_path = manager.capture_successful_run(
            run_id=f"run-{index}",
            task_type="ci_bugfix",
            goal="修复 CI 解析错误",
            inputs={"target_request": "修复 CI 解析错误"},
            steps=[{"tool": "read_file", "success": True}, {"tool": "write_file", "success": True}],
            tool_calls=[
                {"tool": "read_file", "arguments": {"file_path": "parser.py"}, "success": True},
                {"tool": "write_file", "arguments": {"file_path": "parser.py"}, "success": True},
            ],
            artifacts=["parser.py"],
            outputs={"final_answer": "已修复 parser.py"},
            success=True,
            manual_intervention=False,
        )

    assert draft_path is not None
    assert draft_path.name == "ci_bugfix"
    assert (draft_path / "SKILL.md").exists()
    assert (draft_path / "examples.json").exists()

    metadata = json.loads((draft_path / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "draft"
    assert metadata["source_runs"] == ["run-0", "run-1", "run-2"]

    skill_text = (draft_path / "SKILL.md").read_text(encoding="utf-8")
    assert "## 输入参数" in skill_text
    assert "{{target_request}}" in skill_text

    summaries = manager.list_draft_summaries()
    assert len(summaries) == 1
    assert summaries[0].source_run_count == 3
    assert summaries[0].primary_tool_chain == ["read_file", "write_file"]
    assert summaries[0].artifact_types == [".py"]


def test_capture_manager_suggests_task_type_from_query(tmp_path):
    manager = SkillCaptureManager(workspace_dir=tmp_path)

    assert manager.suggest_task_type("修复 CI 日志解析错误并更新 pipeline") == "ci_bugfix"
    assert manager.suggest_task_type("请刷新 README 的安装说明") == "doc_refresh"
    assert manager.suggest_task_type("帮我写一个响应式 landing 页面 UI") == "ui_build"
    assert manager.suggest_task_type("随便聊聊") is None


def test_capture_manager_rejects_invalid_draft_with_absolute_path(tmp_path):
    registry = ToolRegistry()
    registry.register(DummyTool("read_file"))
    manager = SkillCaptureManager(workspace_dir=tmp_path, tool_registry=registry)

    draft_dir = tmp_path / ".agents" / "skills-drafts" / "bad-skill"
    draft_dir.mkdir(parents=True)
    (draft_dir / "SKILL.md").write_text(
        "---\nname: bad-skill\ndescription: bad\nallowed_tools: |\n  - read_file\n---\n"
        "# bad-skill\n\n"
        "## 何时使用\n- 处理 `/Users/demo/project/file.py`\n\n"
        "## 前置条件\n- none\n\n"
        "## 输入参数\n- `{{target_request}}`\n\n"
        "## 推荐步骤\n1. 使用 `read_file`\n\n"
        "## 允许工具\n- `read_file`\n\n"
        "## 成功判定\n- ok\n\n"
        "## 常见失败处理\n- retry\n",
        encoding="utf-8",
    )
    (draft_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": "bad-skill",
                "task_type": "demo",
                "source_runs": ["run-0", "run-1", "run-2"],
                "confidence": 0.9,
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "draft",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (draft_dir / "examples.json").write_text("[]", encoding="utf-8")

    validation = manager.validate_skill_draft("bad-skill")

    assert validation.valid is False
    assert "检测到绝对路径" in validation.errors


def test_publish_skill_draft_moves_into_workspace_skills(tmp_path):
    registry = ToolRegistry()
    registry.register(DummyTool("read_file"))
    registry.register(DummyTool("write_file"))
    manager = SkillCaptureManager(workspace_dir=tmp_path, tool_registry=registry)

    for index in range(3):
        manager.capture_successful_run(
            run_id=f"publish-{index}",
            task_type="doc_refresh",
            goal="刷新说明文档",
            inputs={"target_request": "刷新说明文档"},
            steps=[{"tool": "read_file", "success": True}, {"tool": "write_file", "success": True}],
            tool_calls=[
                {"tool": "read_file", "arguments": {"file_path": "README.md"}, "success": True},
                {"tool": "write_file", "arguments": {"file_path": "README.md"}, "success": True},
            ],
            artifacts=["README.md"],
            outputs={"final_answer": "已更新 README.md"},
            success=True,
            manual_intervention=False,
        )

    published_dir = manager.publish_skill_draft("doc_refresh")

    assert published_dir == tmp_path / "skills" / "doc_refresh"
    assert published_dir.exists()
    metadata = json.loads((published_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "published"
    assert not (tmp_path / ".agents" / "skills-drafts" / "doc_refresh").exists()
