"""
命令处理器

处理 CLI 斜杠命令。
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from codemate_agent.ui import (
    console,
    print_help,
    print_sessions,
    print_error,
    print_success,
)

if TYPE_CHECKING:
    from codemate_agent.agent import CodeMateAgent
    from codemate_agent.persistence import SessionIndex, SessionStorage, MemoryManager


def handle_command(
    command: str,
    agent: "CodeMateAgent",
    session_index: "SessionIndex | None" = None,
    session_storage: "SessionStorage | None" = None,
    memory_manager: "MemoryManager | None" = None,
    sessions_dir: Path = None,
) -> None:
    """处理斜杠命令"""
    # 解析命令：支持 /history <id> 和 /history<id> 两种格式
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # 如果没有参数，尝试解析 /history<id> 格式
    if not args and "<" in cmd and ">" in cmd:
        match = re.match(r"(/[a-z]+)<(.+)>", cmd)
        if match:
            cmd = match.group(1)
            args = match.group(2)

    # 命令路由
    handlers = {
        "/help": lambda: print_help(),
        "/init": lambda: _handle_init(agent, memory_manager),
        "/reset": lambda: _handle_reset(agent),
        "/compact": lambda: _handle_compact(agent),
        "/heartbeat": lambda: _handle_heartbeat(agent),
        "/team": lambda: _handle_team(agent),
        "/inbox": lambda: _handle_inbox(agent),
        "/tasks": lambda: _handle_tasks(agent),
        "/stats": lambda: _handle_stats(agent),
        "/tools": lambda: _handle_tools(agent),
        "/skills": lambda: _handle_skills(agent),
        "/skill-drafts": lambda: _handle_skill_drafts(agent),
        "/sessions": lambda: _handle_sessions(session_index),
        "/memory": lambda: _handle_memory(memory_manager),
        "/rag": lambda: _handle_rag(agent, args),
        "/save": lambda: _handle_save(session_storage, session_index),
    }

    if cmd in handlers:
        handlers[cmd]()
    elif cmd == "/history":
        if args:
            _handle_history(args, agent, session_index, sessions_dir)
        else:
            console.print("[yellow]用法: /history <会话ID>[/yellow]\n")
    elif cmd == "/publish-skill-draft":
        if args:
            _handle_publish_skill_draft(agent, args)
        else:
            console.print("[yellow]用法: /publish-skill-draft <draft-name>[/yellow]\n")
    else:
        print_error(f"未知命令: {command}")
        console.print("输入 /help 查看可用命令\n")


def _handle_reset(agent: "CodeMateAgent") -> None:
    """处理 /reset 命令"""
    agent.reset()
    print_success("✓ Agent 状态已重置")


def _handle_init(agent: "CodeMateAgent", memory_manager: "MemoryManager | None") -> None:
    """处理 /init 命令，初始化项目 codemate.md"""
    if memory_manager is None:
        print_error("记忆管理器未初始化，无法执行 /init")
        return
    workspace_dir = getattr(agent, "workspace_dir", Path.cwd())
    tool_names = []
    if getattr(agent, "tool_registry", None):
        tool_names = agent.tool_registry.list_tools()
    path = memory_manager.init_codemate_file(workspace_dir, tools=tool_names)
    print_success(f"✓ 初始化完成: {path}")


def _handle_compact(agent: "CodeMateAgent") -> None:
    """处理 /compact 命令"""
    if not getattr(agent, "compression_enabled", False) or not getattr(agent, "compressor", None):
        print_error("上下文压缩未启用")
        return
    original_count = len(agent.messages)
    agent.messages = agent.compressor.auto_compact(agent.messages)
    from codemate_agent.tools.compact import CompactTool
    CompactTool._messages_ref = agent.messages
    print_success(f"✓ 上下文压缩完成: {original_count} → {len(agent.messages)} 条消息")


def _handle_heartbeat(agent: "CodeMateAgent") -> None:
    """处理 /heartbeat 命令"""
    status = agent.get_heartbeat_status()
    state = "告警" if status.get("stalled") else "正常"
    console.print(
        "[cyan]心跳状态:[/cyan]\n"
        f"  session: {status.get('session_id')}\n"
        f"  phase: {status.get('phase')}\n"
        f"  beats: {status.get('beats')}\n"
        f"  last_tool: {status.get('last_tool')}\n"
        f"  pending_todos: {status.get('pending_todos')}\n"
        f"  age_seconds: {status.get('age_seconds')}\n"
        f"  idle_seconds: {status.get('idle_seconds')}\n"
        f"  timeout_seconds: {status.get('timeout_seconds')}\n"
        f"  mode: {status.get('mode')}\n"
        f"  status: {state}\n"
    )


def _handle_team(agent: "CodeMateAgent") -> None:
    """处理 /team 命令"""
    getter = getattr(agent, "get_team_status", None)
    if getter is None:
        print_error("当前 Agent 不支持团队状态")
        return
    status = getter()
    if not status.get("enabled"):
        console.print("[yellow]团队运行时未启用（TEAM_AGENT_ENABLED=false）[/yellow]\n")
        return
    console.print(
        "[cyan]团队状态:[/cyan]\n"
        f"  team: {status.get('team_name')}\n"
        f"  agent: {status.get('agent_name')} ({status.get('agent_role')})\n"
        f"  dispatch_enabled: {status.get('dispatch_enabled', False)}\n"
        f"  strict_mode: {status.get('strict_mode', False)}\n"
        f"  strict_progress: {status.get('strict_progress', {})}\n"
        f"  members: {status.get('members', [])}\n"
        f"  queue: {status.get('queue', {})}\n"
        f"  active_task_id: {status.get('active_task_id')}\n"
        f"  inbox_pending: {status.get('inbox_pending')}\n"
        f"  task_stats: {status.get('task_stats')}\n"
        f"  request_tracker: {status.get('request_tracker', {}).get('counts', {})}\n"
    )


def _handle_inbox(agent: "CodeMateAgent") -> None:
    """处理 /inbox 命令"""
    getter = getattr(agent, "peek_team_inbox", None)
    if getter is None:
        print_error("当前 Agent 不支持 inbox 查看")
        return
    messages = getter(limit=20)
    if not messages:
        console.print("[yellow]inbox 为空[/yellow]\n")
        return
    console.print("[cyan]最近 inbox 消息（最多 20 条）:[/cyan]")
    for idx, msg in enumerate(messages, 1):
        console.print(
            f"  {idx:02d}. [{msg.get('type', 'message')}] "
            f"{msg.get('from', '?')} -> {msg.get('content', '')[:120]}"
        )
    console.print("")


def _handle_tasks(agent: "CodeMateAgent") -> None:
    """处理 /tasks 命令"""
    getter = getattr(agent, "list_task_board", None)
    if getter is None:
        print_error("当前 Agent 不支持任务板查看")
        return
    tasks = getter(limit=50)
    if not tasks:
        console.print("[yellow]任务板为空[/yellow]\n")
        return
    console.print("[cyan]任务板:[/cyan]")
    for task in tasks:
        marker = {
            "pending": "[ ]",
            "leased": "[L]",
            "in_progress": "[>]",
            "blocked": "[!]",
            "review": "[R]",
            "completed": "[x]",
            "failed": "[f]",
            "cancelled": "[~]",
        }.get(task.get("status"), "[?]")
        status_text = str(task.get("status", "unknown"))
        owner = f" @{task.get('owner')}" if task.get("owner") else ""
        worktree = f" ({task.get('worktree')})" if task.get("worktree") else ""
        console.print(
            f"  {marker} {status_text:<11} #{task.get('id')}: {task.get('subject', '')}{owner}{worktree}",
            markup=False,
        )
    console.print("")


def _handle_stats(agent: "CodeMateAgent") -> None:
    """处理 /stats 命令"""
    stats = agent.get_stats()
    console.print(f"[cyan]统计信息:[/cyan]\n{stats}\n")


def _handle_tools(agent: "CodeMateAgent") -> None:
    """处理 /tools 命令"""
    tools = agent.tool_registry.list_tools()
    console.print(f"[cyan]可用工具 ({len(tools)}):[/cyan]\n" + "\n".join(f"  - {t}" for t in tools))


def _handle_skills(agent: "CodeMateAgent") -> None:
    """处理 /skills 命令"""
    skills = agent.skill_manager.get_available_skills()
    if skills:
        console.print(f"[cyan]可用 Skills ({len(skills)}):[/cyan]")
        for skill_name in skills:
            desc = agent.skill_manager._index.get(skill_name, "")
            console.print(f"  - [green]/{skill_name}[/green]: {desc}")
        console.print("\n使用方法: /<skill-name> <参数>")
    else:
        console.print("[yellow]暂无可用 Skills[/yellow]")
        console.print(f"Skills 目录: {agent.skill_manager.skills_dir}")


def _handle_skill_drafts(agent: "CodeMateAgent") -> None:
    """处理 /skill-drafts 命令。"""
    manager = getattr(agent, "skill_capture_manager", None)
    if manager is None:
        print_error("当前 Agent 不支持 skill 草稿管理")
        return
    drafts = manager.list_draft_summaries()
    if not drafts:
        console.print("[yellow]暂无 skill 草稿[/yellow]")
        console.print(f"草稿目录: {manager.drafts_dir}")
        return
    console.print(f"[cyan]Skill 草稿 ({len(drafts)}):[/cyan]")
    for draft in drafts:
        tool_chain = " -> ".join(draft.primary_tool_chain[:4]) if draft.primary_tool_chain else "-"
        artifact_types = ", ".join(draft.artifact_types) if draft.artifact_types else "-"
        console.print(
            f"  - [green]{draft.name}[/green] ({draft.status}) "
            f"task_type={draft.task_type} confidence={draft.confidence:.2f} "
            f"runs={draft.source_run_count}"
        )
        console.print(f"    tools: {tool_chain}", markup=False)
        console.print(f"    artifacts: {artifact_types}", markup=False)
        console.print(f"    created_at: {draft.created_at}", markup=False)
        if draft.validation_errors:
            console.print(
                f"    validation_errors: {'; '.join(draft.validation_errors[:3])}",
                markup=False,
            )
    console.print("\n使用方法: /publish-skill-draft <draft-name>")


def _handle_publish_skill_draft(agent: "CodeMateAgent", draft_name: str) -> None:
    """处理 /publish-skill-draft 命令。"""
    manager = getattr(agent, "skill_capture_manager", None)
    if manager is None:
        print_error("当前 Agent 不支持 skill 草稿管理")
        return
    try:
        published_path = manager.publish_skill_draft(draft_name.strip())
    except Exception as exc:
        print_error(str(exc))
        return
    print_success(f"✓ Skill 草稿已发布: {published_path}")


def _handle_sessions(session_index: "SessionIndex | None") -> None:
    """处理 /sessions 命令"""
    if session_index is None:
        print_error("会话索引未初始化")
        return

    sessions = session_index.list_recent(limit=10)
    print_sessions(sessions)


def _handle_history(
    session_id: str,
    agent: "CodeMateAgent",
    session_index: "SessionIndex | None",
    sessions_dir: Path,
) -> None:
    """处理 /history 命令"""
    if session_index is None:
        print_error("会话索引未初始化")
        return

    # 查找完整 session_id（支持模糊匹配）
    sessions = session_index.list_all(limit=1000)
    matched = None
    for s in sessions:
        if s.session_id.startswith(session_id):
            matched = s
            break

    if matched is None:
        print_error(f"找不到会话: {session_id}")
        return

    console.print(f"[cyan]正在加载会话: {matched.title}[/cyan]")

    # 从磁盘加载会话
    from codemate_agent.persistence import SessionStorage
    from rich.panel import Panel

    storage = SessionStorage.load(sessions_dir, matched.session_id)
    messages = storage.get_messages_for_agent()

    # 显示摘要（如果有）
    summary = storage.get_summary()
    if summary:
        console.print(Panel(
            summary[:400] + "..." if len(summary) > 400 else summary,
            title="[bold]会话摘要[/bold]",
            border_style="dim"
        ))

    # 加载到 Agent
    agent.load_session(messages)
    print_success(f"✓ 已加载 {len(messages)} 条历史消息")


def _handle_memory(memory_manager: "MemoryManager | None") -> None:
    """处理 /memory 命令"""
    if memory_manager is None:
        print_error("记忆管理器未初始化")
        return

    from rich.table import Table
    from rich.panel import Panel

    info = memory_manager.get_memory_files_info()

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("记忆文件", style="cyan")
    table.add_column("大小", justify="right")

    for name, data in info.items():
        if data["exists"]:
            size = data["size"]
            table.add_row(name, f"{size} bytes")

    console.print("\n[bold]长期记忆:[/bold]")
    console.print(table)

    # 显示记忆内容摘要
    memory = memory_manager.load_all_memory()
    if memory and not memory.startswith("# 长期记忆\n\n暂无"):
        console.print(Panel(
            memory[:500] + "..." if len(memory) > 500 else memory,
            title="[bold]记忆内容[/bold]",
            border_style="dim"
        ))
    console.print()


def _handle_rag(agent: "CodeMateAgent", args: str) -> None:
    """处理 /rag 命令，显示 RepoRAG 命中的项目片段。"""
    query = (args or "").strip()
    if not query:
        console.print("[yellow]用法: /rag <查询内容>[/yellow]\n")
        return

    inspect = getattr(agent, "inspect_repo_rag", None)
    if inspect is None:
        print_error("当前 Agent 不支持 RepoRAG 查看")
        return

    context = inspect(query)
    if context is None:
        print_error("RepoRAG 未启用")
        return
    if context.is_empty():
        console.print("[yellow]RepoRAG 未命中相关片段[/yellow]\n")
        return

    from rich.panel import Panel
    from rich.table import Table

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", justify="right", style="dim")
    table.add_column("标题", style="cyan")
    table.add_column("来源", style="white")
    table.add_column("分数", justify="right", style="green")

    for idx, chunk in enumerate(context.chunks, 1):
        table.add_row(str(idx), chunk.title, chunk.path or chunk.source, f"{chunk.score:.2f}")

    console.print(f"\n[bold]RepoRAG 命中[/bold] query={query!r}")
    console.print(table)
    console.print(
        f"[dim]sources={context.source_count} chunks={len(context.chunks)} chars={context.total_chars}[/dim]"
    )
    console.print(Panel(context.to_prompt_text(), title="[bold]注入预览[/bold]", border_style="dim"))
    console.print()


def _handle_save(
    session_storage: "SessionStorage | None",
    session_index: "SessionIndex | None",
) -> None:
    """处理 /save 命令"""
    if session_storage is None:
        print_error("对话持久化未启用")
        return

    metadata = session_storage.get_metadata()
    if metadata and session_index:
        session_index.update(metadata)
        print_success(f"✓ 会话已保存: {metadata.title}")
    else:
        print_success("✓ 会话已保存")
