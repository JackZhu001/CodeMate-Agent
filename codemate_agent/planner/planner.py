"""
任务规划器

负责检测复杂任务并生成执行计划。
"""

import json
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from codemate_agent.llm.client import LLMClient as GLMClient
from codemate_agent.schema import Message


logger = logging.getLogger(__name__)


# 规划触发关键词
PLANNING_TRIGGERS = [
    "实现", "implement", "添加", "add", "创建", "create",
    "重构", "refactor", "修改", "modify", "设计", "design",
    "功能", "feature", "模块", "module", "系统", "system",
]

# 简单查询关键词（不需要规划）
SIMPLE_QUERY_PATTERNS = [
    ("是什么", lambda x: len(x) < 50),
    ("有哪些", lambda x: len(x) < 50),
    ("怎么", lambda x: len(x) < 50),
    ("如何", lambda x: len(x) < 50),
    ("what is", lambda x: len(x) < 50),
    ("how to", lambda x: len(x) < 50),
    ("list", lambda x: len(x) < 30),
    ("show", lambda x: len(x) < 30),
    ("find", lambda x: len(x) < 30),
    ("search", lambda x: len(x) < 30),
    ("分析", lambda x: "的" in x and len(x) < 50),
]


@dataclass
class TaskPlan:
    """任务计划"""
    summary: str
    steps: List[Dict[str, str]]  # [{"content": "...", "status": "pending"}]
    requires_planning: bool = True

    def to_todo_params(self) -> Dict[str, Any]:
        """转换为 TodoWrite 工具参数"""
        return {
            "summary": self.summary,
            "todos": self.steps,
        }


