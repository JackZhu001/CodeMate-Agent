"""
路径安全工具

提供安全的路径处理函数，防止路径遍历攻击。
"""

from pathlib import Path
from typing import Union


class PathSecurityError(Exception):
    """路径安全检查失败异常"""
    pass


def safe_path(path: Union[str, Path], workspace: Path = None) -> Path:
    """
    安全地解析路径，防止路径遍历攻击

    Args:
        path: 输入的路径（相对或绝对）
        workspace: 工作目录，解析后的路径必须在此目录内

    Returns:
        解析后的绝对路径

    Raises:
        PathSecurityError: 如果路径超出工作目录

    Example:
        >>> safe_path("src/main.py", Path.cwd())
        PosixPath('/Users/xxx/project/src/main.py')

        >>> safe_path("../../../etc/passwd", Path.cwd())
        PathSecurityError: 路径超出工作目录
    """
    if workspace is None:
        workspace = Path.cwd()

    workspace = workspace.resolve()
    path = Path(path)

    # 如果是绝对路径，直接解析
    if path.is_absolute():
        resolved = path.resolve()
    else:
        # 相对路径基于 workspace 解析
        resolved = (workspace / path).resolve()

    # 检查是否在工作目录内
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise PathSecurityError(
            f"路径 '{path}' 超出工作目录 '{workspace}'。"
            f"解析后的路径为 '{resolved}'"
        )

    return resolved


def validate_path_in_workspace(path: Union[str, Path], workspace: Path = None) -> bool:
    """
    验证路径是否在工作目录内

    Args:
        path: 输入的路径
        workspace: 工作目录

    Returns:
        True 如果路径在工作目录内，否则 False
    """
    try:
        safe_path(path, workspace)
        return True
    except PathSecurityError:
        return False


def is_dangerous_path(path: Union[str, Path]) -> bool:
    """
    检查路径是否危险（包含可疑的路径组件）

    Args:
        path: 输入的路径

    Returns:
        True 如果路径包含危险组件
    """
    path_str = str(path)
    dangerous_patterns = [
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
        "~/.ssh",
        "~/.aws",
        "~/.gitconfig",
    ]
    return any(pattern in path_str for pattern in dangerous_patterns)
