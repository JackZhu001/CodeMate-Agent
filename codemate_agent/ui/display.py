"""
UI 显示模块

Rich 终端输出、横幅、帮助等。
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ███╗   ██╗███████╗██╗    ██╗      ██╗  ██╗███████╗██╗     ║
║   ████╗  ██║██╔════╝██║    ██║      ██║  ██║██╔════╝██║     ║
║   ██╔██╗ ██║█████╗  ██║ █╗ ██║█████╗███████║█████╗  ██║     ║
║   ██║╚██╗██║██╔══╝  ██║███╗██║╚════╝██╔══██║██╔══╝  ██║     ║
║   ██║ ╚████║███████╗╚███╔███╔╝      ██║  ██║███████╗███████╗║
║   ╚═╝  ╚═══╝╚══════╝ ╚══╝╚══╝       ╚═╝  ╚═╝╚══════╝╚══════╝║
║                                                              ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""


def print_banner() -> None:
    """打印欢迎横幅"""
    console.print(BANNER, style="bold cyan")


def print_help() -> None:
    """打印帮助信息"""
    help_text = """
可用命令:

  [cyan]/help[/cyan]       - 显示此帮助信息
  [cyan]/reset[/cyan]      - 重置 Agent 状态
  [cyan]/compact[/cyan]    - 手动压缩当前上下文
  [cyan]/stats[/cyan]      - 显示统计信息
  [cyan]/tools[/cyan]      - 列出可用工具
  [cyan]/skills[/cyan]     - 列出可用 Skills
  [cyan]/sessions[/cyan]   - 列出历史会话
  [cyan]/history <id>[/cyan] - 加载指定会话
  [cyan]/memory[/cyan]     - 查看长期记忆
  [cyan]/save[/cyan]       - 保存当前会话
  [cyan]exit[/cyan]        - 退出程序

Skills 使用:
  - 输入 [green]/<skill-name> <参数>[/green] 执行 Skill
  - 例如: [green]/code-review src/agent/[/green]

使用技巧:
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
    console.print(f"[red]{message}[/red]\n")


def print_warning(message: str) -> None:
    """打印警告信息"""
    console.print(f"[yellow]{message}[/yellow]\n")


def print_success(message: str) -> None:
    """打印成功信息"""
    console.print(f"[green]{message}[/green]\n")


def print_info(message: str) -> None:
    """打印信息"""
    console.print(f"[cyan]{message}[/cyan]\n")