class TaskPlanner:
    """
    任务规划器

    功能：
    1. 检测是否需要规划（复杂度判断）
    2. 生成执行计划（调用 LLM）
    3. 管理计划状态
    """

    # 规划提示词
    PLANNING_PROMPT = """你是一个任务规划专家。请将以下任务分解为具体的执行步骤。

任务描述: {query}

请生成一个清晰的执行计划，要求：
1. 每个步骤应该是具体可执行的
2. 步骤之间有逻辑依赖关系
3. 最多 5-7 个步骤
4. 每个步骤用简洁的中文描述（不超过 40 字）
5. 外部搜索/联网步骤最多 2 步，失败后应切换到本地文档继续推进
6. 如果任务涉及生成网页或长文档，计划中必须包含“分块写入文件（write_file_chunks/append_file_chunks）”

请直接返回 JSON 格式，不要包含其他内容：
{{
    "summary": "任务概述",
    "steps": [
        {{"content": "步骤1描述", "status": "pending"}},
        {{"content": "步骤2描述", "status": "pending"}},
        ...
    ]
}}
"""

    def __init__(
        self,
        llm_client: GLMClient,
        enabled: bool = True,
        auto_planning: bool = True,
    ):
        """
        初始化任务规划器

        Args:
            llm_client: LLM 客户端
            enabled: 是否启用规划功能
            auto_planning: 是否自动触发规划（否则需要手动调用）
        """
        self.llm = llm_client
        self.enabled = enabled
        self.auto_planning = auto_planning
        self.current_plan: Optional[TaskPlan] = None

    def needs_planning(self, query: str) -> bool:
        """
        判断查询是否需要规划

        Args:
            query: 用户查询

        Returns:
            bool: 是否需要规划
        """
        if not self.enabled or not self.auto_planning:
            return False

        query_lower = query.lower().strip()

        # 检查是否是简单查询
        for pattern, condition in SIMPLE_QUERY_PATTERNS:
            if pattern in query_lower and condition(query):
                return False

        # 检查是否包含规划触发词
        for trigger in PLANNING_TRIGGERS:
            if trigger in query_lower:
                return True

        # 检查查询长度（长查询更可能需要规划）
        if len(query) > 100:
            return True

        return False

    def generate_plan(self, query: str) -> Optional[TaskPlan]:
        """
        生成执行计划

        Args:
            query: 用户查询

        Returns:
            TaskPlan: 生成的计划，如果失败返回 None
        """
        if not self.enabled:
            return None

        try:
            prompt = self.PLANNING_PROMPT.format(query=query)

            # 调用 LLM 生成计划
            response = self.llm.complete(
                messages=[Message(role="user", content=prompt)],
                tools=None,  # 不需要工具
            )

            # 解析响应
            plan = self._parse_plan_response(response.content, query)
            if plan:
                self.current_plan = plan
                logger.info(f"生成执行计划: {plan.summary}")
                return plan
            else:
                logger.warning("无法解析规划响应")
                return None

        except Exception as e:
            logger.error(f"生成规划失败: {e}")
            return None

    def _parse_plan_response(self, content: str, query: str) -> Optional[TaskPlan]:
        """
        解析 LLM 返回的计划

        Args:
            content: LLM 响应内容
            query: 原始查询

        Returns:
            TaskPlan: 解析后的计划
        """
        if not content:
            return None

        # 尝试提取 JSON
        content = content.strip()

        # 查找 JSON 代码块
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()

        # 尝试解析 JSON
        try:
            data = json.loads(content)

            summary = data.get("summary", query[:50])
            steps = data.get("steps", [])

            # 确保 steps 格式正确
            validated_steps = []
            for i, step in enumerate(steps):
                if isinstance(step, dict):
                    content_str = step.get("content", "")
                    if content_str:
                        validated_steps.append({
                            "content": str(content_str)[:60],
                            "status": "pending",
                        })
                elif isinstance(step, str):
                    # 简单字符串格式
                    validated_steps.append({
                        "content": step[:60],
                        "status": "pending",
                    })

            if not validated_steps:
                return None

            return TaskPlan(
                summary=summary,
                steps=validated_steps,
            )

        except json.JSONDecodeError:
            # 如果 JSON 解析失败，尝试从文本中提取步骤
            return self._parse_text_plan(content, query)

    def _parse_text_plan(self, content: str, query: str) -> Optional[TaskPlan]:
        """
        从非结构化文本中解析计划

        Args:
            content: 文本内容
            query: 原始查询

        Returns:
            TaskPlan: 解析后的计划
        """
        steps = []
        lines = content.split("\n")

        for line in lines:
            line = line.strip()
            # 查找列表项
            if line.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.",
                               "- ", "* ", "• ", "Step")):
                # 去掉前缀
                step_content = line
                for prefix in ["1.", "2.", "3.", "4.", "5.", "6.", "7.",
                               "- ", "* ", "• ", "Step", "步骤"]:
                    if step_content.startswith(prefix):
                        step_content = step_content[len(prefix):].strip()
                        break

                if step_content and len(step_content) > 3:
                    steps.append({
                        "content": step_content[:60],
                        "status": "pending",
                    })

        if steps:
            return TaskPlan(
                summary=query[:50],
                steps=steps[:7],  # 最多 7 个步骤
            )

        return None

    def update_step_status(self, step_index: int, status: str) -> bool:
        """
        更新步骤状态

        Args:
            step_index: 步骤索引（从 0 开始）
            status: 新状态 (pending/in_progress/completed/cancelled)

        Returns:
            bool: 是否更新成功
        """
        if not self.current_plan:
            return False

        if 0 <= step_index < len(self.current_plan.steps):
            self.current_plan.steps[step_index]["status"] = status
            return True

        return False

    def get_current_step_index(self) -> Optional[int]:
        """
        获取当前进行中的步骤索引

        Returns:
            int: 当前步骤索引，如果没有进行中的步骤返回 None
        """
        if not self.current_plan:
            return None

        for i, step in enumerate(self.current_plan.steps):
            if step["status"] == "in_progress":
                return i

        return None

    def get_next_pending_step(self) -> Optional[int]:
        """
        获取下一个待处理的步骤索引

        Returns:
            int: 下一个待处理步骤索引，如果没有返回 None
        """
        if not self.current_plan:
            return None

        for i, step in enumerate(self.current_plan.steps):
            if step["status"] == "pending":
                return i

        return None

    def is_plan_complete(self) -> bool:
        """
        检查计划是否完成

        Returns:
            bool: 是否所有步骤都已完成
        """
        if not self.current_plan:
            return True

        for step in self.current_plan.steps:
            if step["status"] not in ("completed", "cancelled"):
                return False

        return True

    def get_progress_summary(self) -> str:
        """
        获取进度摘要

        Returns:
            str: 进度摘要文本
        """
        if not self.current_plan:
            return "无执行计划"

        total = len(self.current_plan.steps)
        completed = sum(1 for s in self.current_plan.steps if s["status"] == "completed")
        in_progress = sum(1 for s in self.current_plan.steps if s["status"] == "in_progress")

        return f"{self.current_plan.summary} [{completed}/{total}]"

    def reset(self):
        """重置规划器"""
        self.current_plan = None
