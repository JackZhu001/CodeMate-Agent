"""
工具模块

自动发现和注册所有工具。
"""

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import List

from codemate_agent.tools.base import Tool
from codemate_agent.tools.registry import ToolRegistry


# 工具类别目录
_TOOL_CATEGORIES = ["file", "search", "shell", "todo", "task", "skill"]


def _discover_tools() -> List[Tool]:
    """
    自动发现所有工具类

    Returns:
        List[Tool]: 工具实例列表
    """
    tools = []
    current_dir = Path(__file__).parent

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
                        # 实例化工具
                        try:
                            tool_instance = obj()
                            tools.append(tool_instance)
                        except Exception as e:
                            # 跳过无法实例化的工具
                            pass

            except ImportError:
                # 跳过无法导入的模块
                continue

    return tools


# 预加载所有工具
_cached_tools = _discover_tools()


def get_all_tools() -> List[Tool]:
    """
    获取所有可用工具

    Returns:
        List[Tool]: 工具实例列表
    """
    return _cached_tools.copy()


def get_tool_registry() -> ToolRegistry:
    """
    获取包含所有工具的注册器

    Returns:
        ToolRegistry: 工具注册器实例
    """
    registry = ToolRegistry()
    for tool in _cached_tools:
        registry.register(tool)
    return registry


# 导出基类和注册器
__all__ = [
    "Tool",
    "ToolRegistry",
    "get_all_tools",
    "get_tool_registry",
]
