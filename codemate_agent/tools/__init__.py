"""
工具模块

自动发现和注册所有工具。
"""

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import List, Optional

from codemate_agent.tools.base import Tool
from codemate_agent.tools.registry import ToolRegistry


# 工具类别目录
_TOOL_CATEGORIES = ["file", "search", "shell", "todo", "task", "skill", "compact"]


def _discover_tools(workspace_dir: Optional[str] = None) -> List[Tool]:
    """
    自动发现所有工具类

    Args:
        workspace_dir: 工作目录路径，用于文件操作工具的安全检查

    Returns:
        List[Tool]: 工具实例列表
    """
    tools = []
    current_dir = Path(__file__).parent
    ws_path = Path(workspace_dir) if workspace_dir else Path.cwd()

    for category in _TOOL_CATEGORIES:
        category_path = current_dir / category
        if not category_path.exists():
            continue

        # 遍历类别目录下的所有 Python 文件
        for file_path in category_path.glob("*.py"):
            if file_path.name.startswith("_"):
                continue

            # 构建模块路径
            module_name = f"codemate_agent.tools.{category}.{file_path.stem}"

            try:
                # 动态导入模块
                module = importlib.import_module(module_name)

                # 查找模块中的 Tool 子类
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, Tool) and
                        obj is not Tool and
                        hasattr(obj, '__module__') and
                        obj.__module__ == module_name):
                        # 实例化工具，传递 workspace_dir
                        try:
                            # 检查类是否有 workspace_dir 参数
                            sig = inspect.signature(obj.__init__)
                            if 'workspace_dir' in sig.parameters:
                                tool_instance = obj(workspace_dir=str(ws_path))
                            else:
                                tool_instance = obj()
                            tools.append(tool_instance)
                        except Exception as e:
                            # 跳过无法实例化的工具
                            pass

            except ImportError:
                # 跳过无法导入的模块
                continue

    return tools


# 预加载所有工具（默认工作目录）
_cached_tools = _discover_tools()


def get_all_tools(workspace_dir: Optional[str] = None) -> List[Tool]:
    """
    获取所有可用工具

    Args:
        workspace_dir: 可选的工作目录路径。如果提供，将创建带有该工作目录的工具实例。

    Returns:
        List[Tool]: 工具实例列表
    """
    if workspace_dir is None:
        return _cached_tools.copy()
    return _discover_tools(workspace_dir)


def get_tool_registry(workspace_dir: Optional[str] = None) -> ToolRegistry:
    """
    获取包含所有工具的注册器

    Args:
        workspace_dir: 可选的工作目录路径

    Returns:
        ToolRegistry: 工具注册器实例
    """
    tools = _discover_tools(workspace_dir) if workspace_dir else _cached_tools.copy()
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


# 导出基类和注册器
__all__ = [
    "Tool",
    "ToolRegistry",
    "get_all_tools",
    "get_tool_registry",
]
