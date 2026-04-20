"""
Agent 实现

支持原生 Function Calling 的代码分析 Agent。

这是整个项目的核心模块，实现了基于 Function Calling 的 Agent 循环：
1. 接收用户输入
2. 调用 LLM（带上工具列表）
3. 如果 LLM 请求调用工具，执行工具并获取结果
4. 将工具结果返回给 LLM
5. 重复步骤 2-4，直到 LLM 给出最终答案

与传统 ReAct 的区别：
- ReAct: 解析 LLM 输出的文本（Action: ...），容易出错
- Function Calling: LLM 直接返回结构化的 tool_calls，更可靠
"""

import os
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, List, Optional

from codemate_agent.llm.client import LLMClient as GLMClient, ToolProtocolError
from codemate_agent.schema import Message, LLMResponse, ToolCall, FunctionCall
from codemate_agent.tools.base import Tool
from codemate_agent.tools.registry import ToolRegistry
from codemate_agent.logging import setup_logger, TraceLogger, SessionMetrics, TraceEventType
from codemate_agent.persistence import SessionStorage, MemoryManager
from codemate_agent.context import ContextCompressor, CompressionConfig, ObservationTruncator
from codemate_agent.planner import TaskPlanner
from codemate_agent.retrieval import RepoRAG
from codemate_agent.subagent import TaskTool
from codemate_agent.validation import ArgumentValidator
from codemate_agent.skill import SkillManager, SkillCaptureManager
from codemate_agent.prompts import SYSTEM_PROMPT
from codemate_agent.agent.loop_detector import LoopDetector
from codemate_agent.agent.heartbeat import HeartbeatMonitor
from codemate_agent.agent.loop_guard import LoopGuard
from codemate_agent.agent.team_runtime import TeamRuntime
from codemate_agent.team.coordinator import TeamCoordinator


# 需要用户确认的危险工具
DANGEROUS_TOOLS = {
    "delete_file",
    "write_file",
    "run_shell",
    "background_run",
    "task_cleanup",
}

MAX_INLINE_FILE_CONTENT = 3000


