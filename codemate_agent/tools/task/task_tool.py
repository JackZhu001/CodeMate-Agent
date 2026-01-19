"""
子代理系统 (MVP 重构版)

支持将任务委托给专门的子代理执行。

核心特性：
- 独立会话：子代理有自己的消息历史和系统提示词
- 工具过滤：只能使用只读工具，防止递归和危险操作
- 双模型路由：支持 main/light 模型选择
- 统一响应：遵循通用工具响应协议
- 参数验证：复用主代理的验证逻辑
- 循环检测：防止子代理陷入死循环
"""

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from codemate_agent.llm.client import GLMClient
from codemate_agent.prompts.agents_prompts import (
    get_subagent_prompt,
    get_default_model,
    SUBAGENT_PROMPTS,
)
from codemate_agent.schema import Message, LLMResponse
from codemate_agent.tools.base import Tool
from codemate_agent.tools.registry import ToolRegistry
from codemate_agent.validation import ArgumentValidator

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 子代理类型描述
SUBAGENT_TYPES = {
    "general": "通用子代理 - 处理一般性任务",
    "explore": "探索子代理 - 用于代码库探索和理解",
    "plan": "规划子代理 - 用于生成实现计划",
    "summary": "摘要子代理 - 用于总结和提炼信息",
}

# 允许子代理使用的工具（只读工具）
ALLOWED_TOOLS = frozenset({
    "list_dir",
    "search_files",
    "search_code",
    "read_file",
    "todo_write",
    "file_info",
})

# 禁止子代理使用的工具（写入和危险操作）
DENIED_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "delete_file",
    "append_file",
    "run_shell",
    "task",  # 防止递归
})


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class SubagentResult:
    """子代理执行结果"""
    
    success: bool
    content: str
    tool_usage: Dict[str, int]
    steps_taken: int
    subagent_type: str
    model_used: str = "main"
    error: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class TaskResponse:
    """
    Task 工具的统一响应格式
    
    遵循通用工具响应协议：
    {
        "status": "success" | "error",
        "data": { ... },
        "text": "人类可读的结果",
        "stats": { ... },
        "context": { ... }
    }
    """
    
    status: str  # "success" | "error"
    data: Dict[str, Any]
    text: str
    stats: Dict[str, Any]
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "text": self.text,
            "stats": self.stats,
            "context": self.context,
        }
    
    def to_text(self) -> str:
        """转换为文本格式（用于 LLM 消费）"""
        lines = [
            f"--- TASK RESULT ---",
            f"状态: {self.status}",
            f"子代理类型: {self.data.get('subagent_type', 'unknown')}",
            f"模型: {self.data.get('model_used', 'unknown')}",
            f"执行步数: {self.stats.get('tool_calls', 0)}",
            f"耗时: {self.stats.get('time_ms', 0)}ms",
        ]
        
        # 工具使用统计
        tool_summary = self.data.get("tool_summary", [])
        if tool_summary:
            tools_str = ", ".join(f"{t['tool']}={t['count']}" for t in tool_summary)
            lines.append(f"工具使用: {tools_str}")
        
        lines.append("")
        lines.append("--- 结果 ---")
        lines.append(self.text)
        
        return "\n".join(lines)


# ============================================================================
# 子代理运行器
# ============================================================================

