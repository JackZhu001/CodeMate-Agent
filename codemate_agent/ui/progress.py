"""
进度显示模块

实时显示 Agent 执行进度。
"""

from rich.console import Console


class ProgressDisplay:
    """实时进度显示"""

    # 状态图标
    ICONS = {
        "running": "▶",
        "done": "✓",
        "error": "✗",
    }

    def __init__(self, console: Console):
        self.console = console
        self.current_round = 0
        self.current_tool = ""
        self.max_rounds = 50

    def on_event(self, event: str, data: dict) -> None:
        """处理进度事件"""
        if event == "round_start":
            self.current_round = data.get("round", 0)
            self.max_rounds = data.get("max_rounds", 50)
            self._show_round_progress()
        elif event == "tool_call_start":
            self.current_tool = data.get("tool", "")
            args = data.get("args", "")
            self._show_tool_call(self.current_tool, args)
        elif event == "tool_call_end":
            self.current_tool = ""

    def _show_round_progress(self) -> None:
        """显示轮次进度"""
        width = 16
        done = int((self.current_round / max(self.max_rounds, 1)) * width)
        bar = "🟪" * done + "⬜" * (width - done)
        self.console.print(
            f"[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]\n"
            f"[cyan]🐾 Round {self.current_round}/{self.max_rounds}[/cyan]  {bar}"
        )

    def _show_tool_call(self, tool: str, args: str) -> None:
        """显示工具调用"""
        if args:
            self.console.print(f"  [dim]└─[/dim] 🛠️ [yellow]{tool}[/yellow] [dim]({args})[/dim]")
        else:
            self.console.print(f"  [dim]└─[/dim] 🛠️ [yellow]{tool}[/yellow]")