class CodeMateAgent:
    """
    Oh-My-Claw Agent

    使用原生 Function Calling 进行代码分析的 AI Agent。

    工作流程示例：
        用户: "这个项目有哪些文件？"
        LLM: [tool_call: list_dir(path=".")]
        Agent: 执行 list_dir → 返回文件列表
        LLM: "这个项目包含 main.py, config.py..."
    """

    def __init__(
        self,
        llm_client: "GLMClient",
        tools: List[Tool],
        max_rounds: int = 50,
        workspace_dir: str = ".",
        confirm_callback: Optional[Callable[[str, dict], bool]] = None,
        trace_logger: Optional[TraceLogger] = None,
        metrics: Optional[SessionMetrics] = None,
        session_storage: Optional[SessionStorage] = None,
        memory_manager: Optional[MemoryManager] = None,
        compression_enabled: bool = True,
        compression_config: Optional[CompressionConfig] = None,
        planning_enabled: bool = True,
        plan_display_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, dict], None]] = None,
        light_llm_client: Optional["GLMClient"] = None,
        repo_rag_enabled: bool = True,
        repo_rag_top_k: int = 5,
        repo_rag_char_budget: int = 2500,
    ):
        """
        初始化 Agent

        Args:
            llm_client: LLM 客户端，用于调用 GLM API
            tools: 工具列表，Agent 可以使用的所有工具
            max_rounds: 最大交互轮数，防止无限循环
            workspace_dir: 工作目录，工具将在此目录下操作
            confirm_callback: 用户确认回调函数，接收 (tool_name, arguments)，返回是否同意
            trace_logger: Trace 轨迹日志记录器（可选）
            metrics: 会话指标统计（可选）
            session_storage: 会话持久化存储（可选）
            memory_manager: 长期记忆管理器（可选）
            compression_enabled: 是否启用上下文压缩（默认 True）
            compression_config: 压缩配置（可选）
            planning_enabled: 是否启用任务规划功能（默认 True）
            plan_display_callback: 计划显示回调函数，用于显示执行计划（可选）
            progress_callback: 进度回调函数，接收 (event, data)，用于实时显示进度（可选）
            light_llm_client: 轻量模型客户端，用于子代理的简单任务（可选，默认使用主模型）
            repo_rag_enabled: 是否启用 RepoRAG 项目知识检索
            repo_rag_top_k: RepoRAG 默认返回片段数
            repo_rag_char_budget: RepoRAG 注入上下文的总字符预算
        """
        self.llm = llm_client                    # LLM 客户端
        self.light_llm = light_llm_client        # 轻量模型客户端
        self.max_rounds = max_rounds              # 最大轮数限制
        self.workspace_dir = Path(workspace_dir) # 当前工作目录
        self.confirm_callback = confirm_callback  # 用户确认回调
        self.plan_display_callback = plan_display_callback  # 计划显示回调
        self.progress_callback = progress_callback  # 进度回调
        self._current_run_capture: dict[str, Any] | None = None

        # 日志系统
        self.logger = setup_logger("codemate.agent")
        self.trace_logger = trace_logger
        self.metrics = metrics

        # 持久化系统
        self.session_storage = session_storage
        self.memory_manager = memory_manager
        self.repo_rag_enabled = repo_rag_enabled
        self.repo_rag = None
        if self.repo_rag_enabled:
            self.repo_rag = RepoRAG(
                workspace_dir=self.workspace_dir,
                memory_manager=self.memory_manager,
                top_k=repo_rag_top_k,
                char_budget=repo_rag_char_budget,
            )

        # 上下文压缩
        self.compression_enabled = compression_enabled
        if compression_enabled:
            self.compressor = ContextCompressor(
                config=compression_config or CompressionConfig.from_env(),
                llm_client=llm_client,
            )
        else:
            self.compressor = None

        # 工具输出截断器
        self.truncator = ObservationTruncator()

        # 上一次 API 调用的 token 数（用于压缩判断）
        self._last_usage_tokens = 0
        # 上一次 API 报告的累计 token 数（用于检测累计值）
        self._last_reported_total_tokens = 0
        
        # 循环检测器
        self.loop_detector = LoopDetector(window_size=10)
        # LoopGuard：集中处理连续失败与提前结束防护
        self.loop_guard = LoopGuard(max_consecutive_failures=3)

        # todo 进度跟踪 + nag reminder
        self._todo_all_completed = False  # 所有 todo 是否完成
        self._last_completed_count = 0  # 最近一次完成的任务数
        self._rounds_since_todo = 0  # 距离上次更新 todo 的轮数
        raw_todo_nag_interval = os.getenv("TODO_NAG_INTERVAL", "6")
        try:
            self._max_rounds_without_todo = int(raw_todo_nag_interval)
        except ValueError:
            self.logger.warning(
                f"TODO_NAG_INTERVAL 无效值: {raw_todo_nag_interval}，回退默认 6"
            )
            self._max_rounds_without_todo = 6
        nag_env_enabled = os.getenv("TODO_NAG_ENABLED", "true").lower() == "true"
        self._todo_nag_enabled = nag_env_enabled and self._max_rounds_without_todo > 0
        # 由 LoopGuard 管理 premature finish

        # 工具注册：将所有工具注册到注册器中
        # 这样可以通过工具名称快速查找和执行工具
        self.tool_registry = ToolRegistry()
        for tool in tools:
            self.tool_registry.register(tool)

        # 任务规划器
        self.planning_enabled = planning_enabled
        if planning_enabled:
            self.planner = TaskPlanner(
                llm_client=llm_client,
                enabled=True,
                auto_planning=True,
            )
        else:
            self.planner = None

        # Skill 管理器（工作区优先，回退到内置 skills）
        bundled_skills_dir = Path(__file__).parent.parent.parent / "skills"
        self.skill_manager = SkillManager(
            skills_dir=self.workspace_dir / "skills",
            extra_skills_dirs=[bundled_skills_dir],
        )
        self.skill_capture_manager = SkillCaptureManager(
            workspace_dir=self.workspace_dir,
            tool_registry=self.tool_registry,
            llm_client=self.light_llm or self.llm,
        )
        self.skill_auto_trigger_enabled = os.getenv("SKILL_AUTO_TRIGGER_ENABLED", "true").lower() == "true"

        # Task 工具：用于委托子代理
        # 需要注入依赖（llm_client, tool_registry, 以及可选的 light_llm_client）
        self.team_coordinator = TeamCoordinator(
            workspace_dir=self.workspace_dir,
            main_llm_client=llm_client,
            light_llm_client=light_llm_client,
            tool_registry=self.tool_registry,
        )
        self.task_tool = TaskTool(working_dir=str(self.workspace_dir))
        self.task_tool.set_dependencies(
            main_llm_client=llm_client,
            tool_registry=self.tool_registry,
            light_llm_client=light_llm_client,
            team_coordinator=self.team_coordinator,
            delegate_handler=None,
        )
        # 注册 Task 工具
        self.tool_registry.register(self.task_tool)

        # 消息历史：存储整个对话过程
        # 第一条消息始终是 system 角色的系统提示词
        self.messages: List[Message] = [
            Message(role="system", content=self._get_system_prompt())
        ]

        # Compact 工具：手动触发对话压缩
        # 需要注入依赖（compressor 和 messages 引用）
        from codemate_agent.tools.compact import CompactTool
        self.compact_tool = CompactTool()
        CompactTool.set_dependencies(
            compressor=self.compressor if self.compression_enabled else None,
            messages=self.messages,
        )
        # 注册 Compact 工具
        self.tool_registry.register(self.compact_tool)

        # MemoryWrite / MemoryRead 工具：主动读写长期记忆
        if self.memory_manager is not None:
            from codemate_agent.tools.memory.memory_write import MemoryWriteTool
            MemoryWriteTool.set_dependencies(
                memory_manager=self.memory_manager,
                workspace_dir=self.workspace_dir,
            )
            self.tool_registry.register(MemoryWriteTool())

            from codemate_agent.tools.memory.memory_read import MemoryReadTool
            MemoryReadTool.set_dependencies(
                memory_manager=self.memory_manager,
                repo_rag=self.repo_rag,
            )
            self.tool_registry.register(MemoryReadTool())

        # 统计信息
        self.round_count = 0      # 当前对话轮数
        self.total_tokens = 0     # 累计消耗的 token 数

        # 会话标识
        self.session_id = getattr(self.trace_logger, "session_id", f"local-{uuid.uuid4().hex[:8]}")

        # 心跳监控
        heartbeat_enabled = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
        heartbeat_timeout_seconds = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "45"))
        heartbeat_mode = os.getenv("HEARTBEAT_MODE", "task_polling")  # task_polling | verbose
        heartbeat_poll_seconds = int(os.getenv("HEARTBEAT_POLL_SECONDS", "15"))
        heartbeat_dir = Path(os.getenv("HEARTBEAT_DIR", "logs/sessions"))

        def _todo_stats() -> tuple[int, int]:
            from codemate_agent.tools.todo.todo_write import TodoWriteTool
            todo_state = TodoWriteTool.get_current_state()
            pending = 0
            in_progress = 0
            if todo_state:
                stats = todo_state.get("stats", {})
                pending = int(stats.get("pending", 0))
                in_progress = int(stats.get("in_progress", 0))
            return pending, in_progress

        self.heartbeat = HeartbeatMonitor(
            session_id=self.session_id,
            heartbeat_dir=heartbeat_dir,
            enabled=heartbeat_enabled,
            timeout_seconds=heartbeat_timeout_seconds,
            mode=heartbeat_mode,
            poll_seconds=heartbeat_poll_seconds,
            progress_callback=self.progress_callback,
            logger=self.logger,
            state_provider=lambda: {
                "round": self.round_count,
                "message_count": len(self.messages),
                "total_tokens": self.total_tokens,
            },
            todo_stats_provider=_todo_stats,
            todo_nag_enabled=self._todo_nag_enabled,
        )
        self.heartbeat.emit("idle", source="init")
        self.heartbeat.start_worker()

        # 团队协作运行时（可选）
        self.team_enabled = os.getenv("TEAM_AGENT_ENABLED", "false").lower() == "true"
        self.background_tasks_enabled = os.getenv("BACKGROUND_TASKS_ENABLED", "true").lower() == "true"
        self.team_name = os.getenv("TEAM_NAME", "default")
        self.team_agent_name = os.getenv("TEAM_AGENT_NAME", "lead")
        self.team_agent_role = os.getenv("TEAM_AGENT_ROLE", "lead")
        self.task_auto_claim_enabled = os.getenv("TASK_AUTO_CLAIM_ENABLED", "false").lower() == "true"
        self._identity_reinject_threshold = int(os.getenv("TEAM_IDENTITY_REINJECT_THRESHOLD", "6"))
        self.team = TeamRuntime(
            enabled=self.team_enabled,
            workspace_dir=self.workspace_dir,
            team_name=self.team_name,
            agent_name=self.team_agent_name,
            agent_role=self.team_agent_role,
            tool_registry=self.tool_registry,
            messages=self.messages,
            session_id_provider=lambda: self.session_id,
            round_provider=lambda: self.round_count,
            progress_callback=self.progress_callback,
            logger=self.logger,
            team_coordinator=self.team_coordinator,
            task_auto_claim_enabled=self.task_auto_claim_enabled,
            background_tasks_enabled=self.background_tasks_enabled,
            identity_reinject_threshold=self._identity_reinject_threshold,
        ) if self.team_enabled else None
        if self.team:
            self.task_tool.set_delegate_handler(self.team.dispatch_task)
            self.team.ensure_identity_block(force=True)
            self.team.sync_shell_context()
            self.team.emit_event(
                "team_runtime_ready",
                {
                    "team": self.team_name,
                    "agent_name": self.team_agent_name,
                    "agent_role": self.team_agent_role,
                },
            )

    def run(self, query: str) -> str:
        """
        运行 Agent - 这是核心方法

        执行完整的 Agent 循环，直到获得最终答案或达到最大轮数。

        Args:
            query: 用户的查询问题

        Returns:
            str: Agent 的最终答案

        执行流程：
        ┌─────────────────────────────────────────────────────────────┐
        │ 1. 添加用户消息到历史                                       │
        │ 2. 调用 LLM（带上工具列表）                                │
        │ 3. 检查响应是否包含 tool_calls                             │
        │    ├─ 是：执行所有工具，将结果发回 LLM，回到步骤 2         │
        │    └─ 否：返回 content 作为最终答案                        │
        │ 4. 重复直到有答案或达到最大轮数                            │
        └─────────────────────────────────────────────────────────────┘
        """
        task_type, cleaned_query = self.skill_capture_manager.extract_task_type(query)
        if task_type:
            query = cleaned_query
        else:
            suggested_task_type = self.skill_capture_manager.suggest_task_type(query)
            if suggested_task_type:
                task_type = suggested_task_type
                self._emit_progress(
                    "task_type_suggested",
                    {
                        "task_type": task_type,
                        "hint": "本次未显式标注 task_type，已根据请求内容自动建议并用于 skill 草稿沉淀。",
                    },
                )
                self._emit_team_event("task_type_suggested", {"task_type": task_type})

        # 步骤 -1: 检查是否是 skill 命令
        if query.startswith("/"):
            skill_result = self._handle_skill_command(query)
            if skill_result is not None:
                # skill 命令已处理，将 skill prompt 注入后继续执行
                query = skill_result
        else:
            auto_skill = self._try_auto_trigger_skill(query)
            if auto_skill is not None:
                skill_name, enhanced_query = auto_skill
                query = enhanced_query
                self._emit_progress(
                    "skill_auto_selected",
                    {
                        "skill": skill_name,
                        "hint": "本次由意图自动触发；可在下次输入前加 [no-skill] 关闭自动触发。",
                    },
                )
                self._emit_team_event("skill_auto_selected", {"skill": skill_name})

        # 每轮根据当前 query 刷新 system prompt（包含关键词召回记忆 + codemate.md）
        if self.messages and self.messages[0].role == "system":
            self.messages[0] = Message(role="system", content=self._get_system_prompt(query))
        if self.team:
            self.team.ensure_identity_block()
        self._inject_runtime_warnings(query)

        # 注意: 渐进式 Skill 加载
        # 不再自动注入完整 Skill 内容，而是让 LLM 通过 skill 工具按需加载
        # 系统提示词中只包含 Skill 索引（name + description）

        # 记录用户输入
        self.logger.debug(f"用户输入: {query[:100]}...")
        self.heartbeat.emit("run_started", source="run", query_len=len(query))
        self._emit_team_event("run_started", {"query_len": len(query)})
        if self.trace_logger:
            self.trace_logger.log_event(
                TraceEventType.USER_INPUT,
                {"text": query, "length": len(query)},
                step=0,
            )
        if self.metrics:
            self.metrics.record_round()

        # 保存到持久化存储
        if self.session_storage:
            self.session_storage.add_user_message(query)
        self._start_run_capture(query, task_type)

        # ========== 三层上下文压缩 ==========

        # Layer 1: Micro Compact - 每轮自动压缩旧的 tool_result
        if self.compression_enabled and self.compressor:
            self.messages = self.compressor.micro_compact(self.messages)

        # Layer 2: Auto Compact - token 超阈值时触发
        if self.compression_enabled and self.compressor:
            estimated_tokens = self.compressor.estimate_tokens(self.messages)
            if estimated_tokens > self.compressor.auto_compact_threshold():
                self.logger.info(f"[auto_compact] token 超阈值 ({estimated_tokens})，正在压缩...")
                old_count = len(self.messages)
                self.messages = self.compressor.auto_compact(self.messages)
                from codemate_agent.tools.compact import CompactTool
                CompactTool._messages_ref = self.messages
                self.logger.info(f"[auto_compact] 完成: {old_count} -> {len(self.messages)} 条消息")

                if self.trace_logger:
                    self.trace_logger.log_event(
                        TraceEventType.INFO,
                        {"event": "auto_compact", "before": old_count, "after": len(self.messages)},
                    )

        # Layer 3: 原有压缩（用于增量压缩）
        if self.compression_enabled and self.compressor:
            if self.compressor.should_compress(
                self.messages,
                self.total_tokens,  # 使用累计 token 数而非单次请求 token 数
                query,
            ):
                self.logger.info("上下文过长，正在压缩...")
                old_count = len(self.messages)
                self.messages = self.compressor.compress(self.messages)
                self.logger.info(f"上下文压缩完成: {old_count} → {len(self.messages)} 条消息")

                # 记录压缩事件
                if self.trace_logger:
                    self.trace_logger.log_event(
                        TraceEventType.INFO,
                        {"event": "context_compressed", "before": old_count, "after": len(self.messages)},
                    )

        # 步骤 0.5: 检查是否需要任务规划
        # 在添加用户消息之前检查，避免规划结果被重复添加
        planning_result = None
        if self.planning_enabled and self.planner:
            if self.planner.needs_planning(query):
                self.logger.info("检测到复杂任务，正在生成执行计划...")
                plan = self.planner.generate_plan(query)
                if plan:
                    planning_result = plan
                    # 记录规划事件
                    if self.trace_logger:
                        self.trace_logger.log_event(
                            TraceEventType.INFO,
                            {"event": "task_planned", "summary": plan.summary, "steps": len(plan.steps)},
                        )
                    # 自动执行 TodoWrite 工具创建计划
                    try:
                        todo_result = self.tool_registry.execute(
                            "todo_write",
                            **plan.to_todo_params()
                        )
                        self.logger.info(f"执行计划已创建: {plan.summary}")

                        # 调用计划显示回调（在 CLI 中显示）
                        if self.plan_display_callback:
                            self.plan_display_callback(todo_result)

                        # 将 TodoWrite 结果添加到消息历史
                        self.messages.append(Message(role="system", content=f"""
# 执行计划

{todo_result}

请按照上述计划逐步完成任务。完成每个步骤后，使用 TodoWrite 工具更新步骤状态。
"""))
                    except Exception as e:
                        self.logger.warning(f"创建执行计划失败: {e}")

        # 步骤 1: 将用户输入添加到消息历史
        self.messages.append(Message(role="user", content=query))
        self.round_count = 0
        self._high_context_warned = False  # 每次 run 只注入一次高 context 警告

        # 获取所有工具的 OpenAI Schema 格式
        # LLM 需要知道有哪些工具可用，以及每个工具的参数格式
        tools = [t.to_openai_schema() for t in self.tool_registry.get_all().values()]

        # 步骤 2-4: 主循环
        tool_protocol_repairs = 0
        llm_transient_failures = 0
        llm_transient_retry_rounds = int(os.getenv("LLM_TRANSIENT_RETRY_ROUNDS", "3"))
        llm_transient_soft_fail = os.getenv("LLM_TRANSIENT_SOFT_FAIL", "true").lower() == "true"
        while self.round_count < self.max_rounds:
            self.round_count += 1
            if self.metrics:
                self.metrics.record_round()

            if self.team:
                self.team.ingest_inbox()
                self.team.auto_claim_task()
                self.team.ingest_background_notifications()
                self.team.ensure_identity_block()
            elif self.background_tasks_enabled:
                self._ingest_background_notifications()

            # ========== Layer 1: Micro Compact (每轮执行) ==========
            if self.compression_enabled and self.compressor:
                self.messages = self.compressor.micro_compact(self.messages)
                # 更新 CompactTool 的 messages 引用
                from codemate_agent.tools.compact import CompactTool
                CompactTool._messages_ref = self.messages
                if self.team:
                    self.team.ensure_identity_block()

            # 触发轮次开始事件
            self._emit_progress("round_start", {
                "round": self.round_count,
                "max_rounds": self.max_rounds,
            })
            self.heartbeat.emit("round_start", source="loop", round=self.round_count)
            self._emit_team_event("round_start", {"round": self.round_count})

            # ========== 高 Context 警告（每次 run 只注入一次）==========
            if not self._high_context_warned and self.compression_enabled and self.compressor:
                estimated = self.compressor.estimate_tokens(self.messages)
                if estimated > 50000:
                    self._high_context_warned = True
                    self.messages.append(Message(
                        role="system",
                        content=(
                            "<warning>当前上下文较大（约 {est}k tokens）。"
                            "调用写文件工具时参数必须完整，切勿省略 file_path / chunks / content。"
                            "若因输出截断导致参数为空，请缩短单次输出后重试。</warning>"
                        ).format(est=round(estimated / 1000)),
                    ))
                    self.logger.info(f"[high_context] 已注入警告 (estimated={estimated})")

            # ========== Todo Nag Reminder ==========
            # 如果多轮未更新 todo，注入提醒
            if (
                self._todo_nag_enabled
                and self._rounds_since_todo >= self._max_rounds_without_todo
            ):
                self.logger.info(f"[nag] 超过 {self._rounds_since_todo} 轮未更新 todo，注入提醒")
                self.messages.append(Message(
                    role="system",
                    content="<reminder>请更新你的任务进度。使用 todo_write 工具记录当前进度。</reminder>"
                ))
                # 重置计数器，避免连续提醒
                self._rounds_since_todo = 0

            # 检查 todo 是否全部完成，如果是则添加提示
            if self._todo_all_completed and not hasattr(self, '_completion_hint_sent'):
                self.messages.append(Message(
                    role="system",
                    content="所有计划的任务已完成。请给出最终总结，不要继续执行其他操作。"
                ))
                self._completion_hint_sent = True
                self.logger.info("已发送完成提示，等待 LLM 给出最终答案")

            # 调用 LLM，传入：
            # - messages: 完整的对话历史
            # - tools: 可用工具列表（OpenAI Function Calling 格式）
            start_time = time.time()
            self.heartbeat.emit("llm_request", source="llm", round=self.round_count)
            self._emit_team_event("llm_request", {"round": self.round_count, "messages": len(self.messages)})

            # 记录 LLM 请求
            if self.trace_logger:
                self.trace_logger.log_event(
                    TraceEventType.LLM_REQUEST,
                    {
                        "model": self.llm.model,
                        "messages_count": len(self.messages),
                        "tools_count": len(tools),
                    },
                    step=self.round_count,
                )

            try:
                response: LLMResponse = self.llm.complete(
                    messages=self.messages,
                    tools=tools,
                )
            except ToolProtocolError as e:
                if tool_protocol_repairs >= 1:
                    raise
                tool_protocol_repairs += 1
                self.logger.warning("检测到工具协议链损坏，正在重建兼容历史后重试: %s", e)
                self._repair_tool_protocol_history(str(e))
                continue
            except Exception as e:
                if not self._is_transient_llm_error(str(e)):
                    raise
                llm_transient_failures += 1
                self.logger.warning(
                    "LLM 暂时不可用（第 %s/%s 次）: %s",
                    llm_transient_failures,
                    llm_transient_retry_rounds,
                    e,
                )
                self.heartbeat.emit(
                    "llm_error",
                    source="llm",
                    transient=True,
                    retry=llm_transient_failures,
                )
                self._emit_team_event(
                    "llm_error",
                    {
                        "transient": True,
                        "retry": llm_transient_failures,
                        "error": str(e)[:300],
                    },
                )
                if llm_transient_failures > llm_transient_retry_rounds:
                    fallback = (
                        "上游模型服务持续异常（多次 5xx/网络波动），本次任务已中止以避免无效重试。"
                        "请稍后重试，或切换到更稳定的 provider/model 后再执行。"
                    )
                    self.heartbeat.emit(
                        "llm_unavailable",
                        source="llm",
                        transient=True,
                        retries=llm_transient_failures,
                    )
                    self._emit_team_event(
                        "llm_unavailable",
                        {"retries": llm_transient_failures, "error": str(e)[:300]},
                    )
                    self.logger.error(
                        "上游模型服务持续异常，终止本次运行（soft_fail=%s）: %s",
                        llm_transient_soft_fail,
                        e,
                    )
                    if llm_transient_soft_fail:
                        if self.session_storage:
                            try:
                                self.session_storage.add_assistant_message(fallback)
                                self.session_storage.update_metadata(total_tokens=self.total_tokens)
                            except Exception:
                                pass
                        return fallback
                    raise
                self.messages.append(
                    Message(
                        role="system",
                        content=(
                            "上游模型服务暂时异常（HTTP 5xx/网络波动）。"
                            f"已自动重试 {llm_transient_failures}/{llm_transient_retry_rounds}，"
                            "请继续执行当前任务，不要改变任务目标。"
                        ),
                    )
                )
                continue

            duration_ms = (time.time() - start_time) * 1000
            llm_transient_failures = 0
            self.heartbeat.emit("llm_response", source="llm", duration_ms=round(duration_ms, 2))
            self.heartbeat.check_timeout("llm", duration_ms)
            self._emit_team_event(
                "llm_response",
                {
                    "round": self.round_count,
                    "duration_ms": round(duration_ms, 2),
                    "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
                },
            )

            # 更新 token 统计（用于成本控制）
            if response.usage:
                reported_total = response.usage.total_tokens

                # 检查 token 数是否合理（单次请求通常不应超过 15000）
                # GLM API 有时返回累计值而非单次值
                SINGLE_REQUEST_TOKEN_LIMIT = 15000
                # delta 合法性上限：单次对话不可能超过 100k token
                DELTA_MAX = 100_000
                if reported_total > SINGLE_REQUEST_TOKEN_LIMIT:
                    # 检测到累计值，计算差值
                    if self._last_reported_total_tokens > 0:
                        actual_tokens = reported_total - self._last_reported_total_tokens
                        # 校验 delta 合法性：必须为正且不超过上限
                        if 0 < actual_tokens < DELTA_MAX:
                            self._last_usage_tokens = actual_tokens
                            self.total_tokens += actual_tokens
                            self.logger.debug(
                                f"检测到累计 token，计算差值: {reported_total} - {self._last_reported_total_tokens} = {actual_tokens}"
                            )
                        else:
                            # delta 异常（负数或超大），回退到估算
                            estimated_tokens = len(str(response.content)) // 3 + 500
                            self._last_usage_tokens = estimated_tokens
                            self.total_tokens += estimated_tokens
                            self.logger.warning(
                                f"token delta 异常 ({actual_tokens})，使用估算值: {estimated_tokens}"
                            )
                    else:
                        # 第一次调用，使用估算值
                        estimated_tokens = len(str(response.content)) // 3 + 1000
                        self._last_usage_tokens = estimated_tokens
                        self.total_tokens += estimated_tokens
                        self.logger.warning(
                            f"首次检测到高 token 数，使用估算值: {estimated_tokens}"
                        )
                    self._last_reported_total_tokens = reported_total
                else:
                    # 正常值，直接使用
                    # 但也要检查是否比上次报告的值还小（说明 API 重置了累计）
                    if self._last_reported_total_tokens > 0 and reported_total < self._last_reported_total_tokens:
                        # API 重置了累计值，从本次开始重新跟踪
                        self._last_reported_total_tokens = 0
                        self.logger.info("检测到 token 计数重置，重新开始累计跟踪")

                    self.total_tokens += reported_total
                    self._last_usage_tokens = reported_total

                    # 如果是合理的累计值，也记录下来
                    if reported_total > SINGLE_REQUEST_TOKEN_LIMIT // 2:
                        self._last_reported_total_tokens = reported_total

                # 记录到 metrics
                if self.metrics:
                    self.metrics.record_llm_call(response.usage, duration_ms)

            # 记录 LLM 响应
            if self.trace_logger:
                self.trace_logger.log_event(
                    TraceEventType.LLM_RESPONSE,
                    {
                        "content": response.content[:200] if response.content else "",
                        "tool_calls_count": len(response.tool_calls) if response.tool_calls else 0,
                        "usage": response.usage.model_dump() if response.usage else None,
                        "duration_ms": round(duration_ms, 2),
                    },
                    step=self.round_count,
                )

            # 将 LLM 的响应添加到消息历史
            # 注意：assistant 消息可能包含 content 和 tool_calls
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls
            )
            self.messages.append(assistant_msg)
            decision_summary = self._build_decision_summary(
                response.content or "",
                has_tool_calls=bool(response.tool_calls),
            )
            if decision_summary:
                self._emit_progress(
                    "assistant_decision",
                    {
                        "summary": decision_summary,
                        "tool_calls": len(response.tool_calls) if response.tool_calls else 0,
                    },
                )

            # 注意: 渐进式 Skill 加载
            # 不再检测 LLM 声明，而是让 LLM 主动调用 skill 工具加载内容

            # 步骤 3: 检查 LLM 是否请求调用工具
            if response.tool_calls:
                self.logger.debug(f"LLM 请求调用 {len(response.tool_calls)} 个工具")
                self.loop_guard.reset_premature()

                # 检测循环：记录本次工具调用
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = tool_call.function.arguments
                    # 记录工具调用到循环检测器
                    self.loop_detector.record_call(tool_name, arguments)

                # 检测是否陷入循环
                try:
                    if self._is_stuck_in_loop():
                        loop_info = self.loop_guard.on_loop_detected()
                        loop_count = loop_info.get("count", 1)
                        forced = loop_info.get("forced", False)

                        loop_warning = f"检测到 Agent 陷入循环（第 {loop_count} 次）。"
                        if forced:
                            loop_warning += " 采取强制措施打破循环。"
                            self.logger.warning(loop_warning)
                            self.loop_detector.reset()

                            self.messages.append(Message(
                                role="system",
                                content="""严重警告：已连续 3 次检测到工具调用循环。请立即停止当前尝试的方法。

当前策略明显无效，请：
1. 向用户说明当前遇到的问题
2. 询问用户是否有其他建议
3. 或者尝试完全不同的方法

不要再重复相同的工具调用！"""
                            ))

                            if self.trace_logger:
                                self.trace_logger.log_event(
                                    TraceEventType.WARNING,
                                    {"message": loop_warning, "action": "forced_break", "recent_calls": self.loop_detector.recent_calls},
                                    step=self.round_count,
                                )
                        else:
                            self.logger.warning(loop_warning)
                            if self.trace_logger:
                                self.trace_logger.log_event(
                                    TraceEventType.WARNING,
                                    {"message": loop_warning, "recent_calls": self.loop_detector.recent_calls},
                                    step=self.round_count,
                                )
                            self.messages.append(Message(
                                role="system",
                                content=f"警告：检测到重复的工具调用模式（第 {loop_count} 次）。请重新评估当前状态，尝试不同的方法。"
                            ))
                except Exception as e:
                    self.logger.error(f"循环检测出错: {e}")
                    # 清空历史以防止持续出错
                    self.loop_detector.reset()

                # LLM 请求调用工具，执行所有工具调用
                used_todo_this_round = False
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = tool_call.function.arguments

                    # 触发工具调用开始事件
                    self._emit_progress("tool_call_start", {
                        "tool": tool_name,
                        "args": self._format_args_for_display(arguments),
                        "arguments": arguments,
                    })
                    self.heartbeat.emit("tool_call_start", source="tool", tool=tool_name)
                    self._emit_team_event(
                        "tool_call_start",
                        {"tool": tool_name, "round": self.round_count},
                    )

                    tool_start = time.time()
                    result = self._execute_tool_call(tool_call)
                    tool_duration_ms = (time.time() - tool_start) * 1000
                    self.heartbeat.emit(
                        "tool_call_end",
                        source="tool",
                        tool=tool_name,
                        duration_ms=round(tool_duration_ms, 2),
                    )
                    self.heartbeat.check_timeout(f"tool:{tool_name}", tool_duration_ms)
                    self._emit_team_event(
                        "tool_call_end",
                        {
                            "tool": tool_name,
                            "round": self.round_count,
                            "duration_ms": round(tool_duration_ms, 2),
                        },
                    )

                    # ========== 更新 todo 进度跟踪 ==========
                    if tool_name == "todo_write":
                        used_todo_this_round = True
                        # 使用了 todo 工具，重置计数器
                        self._rounds_since_todo = 0
                        self.logger.debug(f"使用了 todo_write，重置计数器")

                        # 检查 todo 完成状态
                        if self._check_todo_completion(result):
                            self._todo_all_completed = True
                            self.logger.debug("检测到所有 todo 任务已完成")
                    # 触发工具调用完成事件
                    self._emit_progress("tool_call_end", {
                        "tool": tool_name,
                        "success": not self.loop_guard.is_error_result(result),
                        "result_preview": self._summarize_tool_result(tool_name, result),
                        "duration_ms": round(tool_duration_ms, 2),
                    })

                    # 将工具执行结果添加到消息历史
                    # role="tool" 表示这是工具返回的结果
                    # tool_call_id 用于关联到对应的工具调用
                    self.messages.append(Message(
                        role="tool",
                        content=result,
                        tool_call_id=tool_call.id,
                        name=tool_call.function.name
                    ))

                    intervention = self.loop_guard.on_tool_result(tool_name, result)
                    if intervention:
                        self.logger.warning(f"工具 '{tool_name}' 连续失败，注入干预消息")
                        self.messages.append(Message(
                            role="system",
                            content=intervention
                        ))

                # 每轮最多增加 1 次 nag 计数，避免单轮多工具导致计数暴涨
                if not used_todo_this_round:
                    self._rounds_since_todo += 1
                
                # 工具结果已添加，继续循环，让 LLM 处理工具结果
            else:
                # 若存在未完成计划且回答为空/阶段性口吻，强制继续执行，避免“提前结束”
                intervention = self.loop_guard.on_llm_response(
                    response.content or "",
                    has_unfinished_plan=self._has_unfinished_plan(),
                    is_substantive=self._is_substantive_response(response.content or ""),
                    is_non_final_progress=self._is_non_final_progress_response(response.content or ""),
                )
                if intervention:
                    self.logger.warning("检测到计划未完成且响应内容不足，注入继续执行提示")
                    self.messages.append(Message(
                        role="system",
                        content=intervention,
                    ))
                    continue

                team_intervention = self._build_team_completion_intervention()
                if team_intervention:
                    self.logger.warning("TEAM_STRICT_MODE 阶段未完成，注入继续执行提示")
                    self.messages.append(Message(role="system", content=team_intervention))
                    continue

                # 没有工具调用，说明 LLM 已经给出最终答案
                self.logger.debug(f"任务完成，共 {self.round_count} 轮")
                self.heartbeat.emit("completed", source="run", total_rounds=self.round_count)
                self._emit_team_event("run_completed", {"total_rounds": self.round_count})
                if self.team:
                    self.team.complete_active_task()

                # 保存助手回答到持久化存储
                if self.session_storage:
                    self.session_storage.add_assistant_message(response.content or "")
                    self.session_storage.update_metadata(total_tokens=self.total_tokens)

                    # 自动生成会话摘要
                    try:
                        self.session_storage.generate_summary(self.llm, response.content or "")
                        self.logger.debug("会话摘要已生成")
                    except Exception as e:
                        self.logger.warning(f"摘要生成失败: {e}")

                # 记录会话结束
                if self.trace_logger:
                    self.trace_logger.log_event(
                        TraceEventType.SESSION_END,
                        {
                            "final_answer": response.content[:500],
                            "total_rounds": self.round_count,
                        },
                        step=self.round_count,
                    )

                self._finalize_run_capture(response.content or "", success=True)
                return response.content

        # 达到最大轮数仍未完成任务
        self.logger.warning(f"达到最大轮数 ({self.max_rounds})")
        if self.trace_logger:
            self.trace_logger.log_event(
                TraceEventType.WARNING,
                {"message": f"达到最大轮数 ({self.max_rounds})，任务未完成"},
                step=self.round_count,
            )
        self.heartbeat.emit("max_rounds", source="run", total_rounds=self.round_count)
        self._emit_team_event("run_max_rounds", {"total_rounds": self.round_count})
        self._finalize_run_capture(
            f"已达到最大轮数 ({self.max_rounds})，无法完成任务。",
            success=False,
        )
        return f"已达到最大轮数 ({self.max_rounds})，无法完成任务。"

    def _is_substantive_response(self, content: str) -> bool:
        """判断响应是否包含可交付内容（过滤空白和纯 <think> 片段）。"""
        text = (content or "").strip()
        if not text:
            return False
        # 去除 think 标签后再判断
        import re
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return bool(text)

    def _is_non_final_progress_response(self, content: str) -> bool:
        """判断是否是“还在进行中”的阶段性描述，防止未完成计划提前结束。"""
        import re

        text = (content or "").strip()
        if not text:
            return True
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        if not text:
            return True

        final_markers = ("已完成", "完成如下", "最终结果", "文件清单", "已生成", "总结")
        if any(marker in text for marker in final_markers):
            return False

        tool_protocol_markers = (
            "[append_file output]",
            "[write_file output]",
            "[write_file_chunks output]",
            "[append_file_chunks output]",
            "[tool ",
            "</tool_call>",
            "<tool_call",
            "<minimax:tool_call",
            "[tool_call]",
            "[/tool_call]",
            "<invoke",
            "[invoke",
        )
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in tool_protocol_markers):
            return True

        # 未完成计划时，短句式的“自我指令/下一步动作”通常不是最终交付。
        normalized = " ".join(text.split())
        if len(normalized) <= 120:
            short_progress_prefixes = (
                "让我",
                "让我先",
                "先让我",
                "我来",
                "我先",
                "先读取",
                "先搜索",
                "开始",
                "接下来我",
                "现在让我",
            )
            if normalized.startswith(short_progress_prefixes):
                return True

        if text.endswith((":", "：")):
            return True

        progress_markers = (
            "现在进行",
            "正在",
            "即将",
            "接下来",
            "稍后",
            "下一步",
            "将会",
            "我会",
            "我来",
            "我先",
            "让我",
            "立即",
            "再次执行",
            "继续执行",
            "继续搜索",
            "继续读取",
            "继续查找",
            "验证",
            # 英文关键词（LLM 偶尔混合语境回答时使用）
            "working on",
            "next step",
            "I will",
            "I'll",
            "about to",
            "proceeding",
            "in progress",
        )
        return any(marker in text for marker in progress_markers)

    def _inject_runtime_warnings(self, query: str) -> None:
        """按查询内容注入运行时前置告警，避免无效验收。"""
        text = (query or "").lower()
        if self.team_enabled:
            return
        team_keywords = ("events.jsonl", "inbox_ingested", "background_results", "team_status", "/team")
        if not any(k in text for k in team_keywords):
            return
        warning = (
            "当前 TEAM runtime 未启用（TEAM_AGENT_ENABLED=false）。"
            "team_status 将返回 enabled=false，且不会产生 .team/events.jsonl。"
            "如需验收 team 事件，请在启动前设置 TEAM_AGENT_ENABLED=true 后重试。"
        )
        if any(msg.role == "system" and warning in (msg.content or "") for msg in self.messages[-6:]):
            return
        self.messages.append(Message(role="system", content=warning))
        self._emit_progress("runtime_warning", {"message": warning})

    def _build_decision_summary(self, content: str, has_tool_calls: bool = False) -> str:
        """提取简短决策摘要，供 CLI 进度面板展示。"""
        import re

        text = (content or "").strip()
        if not text:
            return "准备调用工具" if has_tool_calls else ""

        think_match = re.search(r"<think>(.*?)</think>", text, flags=re.DOTALL | re.IGNORECASE)
        think_text = think_match.group(1).strip() if think_match else ""
        visible = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        candidate = visible or think_text
        if not candidate:
            return "准备调用工具" if has_tool_calls else ""

        compact = " ".join(candidate.split())
        if len(compact) > 120:
            compact = compact[:117] + "..."
        return compact

    def _summarize_tool_result(self, tool_name: str, result: str) -> str:
        """压缩工具输出为单行观察，避免 UI 过于嘈杂。"""
        text = str(result or "").strip()
        if not text:
            return "(no output)"

        if tool_name == "todo_write" and "--- TODO UPDATE ---" in text:
            return "TODO 已更新"

        if tool_name in {"task_create", "task_get", "task_update", "task_cleanup", "team_status"}:
            try:
                payload = json.loads(text)
                if tool_name in {"task_create", "task_get", "task_update"}:
                    tid = payload.get("id")
                    status = payload.get("status")
                    blocked = payload.get("blockedBy", [])
                    return f"task#{tid} status={status} blockedBy={blocked}"
                if tool_name == "task_cleanup":
                    deleted = payload.get("deleted_count", 0)
                    ns = payload.get("namespace", "")
                    return f"task_cleanup namespace={ns or 'ALL'} deleted={deleted}"
                if tool_name == "team_status":
                    enabled = payload.get("enabled")
                    inbox_pending = payload.get("inbox_pending", 0)
                    events_total = payload.get("events_total", 0)
                    return f"team_status enabled={enabled} inbox={inbox_pending} events={events_total}"
            except json.JSONDecodeError:
                pass

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "(no output)"
        first = lines[0]
        if len(first) > 120:
            return first[:117] + "..."
        return first

    def _has_unfinished_plan(self) -> bool:
        """判断当前计划是否仍有未完成任务。"""
        from codemate_agent.tools.todo.todo_write import TodoWriteTool

        todo_state = TodoWriteTool.get_current_state()
        if not todo_state:
            return bool(
                self.planning_enabled
                and self.planner
                and self.planner.current_plan is not None
                and not self._todo_all_completed
            )

        stats = todo_state.get("stats", {})
        pending = int(stats.get("pending", 0))
        in_progress = int(stats.get("in_progress", 0))
        if pending + in_progress > 0:
            return True

        total = int(stats.get("total", 0))
        completed = int(stats.get("completed", 0))
        cancelled = int(stats.get("cancelled", 0))
        if total > 0 and completed + cancelled >= total:
            return False
        return not self._todo_all_completed

    def _team_strict_status(self) -> dict[str, Any]:
        if not self.team:
            return {}
        status = self.team.get_status()
        if not status.get("strict_mode"):
            return {}
        progress = status.get("strict_progress", {})
        if not isinstance(progress, dict):
            return {}
        return progress

    def _build_team_completion_intervention(self) -> str:
        progress = self._team_strict_status()
        if not progress:
            return ""
        if int(progress.get("session_task_count", 0)) <= 0:
            return ""
        if progress.get("reviewer_done"):
            return ""
        missing: list[str] = []
        if not progress.get("researcher_done"):
            missing.append("researcher")
        if not progress.get("builder_done"):
            missing.append("builder")
        if not progress.get("reviewer_done"):
            missing.append("reviewer")
        needed = " -> ".join(missing) if missing else "reviewer"
        return (
            "TEAM_STRICT_MODE: 当前会话已进入团队流程，但阶段尚未完成。"
            f"缺失阶段: {needed}。请继续使用 task 工具按阶段委托，"
            "完成 reviewer 验收后再给最终答案。"
        )

    def _build_team_tool_intervention(self, tool_name: str) -> str:
        progress = self._team_strict_status()
        if not progress:
            return ""
        blocked_tools = {
            "write_file",
            "append_file",
            "write_file_chunks",
            "append_file_chunks",
            "edit_file",
            "delete_file",
            "run_shell",
            "background_run",
        }
        if tool_name not in blocked_tools:
            return ""
        return (
            "TEAM_STRICT_MODE: lead 不允许直接调用写入/shell 类工具。"
            "请使用 task 工具并显式指定 agent_id 委托成员执行："
            "researcher(调研) -> builder(实现) -> reviewer(验收)。"
        )

    def _is_transient_llm_error(self, error_text: str) -> bool:
        probe = (error_text or "").lower()
        transient_markers = (
            "server_error",
            "http_code': '500",
            '"http_code": "500',
            " 500 ",
            "(1000)",
            " 520 ",
            "connection",
            "timeout",
            "temporarily",
            "rate limit",
            " 429 ",
        )
        return any(marker in probe for marker in transient_markers)

    def _repair_tool_protocol_history(self, error_detail: str) -> None:
        """MiniMax 工具协议链损坏后，将历史工具轮次扁平化为纯文本再继续。"""
        repaired_messages: list[Message] = []
        for msg in self.messages:
            if msg.role == "tool":
                tool_name = msg.name or "tool"
                repaired_messages.append(
                    Message(role="assistant", content=f"[{tool_name} output]\n{msg.content or ''}")
                )
                continue

            if msg.role == "assistant" and msg.tool_calls:
                content = (msg.content or "").strip() or "[Tool call context omitted for compatibility]"
                repaired_messages.append(Message(role="assistant", content=content))
                continue

            repaired_messages.append(
                Message(role=msg.role, content=msg.content or "")
            )

        repaired_messages.append(
            Message(
                role="system",
                content=(
                    "检测到上一轮工具协议历史与 MiniMax 不兼容，已将旧工具轨迹压平成纯文本继续。"
                    "接下来只能使用真实工具调用；不要在回答中模拟 [tool output]、tool_call 或 invoke 标签。"
                    f" 原始错误: {error_detail}"
                ),
            )
        )

        self.messages = repaired_messages
        self.loop_guard.reset_premature()
        self.loop_detector.reset()
        self._emit_progress(
            "runtime_warning",
            {"message": "检测到工具协议链损坏，已重建历史后继续执行"},
        )

    def _execute_tool_call(self, tool_call: ToolCall) -> str:
        """
        执行单个工具调用

        Args:
            tool_call: 工具调用信息，包含工具名和参数

        Returns:
            str: 工具执行的结果（字符串形式）

        错误处理：
        - 如果工具不存在或执行失败，返回错误信息
        - 错误信息会被发送给 LLM，LLM 可能会尝试其他方法

        确认机制：
        - 危险工具（delete_file, write_file, run_shell）需要用户确认
        - 如果用户拒绝，返回取消信息
        """
        tool_name = tool_call.function.name      # 工具名称，如 "read_file"
        arguments = tool_call.function.arguments # 工具参数，如 {"file_path": "main.py"}
        tool_name, arguments, normalization_note = self._normalize_file_write_call(tool_name, arguments)

        # 参数验证：检测可疑的参数值（GLM API 有时会返回类型名称而非实际值）
        validation_error = self._validate_arguments(tool_name, arguments)
        if validation_error:
            self.logger.warning(f"参数验证失败: {validation_error}")

            # 增强错误消息，包含工具正确用法示例
            tool = self.tool_registry.get(tool_name)
            if tool:
                usage_hint = self._get_tool_usage_hint(tool_name, tool)
                return f"错误: {validation_error}\n\n{usage_hint}"
            return f"错误: {validation_error}。请提供正确的参数值。"

        team_tool_intervention = self._build_team_tool_intervention(tool_name)
        if team_tool_intervention:
            return f"错误: {team_tool_intervention}"

        if tool_name == "run_shell" and self.team:
            self.team.sync_shell_context()

        # 记录工具调用开始
        self.logger.debug(f"执行工具: {tool_name}")
        if self.trace_logger:
            self.trace_logger.log_event(
                TraceEventType.TOOL_CALL,
                {
                    "tool": tool_name,
                    "arguments": arguments,
                },
                step=self.round_count,
            )

        # 检查是否需要用户确认
        if tool_name in DANGEROUS_TOOLS and self.confirm_callback is not None:
            # 调用确认回调，询问用户是否同意执行
            approved = self.confirm_callback(tool_name, arguments)
            self._mark_run_manual_intervention()
            if not approved:
                # 用户取消操作
                result = f"用户取消了操作: {tool_name}"

                if self.trace_logger:
                    self.trace_logger.log_event(
                        TraceEventType.USER_CONFIRM,
                        {"tool": tool_name, "approved": False},
                        step=self.round_count,
                    )

                if self.metrics:
                    self.metrics.record_tool_call(tool_name, success=False)

                self._record_run_tool_event(tool_name, arguments, result, success=False)
                return result

            if self.trace_logger:
                self.trace_logger.log_event(
                    TraceEventType.USER_CONFIRM,
                    {"tool": tool_name, "approved": True},
                    step=self.round_count,
                )

        try:
            # 通过工具注册器执行工具
            # 注册器会根据工具名称找到对应的工具实例并执行
            result = self.tool_registry.execute(tool_name, **arguments)
            if normalization_note and not self.loop_guard.is_error_result(str(result)):
                result = f"{result}\n{normalization_note}"

            # 截断过长的工具输出
            if not self.truncator.should_skip_truncation(tool_name):
                original_length = len(str(result))
                result = self.truncator.truncate(str(result), tool_name)
                if len(result) < original_length:
                    self.logger.info(f"{tool_name} 输出已截断: {original_length} → {len(result)} 字符")

            # 记录工具执行成功
            if self.trace_logger:
                self.trace_logger.log_event(
                    TraceEventType.TOOL_RESULT,
                    {
                        "tool": tool_name,
                        "result": str(result)[:500],  # 限制长度
                        "success": True,
                    },
                    step=self.round_count,
                )

            # 检查工具返回的字符串是否表示失败（大多数工具通过 return 而非 raise 报错）
            result_str = str(result)
            is_error = self.loop_guard.is_error_result(result_str)

            if self.metrics:
                self.metrics.record_tool_call(tool_name, success=not is_error)
                if is_error:
                    self.metrics.record_error()
            self._emit_team_event("tool_result", {"tool": tool_name, "success": not is_error})
            self._record_run_tool_event(tool_name, arguments, result, success=not is_error)

            return result

        except Exception as e:
            # 工具执行失败，返回错误信息给 LLM
            # LLM 可以根据错误信息决定是否重试或使用其他方法
            error_msg = f"工具执行失败: {e}"
            
            # 记录错误
            self.logger.error(f"{tool_name} 执行失败: {e}")

            if self.trace_logger:
                self.trace_logger.log_event(
                    TraceEventType.TOOL_ERROR,
                    {
                        "tool": tool_name,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                    step=self.round_count,
                )

            if self.metrics:
                self.metrics.record_tool_call(tool_name, success=False)
                self.metrics.record_error()
            self._emit_team_event(
                "tool_result",
                {"tool": tool_name, "success": False, "error": str(e)},
            )
            self._record_run_tool_event(tool_name, arguments, error_msg, success=False)

            return error_msg

    def _normalize_file_write_call(self, tool_name: str, arguments: dict) -> tuple[str, dict, str]:
        """将超长 write/append 请求自动转换为 chunk 工具，减少模型反复失败。"""
        if tool_name not in {"write_file", "append_file"}:
            return tool_name, arguments, ""
        if not isinstance(arguments, dict):
            return tool_name, arguments, ""

        file_path = arguments.get("file_path")
        content = arguments.get("content")
        if not isinstance(file_path, str) or not file_path.strip():
            return tool_name, arguments, ""
        if not isinstance(content, str) or len(content) <= MAX_INLINE_FILE_CONTENT:
            return tool_name, arguments, ""

        chunk_tool = "write_file_chunks" if tool_name == "write_file" else "append_file_chunks"
        chunks = [
            content[i:i + MAX_INLINE_FILE_CONTENT]
            for i in range(0, len(content), MAX_INLINE_FILE_CONTENT)
        ]
        normalized_arguments = {"file_path": file_path, "chunks": chunks}
        note = (
            f"ℹ️ 已自动将超长 {tool_name} 请求转换为 {chunk_tool}"
            f"（{len(content)} 字符 / {len(chunks)} 块）。"
        )
        self.logger.info(
            "自动转换超长文件写入: %s -> %s (%s chars, %s chunks)",
            tool_name,
            chunk_tool,
            len(content),
            len(chunks),
        )
        return chunk_tool, normalized_arguments, note

    def _get_system_prompt(self, query: str = "") -> str:
        """
        获取完整的系统提示词

        系统提示词包括：
        1. 基础提示词（SYSTEM_PROMPT）：定义 Agent 的角色
        2. 长期记忆（如果有）：用户偏好、项目上下文等
        3. 可用 Skills（索引层）：轻量提示
        4. 工具列表：告诉 LLM 有哪些工具可用

        Returns:
            str: 完整的系统提示词
        """
        prompt_parts = [SYSTEM_PROMPT]  # 使用模块级常量

        prompt_parts.append(
            "\n## 当前运行时\n"
            f"- 当前工作目录: {self.workspace_dir}\n"
            "- 所有文件与命令都必须基于这个真实工作目录，不要臆测其他路径。"
        )
        if (
            os.getenv("TEAM_AGENT_ENABLED", "false").lower() == "true"
            and os.getenv("TEAM_STRICT_MODE", "false").lower() == "true"
        ):
            prompt_parts.append(
                "\n## TEAM_STRICT_MODE 约束\n"
                "- 你当前是 lead，禁止直接调用写入类工具：write_file/append_file/write_file_chunks/append_file_chunks/edit_file/delete_file。\n"
                "- 必须按顺序委托：researcher（调研）-> builder（实现）-> reviewer（验收）。\n"
                "- 委托时优先使用 agent_id（示例：task(agent_id='researcher', description='...', prompt='...')）。\n"
                "- 如需产出文件，先用 task 工具委托 builder 执行写入，再由 reviewer 验收后才能给最终答案。"
            )

        # 添加 RepoRAG 项目上下文；若未启用则回退到原有长期记忆
        if self.repo_rag is not None and self._should_use_repo_rag(query):
            repo_context = self.repo_rag.retrieve(query)
            prompt_text = repo_context.to_prompt_text()
            if prompt_text:
                self._emit_progress(
                    "repo_rag_retrieved",
                    {
                        "query": query,
                        "mode": repo_context.plan.mode if repo_context.plan is not None else "",
                        "chunks": len(repo_context.chunks),
                        "sources": repo_context.paths,
                        "source_count": repo_context.source_count,
                        "total_chars": repo_context.total_chars,
                    },
                )
                prompt_parts.append(f"\n{prompt_text}")
                self.logger.debug(
                    "[repo_rag] mode=%s query=%r chunks=%s chars=%s sources=%s",
                    repo_context.plan.mode if repo_context.plan is not None else "unknown",
                    query[:80],
                    len(repo_context.chunks),
                    repo_context.total_chars,
                    [chunk.path or chunk.source for chunk in repo_context.chunks],
                )
        elif self.memory_manager:
            memory = self.memory_manager.retrieve_relevant_memory(query, top_k=3)
            if memory.strip() and not memory.startswith("# 长期记忆\n\n暂无"):
                prompt_parts.append(f"\n## 长期记忆\n{memory}")

            codemate_context = self.memory_manager.load_codemate_file(self.workspace_dir)
            if codemate_context.strip():
                prompt_parts.append(f"\n## 项目记忆（codemate.md）\n{codemate_context[:5000]}")

        # 添加可用 Skills（只是索引，很轻量）
        skills_hint = self.skill_manager.get_system_prompt_addition()
        if skills_hint:
            prompt_parts.append(skills_hint)

        # 获取所有工具的描述信息
        tools_desc = self.tool_registry.get_tools_description()
        prompt_parts.append(f"\n## 可用工具\n{tools_desc}")

        return "\n".join(prompt_parts)

    def inspect_repo_rag(self, query: str, top_k: int | None = None):
        """手动查看 RepoRAG 的检索结果。"""
        if self.repo_rag is None:
            return None
        return self.repo_rag.retrieve(query, top_k=top_k)

    def _should_use_repo_rag(self, query: str) -> bool:
        """对明显的寒暄/空泛输入跳过 RepoRAG，减少噪音与无效检索。"""
        text = " ".join((query or "").strip().lower().split())
        if not text:
            return False

        greeting_phrases = {
            "hi",
            "hello",
            "hey",
            "你好",
            "您好",
            "嗨",
            "在吗",
            "早上好",
            "下午好",
            "晚上好",
        }
        if text in greeting_phrases:
            return False

        short_phatic_prefixes = (
            "hello ",
            "hi ",
            "hey ",
            "你好 ",
            "您好 ",
        )
        if any(text.startswith(prefix) for prefix in short_phatic_prefixes) and len(text) <= 20:
            return False

        return True

    def _detect_skill_declaration(self, content: str) -> Optional[str]:
        """
        检测 LLM 响应中是否声明使用了 Skill
        
        格式: [使用 Skill: skill-name] 或 [Using Skill: skill-name]
        
        Args:
            content: LLM 响应内容
            
        Returns:
            skill 名称，或 None
        """
        import re
        
        # 匹配中英文声明格式
        patterns = [
            r'\[使用\s*Skill[:\s]*([a-zA-Z0-9_-]+)\]',
            r'\[Using\s*Skill[:\s]*([a-zA-Z0-9_-]+)\]',
            r'\[Skill[:\s]*([a-zA-Z0-9_-]+)\]',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                skill_name = match.group(1).strip()
                if self.skill_manager.skill_exists(skill_name):
                    return skill_name
        
        return None

    def _inject_skill_as_tool_result(self, skill_name: str, skill_content: str, arguments: str = "") -> None:
        """
        将 skill 内容以合成 tool result 形式注入 messages。

        这样 skill body 落在 role=tool 消息里，而非 user message。
        MiniMax 对 2 轮以外的 tool 消息自动降级为普通文本，可被 micro_compact 压缩。
        """
        call_id = f"call_skill_{uuid.uuid4().hex[:8]}"
        synthetic_call = ToolCall(
            id=call_id,
            type="function",
            function=FunctionCall(
                name="skill",
                arguments={"action": "load", "skill_name": skill_name, "arguments": arguments},
            ),
        )
        self.messages.append(Message(role="assistant", content="", tool_calls=[synthetic_call]))
        self.messages.append(Message(role="tool", content=skill_content, tool_call_id=call_id, name="skill"))

    def _load_skill_content(self, skill_name: str, arguments: str, mode: str) -> Optional[str]:
        """
        加载 skill 内容，并通过进度事件显式记录为一次 skill 工具调用。

        优先走真实 skill 工具（可审计），若工具不可用再回退到 SkillManager 直读。
        """
        tool_args = {"action": "load", "skill_name": skill_name}
        self._emit_progress(
            "tool_call_start",
            {
                "tool": "skill",
                "args": f"action=load, skill_name={skill_name}",
                "arguments": tool_args,
            },
        )
        self.heartbeat.emit("tool_call_start", source="tool", tool="skill")
        self._emit_team_event("tool_call_start", {"tool": "skill", "mode": mode})
        tool_start = time.time()

        result = ""
        success = False
        skill_tool = self.tool_registry.get("skill")
        if skill_tool is not None:
            tool_call = ToolCall(
                id=f"call_skill_load_{uuid.uuid4().hex[:8]}",
                type="function",
                function=FunctionCall(name="skill", arguments=tool_args),
            )
            result = str(self._execute_tool_call(tool_call))
            success = not self.loop_guard.is_error_result(result)

        if not success:
            fallback = self.skill_manager.prepare_execution(skill_name, arguments)
            if fallback:
                result = fallback
                success = True

        duration_ms = (time.time() - tool_start) * 1000
        self.heartbeat.emit(
            "tool_call_end",
            source="tool",
            tool="skill",
            duration_ms=round(duration_ms, 2),
        )
        self._emit_team_event(
            "tool_call_end",
            {"tool": "skill", "mode": mode, "duration_ms": round(duration_ms, 2), "success": success},
        )
        self._emit_progress(
            "tool_call_end",
            {
                "tool": "skill",
                "success": success,
                "result_preview": self._summarize_tool_result("skill", result),
                "duration_ms": round(duration_ms, 2),
            },
        )
        return result if success else None

    def _handle_skill_command(self, query: str) -> Optional[str]:
        """
        处理 skill 命令
        
        Args:
            query: 用户输入，以 / 开头
            
        Returns:
            原始目标 query（skill 内容已注入为合成 tool result），或 None（不是 skill 命令）
        """
        # 解析命令: /skill-name args
        parts = query[1:].split(maxsplit=1)
        if not parts:
            return None
        
        skill_name = parts[0]
        arguments = parts[1] if len(parts) > 1 else ""
        
        # 检查是否是有效的 skill
        if not self.skill_manager.skill_exists(skill_name):
            return None  # 不是 skill 命令，继续正常处理
        
        # 加载完整 skill 内容
        skill_prompt = self._load_skill_content(skill_name, arguments, mode="manual")
        if not skill_prompt:
            return None

        self.logger.info(f"执行 Skill: {skill_name}, 参数: {arguments}")

        # 记录 skill 执行事件
        if self.trace_logger:
            self.trace_logger.log_event(
                TraceEventType.INFO,
                {"event": "skill_execution", "skill": skill_name, "arguments": arguments, "mode": "manual"},
            )

        # 将 skill 内容注入为合成 tool result，返回原始目标
        self._inject_skill_as_tool_result(skill_name, skill_prompt, arguments)
        return arguments if arguments else f"按照 {skill_name} skill 的步骤执行"

    def _should_skip_auto_skill(self, query: str) -> bool:
        text = (query or "").lower()
        skip_markers = ("[no-skill]", "不使用skill", "不要用skill", "disable skill auto")
        return any(marker in text for marker in skip_markers)

    def _try_auto_trigger_skill(self, query: str) -> Optional[tuple[str, str]]:
        """根据关键词尝试自动触发 skill。"""
        if not self.skill_auto_trigger_enabled:
            return None
        if self._should_skip_auto_skill(query):
            return None

        skill_name = self.skill_manager.match_skill_by_keywords(query)
        if not skill_name or not self.skill_manager.skill_exists(skill_name):
            return None

        skill_prompt = self._load_skill_content(skill_name, query, mode="auto")
        if not skill_prompt:
            return None

        self.logger.info(f"自动触发 Skill: {skill_name}")
        if self.trace_logger:
            self.trace_logger.log_event(
                TraceEventType.INFO,
                {"event": "skill_execution", "skill": skill_name, "arguments": query, "mode": "auto"},
            )
        self._inject_skill_as_tool_result(skill_name, skill_prompt, query)
        return skill_name, query

    def _ingest_background_notifications(self) -> None:
        """Direct background notification ingestion when TeamRuntime is not available."""
        from codemate_agent.tools.shell.background_tasks import drain_background_notifications
        try:
            notifications = drain_background_notifications(self.workspace_dir, limit=20)
        except Exception as e:
            self.logger.debug(f"读取后台任务通知失败: {e}")
            return
        if notifications:
            payload = json.dumps(notifications, ensure_ascii=False)
            self.messages.append(
                Message(role="system", content=f"<background_results>{payload}</background_results>")
            )

    def _start_run_capture(self, goal: str, task_type: Optional[str]) -> None:
        """初始化当前运行的 skill 沉淀状态。"""
        self._current_run_capture = {
            "task_type": task_type,
            "goal": goal,
            "inputs": {"target_request": goal} if goal else {},
            "steps": [],
            "tool_calls": [],
            "artifacts": set(),
            "manual_intervention": False,
        }

    def _mark_run_manual_intervention(self) -> None:
        if self._current_run_capture is not None:
            self._current_run_capture["manual_intervention"] = True

    def _record_run_tool_event(self, tool_name: str, arguments: dict[str, Any], result: str, *, success: bool) -> None:
        if self._current_run_capture is None:
            return
        event = {
            "tool": tool_name,
            "arguments": self._sanitize_capture_arguments(arguments),
            "success": success,
        }
        self._current_run_capture["tool_calls"].append(event)
        self._current_run_capture["steps"].append({"tool": tool_name, "success": success})
        self._current_run_capture["artifacts"].update(
            self._extract_artifacts_from_tool(tool_name, arguments)
        )

    def _sanitize_capture_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        safe_args = {}
        for key, value in (arguments or {}).items():
            if key.lower() in {"content", "patch", "text"}:
                safe_args[key] = "<omitted>"
            else:
                safe_args[key] = value
        return safe_args

    def _extract_artifacts_from_tool(self, tool_name: str, arguments: dict[str, Any]) -> set[str]:
        artifact_paths: set[str] = set()
        if not tool_name.startswith(("write_", "append_", "edit_", "delete_")):
            return artifact_paths
        for key in ("file_path", "path", "target_path"):
            value = arguments.get(key)
            if not isinstance(value, str) or not value:
                continue
            path = Path(value)
            resolved = path if path.is_absolute() else self.workspace_dir / path
            try:
                normalized = resolved.resolve()
            except OSError:
                continue
            if normalized.exists() and normalized.is_file():
                try:
                    artifact_paths.add(str(normalized.relative_to(self.workspace_dir)))
                except ValueError:
                    artifact_paths.add(str(normalized))
        return artifact_paths

    def _finalize_run_capture(self, final_answer: str, *, success: bool) -> None:
        if self._current_run_capture is None:
            return
        capture = self._current_run_capture
        self._current_run_capture = None
        task_type = capture.get("task_type")
        if not task_type:
            return
        self.skill_capture_manager.capture_successful_run(
            run_id=f"{self.session_id}-{int(time.time() * 1000)}",
            task_type=task_type,
            goal=capture.get("goal", ""),
            inputs=capture.get("inputs", {}),
            steps=list(capture.get("steps", [])),
            tool_calls=list(capture.get("tool_calls", [])),
            artifacts=sorted(capture.get("artifacts", set())),
            outputs={"final_answer": final_answer[:1000]},
            success=success,
            manual_intervention=bool(capture.get("manual_intervention")),
        )

    def reset(self):
        """
        重置 Agent 状态

        用于开始新的对话，清空消息历史和统计信息。
        但保留工具配置。
        """
        self.messages = [Message(role="system", content=self._get_system_prompt())]
        self.round_count = 0
        self.total_tokens = 0
        self._last_usage_tokens = 0
        self._last_reported_total_tokens = 0
        self.loop_detector.reset()  # 重置循环检测器
        self.loop_guard.reset()
        self._skill_injected = False  # 重置 skill 注入标记
        self._current_run_capture = None
        if self.planner:
            self.planner.reset()
        # 清理 skill 缓存
        self.skill_manager.clear_cache()
        if self.team:
            self.team.reset()
            self.team.ensure_identity_block(force=True)

    def get_stats(self) -> dict:
        """
        获取 Agent 统计信息

        用于监控和调试，了解 Agent 的运行情况。

        Returns:
            dict: 包含 round_count, total_tokens, message_count
        """
        return {
            "round_count": self.round_count,          # 对话轮数
            "total_tokens": self.total_tokens,        # 累计 token 消耗
            "message_count": len(self.messages),      # 消息总数
        }

    def get_heartbeat_status(self) -> dict:
        """获取心跳状态"""
        return self.heartbeat.get_status()

    def load_session(self, messages: list[dict]) -> None:
        """
        加载历史会话消息

        从持久化存储加载历史消息，恢复对话上下文。

        Args:
            messages: 历史消息列表（字典格式）

        注意：
            - 会清空当前消息历史
            - 第一条消息始终是 system 提示词
            - 历史消息会追加到 system 消息之后
        """
        # 重置为初始状态（只有 system 消息）
        self.messages = [Message(role="system", content=self._get_system_prompt())]
        self._current_run_capture = None

        # 加载历史消息
        for msg_dict in messages:
            role = msg_dict.get("role")
            content = msg_dict.get("content", "")

            if role == "tool":
                # 工具消息需要特殊处理
                self.messages.append(Message(
                    role="tool",
                    content=content,
                    tool_call_id=msg_dict.get("tool_call_id", ""),
                    name=msg_dict.get("name", ""),
                ))
            elif role in ("user", "assistant", "system"):
                # 普通消息
                self.messages.append(Message(role=role, content=content))

        self.logger.info(f"已加载 {len(self.messages) - 1} 条历史消息")

    def _emit_progress(self, event: str, data: dict) -> None:
        """
        触发进度回调

        Args:
            event: 事件类型 (round_start, tool_call_start, tool_call_end, etc.)
            data: 事件数据
        """
        if self.progress_callback:
            try:
                self.progress_callback(event, data)
            except Exception as e:
                # 回调异常不应影响主流程
                self.logger.debug(f"进度回调异常: {e}")

    def _emit_team_event(self, event: str, payload: Optional[dict[str, Any]] = None) -> None:
        """写入结构化团队事件日志。"""
        if not self.team:
            return
        self.team.emit_event(event, payload or {})

    def send_team_message(
        self,
        to: str,
        content: str,
        *,
        msg_type: str = "message",
        request_id: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        if not self.team:
            return None
        return self.team.send_message(
            to=to,
            content=content,
            msg_type=msg_type,
            request_id=request_id,
            extra=extra,
        )

    def get_team_status(self) -> dict[str, Any]:
        if not self.team:
            return {"enabled": False}
        return self.team.get_status()

    @property
    def message_bus(self):
        """Proxy to TeamRuntime.message_bus for backwards compatibility."""
        return self.team.message_bus if self.team else None

    def peek_team_inbox(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.team:
            return []
        return self.team.peek_inbox(limit=limit)

    def list_task_board(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.team:
            return []
        return self.team.list_task_board(limit=limit)

    def _format_args_for_display(self, arguments: dict) -> str:
        """
        格式化工具参数用于显示

        Args:
            arguments: 工具参数字典

        Returns:
            格式化后的参数字符串
        """
        if not arguments:
            return ""

        # 根据参数类型优化显示
        if "file_path" in arguments:
            file_path = arguments.get("file_path", "")
            return f"file={file_path}"
        elif "command" in arguments:
            cmd = arguments.get("command", "")
            return f"cmd={cmd[:50]}..." if len(cmd) > 50 else f"cmd={cmd}"
        elif "prompt" in arguments:
            # task 工具的特殊处理
            return f"description={arguments.get('description', '')[:30]}"
        elif "pattern" in arguments:
            # search_files 工具
            return f"pattern={arguments.get('pattern', '')}"
        elif "path" in arguments:
            return f"path={arguments.get('path', '')}"

        # 通用格式化
        parts = []
        for k, v in list(arguments.items())[:3]:  # 最多显示 3 个参数
            v_str = str(v)
            if len(v_str) > 30:
                v_str = v_str[:27] + "..."
            parts.append(f"{k}={v_str}")
        return ", ".join(parts)

    def _get_tool_call_signature(self, tool_name: str, arguments: dict) -> str:
        """
        生成工具调用的唯一签名

        用于检测重复的调用模式。

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            调用签名字符串
        """
        # 提取关键参数
        key_parts = [tool_name]

        # 如果 arguments 不是 dict，返回简单签名
        if not isinstance(arguments, dict):
            self.logger.warning(f"arguments 不是 dict: {type(arguments).__name__}")
            return f"{tool_name}|invalid_args"

        try:
            # 对于文件操作，文件路径是关键
            if "file_path" in arguments:
                value = arguments["file_path"]
                # 处理各种可能的类型
                if isinstance(value, list):
                    value_str = f"[list:{len(value)}]"
                elif isinstance(value, dict):
                    value_str = "[dict]"
                else:
                    value_str = str(value)[:100]
                key_parts.append(value_str)
            elif "path" in arguments:
                value = arguments["path"]
                if isinstance(value, list):
                    value_str = f"[list:{len(value)}]"
                elif isinstance(value, dict):
                    value_str = "[dict]"
                else:
                    value_str = str(value)[:100]
                key_parts.append(value_str)
            elif "command" in arguments:
                # 对于 shell 命令，取前 50 个字符
                cmd = arguments["command"]
                if isinstance(cmd, str):
                    key_parts.append(cmd[:50] if len(cmd) > 50 else cmd)
                else:
                    key_parts.append(str(cmd)[:50])
            elif "todos" in arguments:
                # todo_write 工具的特殊处理
                todos = arguments["todos"]
                if isinstance(todos, list):
                    key_parts.append(f"todos:{len(todos)}")
                else:
                    key_parts.append(f"todos:invalid")
            else:
                # 使用参数的哈希值 - 先转换为字符串避免比较问题
                try:
                    items_str = str(list(arguments.keys()))
                    key_parts.append(items_str[:50])
                except Exception:
                    key_parts.append("unknown")

            return "|".join(key_parts)
        except Exception as e:
            # 如果签名生成失败，返回一个简单的签名
            self.logger.warning(f"签名生成失败 '{tool_name}': {e}")
            return f"{tool_name}|error"

    def _is_stuck_in_loop(self) -> bool:
        """
        检测 Agent 是否陷入循环
        
        委托给 LoopDetector 进行检测。

        Returns:
            是否陷入循环
        """
        return self.loop_detector.is_stuck()

    def _validate_arguments(self, tool_name: str, arguments: dict) -> Optional[str]:
        """
        验证工具参数
        
        使用统一的 ArgumentValidator 模块进行验证。

        Args:
            tool_name: 工具名称
            arguments: 参数字典

        Returns:
            错误信息，如果验证通过则返回 None
        """
        return ArgumentValidator.validate(tool_name, arguments)

    def _get_tool_usage_hint(self, tool_name: str, tool) -> str:
        """
        获取工具使用提示

        当参数验证失败时，提供清晰的使用示例帮助 LLM 纠正调用。

        Args:
            tool_name: 工具名称
            tool: 工具实例

        Returns:
            使用提示字符串
        """
        hints = {
            "write_file": "write_file 使用方法:\n"
                          "- file_path: 完整文件路径，如 'src/main.py' 或 'codemate_agent/agent/agent.py'\n"
                          "- content: 要写入的实际文件内容（字符串格式）\n"
                          "示例: write_file(file_path='myfile.py', content='print(\"hello\")')",
            "read_file": "read_file 使用方法:\n"
                         "- file_path: 完整文件路径\n"
                         "示例: read_file(file_path='src/main.py')",
            "search_code": "search_code 使用方法:\n"
                           "- pattern: 搜索模式（字符串）\n"
                           "示例: search_code(pattern='def hello')",
            "write_file_chunks": "write_file_chunks 使用方法:\n"
                                "- file_path: 目标文件路径\n"
                                "- chunks: 字符串数组（每块建议 <= 3000 字符）\n"
                                "示例: write_file_chunks(file_path='site/index.html', chunks=['<html>...', '...'])",
            "append_file_chunks": "append_file_chunks 使用方法:\n"
                                 "- file_path: 目标文件路径\n"
                                 "- chunks: 字符串数组（每块建议 <= 3000 字符）\n"
                                 "示例: append_file_chunks(file_path='site/index.html', chunks=['后续内容'])",
            "task_create": "task_create 使用方法:\n"
                           "- subject: 任务标题（必填）\n"
                           "- description: 任务描述（可选）\n"
                           "- blocked_by / blocks: 依赖关系（可选）\n"
                           "- namespace: 命名空间（可选，如 ITEST）\n"
                           "示例: task_create(subject='重构认证模块', description='拆分 service 层', namespace='ITEST')",
            "task_get": "task_get 使用方法:\n"
                        "- task_id: 任务 ID（整数）\n"
                        "示例: task_get(task_id=1)",
            "task_update": "task_update 使用方法:\n"
                           "- task_id: 任务 ID（整数，必填）\n"
                           "- status: pending|in_progress|completed|cancelled（可选）\n"
                           "- owner: 负责人（可选）\n"
                           "- add_blocked_by / add_blocks: 依赖关系（可选）\n"
                           "示例: task_update(task_id=1, status='completed')",
            "task_cleanup": "task_cleanup 使用方法:\n"
                            "- namespace: 命名空间前缀删除（可选）\n"
                            "- all_tasks: 是否清空全部任务（可选，默认 false）\n"
                            "示例: task_cleanup(namespace='ITEST') 或 task_cleanup(all_tasks=true)",
            "team_status": "team_status 使用方法:\n"
                           "- event_limit: 最近事件条数（可选，默认 10）\n"
                           "示例: team_status(event_limit=20)",
            "background_run": "background_run 使用方法:\n"
                              "- command: 后台执行的命令（必填）\n"
                              "- timeout: 超时秒数（可选，默认 120）\n"
                              "- allow_parallel: 是否允许与当前后台任务并行（可选，默认 false）\n"
                              "示例: background_run(command='pytest -q', timeout=180, allow_parallel=false)",
            "check_background": "check_background 使用方法:\n"
                                "- task_id: 可选，指定任务 ID 查看详情\n"
                                "示例: check_background(task_id='abcd1234') 或 check_background()",
            "memory_write": "memory_write 使用方法:\n"
                            "- content: 要记住的内容（字符串，最多 500 字，必填）\n"
                            "- category: 分类，必须是 'preference' / 'project' / 'finding' 之一（必填）\n"
                            "示例: memory_write(content='用户偏好用 dataclass', category='preference')",
            "memory_read": "memory_read 使用方法:\n"
                           "- query: 检索关键词（字符串，必填）\n"
                           "- top_k: 返回结果数（可选，默认 3，最大 5）\n"
                           "示例: memory_read(query='测试框架', top_k=3)",
        }

        if tool_name in hints:
            return hints[tool_name]

        # 通用提示
        params = tool.parameters.get("properties", {})
        required = tool.parameters.get("required", [])

        hint_parts = [f"{tool_name} 参数:"]
        for param_name in required:
            param_info = params.get(param_name, {})
            param_desc = param_info.get("description", "无描述")
            hint_parts.append(f"- {param_name}: {param_desc}")

        return "\n".join(hint_parts)

    def _check_todo_completion(self, tool_result: str) -> bool:
        """
        检查 todo_write 结果是否全部完成

        Args:
            tool_result: todo_write 工具返回的字符串

        Returns:
            是否全部完成
        """
        import re

        # 解析格式: "--- [3/3] 完成 ---"
        match = re.search(r'\[(\d+)/(\d+)\]\s*完成', tool_result)
        if match:
            completed = int(match.group(1))
            total = int(match.group(2))
            return completed == total and total > 0

        # 检查是否所有任务都有 [✓] 图标
        lines = tool_result.split('\n')
        todo_lines = [
            l for l in lines
            if l.strip().startswith('[✓]') or
               l.strip().startswith('[▶]') or
               l.strip().startswith('[ ]')
        ]
        if todo_lines and all('[✓]' in line for line in todo_lines):
            return len(todo_lines) > 0

        return False


# 保留旧的 ReActAgent 类名作为别名
# 这样可以兼容旧代码，同时使用新的 Function Calling Agent
ReActAgent = CodeMateAgent
