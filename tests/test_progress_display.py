import io

from rich.console import Console

from codemate_agent.ui.progress import ProgressDisplay


def test_progress_display_shows_decision_action_observation():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    display = ProgressDisplay(console)

    display.on_event("round_start", {"round": 1, "max_rounds": 50})
    display.on_event("assistant_decision", {"summary": "准备调用 explore 子代理分析项目结构"})
    display.on_event(
        "tool_call_start",
        {
            "tool": "task",
            "args": "description=分析项目结构",
            "arguments": {"subagent_type": "explore", "description": "分析项目结构"},
        },
    )
    display.on_event(
        "tool_call_end",
        {"success": True, "result_preview": "--- TASK RESULT ---", "duration_ms": 128},
    )

    output = stream.getvalue()
    assert "进度 1/50" in output
    assert "阶段: 子代理" in output
    assert "决策" in output
    assert "task[subagent:explore]" in output
    assert "观察" in output


def test_progress_display_shows_skill_call_details():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    display = ProgressDisplay(console)

    display.on_event("round_start", {"round": 1, "max_rounds": 50})
    display.on_event(
        "tool_call_start",
        {
            "tool": "skill",
            "args": "action=load, skill_name=integration-validation",
            "arguments": {"action": "load", "skill_name": "integration-validation"},
        },
    )

    output = stream.getvalue()
    assert "skill[load] integration-validation" in output


def test_progress_display_collapses_repeated_actions():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    display = ProgressDisplay(console)

    display.on_event("round_start", {"round": 1, "max_rounds": 50})
    payload = {
        "tool": "background_run",
        "args": 'cmd=echo "health api done"',
        "arguments": {"command": 'echo "health api done"'},
    }
    display.on_event("tool_call_start", payload)
    display.on_event("tool_call_start", payload)

    output = stream.getvalue()
    assert "background_run" in output
    assert "重复行动已折叠" in output


def test_progress_display_shows_each_round_header():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    display = ProgressDisplay(console)

    display.on_event("round_start", {"round": 1, "max_rounds": 50})
    display.on_event("round_start", {"round": 2, "max_rounds": 50})

    output = stream.getvalue()
    assert "进度 1/50" in output
    assert "进度 2/50" in output


def test_progress_display_shows_skill_auto_selected_hint():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    display = ProgressDisplay(console)

    display.on_event(
        "skill_auto_selected",
        {
            "skill": "ui-ux-pro-max",
            "hint": "本次由意图自动触发；可在下次输入前加 [no-skill] 关闭自动触发。",
        },
    )

    output = stream.getvalue()
    assert "自动 Skill: ui-ux-pro-max" in output
    assert "[no-skill]" in output


def test_progress_display_shows_repo_rag_summary():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    display = ProgressDisplay(console)

    display.on_event(
        "repo_rag_retrieved",
        {"mode": "concept_lookup", "chunks": 3, "source_count": 2, "total_chars": 1200},
    )

    output = stream.getvalue()
    assert "RepoRAG" in output
    assert "concept_lookup" in output
    assert "3 个片段" in output


def test_progress_display_task_member_label_for_team_dispatch():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    display = ProgressDisplay(console)

    display.on_event("round_start", {"round": 1, "max_rounds": 50})
    display.on_event(
        "tool_call_start",
        {
            "tool": "task",
            "args": "description=收集项目事实",
            "arguments": {"agent_id": "researcher", "description": "收集项目事实"},
        },
    )

    output = stream.getvalue()
    assert "阶段: 团队委托" in output
    assert "task[member:researcher]" in output