class SubagentRunner:
    """
    子代理运行器
    
    运行一个独立的子代理会话，具有：
    - 独立的消息历史
    - 受限的工具访问
    - 循环检测
    - 参数验证
    """
    
    # 循环检测配置
    MAX_RECENT_CALLS = 5
    LOOP_THRESHOLD = 3  # 连续相同调用次数阈值
    
    def __init__(
        self,
        llm_client: GLMClient,
        tool_registry: ToolRegistry,
        subagent_type: str = "general",
        max_steps: int = 15,
        workspace_dir: Path = None,
    ):
        """
        初始化子代理运行器
        
        Args:
            llm_client: LLM 客户端
            tool_registry: 工具注册器（会被过滤）
            subagent_type: 子代理类型
            max_steps: 最大执行步数
            workspace_dir: 工作目录
        """
        self.llm = llm_client
        self.subagent_type = subagent_type
        self.max_steps = max_steps
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        
        # 创建受限的工具注册器
        self.tool_registry = self._create_filtered_registry(tool_registry)
        
        # 消息历史
        self.messages: List[Message] = []
        
        # 工具使用统计
        self.tool_usage: Dict[str, int] = {}
        
        # 循环检测
        self._recent_calls: List[str] = []
        self._loop_warnings = 0
    
    def _create_filtered_registry(self, full_registry: ToolRegistry) -> ToolRegistry:
        """创建受限的工具注册器"""
        filtered = ToolRegistry()
        
        for tool in full_registry.get_all().values():
            tool_name = tool.name
            
            # 检查是否在禁止列表
            if tool_name in DENIED_TOOLS:
                continue
            
            # 只添加允许的工具
            if tool_name in ALLOWED_TOOLS:
                filtered.register(tool)
        
        logger.debug(f"子代理工具过滤: {list(filtered.list_tools())}")
        return filtered
    
    def run(self, task_description: str, task_prompt: str) -> SubagentResult:
        """
        运行子代理
        
        Args:
            task_description: 任务简述
            task_prompt: 详细任务指令
            
        Returns:
            SubagentResult: 执行结果
        """
        # 获取子代理类型对应的系统提示词
        try:
            role_prompt = get_subagent_prompt(self.subagent_type)
        except ValueError as e:
            return SubagentResult(
                success=False,
                content=str(e),
                tool_usage={},
                steps_taken=0,
                subagent_type=self.subagent_type,
                error=str(e),
            )
        
        # 构建系统提示词：角色提示 + 任务描述
        system_prompt = f"{role_prompt}\n\n# 当前任务\n{task_description}"
        
        # 初始化消息
        self.messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=task_prompt),
        ]
        
        # 主循环
        for step in range(self.max_steps):
            # 调用 LLM
            try:
                response = self.llm.complete(
                    messages=self.messages,
                    tools=self._get_tools_schemas(),
                )
            except Exception as e:
                logger.error(f"子代理 LLM 调用失败: {e}")
                return SubagentResult(
                    success=False,
                    content=f"LLM 调用失败: {e}",
                    tool_usage=self.tool_usage,
                    steps_taken=step,
                    subagent_type=self.subagent_type,
                    error=str(e),
                )
            
            # 添加助手响应
            self.messages.append(Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))
            
            # 检查是否有工具调用
            if response.tool_calls:
                # 检测循环
                if self._detect_loop(response.tool_calls):
                    self._loop_warnings += 1
                    if self._loop_warnings >= 2:
                        # 强制终止
                        logger.warning("子代理检测到循环，强制终止")
                        return SubagentResult(
                            success=False,
                            content="检测到重复的工具调用模式，任务终止",
                            tool_usage=self.tool_usage,
                            steps_taken=step + 1,
                            subagent_type=self.subagent_type,
                            error="循环检测终止",
                        )
                    else:
                        # 添加警告消息
                        self.messages.append(Message(
                            role="system",
                            content="警告：检测到重复的工具调用，请尝试其他方法或直接给出答案。"
                        ))
                
                # 执行所有工具调用
                for tool_call in response.tool_calls:
                    tool_result = self._execute_tool_call(tool_call)
                    
                    self.messages.append(Message(
                        role="tool",
                        content=tool_result,
                        tool_call_id=tool_call.id,
                        name=tool_call.function.name,
                    ))
            else:
                # 没有工具调用，任务完成
                logger.info(f"子代理完成，共 {step + 1} 步")
                return SubagentResult(
                    success=True,
                    content=response.content or "",
                    tool_usage=self.tool_usage,
                    steps_taken=step + 1,
                    subagent_type=self.subagent_type,
                )
        
        # 达到最大步数
        return SubagentResult(
            success=False,
            content="达到最大步数限制，任务未完成",
            tool_usage=self.tool_usage,
            steps_taken=self.max_steps,
            subagent_type=self.subagent_type,
            error="达到最大步数",
        )
    
    def _get_tools_schemas(self) -> List[Dict[str, Any]]:
        """获取工具的 OpenAI Schema 格式"""
        return [t.to_openai_schema() for t in self.tool_registry.get_all().values()]
    
    def _execute_tool_call(self, tool_call) -> str:
        """执行单个工具调用（带参数验证）"""
        tool_name = tool_call.function.name
        arguments = tool_call.function.arguments
        
        logger.debug(f"子代理执行工具: {tool_name}")
        
        # 参数验证
        fixed_args, validation_error = ArgumentValidator.validate_and_fix(
            tool_name, arguments
        )
        
        if validation_error:
            logger.warning(f"子代理参数验证失败: {validation_error}")
            hint = ArgumentValidator.get_usage_hint(tool_name)
            return f"参数错误: {validation_error}\n正确用法: {hint}"
        
        # 统计工具使用
        self.tool_usage[tool_name] = self.tool_usage.get(tool_name, 0) + 1
        
        try:
            result = self.tool_registry.execute(tool_name, **fixed_args)
            return str(result)
        except Exception as e:
            error_msg = f"工具执行失败: {e}"
            logger.error(error_msg)
            return error_msg
    
    def _detect_loop(self, tool_calls) -> bool:
        """检测是否陷入循环"""
        # 生成调用签名
        signatures = []
        for tc in tool_calls:
            name = tc.function.name
            args = tc.function.arguments
            # 简化签名：工具名 + 主要参数的哈希
            args_hash = hashlib.md5(str(args).encode()).hexdigest()[:8]
            signatures.append(f"{name}:{args_hash}")
        
        current_sig = "|".join(sorted(signatures))
        self._recent_calls.append(current_sig)
        
        # 保留最近 N 次调用
        if len(self._recent_calls) > self.MAX_RECENT_CALLS:
            self._recent_calls.pop(0)
        
        # 检查是否有连续相同的调用
        if len(self._recent_calls) >= self.LOOP_THRESHOLD:
            recent = self._recent_calls[-self.LOOP_THRESHOLD:]
            if len(set(recent)) == 1:
                return True
        
        return False


