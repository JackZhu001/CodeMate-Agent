"""
写入文件内容工具
"""

from pathlib import Path
from codemate_agent.tools.base import Tool
from codemate_agent.tools.utils import safe_path, PathSecurityError


class WriteFileTool(Tool):
    """写入文件内容工具（谨慎使用）"""

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return """向文件写入内容。注意：此工具会覆盖现有文件内容，请谨慎使用。

参数:
- file_path (必需): 文件路径，如 "src/main.py" 或 "codemate_agent/agent/agent.py"
- content (必需): 要写入的完整文件内容（字符串格式）

示例: write_file(file_path="myfile.py", content="print('hello')")

输出: 操作结果"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要写入的文件路径"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容"
                }
            },
            "required": ["file_path", "content"]
        }

    def run(self, file_path: str, content: str, **kwargs) -> str:
        try:
            # 使用安全路径检查
            path = safe_path(file_path, self.workspace_dir)
        except PathSecurityError as e:
            return f"错误: {e}"

        try:
            # 创建父目录
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return f"已成功写入文件: {file_path}"

        except PermissionError:
            return f"错误: 权限不足，无法写入文件: {file_path}"
        except Exception as e:
            return f"错误: 写入文件失败: {e}"
