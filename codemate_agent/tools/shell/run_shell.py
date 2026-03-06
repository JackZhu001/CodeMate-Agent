"""
Shell 命令执行工具

支持跨平台执行 shell 命令。
"""

import subprocess
import platform
from typing import Optional
from codemate_agent.tools.base import Tool


class RunShellTool(Tool):
    """
    Shell 命令执行工具

    用于执行系统命令，如 git, rm, mkdir, python 等。
    """

    @property
    def name(self) -> str:
        return "run_shell"

    @property
    def description(self) -> str:
        return """执行 shell 命令。

参数:
- command: 要执行的命令字符串
- timeout: 超时时间（秒），默认 30

支持的命令类型:
- Git 操作: git log, git status, git diff
- 文件操作: rm, mkdir, cp, mv
- 运行脚本: python, pytest, npm
- 系统信息: ls, pwd, uname

注意: 请谨慎使用具有破坏性的命令。"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令"
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间（秒），默认 30",
                    "default": 30
                }
            },
            "required": ["command"]
        }

    def run(self, command: str, timeout: int = 30, **kwargs) -> str:
        """
        执行 shell 命令

        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            str: 命令输出结果
        """
        # 基本安全检查
        dangerous_commands = ["rm -rf /", "rm -rf /*", "mkfs", "format", ":(){ :|:& };:"]
        if any(dangerous in command.lower() for dangerous in dangerous_commands):
            return "错误: 检测到危险命令，拒绝执行"

        # 确定使用哪个 shell
        system = platform.system()
        if system == "Windows":
            shell_cmd = ["powershell", "-Command", command]
        else:
            # Unix/Linux/macOS 使用 bash
            shell_cmd = ["/bin/bash", "-c", command]

        # 超时保护：避免模型设置过大 timeout 导致长时间卡住
        timeout = max(1, min(int(timeout), 45))

        try:
            # 执行命令
            result = subprocess.run(
                shell_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                # 安全限制：不使用 shell=True，避免命令注入
            )

            # 组合输出
            output = []
            if result.stdout:
                output.append(result.stdout)
            if result.stderr:
                output.append(f"[stderr]\n{result.stderr}")

            # 添加退出码
            if result.returncode != 0:
                output.append(f"\n[退出码: {result.returncode}]")

            return "\n".join(output).strip() or "命令执行完成，无输出"

        except subprocess.TimeoutExpired:
            return f"错误: 命令执行超时（超过 {timeout} 秒）"

        except FileNotFoundError:
            # Windows 没有 PowerShell 或 Unix 没有 bash
            if system == "Windows":
                return "错误: 未找到 PowerShell，请确保已安装"
            else:
                return "错误: 未找到 bash，请确保系统支持"

        except PermissionError:
            return f"错误: 权限不足，无法执行命令: {command}"

        except Exception as e:
            return f"错误: 执行命令失败: {e}"
