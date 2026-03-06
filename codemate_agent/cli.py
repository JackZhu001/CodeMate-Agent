"""
CodeMate AI CLI

命令行交互入口。
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

from codemate_agent.config import Config, get_config
from codemate_agent.llm.client import LLMClient
from codemate_agent.agent import CodeMateAgent
from codemate_agent.tools import get_all_tools
from codemate_agent.logging import setup_logger, TraceLogger, SessionMetrics, generate_session_id, TraceEventType
from codemate_agent.persistence import SessionStorage, MemoryManager, SessionIndex
from codemate_agent.context import CompressionConfig
from codemate_agent.ui import console, print_banner, print_help, ProgressDisplay
from codemate_agent.commands import handle_command


def run_interactive(config: Config) -> None:
    """运行交互模式"""
    print_banner()

    # 设置日志级别
    setup_logger("codemate", level=config.log_level)

    # 显示配置信息
    config_table = Table(show_header=False, show_edge=False)
    config_table.add_column("配置项", style="cyan")
    config_table.add_column("值", style="yellow")
    config_table.add_row("模型", config.model)
    config_table.add_row("最大轮数", str(config.max_rounds))
    config_table.add_row("日志级别", config.log_level)
    config_table.add_row("Trace 日志", "启用" if config.trace_enabled else "禁用")
    config_table.add_row("Metrics 统计", "启用" if config.metrics_enabled else "禁用")
    config_table.add_row("对话持久化", "启用" if config.persistence_enabled else "禁用")
    config_table.add_row("上下文压缩", "启用" if config.persistence_enabled else "禁用")  # 与持久化同步
    config_table.add_row("任务规划", "启用" if config.persistence_enabled else "禁用")  # 与持久化同步
    config_table.add_row("工作目录", str(Path.cwd()))
    console.print(Panel(config_table, title="[bold]✨ 当前配置[/bold]", border_style="bright_magenta"))
    console.print("")

    # 初始化日志系统
    session_id = generate_session_id()
    trace_logger = TraceLogger(
        session_id=session_id,
        trace_dir=config.trace_dir,
        enabled=config.trace_enabled,
    ) if config.trace_enabled else None

    metrics = SessionMetrics(
        session_id=session_id,
        model=config.model,
    ) if config.metrics_enabled else None

    # 初始化持久化系统
    session_storage = None
    memory_manager = None
    session_index = None

    if config.persistence_enabled:
        session_storage = SessionStorage(
            sessions_dir=config.sessions_dir,
            session_id=session_id,
        )
        session_storage.ensure_dir()
        session_storage.update_metadata(title="新会话")

        memory_manager = MemoryManager(memory_dir=config.memory_dir)
        session_index = SessionIndex(sessions_dir=config.sessions_dir)

    # 定义计划显示回调函数（需要在 try 块之前定义）
    def plan_display_callback(plan_text: str) -> None:
        """
        显示执行计划

        Args:
            plan_text: TodoWrite 返回的计划文本
        """
        console.print(f"\n[cyan]▶ 生成执行计划[/cyan]")
        console.print(Panel(plan_text, border_style="cyan", padding=(0, 1)))
        console.print("")  # 空行

    # 创建进度显示实例
    progress_display = ProgressDisplay(console)

    # 初始化 Agent
    try:
        llm = LLMClient(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            temperature=config.temperature,
            provider=config.api_provider,
        )
        tools = get_all_tools()

        # 创建压缩配置
        compression_config = CompressionConfig.from_env() if config.persistence_enabled else None

        agent = CodeMateAgent(
            llm_client=llm,
            tools=tools,
            max_rounds=config.max_rounds,
            trace_logger=trace_logger,
            metrics=metrics,
            session_storage=session_storage,
            memory_manager=memory_manager,
            compression_enabled=config.persistence_enabled,
            compression_config=compression_config,
            planning_enabled=config.persistence_enabled,
            plan_display_callback=plan_display_callback,
            progress_callback=progress_display.on_event,
        )
    except Exception as e:
        console.print(f"[red]初始化失败: {e}[/red]")
        console.print("\n[yellow]提示: 请确保已设置 API_KEY 环境变量或在 .env 文件中配置[/yellow]")
        sys.exit(1)

    # 历史记录和样式
    history_path = Path(config.config_dir) / "history"

    # 定义 prompt_toolkit 样式
    prompt_style = Style.from_dict({
        'prompt': 'ansicyan bold',
    })

    session = PromptSession(
        history=FileHistory(str(history_path)),
        style=prompt_style,
    )

    # 定义用户确认回调函数（支持批量确认）
    # 使用闭包保存批量确认状态
    batch_state = {"auto_confirm": False, "auto_cancel": False}

    def confirm_callback(tool_name: str, arguments: dict) -> bool:
        """
        危险操作的确认回调（支持批量确认）

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            bool: 用户是否同意执行
        """
        # 检查批量确认状态
        if batch_state["auto_confirm"]:
            return True
        if batch_state["auto_cancel"]:
            return False

        # 格式化参数显示 - 根据工具类型优化
        if tool_name == "write_file":
            file_path = arguments.get("file_path", "未知文件")
            content = arguments.get("content", "")
            content_preview = f"({len(content)} 字符)" if content else "(空)"
            params_display = f"file_path={repr(file_path)}, content={content_preview}"
        elif tool_name == "delete_file":
            file_path = arguments.get("file_path", "未知文件")
            params_display = f"file_path={repr(file_path)}"
        elif tool_name == "run_shell":
            cmd = arguments.get("command", "")
            cmd_preview = (cmd[:60] + "...") if len(cmd) > 60 else cmd
            params_display = f"command={repr(cmd_preview)}"
        else:
            # 通用格式化，限制每个参数的显示长度
            params = []
            for k, v in arguments.items():
                v_str = repr(v)
                if len(v_str) > 50:
                    v_str = v_str[:47] + "..."
                params.append(f"{k}={v_str}")
            params_display = ", ".join(params)

        # 显示确认提示
        console.print(f"\n[red]⚠️  即将执行危险操作:[/red]")
        console.print(f"  [yellow]工具:[/yellow] {tool_name}")
        console.print(f"  [yellow]参数:[/yellow] {params_display}")

        # 获取用户输入
        while True:
            try:
                response = session.prompt("  确认执行吗？(y/a/n/q): ").strip().lower()
                if response in ['y', 'yes']:
                    console.print("[green]✓[/green] 已同意执行\n")
                    return True
                elif response in ['a', 'all']:
                    console.print("[green]✓[/green] 已同意执行（后续操作自动确认）\n")
                    batch_state["auto_confirm"] = True
                    return True
                elif response in ['n', 'no', '']:
                    console.print("[red]✗[/red] 已取消操作\n")
                    return False
                elif response in ['q', 'quit']:
                    console.print("[red]✗[/red] 已取消操作（后续操作自动取消）\n")
                    batch_state["auto_cancel"] = True
                    return False
            except (KeyboardInterrupt, EOFError):
                console.print("\n[red]✗[/red] 已取消操作\n")
                return False

    # 重新初始化 Agent，传入确认回调
    agent.confirm_callback = confirm_callback

    console.print("[green]✓[/green] Agent 已就绪，来聊天吧～（输入 'exit' 或 'quit' 退出）\n")

    while True:
        try:
            user_input = session.prompt(
                '🐱 You > ',
                auto_suggest=AutoSuggestFromHistory()
            ).strip()

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("\n[yellow]再见！[/yellow]")
                # 结束日志
                if trace_logger:
                    trace_logger.finalize()
                if metrics:
                    metrics.finalize()
                    metrics.print_summary()
                    metrics.save(config.metrics_dir)
                break

            # 处理特殊命令
            if user_input.startswith("/"):
                handle_command(user_input, agent, session_index, session_storage, memory_manager, config.sessions_dir)
                continue

            # 运行 Agent
            console.print("\n[bold yellow]🐾 CodeMate:[/bold yellow] [dim]思考中...[/dim]\n")

            try:
                result = agent.run(user_input)

                # 显示结果
                console.print(Panel(result, title="[bold green]答案[/bold green]", border_style="green"))

                # 显示统计
                stats = agent.get_stats()
                console.print(f"\n[dim]━━━ 轮数: {stats['round_count']} | Tokens: {stats['total_tokens']} ━━━[/dim]\n")

                # 每次对话结束后更新 trace
                if trace_logger:
                    trace_logger.finalize()

            except Exception as e:
                console.print(f"[red]执行出错: {e}[/red]\n")
                if trace_logger:
                    trace_logger.log_event(
                        TraceEventType.ERROR,
                        {"error": str(e), "type": type(e).__name__},
                    )

        except KeyboardInterrupt:
            console.print("\n\n[yellow]中断[/yellow]")
            continue
        except EOFError:
            console.print("\n\n[yellow]再见！[/yellow]")
            # 结束日志
            if trace_logger:
                trace_logger.finalize()
            if metrics:
                metrics.finalize()
                metrics.print_summary()
                metrics.save(config.metrics_dir)
            break


def run_single_prompt(prompt: str, config: Config) -> None:
    """运行单次查询模式"""
    # 设置日志级别
    setup_logger("codemate", level=config.log_level)

    # 初始化日志系统
    session_id = generate_session_id()
    trace_logger = TraceLogger(
        session_id=session_id,
        trace_dir=config.trace_dir,
        enabled=config.trace_enabled,
    ) if config.trace_enabled else None

    metrics = SessionMetrics(
        session_id=session_id,
        model=config.model,
    ) if config.metrics_enabled else None

    # 初始化持久化系统
    session_storage = None
    memory_manager = None
    session_index = None

    if config.persistence_enabled:
        session_storage = SessionStorage(
            sessions_dir=config.sessions_dir,
            session_id=session_id,
        )
        session_storage.ensure_dir()
        session_storage.update_metadata(title=prompt[:50])

        memory_manager = MemoryManager(memory_dir=config.memory_dir)
        session_index = SessionIndex(sessions_dir=config.sessions_dir)

    # 定义计划显示回调函数（单次模式使用简单的 console.print）
    def plan_display_callback(plan_text: str) -> None:
        console.print(f"\n[cyan]▶ 生成执行计划[/cyan]")
        console.print(Panel(plan_text, border_style="cyan", padding=(0, 1)))
        console.print("")

    # 创建进度显示实例（单次模式也启用进度显示）
    progress_display = ProgressDisplay(console)

    # 初始化 Agent
    try:
        llm = LLMClient(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            temperature=config.temperature,
            provider=config.api_provider,
        )
        tools = get_all_tools()

        # 创建压缩配置
        compression_config = CompressionConfig.from_env() if config.persistence_enabled else None

        agent = CodeMateAgent(
            llm_client=llm,
            tools=tools,
            max_rounds=config.max_rounds,
            trace_logger=trace_logger,
            metrics=metrics,
            session_storage=session_storage,
            memory_manager=memory_manager,
            compression_enabled=config.persistence_enabled,
            compression_config=compression_config,
            planning_enabled=config.persistence_enabled,
            plan_display_callback=plan_display_callback,
            progress_callback=progress_display.on_event,
        )
    except Exception as e:
        console.print(f"[red]初始化失败: {e}[/red]")
        sys.exit(1)

    console.print(f"[cyan]问题:[/cyan] {prompt}\n")
    console.print("[bold yellow]Agent:[/bold yellow] [dim]思考中...[/dim]\n")

    try:
        result = agent.run(prompt)
        console.print(Panel(result, title="[bold green]答案[/bold green]", border_style="green"))

        stats = agent.get_stats()
        console.print(f"\n[dim]轮数: {stats['round_count']} | Tokens: {stats['total_tokens']}[/dim]")

        # 更新会话索引
        if session_storage and session_index:
            metadata = session_storage.get_metadata()
            if metadata:
                session_index.update(metadata)

        # 结束日志并显示统计
        if trace_logger:
            trace_logger.finalize()
        if metrics:
            metrics.finalize()
            metrics.print_summary()
            metrics.save(config.metrics_dir)

    except Exception as e:
        console.print(f"[red]执行出错: {e}[/red]")
        if trace_logger:
            trace_logger.log_event(
                TraceEventType.ERROR,
                {"error": str(e), "type": type(e).__name__},
            )


def main() -> None:
    """主入口"""
    parser = argparse.ArgumentParser(
        description="CodeMate AI - 基于 Function Calling 的代码分析 Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  codemate                    # 交互模式
  codemate "分析这个项目"     # 单次查询
  codemate --model MiniMax-M2 # 使用指定模型
        """
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="单次查询的问题（不指定则进入交互模式）"
    )
    parser.add_argument(
        "--model", "-m",
        help="使用的模型 (默认: MiniMax-M2)"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        help="最大对话轮数 (默认: 50)"
    )
    parser.add_argument(
        "--api-key",
        help="API Key"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="codemate-agent 0.3.0"
    )

    args = parser.parse_args()

    # 加载配置
    config = Config.from_env()

    # 命令行参数覆盖
    if args.model:
        config.model = args.model
    if args.max_rounds:
        config.max_rounds = args.max_rounds
    if args.api_key:
        config.api_key = args.api_key

    # 验证配置
    valid, error = config.validate()
    if not valid:
        console.print(f"[red]配置错误: {error}[/red]")
        sys.exit(1)

    # 运行
    if args.prompt:
        run_single_prompt(args.prompt, config)
    else:
        run_interactive(config)


if __name__ == "__main__":
    main()