# ============================================================================
# Task 工具
# ============================================================================

class TaskTool(Tool):
    """
    任务委托工具 (MVP 版本)
    
    允许主代理将任务委托给子代理执行。
    
    特性：
    - 支持 main/light 双模型路由
    - 统一响应格式
    - 智能摘要（可选）
    - 参数验证
    """
    
    # 智能摘要配置
    DEFAULT_SUMMARY_THRESHOLD = 1500  # 超过此长度触发摘要
    SUMMARY_CACHE_TTL = 300  # 摘要缓存有效期（秒）
    
    def __init__(self, working_dir: str = "."):
        super().__init__()
        self._working_dir = working_dir
        
        # 主模型客户端（运行时注入）
        self._main_llm_client: Optional[GLMClient] = None
        # 轻量模型客户端（运行时注入或与主模型相同）
        self._light_llm_client: Optional[GLMClient] = None
        # 工具注册器
        self._tool_registry: Optional[ToolRegistry] = None
        
        # 摘要缓存
        self._summary_cache: Dict[str, Tuple[str, float]] = {}
    
    def set_dependencies(
        self,
        main_llm_client: GLMClient,
        tool_registry: ToolRegistry,
        light_llm_client: Optional[GLMClient] = None,
    ):
        """
        设置依赖（由 Agent 注入）
        
        Args:
            main_llm_client: 主模型客户端
            tool_registry: 工具注册器
            light_llm_client: 轻量模型客户端（可选，默认使用主模型）
        """
        self._main_llm_client = main_llm_client
        self._light_llm_client = light_llm_client or main_llm_client
        self._tool_registry = tool_registry
    
    @property
    def name(self) -> str:
        return "task"
    
    @property
    def description(self) -> str:
        return """将任务委托给子代理处理。

【什么时候使用子代理】
- 需要多步探索（如：遍历目录、查找相关文件、分析项目结构）
- 不确定需要多少次工具调用才能完成
- 主要是信息收集和分析，不需要实时反馈
- 可能产生大量中间结果（使用子代理避免占用主对话上下文）

【什么时候直接处理】
- 单次工具调用就能完成（如：读取单个文件）
- 需要实时反馈给用户的操作
- 简单操作（1-2 步内完成）

【子代理类型说明】
- general: 通用任务处理
- explore: 代码探索、文件搜索（推荐用于探索项目结构）
- plan: 生成实现计划
- summary: 总结和提炼信息

【模型选择】
- main: 主模型，用于复杂推理任务
- light: 轻量模型，用于简单任务（默认根据类型自动选择）

参数：
- description: 任务简述（必填，如 "分析项目结构"）
- prompt: 详细任务指令（必填，描述具体要做什么）
- subagent_type: 子代理类型（可选，默认: general）
- model: 模型选择（可选，默认: 根据类型自动选择）

返回：
- 任务执行结果
- 工具使用统计
- 执行步数和耗时"""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "任务简述，如 '分析项目结构'"
                },
                "prompt": {
                    "type": "string",
                    "description": "详细任务指令，描述具体要做什么"
                },
                "subagent_type": {
                    "type": "string",
                    "enum": ["general", "explore", "plan", "summary"],
                    "description": "子代理类型，默认为 general"
                },
                "model": {
                    "type": "string",
                    "enum": ["main", "light"],
                    "description": "模型选择，默认根据类型自动选择"
                }
            },
            "required": ["description", "prompt"]
        }
    
    def run(self, **kwargs) -> str:
        """
        执行任务委托
        
        Args:
            description: 任务简述
            prompt: 详细任务指令
            subagent_type: 子代理类型（可选）
            model: 模型选择（可选）
            
        Returns:
            str: 格式化的结果字符串
        """
        # 检查依赖
        if not self._main_llm_client or not self._tool_registry:
            return self._format_error("INTERNAL_ERROR", "Task 工具未正确初始化（缺少依赖）")
        
        # 提取参数
        description = kwargs.get("description", "")
        prompt = kwargs.get("prompt", "")
        subagent_type = kwargs.get("subagent_type", "general")
        model = kwargs.get("model")
        
        # 参数验证
        validation_error = ArgumentValidator.validate("task", kwargs)
        if validation_error:
            return self._format_error("INVALID_PARAM", validation_error)
        
        # 验证子代理类型
        if subagent_type not in SUBAGENT_TYPES:
            return self._format_error(
                "INVALID_PARAM",
                f"不支持的子代理类型: {subagent_type}。"
                f"支持的类型: {list(SUBAGENT_TYPES.keys())}"
            )
        
        # 确定使用的模型
        if model is None:
            model = get_default_model(subagent_type)
        
        llm_client = self._light_llm_client if model == "light" else self._main_llm_client
        
        # 获取最大步数
        import os
        max_steps = int(os.getenv("SUBAGENT_MAX_STEPS", "15"))
        
        # 创建并运行子代理
        start_time = time.time()
        session_id = str(uuid.uuid4())[:8]
        
        logger.info(f"启动子代理 [{session_id}]: type={subagent_type}, model={model}")
        
        try:
            runner = SubagentRunner(
                llm_client=llm_client,
                tool_registry=self._tool_registry,
                subagent_type=subagent_type,
                max_steps=max_steps,
                workspace_dir=self._working_dir,
            )
            
            result = runner.run(description, prompt)
            result.model_used = model
            
        except Exception as e:
            logger.error(f"子代理执行失败: {e}")
            return self._format_error("INTERNAL_ERROR", str(e))
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 格式化响应
        return self._format_success(result, duration_ms, kwargs)
    
    def _format_success(
        self,
        result: SubagentResult,
        duration_ms: int,
        params_input: Dict[str, Any],
    ) -> str:
        """格式化成功响应"""
        # 处理内容：可选智能摘要
        content = result.content
        content_length = len(content)
        
        if content_length > self.DEFAULT_SUMMARY_THRESHOLD:
            summary = self._generate_intelligent_summary(content, result.subagent_type)
            if summary:
                content = summary
                logger.info(f"子代理结果已摘要: {content_length} → {len(summary)} 字符")
            else:
                # 摘要失败，使用结构化截断
                content = self._truncate_content(content)
        
        # 构建工具使用统计
        tool_summary = [
            {"tool": tool, "count": count}
            for tool, count in result.tool_usage.items()
        ]
        
        # 构建响应
        response = TaskResponse(
            status="success" if result.success else "error",
            data={
                "status": "completed" if result.success else "failed",
                "result": content,
                "tool_summary": tool_summary,
                "model_used": result.model_used,
                "subagent_type": result.subagent_type,
            },
            text=content,
            stats={
                "time_ms": duration_ms,
                "tool_calls": sum(result.tool_usage.values()),
                "steps": result.steps_taken,
                "model": result.model_used,
            },
            context={
                "cwd": str(self._working_dir),
                "params_input": params_input,
            },
        )
        
        return response.to_text()
    
    def _format_error(self, error_code: str, message: str) -> str:
        """格式化错误响应"""
        response = TaskResponse(
            status="error",
            data={
                "error_code": error_code,
                "message": message,
            },
            text=f"错误 [{error_code}]: {message}",
            stats={},
            context={},
        )
        return response.to_text()
    
    def _truncate_content(self, content: str) -> str:
        """结构化截断内容"""
        max_length = 2000
        if len(content) <= max_length:
            return content
        
        # 保留开头和结尾
        head_length = int(max_length * 0.6)
        tail_length = int(max_length * 0.3)
        
        head = content[:head_length]
        tail = content[-tail_length:]
        
        omitted = len(content) - head_length - tail_length
        return f"{head}\n\n... [省略 {omitted} 字符] ...\n\n{tail}"
    
    def _generate_intelligent_summary(
        self,
        content: str,
        subagent_type: str,
    ) -> Optional[str]:
        """
        生成智能摘要
        
        成本控制策略：
        1. 内容哈希缓存
        2. 最大输入长度限制
        """
        if not self._light_llm_client:
            return None
        
        # 计算内容哈希
        content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
        
        # 检查缓存
        current_time = time.time()
        if content_hash in self._summary_cache:
            cached_summary, cache_time = self._summary_cache[content_hash]
            if current_time - cache_time < self.SUMMARY_CACHE_TTL:
                logger.debug(f"使用缓存的摘要: {content_hash}")
                return cached_summary
        
        # 限制输入长度
        max_input_length = 4000
        truncated_content = content[:max_input_length]
        if len(content) > max_input_length:
            truncated_content += "\n...(后续内容省略)"
        
        # 摘要提示词
        prompt = f"""请将以下{subagent_type}子代理的执行结果摘要为简洁的要点。

要求：
1. 提取关键发现和结论
2. 列出主要操作结果
3. 省略中间过程
4. 使用 Markdown 格式
5. 控制在 300 字以内

原始结果：
{truncated_content}

请生成摘要："""
        
        try:
            response = self._light_llm_client.complete(
                messages=[Message(role="user", content=prompt)],
                tools=None,
            )
            
            summary = response.content.strip() if response.content else None
            
            if summary and len(summary) < len(content):
                # 缓存结果
                self._summary_cache[content_hash] = (summary, current_time)
                
                # 清理过期缓存
                self._cleanup_cache(current_time)
                
                return summary
        
        except Exception as e:
            logger.warning(f"智能摘要生成失败: {e}")
        
        return None
    
    def _cleanup_cache(self, current_time: float) -> None:
        """清理过期缓存"""
        expired = [
            key for key, (_, ts) in self._summary_cache.items()
            if current_time - ts > self.SUMMARY_CACHE_TTL
        ]
        for key in expired:
            del self._summary_cache[key]
