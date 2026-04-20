"""
进度显示模块

实时显示 Agent 执行进度。
"""

from __future__ import annotations

from rich.console import Console


class ProgressDisplay:
    """实时进度显示（Focus 模式：降噪展示）。"""

    KEY_TOOLS = {
        "task",
        "skill",
        "todo_write",
        "background_run",
        "check_background",
        "task_create",
        "task_get",
        "task_update",
        "task_list",
        "task_cleanup",
        "team_status",
        "run_shell",
    }

    NOISY_TOOLS = {
        "list_dir",
        "search_files",
        "search_code",
        "read_file",
        "file_info",
    }

    def __init__(self, console: Console):
        self.console = console
        self.current_round = 0
        self.max_rounds = 50
        self.action_index = 0
        self.current_tool = ""
        self.current_tool_is_key = False
        self.current_action_is_repeat = False
        self.current_action_signature = ""
        self.last_stage = ""
        self.last_decision = ""
        self.last_decision_round = 0
        self.last_action_signature = ""
        self.last_action_label = ""
        self.last_action_repeat_count = 0

    def on_event(self, event: str, data: dict) -> None:
        """处理进度事件"""
        if event == "round_start":
            self._flush_repeat_summary_if_needed()
            self.current_round = data.get("round", 0)
            self.max_rounds = data.get("max_rounds", 50)
            self.action_index = 0
            self.current_tool = ""
            self.current_tool_is_key = False
            self.current_action_is_repeat = False
            self.current_action_signature = ""
            self.last_action_signature = ""
            self.last_action_label = ""
            self.last_action_repeat_count = 0
            self._show_round_progress()
        elif event == "assistant_decision":
            self._show_decision(data.get("summary", ""))
        elif event == "tool_call_start":
            self.current_tool = data.get("tool", "")
            args = data.get("args", "")
            arguments = data.get("arguments", {}) if isinstance(data, dict) else {}
            self.current_tool_is_key = self.current_tool in self.KEY_TOOLS
            details = self._render_tool_details(self.current_tool, args, arguments)
            signature = f"{self.current_tool}|{details}"
            stage = self._classify_stage(self.current_tool, arguments)
            if self.current_tool_is_key and self.current_tool not in self.NOISY_TOOLS:
                self._show_stage_if_changed(stage)
            self.current_action_signature = signature

            if signature == self.last_action_signature:
                self.last_action_repeat_count += 1
                self.current_action_is_repeat = True
                if self.last_action_repeat_count == 2 and self.current_tool_is_key:
                    self.console.print(
                        f"  ↪ 重复行动已折叠: {self._shorten(self.last_action_label, 96)} ×2",
                        style="dim",
                        markup=False,
                    )
                return

            self._flush_repeat_summary_if_needed()
            self.current_action_is_repeat = False
            self.last_action_signature = signature
            self.last_action_label = details
            self.last_action_repeat_count = 1
            self.action_index += 1
            self._show_tool_call(self.current_tool, details)
        elif event == "tool_call_end":
            success = bool(data.get("success", True))
            preview = str(data.get("result_preview", ""))
            duration_ms = self._to_float(data.get("duration_ms", 0))
            if self._should_show_observation(success, preview):
                self._show_observation(
                    success=success,
                    preview=preview,
                    duration_ms=duration_ms,
                )
            self.current_tool = ""
            self.current_tool_is_key = False
            self.current_action_is_repeat = False
            self.current_action_signature = ""
        elif event == "team_inbox":
            count = self._to_int(data.get("count", 0))
            self._show_observation(
                success=bool(data.get("success", True)),
                preview=f"inbox 已摄取 {count} 条消息",
                duration_ms=0,
            )
        elif event == "background_results":
            count = self._to_int(data.get("count", 0))
            self._show_observation(True, f"收到 {count} 条后台结果通知", 0)
        elif event == "heartbeat_alert":
            op = str(data.get("operation", "unknown"))
            duration_ms = self._to_float(data.get("duration_ms", 0))
            self._show_observation(False, f"心跳告警: {op}", duration_ms)
        elif event == "runtime_warning":
            message = self._shorten(str(data.get("message", "")), 140)
            if message:
                self._show_observation(False, message, 0)
        elif event == "skill_auto_selected":
            skill = str(data.get("skill", "")).strip()
            hint = self._shorten(str(data.get("hint", "")), 120)
            if skill:
                self.console.print(f"  ✨ 自动 Skill: {skill}", style="magenta", markup=False)
            if hint:
                self.console.print(f"  ℹ️ {hint}", style="dim", markup=False)
        elif event == "repo_rag_retrieved":
            count = self._to_int(data.get("chunks", 0))
            source_count = self._to_int(data.get("source_count", 0))
            total_chars = self._to_int(data.get("total_chars", 0))
            mode = str(data.get("mode", "") or "").strip()
            mode_text = f" [{mode}]" if mode else ""
            self.console.print(
                f"  📚 RepoRAG{mode_text}: 命中 {count} 个片段 / {source_count} 个来源 ({total_chars} chars)",
                style="bright_blue",
                markup=False,
            )

    def _show_round_progress(self) -> None:
        """显示循环头（每轮显示）。"""
        self.console.print(
            f"━━ 进度 {self.current_round}/{self.max_rounds}",
            style="cyan",
            markup=False,
        )

    def _show_decision(self, summary: str) -> None:
        """显示决策摘要。"""
        compact = self._shorten(summary, 110)
        if not compact:
            return
        if compact == self.last_decision:
            return
        if (
            self.last_decision_round > 0
            and self.current_round - self.last_decision_round < 2
            and not self._is_high_signal_text(compact)
        ):
            return
        self.last_decision = compact
        self.last_decision_round = self.current_round
        self.console.print(f"  🧠 决策: {compact}", style="bright_blue", markup=False)

    def _show_tool_call(self, tool: str, details: str) -> None:
        """显示行动信息（含 subagent / skill 关键上下文）。"""
        if (tool not in self.KEY_TOOLS) or (tool in self.NOISY_TOOLS):
            return
        self.console.print(
            f"  ⚙️ 行动{self.action_index}: {details}",
            style="yellow",
            markup=False,
        )

    def _show_observation(self, success: bool, preview: str, duration_ms: float) -> None:
        """显示行动观察结果。"""
        icon = "✅" if success else "⚠️"
        tail = self._shorten(preview or "(no output)", 120)
        if duration_ms > 0:
            tail = f"{tail} ({duration_ms:.0f}ms)"
        style = "green" if success else "red"
        self.console.print(f"  👀 观察: {icon} {tail}", style=style, markup=False)

    def _render_tool_details(self, tool: str, args: str, arguments: dict) -> str:
        if tool == "todo_write":
            return "todo_write (计划更新)"
        if tool == "task":
            member = self._extract_task_member(arguments)
            desc = self._shorten(str(arguments.get("description", "")), 60)
            if member:
                return f"task[member:{member}] {desc}".strip()
            subagent = str(arguments.get("subagent_type", "general"))
            return f"task[subagent:{subagent}] {desc}".strip()
        if tool == "skill":
            action = str(arguments.get("action", "load"))
            skill_name = str(arguments.get("skill_name", ""))
            return f"skill[{action}] {skill_name}".strip()
        return f"{tool} ({self._shorten(args, 80)})" if args else tool

    def _classify_stage(self, tool: str, arguments: dict) -> str:
        if tool == "todo_write":
            return "计划同步"
        if tool in {"task_create", "task_get", "task_update", "task_list", "task_cleanup"}:
            return "任务系统"
        if tool in {"background_run", "check_background"}:
            return "后台任务"
        if tool == "task":
            if self._extract_task_member(arguments):
                return "团队委托"
            return "子代理"
        if tool == "skill":
            return "Skill"
        if tool == "team_status":
            return "团队状态"
        if tool == "run_shell":
            cmd = str(arguments.get("command", "")).lower()
            if ".team" in cmd:
                return "团队证据"
            return "Shell执行"
        return "工具执行"

    def _show_stage_if_changed(self, stage: str) -> None:
        if not stage or stage == self.last_stage:
            return
        self.last_stage = stage
        self.console.print(f"── 阶段: {stage}", style="magenta", markup=False)

    def _flush_repeat_summary_if_needed(self) -> None:
        if self.last_action_repeat_count <= 2:
            return
        self.console.print(
            f"  ↪ 重复行动已折叠: {self._shorten(self.last_action_label, 96)} ×{self.last_action_repeat_count}",
            style="dim",
            markup=False,
        )

    def _should_show_observation(self, success: bool, preview: str) -> bool:
        if self.current_tool in self.NOISY_TOOLS:
            return (not success)
        if not success:
            return True
        if self.current_tool_is_key:
            if self.current_action_is_repeat:
                return self._is_high_signal_text(preview)
            return True
        return self._is_high_signal_text(preview)

    def _is_high_signal_text(self, text: str) -> bool:
        probe = str(text or "")
        markers = (
            "错误",
            "error",
            "failed",
            "warning",
            "Background task",
            "task_id",
            "blockedBy",
            "TODO UPDATE",
            "completed",
            "已完成",
            "inbox",
            "background",
        )
        return any(marker.lower() in probe.lower() for marker in markers)

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        value = " ".join(str(text or "").split())
        if len(value) <= limit:
            return value
        return value[: max(limit - 3, 0)] + "..."

    @staticmethod
    def _to_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _extract_task_member(arguments: dict) -> str:
        if not isinstance(arguments, dict):
            return ""
        agent_id = str(arguments.get("agent_id", "")).strip().lower()
        if agent_id:
            return agent_id

        raw = str(arguments.get("subagent_type", "")).strip().lower()
        if raw.startswith("team:"):
            return raw.split(":", 1)[1].strip()
        if raw in {"researcher", "builder", "reviewer", "lead"}:
            return raw
        return ""

    @staticmethod
    def _to_float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
