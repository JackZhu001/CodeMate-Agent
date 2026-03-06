"""
读取文件内容工具
"""

from pathlib import Path
from codemate_agent.tools.base import Tool
from codemate_agent.tools.utils import safe_path, PathSecurityError


class ReadFileTool(Tool):
    """读取文件内容工具"""

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取文件内容并返回文本"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径（相对或绝对路径）"
                }
            },
            "required": ["file_path"]
        }

    def run(self, file_path: str, **kwargs) -> str:
        try:
            # 使用安全路径检查
            path = safe_path(file_path, self.workspace_dir)
        except PathSecurityError as e:
            return f"错误: {e}"

        if not path.exists():
            return f"错误: 文件不存在: {file_path}"

        if not path.is_file():
            return f"错误: 路径不是文件: {file_path}"

        # 限制读取大小，防止过大
        max_size = 100_000  # 100KB
        file_size = path.stat().st_size

        try:
            if file_size > max_size:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read(max_size)
                    remaining = file_size - max_size
                    return f"{content}\n\n... (文件过大，剩余 {remaining} 字节未显示)"

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        except PermissionError:
            return f"错误: 权限不足，无法读取文件: {file_path}"
        except Exception as e:
            return f"错误: 读取文件失败: {e}"
