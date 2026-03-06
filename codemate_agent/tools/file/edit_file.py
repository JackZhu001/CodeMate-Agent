"""
编辑文件工具

使用统一差异格式（diff）精确修改文件的指定部分。
"""

from pathlib import Path
from typing import Optional
from codemate_agent.tools.base import Tool
from codemate_agent.tools.utils import safe_path, PathSecurityError


class EditFileTool(Tool):
    """
    编辑文件工具

    使用 diff 格式精确修改文件，而不是覆盖整个文件。
    适用于只修改文件的一小部分内容。
    """

    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return """使用 diff 格式精确修改文件的部分内容。

参数:
- file_path: 要修改的文件路径
- diff: 统一差异格式的补丁

diff 格式说明:
@@ -行数,行数 +行数,行数 @@
要删除的行（以 - 开头）
要添加的行（以 + 开头）

示例:
删除一行，添加一行:
@@ -1,3 +1,3 @@
-old line
+new line

示例2: 只修改某一行:
@@ -5,1 +5,1 @@
-def hello():
+def hello_world():

注意: 行号从 1 开始，必须是准确的行号"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要修改的文件路径"
                },
                "diff": {
                    "type": "string",
                    "description": "统一差异格式的补丁内容"
                }
            },
            "required": ["file_path", "diff"]
        }

    def run(self, file_path: str, diff: str, **kwargs) -> str:
        """
        执行文件编辑

        Args:
            file_path: 文件路径
            diff: diff 补丁内容

        Returns:
            str: 操作结果
        """
        try:
            # 使用安全路径检查
            path = safe_path(file_path, self.workspace_dir)
        except PathSecurityError as e:
            return f"错误: {e}"

        # 检查文件是否存在
        if not path.exists():
            return f"错误: 文件不存在: {file_path}"

        if not path.is_file():
            return f"错误: 路径不是文件: {file_path}"

        try:
            # 读取原始内容
            with open(path, "r", encoding="utf-8") as f:
                original_lines = f.readlines()

            # 应用 diff
            result_lines = self._apply_patch(original_lines, diff)

            # 写回文件
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(result_lines)

            # 计算改动
            changes = len(original_lines) - len(result_lines)
            change_desc = f"减少了 {-changes} 行" if changes > 0 else f"增加了 {abs(changes)} 行" if changes < 0 else "行数相同"

            return f"✓ 已修改文件: {file_path} ({change_desc})"

        except ValueError as e:
            return f"错误: diff 格式无效 - {e}"
        except Exception as e:
            return f"错误: 修改文件失败: {e}"

    def _apply_patch(self, original_lines: list[str], diff: str) -> list[str]:
        """
        应用 diff 补丁到原始内容

        Args:
            original_lines: 原始文件行列表
            diff: diff 补丁内容

        Returns:
            list[str]: 修改后的行列表
        """
        result = original_lines.copy()
        offset = 0  # 行号偏移量（因为修改会影响后续行号）

        # 解析 diff
        chunks = self._parse_diff(diff)

        for chunk in chunks:
            # 计算实际行号（考虑之前的偏移）
            start_line = chunk["old_start"] - 1 + offset

            # 验证行号范围
            if start_line < 0 or start_line > len(result):
                raise ValueError(f"行号 {chunk['old_start']} 超出文件范围")

            if start_line + chunk["old_len"] > len(result):
                raise ValueError(f"删除范围超出文件实际行数")

            # 检查上下文是否匹配
            actual_context = result[start_line:start_line + chunk["old_len"]]
            if chunk.get("context") and actual_context != chunk["context"]:
                raise ValueError("文件内容已更改，无法应用补丁（上下文不匹配）")

            # 应用修改：删除旧行，添加新行
            result[start_line:start_line + chunk["old_len"]] = chunk["new_lines"]

            # 更新偏移量
            offset += len(chunk["new_lines"]) - chunk["old_len"]

        return result

    def _parse_diff(self, diff: str) -> list[dict]:
        """
        解析 diff 内容

        支持 unified diff 格式：
        @@ -old_start,old_len +new_start,new_len @@
        content

        Returns:
            list[dict]: 解析后的块列表
        """
        chunks = []
        lines = diff.strip().split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            # 查找块头
            if line.startswith('@@'):
                # 解析 @@ -old_start,old_len +new_start,new_len @@
                try:
                    header = line.strip('@').strip()
                    old_part, new_part = header.split(' ')
                    old_start, old_len = map(int, old_part[1:].split(','))
                    new_start, new_len = map(int, new_part[1:].split(','))
                except (ValueError, IndexError):
                    raise ValueError(f"无效的 diff 头: {line}")

                i += 1
                old_lines = []
                new_lines = []

                # 解析块内容
                while i < len(lines):
                    content_line = lines[i]
                    if content_line.startswith('@@'):
                        break  # 下一个块

                    if content_line.startswith(' '):
                        # 上下文行（两边都有）
                        line_content = content_line[1:]
                        old_lines.append(line_content + '\n')
                        new_lines.append(line_content + '\n')
                    elif content_line.startswith('-'):
                        # 删除的行（只有旧版本有）
                        old_lines.append(content_line[1:] + '\n')
                    elif content_line.startswith('+'):
                        # 添加的行（只有新版本有）
                        new_lines.append(content_line[1:] + '\n')
                    elif content_line == '' or content_line.startswith('\\'):
                        # 空行或 No newline at end of line
                        pass
                    else:
                        # 不以 +/- 开头的行，当作上下文
                        line_content = content_line
                        old_lines.append(line_content + '\n')
                        new_lines.append(line_content + '\n')

                    i += 1

                chunks.append({
                    "old_start": old_start,
                    "old_len": old_len,
                    "new_start": new_start,
                    "new_len": new_len,
                    "old_lines": old_lines,
                    "new_lines": new_lines,
                    "context": old_lines if old_len > 0 else None
                })
            else:
                i += 1

        return chunks
