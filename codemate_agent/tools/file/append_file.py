"""
追加文件内容工具

向文件末尾追加内容，不覆盖原有内容。
"""

from pathlib import Path
from codemate_agent.tools.base import Tool
from codemate_agent.tools.utils import safe_path, PathSecurityError


class AppendFileTool(Tool):
    """
    追加文件内容工具

    用于向文件末尾添加内容，常用于日志记录、增量更新等场景。
    """

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "append_file"

    @property
    def description(self) -> str:
        return """向文件末尾追加内容，不会覆盖原有内容。

参数:
- file_path: 文件路径
- content: 要追加的内容

注意: 如果文件不存在，会创建新文件。

适用场景:
- 日志记录
- 增量添加配置
- 逐步构建文件"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径（相对或绝对路径）"
                },
                "content": {
                    "type": "string",
                    "description": "要追加到文件末尾的内容"
                }
            },
            "required": ["file_path", "content"]
        }

    def run(self, file_path: str, content: str, **kwargs) -> str:
        """
        执行文件追加

        Args:
            file_path: 文件路径
            content: 要追加的内容

        Returns:
            str: 操作结果
        """
        try:
            # 使用安全路径检查
            path = safe_path(file_path, self.workspace_dir)
        except PathSecurityError as e:
            return f"错误: {e}"

        try:
            # 如果文件不存在，创建父目录
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

            # 追加写入
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)

            # 如果内容没有换行符结尾，添加一个
            if content and not content.endswith("\n"):
                with open(path, "rb") as f:
                    f.seek(0, 2)
                    if f.read(1) != b"\n":
                        with open(path, "a", encoding="utf-8") as f:
                            f.write("\n")

            return f"已成功追加内容到文件: {file_path}"

        except PermissionError:
            return f"错误: 权限不足，无法写入文件: {file_path}"
        except Exception as e:
            return f"错误: 追加文件内容失败: {e}"
