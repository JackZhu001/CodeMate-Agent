"""
UI 显示模块

Rich 终端输出、横幅、帮助等。
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


BANNER = r"""
   /ᐠ - ˕ -マ Ⳋ  Oh-My-Claw
  /  ▞   ▞   ⟡  Engineering claw assistant
 /   づ  づ
"""


def print_banner() -> None:
    """打印欢迎横幅"""
    console.print(Panel(BANNER, border_style="magenta", title="[bold pink1]🐾 Welcome[/bold pink1]"))


def print_startup_summary(config: object) -> None:
    """打印启动状态卡片。"""
    runtime_table = Table(show_header=False, box=None, pad_edge=False)
    runtime_table.add_column("项目", style="cyan", no_wrap=True)
    runtime_table.add_column("值", style="white")
    runtime_table.add_row("模型", str(getattr(config, "model", "")))
    runtime_table.add_row("轮数上限", str(getattr(config, "max_rounds", "")))
    runtime_table.add_row("工作目录", str(getattr(config, "cwd", getattr(config, "workspace_dir", "")) or ""))

    features = []
    if getattr(config, "trace_enabled", False):
        features.append("Trace")
    if getattr(config, "metrics_enabled", False):
        features.append("Metrics")
    if getattr(config, "persistence_enabled", False):
        features.append("Memory")
        features.append("Compact")
        features.append("Planning")
    if getattr(config, "repo_rag_enabled", False):
        features.append("RepoRAG")

    feature_table = Table(show_header=False, box=None, pad_edge=False)
    feature_table.add_column("状态", style="cyan", no_wrap=True)
    feature_table.add_column("值", style="white")
    feature_table.add_row("Provider", str(getattr(config, "api_provider", "")))
    feature_table.add_row("日志级别", str(getattr(config, "log_level", "")))
    feature_table.add_row("能力", " · ".join(features) if features else "基础模式")

    console.print(Panel(runtime_table, title="[bold]Runtime[/bold]", border_style="bright_magenta"))
    console.print(Panel(feature_table, title="[bold]Capabilities[/bold]", border_style="cyan"))


def print_help() -> None:
    """打印帮助信息"""
    help_text = """
    🧸 可用命令:

  [cyan]/help[/cyan]       - 显示此帮助信息
  [cyan]/init[/cyan]       - 初始化项目记忆文件（codemate.md）
  [cyan]/reset[/cyan]      - 重置 Agent 状态
  [cyan]/compact[/cyan]    - 手动压缩当前上下文
  [cyan]/heartbeat[/cyan]  - 查看心跳与看门狗状态
  [cyan]/team[/cyan]       - 查看团队运行时状态
  [cyan]/inbox[/cyan]      - 查看团队消息 inbox（不清空）
  [cyan]/tasks[/cyan]      - 查看任务板状态
  [cyan]/stats[/cyan]      - 显示统计信息
  [cyan]/tools[/cyan]      - 列出可用工具
  [cyan]/skills[/cyan]     - 列出可用 Skills
  [cyan]/skill-drafts[/cyan] - 列出待发布的 Skill 草稿
  [cyan]/sessions[/cyan]   - 列出历史会话
  [cyan]/history <id>[/cyan] - 加载指定会话
  [cyan]/memory[/cyan]     - 查看长期记忆
  [cyan]/rag <query>[/cyan] - 查看 RepoRAG 命中的项目上下文
  [cyan]/save[/cyan]       - 保存当前会话
  [cyan]/publish-skill-draft <name>[/cyan] - 发布指定 Skill 草稿
  [cyan]exit[/cyan]        - 退出程序

🌟 Skills 使用:
  - 输入 [green]/<skill-name> <参数>[/green] 执行 Skill
  - 例如: [green]/code-review src/agent/[/green]

💡 使用技巧:
  - 可以问关于代码结构的问题
  - 可以请求分析特定文件
  - 可以搜索代码中的关键词
  - 按 Tab 键可以自动补全历史输入
  - 使用 /sessions 查看历史对话
"""
    console.print(Panel(help_text, title="[bold]帮助[/bold]", border_style="cyan"))


def print_stats(stats: dict, total_tokens: int) -> None:
    """打印统计信息"""
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    
    table.add_row("轮数", str(stats.get("round_count", 0)))
    table.add_row("Tokens", str(total_tokens))
    table.add_row("消息数", str(stats.get("message_count", 0)))
    
    console.print("\n[bold]统计信息:[/bold]")
    console.print(table)
    console.print()


def print_tools(tools_list: list) -> None:
    """打印工具列表"""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("工具名", style="cyan")
    table.add_column("描述", style="white")
    
    for tool in tools_list:
        table.add_row(tool.name, tool.description[:50] + "..." if len(tool.description) > 50 else tool.description)
    
    console.print("\n[bold]可用工具:[/bold]")
    console.print(table)
    console.print()


def print_sessions(sessions: list) -> None:
    """打印会话列表"""
    if not sessions:
        console.print("[yellow]暂无历史会话[/yellow]\n")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("会话 ID", style="cyan")
    table.add_column("标题", style="white")
    table.add_column("消息数", justify="right")
    table.add_column("更新时间", style="dim")

    for s in sessions:
        short_id = s.session_id[:20] + "..."
        table.add_row(short_id, s.title, str(s.message_count), s.updated_at[:19])

    console.print("\n[bold]最近会话:[/bold]")
    console.print(table)
    console.print()


def print_error(message: str) -> None:
    """打印错误信息"""
    console.print(message, style="red", markup=False)
    console.print("")


def print_warning(message: str) -> None:
    """打印警告信息"""
    console.print(message, style="yellow", markup=False)
    console.print("")


def print_success(message: str) -> None:
    """打印成功信息"""
    console.print(message, style="green", markup=False)
    console.print("")


def print_info(message: str) -> None:
    """打印信息"""
    console.print(message, style="cyan", markup=False)
    console.print("")
