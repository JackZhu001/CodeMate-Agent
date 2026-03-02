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
    parts = command.lower().split(maxsplit=1)
    cmd = parts[0]
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
        "/reset": lambda: _handle_reset(agent),
        "/compact": lambda: _handle_compact(agent),
        "/stats": lambda: _handle_stats(agent),
        "/tools": lambda: _handle_tools(agent),
        "/skills": lambda: _handle_skills(agent),
        "/sessions": lambda: _handle_sessions(session_index),
        "/memory": lambda: _handle_memory(memory_manager),
        "/save": lambda: _handle_save(session_storage, session_index),
    }

    if cmd in handlers:
        handlers[cmd]()
    elif cmd == "/history":
        if args:
            _handle_history(args, agent, session_index, sessions_dir)
        else:
            console.print("[yellow]用法: /history <会话ID>[/yellow]\n")
    else:
        print_error(f"未知命令: {command}")
        console.print("输入 /help 查看可用命令\n")


def _handle_reset(agent: "CodeMateAgent") -> None:
    """处理 /reset 命令"""
    agent.reset()
    print_success("✓ Agent 状态已重置")


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
