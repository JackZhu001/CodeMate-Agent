"""
分块写入文件工具

用于写入大内容，避免单次 tool 参数过长被截断。
"""

from pathlib import Path
from typing import List

from codemate_agent.tools.base import Tool
from codemate_agent.tools.utils import safe_path, PathSecurityError


class WriteFileChunksTool(Tool):
    """分块写入文件（覆盖模式）"""

    MAX_CHUNK_CHARS = 3000

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "write_file_chunks"

    @property
    def description(self) -> str:
        return (
            "将大文件内容按 chunks 分块写入（覆盖写）。"
            "适合 HTML/CSS/长代码等场景，降低参数截断风险。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "目标文件路径"},
                "chunks": {
                    "type": "array",
                    "description": f"内容分块数组，每块建议 <= {self.MAX_CHUNK_CHARS} 字符",
                    "items": {"type": "string"},
                },
            },
            "required": ["file_path", "chunks"],
        }

    def run(self, file_path: str = "", chunks: List[str] = None, **kwargs) -> str:
        # 兼容常见别名，避免模型参数名轻微偏差直接抛异常
        file_path = file_path or kwargs.get("file_path") or kwargs.get("file") or kwargs.get("path", "")
        if chunks is None:
            chunks = kwargs.get("chunks")
        if chunks is None and isinstance(kwargs.get("content"), str):
            chunks = [kwargs.get("content")]

        try:
            path = safe_path(file_path, self.workspace_dir)
        except PathSecurityError as e:
            return f"错误: {e}"

        if not isinstance(chunks, list) or not chunks:
            return "错误: chunks 不能为空，且必须是字符串数组"
        if not all(isinstance(c, str) for c in chunks):
            return "错误: chunks 必须全部是字符串"
        if any(len(c) > self.MAX_CHUNK_CHARS for c in chunks):
            return f"错误: 单个 chunk 超过限制（{self.MAX_CHUNK_CHARS} 字符），请继续拆分"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = "".join(chunks)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"已成功分块写入文件: {file_path}（{len(chunks)} 块，{len(content)} 字符）"
        except PermissionError:
            return f"错误: 权限不足，无法写入文件: {file_path}"
        except Exception as e:
            return f"错误: 分块写入文件失败: {e}"
