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

import json
import os
import uuid
import time
from typing import List, Optional, Callable
from pathlib import Path

from codemate_agent.llm.client import LLMClient as GLMClient
from codemate_agent.schema import Message, LLMResponse, ToolCall
from codemate_agent.tools.base import Tool
from codemate_agent.tools.registry import ToolRegistry
from codemate_agent.logging import setup_logger, TraceLogger, SessionMetrics, generate_session_id, TraceEventType
from codemate_agent.persistence import SessionStorage, MemoryManager
from codemate_agent.context import ContextCompressor, CompressionConfig, ObservationTruncator
from codemate_agent.planner import TaskPlanner
from codemate_agent.subagent import TaskTool
from codemate_agent.validation import ArgumentValidator
from codemate_agent.skill import SkillManager
from codemate_agent.prompts import SYSTEM_PROMPT
from codemate_agent.agent.loop_detector import LoopDetector


# 需要用户确认的危险工具
DANGEROUS_TOOLS = {
    "delete_file",
    "write_file",
    "run_shell",
}


class CodeMateAgent:
    """
    CodeMate Agent

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
        """
        self.llm = llm_client                    # LLM 客户端
        self.light_llm = light_llm_client        # 轻量模型客户端
        self.max_rounds = max_rounds              # 最大轮数限制
        self.workspace_dir = Path(workspace_dir) # 当前工作目录
        self.confirm_callback = confirm_callback  # 用户确认回调
        self.plan_display_callback = plan_display_callback  # 计划显示回调
        self.progress_callback = progress_callback  # 进度回调

        # 日志系统
        self.logger = setup_logger("codemate.agent")
        self.trace_logger = trace_logger
        self.metrics = metrics

        # 持久化系统
        self.session_storage = session_storage
        self.memory_manager = memory_manager

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
        self._loop_count = 0  # 循环检测计数器
        
        # 连续失败跟踪（现在由 ToolExecutor 管理，这里只保留引用）
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3

        # todo 进度跟踪 + nag reminder
        self._todo_all_completed = False  # 所有 todo 是否完成
        self._last_completed_count = 0  # 最近一次完成的任务数
        self._rounds_since_todo = 0  # 距离上次更新 todo 的轮数
        self._max_rounds_without_todo = 3  # 超过此轮数未更新 todo 则 nag

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

        # Skill 管理器（渐进式加载）
        self.skill_manager = SkillManager()

        # Task 工具：用于委托子代理
        # 需要注入依赖（llm_client, tool_registry, 以及可选的 light_llm_client）
        self.task_tool = TaskTool(working_dir=str(self.workspace_dir))
        self.task_tool.set_dependencies(
            main_llm_client=llm_client,
            tool_registry=self.tool_registry,
            light_llm_client=light_llm_client,
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

        # 统计信息
        self.round_count = 0      # 当前对话轮数
        self.total_tokens = 0     # 累计消耗的 token 数

        # 心跳监控
        self.heartbeat_enabled = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
        self.heartbeat_timeout_seconds = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "45"))
        session_id = getattr(self.trace_logger, "session_id", f"local-{uuid.uuid4().hex[:8]}")
        heartbeat_dir = Path(os.getenv("HEARTBEAT_DIR", "logs/sessions"))
        heartbeat_dir.mkdir(parents=True, exist_ok=True)
        self._heartbeat_file = heartbeat_dir / f"heartbeat-{session_id}.jsonl"
        self._heartbeat_state = {
            "session_id": session_id,
            "phase": "idle",
            "last_beat_ts": time.time(),
            "last_tool": "",
            "beats": 0,
            "stalled": False,
            "last_alert": "",
        }
        self._emit_heartbeat("idle", source="init")

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
        # 步骤 -1: 检查是否是 skill 命令
        if query.startswith("/"):
            skill_result = self._handle_skill_command(query)
            if skill_result is not None:
                # skill 命令已处理，将 skill prompt 注入后继续执行
                query = skill_result

        # 每轮根据当前 query 刷新 system prompt（包含关键词召回记忆 + codemate.md）
        if self.messages and self.messages[0].role == "system":
            self.messages[0] = Message(role="system", content=self._get_system_prompt(query))

        # 注意: 渐进式 Skill 加载
        # 不再自动注入完整 Skill 内容，而是让 LLM 通过 skill 工具按需加载
        # 系统提示词中只包含 Skill 索引（name + description）

        # 记录用户输入
        self.logger.info(f"用户输入: {query[:100]}...")
        self._emit_heartbeat("run_started", source="run", query_len=len(query))
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

        # 获取所有工具的 OpenAI Schema 格式
        # LLM 需要知道有哪些工具可用，以及每个工具的参数格式
        tools = [t.to_openai_schema() for t in self.tool_registry.get_all().values()]

        # 步骤 2-4: 主循环
        while self.round_count < self.max_rounds:
            self.round_count += 1
            if self.metrics:
                self.metrics.record_round()

            # ========== Layer 1: Micro Compact (每轮执行) ==========
            if self.compression_enabled and self.compressor:
                self.messages = self.compressor.micro_compact(self.messages)
                # 更新 CompactTool 的 messages 引用
                from codemate_agent.tools.compact import CompactTool
                CompactTool._messages_ref = self.messages

            # 触发轮次开始事件
            self._emit_progress("round_start", {
                "round": self.round_count,
                "max_rounds": self.max_rounds,
            })
            self._emit_heartbeat("round_start", source="loop", round=self.round_count)

            # ========== Todo Nag Reminder ==========
            # 如果多轮未更新 todo，注入提醒
            if self._rounds_since_todo >= self._max_rounds_without_todo:
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
            self._emit_heartbeat("llm_request", source="llm", round=self.round_count)

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

            response: LLMResponse = self.llm.complete(
                messages=self.messages,
                tools=tools,
            )

            duration_ms = (time.time() - start_time) * 1000
            self._emit_heartbeat("llm_response", source="llm", duration_ms=round(duration_ms, 2))
            self._check_heartbeat_timeout("llm", duration_ms)

            # 更新 token 统计（用于成本控制）
            if response.usage:
                reported_total = response.usage.total_tokens

                # 检查 token 数是否合理（单次请求通常不应超过 15000）
                # GLM API 有时返回累计值而非单次值
                SINGLE_REQUEST_TOKEN_LIMIT = 15000
                if reported_total > SINGLE_REQUEST_TOKEN_LIMIT:
                    # 检测到累计值，计算差值
                    if self._last_reported_total_tokens > 0:
                        actual_tokens = reported_total - self._last_reported_total_tokens
                        self._last_usage_tokens = actual_tokens
                        self.total_tokens += actual_tokens
                        self.logger.debug(
                            f"检测到累计 token，计算差值: {reported_total} - {self._last_reported_total_tokens} = {actual_tokens}"
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

            # 注意: 渐进式 Skill 加载
            # 不再检测 LLM 声明，而是让 LLM 主动调用 skill 工具加载内容

            # 步骤 3: 检查 LLM 是否请求调用工具
            if response.tool_calls:
                self.logger.debug(f"LLM 请求调用 {len(response.tool_calls)} 个工具")

                # 检测循环：记录本次工具调用
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = tool_call.function.arguments
                    # 记录工具调用到循环检测器
                    self.loop_detector.record_call(tool_name, arguments)

                # 检测是否陷入循环
                try:
                    if self._is_stuck_in_loop():
                        loop_count = getattr(self, '_loop_count', 0) + 1
                        self._loop_count = loop_count

                        loop_warning = (
                            f"检测到 Agent 陷入循环（第 {loop_count} 次）。"
                        )

                        if loop_count >= 3:
                            # 强制打破循环
                            loop_warning += " 采取强制措施打破循环。"
                            self.logger.warning(loop_warning)

                            # 清空循环检测器
                            self.loop_detector.reset()
                            self._loop_count = 0

                            # 添加强制干预消息
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
                            # 添加警告消息
                            self.messages.append(Message(
                                role="system",
                                content=f"警告：检测到重复的工具调用模式（第 {loop_count} 次）。请重新评估当前状态，尝试不同的方法。"
                            ))
                except Exception as e:
                    self.logger.error(f"循环检测出错: {e}")
                    # 清空历史以防止持续出错
                    self.loop_detector.reset()

                # LLM 请求调用工具，执行所有工具调用
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = tool_call.function.arguments

                    # 触发工具调用开始事件
                    self._emit_progress("tool_call_start", {
                        "tool": tool_name,
                        "args": self._format_args_for_display(arguments),
                    })
                    self._emit_heartbeat("tool_call_start", source="tool", tool=tool_name)

                    tool_start = time.time()
                    result = self._execute_tool_call(tool_call)
                    tool_duration_ms = (time.time() - tool_start) * 1000
                    self._emit_heartbeat(
                        "tool_call_end",
                        source="tool",
                        tool=tool_name,
                        duration_ms=round(tool_duration_ms, 2),
                    )
                    self._check_heartbeat_timeout(f"tool:{tool_name}", tool_duration_ms)

                    # ========== 更新 todo 进度跟踪 ==========
                    if tool_name == "todo_write":
                        # 使用了 todo 工具，重置计数器
                        self._rounds_since_todo = 0
                        self.logger.debug(f"使用了 todo_write，重置计数器")

                        # 检查 todo 完成状态
                        if self._check_todo_completion(result):
                            self._todo_all_completed = True
                            self.logger.info("检测到所有 todo 任务已完成")
                    else:
                        # 未使用 todo 工具，增加计数器
                        self._rounds_since_todo += 1

                    # 触发工具调用完成事件
                    self._emit_progress("tool_call_end", {
                        "tool": tool_name,
                        "success": not ("失败" in result or "错误" in result)
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
                
                # 🆕 检测连续失败次数，超过阈值时强制停止并报告
                if self._consecutive_failures >= self._max_consecutive_failures:
                    failure_msg = (
                        f"⚠️ 检测到连续 {self._consecutive_failures} 次工具调用失败。\n\n"
                        "这通常意味着当前方法不可行。可能的原因：\n"
                        "1. 内容过长，超过单次输出限制\n"
                        "2. 参数格式不正确\n"
                        "3. 目标文件/路径不存在\n\n"
                        "建议：请尝试将任务分解为更小的步骤，或使用不同的方法。"
                    )
                    self.logger.warning(f"连续失败 {self._consecutive_failures} 次，注入干预消息")
                    self.messages.append(Message(
                        role="system",
                        content=failure_msg
                    ))
                    # 重置计数器，给 LLM 一次机会改变策略
                    self._consecutive_failures = 0
                
                # 工具结果已添加，继续循环，让 LLM 处理工具结果
            else:
                # 没有工具调用，说明 LLM 已经给出最终答案
                self.logger.info(f"任务完成，共 {self.round_count} 轮")
                self._emit_heartbeat("completed", source="run", total_rounds=self.round_count)

                # 保存助手回答到持久化存储
                if self.session_storage:
                    self.session_storage.add_assistant_message(response.content or "")
                    self.session_storage.update_metadata(total_tokens=self.total_tokens)

                    # 自动生成会话摘要
                    try:
                        self.session_storage.generate_summary(self.llm, response.content or "")
                        self.logger.info("会话摘要已生成")
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

                return response.content

        # 达到最大轮数仍未完成任务
        self.logger.warning(f"达到最大轮数 ({self.max_rounds})")
        if self.trace_logger:
            self.trace_logger.log_event(
                TraceEventType.WARNING,
                {"message": f"达到最大轮数 ({self.max_rounds})，任务未完成"},
                step=self.round_count,
            )
        self._emit_heartbeat("max_rounds", source="run", total_rounds=self.round_count)
        return f"已达到最大轮数 ({self.max_rounds})，无法完成任务。"

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

        # 参数验证：检测可疑的参数值（GLM API 有时会返回类型名称而非实际值）
        validation_error = self._validate_arguments(tool_name, arguments)
        if validation_error:
            self.logger.warning(f"参数验证失败: {validation_error}")
            
            # 🆕 增加连续失败计数
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_consecutive_failures:
                self.logger.error(f"连续 {self._consecutive_failures} 次工具调用失败，建议更换策略")
            
            # 增强错误消息，包含工具正确用法示例
            tool = self.tool_registry.get(tool_name)
            if tool:
                usage_hint = self._get_tool_usage_hint(tool_name, tool)
                return f"错误: {validation_error}\n\n{usage_hint}\n\n⚠️ 这是连续第 {self._consecutive_failures} 次失败，请考虑更换方法。"
            return f"错误: {validation_error}。请提供正确的参数值。（连续第 {self._consecutive_failures} 次失败）"

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

            if self.metrics:
                self.metrics.record_tool_call(tool_name, success=True)

            # 🆕 工具执行成功，重置连续失败计数器
            self._consecutive_failures = 0

            return result

        except Exception as e:
            # 工具执行失败，返回错误信息给 LLM
            # LLM 可以根据错误信息决定是否重试或使用其他方法
            error_msg = f"工具执行失败: {e}"
            
            # 🆕 增加连续失败计数
            self._consecutive_failures += 1

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

            return error_msg

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

        # 添加长期记忆
        if self.memory_manager:
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

    def _handle_skill_command(self, query: str) -> Optional[str]:
        """
        处理 skill 命令
        
        Args:
            query: 用户输入，以 / 开头
            
        Returns:
            处理后的 query（注入了 skill prompt），或 None（不是 skill 命令）
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
        skill_prompt = self.skill_manager.prepare_execution(skill_name, arguments)
        if not skill_prompt:
            return None
        
        self.logger.info(f"执行 Skill: {skill_name}, 参数: {arguments}")
        
        # 记录 skill 执行事件
        if self.trace_logger:
            self.trace_logger.log_event(
                TraceEventType.INFO,
                {"event": "skill_execution", "skill": skill_name, "arguments": arguments},
            )
        
        # 构造增强的 query：skill 指令 + 原始参数
        enhanced_query = f"""执行 Skill: {skill_name}

## Skill 指令

{skill_prompt}

## 目标

{arguments if arguments else "按照上述步骤执行"}
"""
        
        return enhanced_query

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
        self._loop_count = 0
        self._consecutive_failures = 0
        self._skill_injected = False  # 重置 skill 注入标记
        # 重置规划器
        if self.planner:
            self.planner.reset()
        # 清理 skill 缓存
        self.skill_manager.clear_cache()

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
        state = self._heartbeat_state.copy()
        state["age_seconds"] = round(time.time() - state["last_beat_ts"], 2)
        state["timeout_seconds"] = self.heartbeat_timeout_seconds
        state["enabled"] = self.heartbeat_enabled
        return state

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

    def _emit_heartbeat(self, phase: str, source: str = "", **extra) -> None:
        """记录并发射心跳事件"""
        if not self.heartbeat_enabled:
            return
        now = time.time()
        self._heartbeat_state["phase"] = phase
        self._heartbeat_state["last_beat_ts"] = now
        self._heartbeat_state["beats"] += 1
        self._heartbeat_state["last_tool"] = extra.get("tool", self._heartbeat_state["last_tool"])
        self._heartbeat_state["stalled"] = extra.get("stalled", self._heartbeat_state["stalled"])
        if extra.get("alert"):
            self._heartbeat_state["last_alert"] = extra.get("message", "")

        payload = {
            "ts": now,
            "session_id": self._heartbeat_state["session_id"],
            "phase": phase,
            "source": source,
            "round": self.round_count,
            "message_count": len(self.messages),
            "total_tokens": self.total_tokens,
            "last_tool": self._heartbeat_state["last_tool"],
            "stalled": self._heartbeat_state["stalled"],
            **extra,
        }

        try:
            with open(self._heartbeat_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.debug(f"写入心跳日志失败: {e}")

        self._emit_progress("heartbeat", payload)

    def _check_heartbeat_timeout(self, operation: str, duration_ms: float) -> None:
        """超时检测，触发心跳告警"""
        if not self.heartbeat_enabled:
            return
        timeout_ms = self.heartbeat_timeout_seconds * 1000
        if duration_ms <= timeout_ms:
            return
        message = (
            f"心跳告警: {operation} 执行耗时 {duration_ms/1000:.2f}s，"
            f"超过阈值 {self.heartbeat_timeout_seconds}s"
        )
        self.logger.warning(message)
        self._emit_heartbeat(
            "watchdog_alert",
            source="watchdog",
            alert=True,
            stalled=True,
            operation=operation,
            duration_ms=round(duration_ms, 2),
            message=message,
        )
        self._emit_progress("heartbeat_alert", {"operation": operation, "duration_ms": round(duration_ms, 2)})

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
            self.logger.warning(f"签名生成失败 [{tool_name}]: {e}")
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
