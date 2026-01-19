"""
TodoWrite 工具 - 任务列表管理

参考设计：
- 声明式更新：LLM 提交完整列表，工具负责 diff
- 低心智负担：模型不维护 id，只提交 content + status
- UI 分离：data 面向模型，text 面向用户
- 持久化存储：类级别存储，支持跨轮次状态保持
"""

from typing import Any, Dict, List, Optional, ClassVar
from pathlib import Path

from codemate_agent.tools.base import Tool


# 有效的任务状态
VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}

# 约束常量
MAX_TODO_COUNT = 10
MAX_CONTENT_LENGTH = 60


class TodoWriteTool(Tool):
    """
    任务列表管理工具

    支持声明式覆盖更新任务列表，带持久化存储。
    """

    # 状态图标
    STATUS_ICONS = {
        "pending": "[ ]",
        "in_progress": "[▶]",
        "completed": "[✓]",
        "cancelled": "[~]",
    }

    # 类级别持久化存储
    _current_todos: ClassVar[List[Dict]] = []
    _current_summary: ClassVar[str] = ""

    def __init__(self, working_dir: str = "."):
        """初始化 TodoWrite 工具"""
        self._working_dir = working_dir

    @classmethod
    def get_current_state(cls) -> Optional[Dict[str, Any]]:
        """
        获取当前 todo 状态（供 Agent 层访问）

        Returns:
            {
                "summary": "任务概述",
                "todos": [...],
                "stats": {...},
                "formatted": "格式化字符串"
            }
            如果没有 todo，返回 None
        """
        if not cls._current_todos:
            return None

        stats = {
            "total": len(cls._current_todos),
            "pending": sum(1 for t in cls._current_todos if t["status"] == "pending"),
            "in_progress": sum(1 for t in cls._current_todos if t["status"] == "in_progress"),
            "completed": sum(1 for t in cls._current_todos if t["status"] == "completed"),
            "cancelled": sum(1 for t in cls._current_todos if t["status"] == "cancelled"),
        }

        # 生成简洁的格式化字符串
        lines = [f"📋 {cls._current_summary}"]
        for todo in cls._current_todos:
            icon = cls.STATUS_ICONS.get(todo["status"], "[ ]")
            lines.append(f"  {icon} {todo['content']}")
        done = stats["completed"] + stats["cancelled"]
        lines.append(f"  进度: {done}/{stats['total']}")

        return {
            "summary": cls._current_summary,
            "todos": cls._current_todos,
            "stats": stats,
            "formatted": "\n".join(lines),
        }

    @classmethod
    def clear(cls) -> None:
        """清空当前 todo 状态（任务完成或新会话开始时调用）"""
        cls._current_todos = []
        cls._current_summary = ""

    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return """管理任务列表。

支持的操作：
- 创建/更新任务列表
- 更新任务状态
- 显示进度

参数：
- summary: 总体任务概述（必填）
- todos: 任务列表，每项包含 {content: string, status: pending|in_progress|completed|cancelled}（必填）

约束：
- 最多 10 个任务
- 每个任务最多 60 字符
- 同时只能有 1 个 in_progress 状态的任务

返回格式化的任务列表显示。"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "总体任务概述"
                },
                "todos": {
                    "type": "array",
                    "description": "任务列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "任务内容"
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "任务状态"
                            }
                        },
                        "required": ["content"]
                    }
                }
            },
            "required": ["summary", "todos"]
        }

    def run(self, **kwargs) -> str:
        """
        执行任务列表更新

        Args:
            summary: 总体任务概述
            todos: 任务列表

        Returns:
            格式化的响应字符串
        """
        summary = kwargs.get("summary", "")
        todos = kwargs.get("todos", [])

        # 防护：确保 todos 是列表
        if not isinstance(todos, list):
            return self._error(f"todos 必须是数组，实际收到 {type(todos).__name__}")

        # 参数校验
        if not summary:
            return self._error("summary 参数不能为空")

        if not isinstance(todos, list):
            return self._error("todos 必须是数组")

        if len(todos) > MAX_TODO_COUNT:
            return self._error(f"最多支持 {MAX_TODO_COUNT} 个任务")

        # 验证并生成任务列表
        validated_todos = []
        in_progress_count = 0

        for idx, item in enumerate(todos):
            # 确保 item 是字典
            if not isinstance(item, dict):
                continue

            try:
                content = item.get("content", "")
                status = item.get("status", "pending")

                # content 必填
                if not content:
                    continue

                # 确保 content 和 status 是字符串
                if not isinstance(content, str):
                    content = str(content)
                if not isinstance(status, str):
                    status = "pending"

                content = content.strip()[:MAX_CONTENT_LENGTH]

                # status 默认为 pending
                if status not in VALID_STATUSES:
                    status = "pending"

                # 统计 in_progress
                if status == "in_progress":
                    in_progress_count += 1

                validated_todos.append({
                    "id": f"t{idx + 1}",
                    "content": content,
                    "status": status,
                })
            except Exception as e:
                # 跳过有问题的项目
                import logging
                logging.getLogger(__name__).warning(f"处理任务 {idx} 时出错: {e}")
                continue

        # 约束：最多一个 in_progress
        if in_progress_count > 1:
            return self._error("同时只能有 1 个进行中的任务")

        # 计算 diff（与上次状态对比）
        diff = self._compute_diff(TodoWriteTool._current_todos, validated_todos)

        # 持久化到类变量
        TodoWriteTool._current_todos = validated_todos
        TodoWriteTool._current_summary = summary

        # 生成统计
        stats = self._get_stats(validated_todos)

        # 生成响应（带 diff）
        return self._format_response(
            todos=validated_todos,
            diff=diff,
            summary=summary,
            stats=stats,
        )

    def _get_stats(self, todos: List[Dict]) -> Dict[str, int]:
        """获取任务统计"""
        return {
            "total": len(todos),
            "pending": sum(1 for t in todos if t["status"] == "pending"),
            "in_progress": sum(1 for t in todos if t["status"] == "in_progress"),
            "completed": sum(1 for t in todos if t["status"] == "completed"),
            "cancelled": sum(1 for t in todos if t["status"] == "cancelled"),
        }

    def _compute_diff(
        self,
        old_todos: List[Dict],
        new_todos: List[Dict]
    ) -> Dict[str, List[str]]:
        """
        计算两次 todo 列表的差异

        Returns:
            {
                "newly_completed": ["任务1", "任务2"],
                "newly_added": ["任务3"],
                "status_changed": ["任务4: pending → in_progress"]
            }
        """
        diff = {
            "newly_completed": [],
            "newly_added": [],
            "status_changed": [],
        }

        # 构建旧状态索引 (content -> status)
        old_map = {t["content"]: t["status"] for t in old_todos}

        for todo in new_todos:
            content = todo["content"]
            new_status = todo["status"]

            if content not in old_map:
                # 新增任务
                diff["newly_added"].append(content)
            else:
                old_status = old_map[content]
                if old_status != new_status:
                    if new_status == "completed":
                        diff["newly_completed"].append(content)
                    else:
                        diff["status_changed"].append(
                            f"{content}: {old_status} → {new_status}"
                        )

        return diff

    def _format_response(
        self,
        todos: List[Dict],
        summary: str,
        stats: Dict[str, int],
        diff: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """格式化响应（带 diff 信息）"""
        lines = []
        lines.append("--- TODO UPDATE ---")
        lines.append(f"任务: {summary}")

        # 显示 diff（如果有变化）
        if diff:
            if diff["newly_completed"]:
                lines.append(f"✅ 刚完成: {', '.join(diff['newly_completed'])}")
            if diff["newly_added"]:
                lines.append(f"➕ 新增: {', '.join(diff['newly_added'])}")
            if diff["status_changed"]:
                lines.append(f"🔄 状态变化: {', '.join(diff['status_changed'])}")

        lines.append("")  # 空行分隔

        for todo in todos:
            icon = self.STATUS_ICONS.get(todo["status"], "[ ]")
            lines.append(f"{icon} {todo['content']}")

        # 统计行
        done = stats["completed"] + stats["cancelled"]
        lines.append(f"--- [{done}/{stats['total']}] 完成 ---")

        return "\n".join(lines)

    def _error(self, message: str) -> str:
        """返回错误信息"""
        return f"❌ TodoWrite 错误: {message}"
