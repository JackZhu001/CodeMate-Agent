"""
文件名搜索工具

按文件名模式查找文件，支持通配符。
"""

from pathlib import Path
from typing import Optional
from codemate_agent.tools.base import Tool
from codemate_agent.tools.utils import safe_path, PathSecurityError


class SearchFilesTool(Tool):
    """
    文件名搜索工具

    用于按文件名模式查找文件，与 search_code（搜索内容）不同。
    """

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return """按文件名模式查找文件。

参数:
- pattern: 文件名模式，支持通配符，如 "*.py", "test_*.py", "*.md"
- path: 搜索路径（默认当前目录）

输出: 匹配的文件路径列表

示例:
- pattern="*.py" → 找所有 Python 文件
- pattern="test_*" → 找所有 test 开头的文件
- pattern="*.json" → 找所有 JSON 文件"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "文件名模式，支持 * 和 ? 通配符，如 *.py, test_*.py"
                },
                "path": {
                    "type": "string",
                    "description": "搜索路径，默认为当前目录"
                }
            },
            "required": ["pattern"]
        }

    def run(
        self,
        pattern: str,
        path: str = ".",
        **kwargs
    ) -> str:
        """
        执行文件名搜索

        Args:
            pattern: 文件名模式（支持通配符）
            path: 搜索路径

        Returns:
            str: 匹配的文件路径列表
        """
        try:
            # 使用安全路径检查
            root = safe_path(path, self.workspace_dir)
        except PathSecurityError as e:
            return f"错误: {e}"

        if not root.exists():
            return f"错误: 路径不存在: {path}"

        if not root.is_dir():
            return f"错误: 路径不是目录: {path}"

        # 忽略的目录
        ignored_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv",
                       ".idea", ".vscode", "dist", "build", "*.egg-info"}

        try:
            results = []
            # 使用 glob 进行模式匹配
            for item in root.rglob(pattern):
                # 跳过忽略的目录
                if any(ignored in str(item) for ignored in ignored_dirs):
                    continue

                if item.is_file():
                    rel_path = item.relative_to(root)
                    results.append(str(rel_path))

            if not results:
                return f"未找到匹配模式 '{pattern}' 的文件"

            # 限制结果数量
            max_results = 100
            if len(results) > max_results:
                total_count = len(results)
                results = results[:max_results]
                results.append(f"... (还有 {total_count - max_results} 个文件未显示)")

            return "\n".join(results)

        except PermissionError:
            return f"错误: 权限不足，无法访问目录: {path}"
        except Exception as e:
            return f"错误: 搜索文件失败: {e}"
