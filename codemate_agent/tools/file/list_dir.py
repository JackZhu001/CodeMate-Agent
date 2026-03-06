"""
列出目录内容工具
"""

from pathlib import Path
from codemate_agent.tools.base import Tool
from codemate_agent.tools.utils import safe_path, PathSecurityError


class ListDirectoryTool(Tool):
    """列出目录内容工具"""

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return """列出目录中的文件和子目录。

参数:
- path: 目录路径（默认当前目录）
- recursive: 是否递归列出子目录（默认 False）

输出: 目录内容列表，包含文件/目录名称和类型"""

    def run(self, path: str = ".", recursive: bool = False, **kwargs) -> str:
        try:
            # 使用安全路径检查
            root = safe_path(path, self.workspace_dir)
        except PathSecurityError as e:
            return f"错误: {e}"

        if not root.exists():
            return f"错误: 目录不存在: {path}"

        if not root.is_dir():
            return f"错误: 路径不是目录: {path}"

        items = []
        ignored_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}

        try:
            if recursive:
                for item in root.rglob("*"):
                    if any(ignored in item.parts for ignored in ignored_dirs):
                        continue
                    if item.is_dir():
                        continue
                    rel_path = item.relative_to(root)
                    items.append(f"[FILE] {rel_path}")
            else:
                for item in root.iterdir():
                    if item.name in ignored_dirs:
                        continue
                    item_type = "[DIR]" if item.is_dir() else "[FILE]"
                    items.append(f"{item_type} {item.name}")

            if not items:
                return "目录为空"

            return "\n".join(items)

        except PermissionError:
            return f"错误: 权限不足，无法访问目录: {path}"
        except Exception as e:
            return f"错误: 列出目录失败: {e}"
