"""
参数验证器

检测和修复 LLM 返回的异常参数值。
"""

import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """参数验证错误"""
    pass


class ArgumentValidator:
    """
    通用参数验证器
    
    检测 LLM（特别是 GLM API）返回的异常参数，例如：
    - 类型名称作为值（如 "str", "int"）
    - 空字符串参数
    - 缺失必填参数
    """
    
    # 可疑的参数值列表（类型名称等）
    SUSPICIOUS_VALUES = frozenset({
        "str", "int", "float", "bool", "list", "dict", 
        "None", "null", "undefined", "string", "number",
        "object", "array", "path", "file", "content",
    })
    
    # 需要验证的关键参数
    CRITICAL_PARAMS = frozenset({
        "file_path", "path", "content", "command", "pattern",
        "description", "prompt", "query",
    })
    
    # 工具特定的参数规则
    TOOL_PARAM_RULES = {
        "write_file": {
            "required": ["file_path", "content"],
            "min_length": {"file_path": 3},
            "max_length": {"content": 3000},
        },
        "read_file": {
            "required": ["file_path"],
            "min_length": {"file_path": 1},
        },
        "append_file": {
            "required": ["file_path", "content"],
            "min_length": {"file_path": 3},
            "max_length": {"content": 3000},
        },
        "write_file_chunks": {
            "required": ["file_path", "chunks"],
            "min_length": {"file_path": 3},
        },
        "append_file_chunks": {
            "required": ["file_path", "chunks"],
            "min_length": {"file_path": 3},
        },
        "delete_file": {
            "required": ["file_path"],
            "min_length": {"file_path": 3},
        },
        "edit_file": {
            "required": ["file_path"],
            "min_length": {"file_path": 3},
        },
        "run_shell": {
            "required": ["command"],
            "min_length": {"command": 1},
        },
        "search_code": {
            "required": ["pattern"],
            "min_length": {"pattern": 1},
        },
        "search_files": {
            "required": ["pattern"],
            "min_length": {"pattern": 1},
        },
        "task": {
            "required": ["description", "prompt"],
            "min_length": {"description": 3, "prompt": 5},
        },
    }
    
    @classmethod
    def validate(cls, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """
        验证工具参数
        
        Args:
            tool_name: 工具名称
            arguments: 参数字典
            
        Returns:
            错误信息，如果验证通过则返回 None
        """
        if not arguments:
            # 某些工具可能不需要参数
            rules = cls.TOOL_PARAM_RULES.get(tool_name, {})
            if rules.get("required"):
                # 🆕 检测是否是写文件类工具，给出更有用的建议
                if tool_name in ("write_file", "append_file", "edit_file"):
                    return (
                        f"工具 '{tool_name}' 参数为空（可能是输出被截断）。\n"
                        f"建议：如果要写入大量代码，请分多次写入：\n"
                        f"1. 优先使用 write_file_chunks / append_file_chunks\n"
                        f"2. 或先用 write_file 写首段，再用 append_file 追加\n"
                        f"3. 每次 content 控制在 3000 字符以内"
                    )
                return f"工具 '{tool_name}' 缺少必填参数: {rules['required']}"
            return None
        
        # 分块写工具参数别名兼容
        if tool_name in ("write_file_chunks", "append_file_chunks"):
            if "file_path" not in arguments:
                alias = arguments.get("file") or arguments.get("path")
                if isinstance(alias, str) and alias.strip():
                    arguments["file_path"] = alias
            if "chunks" not in arguments and isinstance(arguments.get("content"), str):
                arguments["chunks"] = [arguments["content"]]

        # 1. 检查可疑值
        for key, value in arguments.items():
            error = cls._check_suspicious_value(key, value)
            if error:
                return error
        
        # 2. 检查工具特定规则
        rules = cls.TOOL_PARAM_RULES.get(tool_name, {})
        
        # 检查必填参数
        for required_param in rules.get("required", []):
            if required_param not in arguments:
                return f"缺少必填参数: '{required_param}'"
            if not arguments[required_param]:
                # 🆕 针对 content 为空给出更有用的建议
                if required_param == "content":
                    return (
                        f"参数 'content' 为空。"
                        f"这通常是因为内容太长被截断了。"
                        f"请使用分块写入：write_file_chunks 或 append_file_chunks（每块 <= 3000 字符）。"
                    )
                return f"参数 '{required_param}' 不能为空"

        if tool_name in ("write_file_chunks", "append_file_chunks") and "chunks" in arguments:
            chunks = arguments.get("chunks")
            if not isinstance(chunks, list) or not chunks:
                return "参数 'chunks' 必须是非空字符串数组"
            if not all(isinstance(c, str) for c in chunks):
                return "参数 'chunks' 必须全部是字符串"
        
        # 检查最小长度
        for param, min_len in rules.get("min_length", {}).items():
            if param in arguments:
                value = arguments[param]
                if isinstance(value, str) and len(value) < min_len:
                    return f"参数 '{param}' 长度不足（最少 {min_len} 字符）"

        # 检查最大长度（避免单次参数过长被模型/网关截断）
        for param, max_len in rules.get("max_length", {}).items():
            if param in arguments:
                value = arguments[param]
                if isinstance(value, str) and len(value) > max_len:
                    return (
                        f"参数 '{param}' 过长（{len(value)} 字符，最大 {max_len}）。"
                        f"请改用 write_file_chunks/append_file_chunks 分块写入。"
                    )
        
        return None
    
    @classmethod
    def _check_suspicious_value(cls, key: str, value: Any) -> Optional[str]:
        """检查单个参数值是否可疑"""
        # 只检查关键参数
        if key not in cls.CRITICAL_PARAMS:
            return None
        
        # 检查类型
        if key in ("file_path", "path", "content", "command", "pattern"):
            if not isinstance(value, str):
                return f"参数 '{key}' 类型错误：期望字符串，实际是 {type(value).__name__}"
        
        # 检查可疑值
        if isinstance(value, str):
            if value in cls.SUSPICIOUS_VALUES:
                return f"参数 '{key}' 的值 '{value}' 无效（不能是类型名称）"
            
            # 检查空字符串（对于必要参数）
            if not value.strip() and key in ("file_path", "path", "command"):
                return f"参数 '{key}' 不能为空字符串"
        
        return None
    
    @classmethod
    def validate_and_fix(
        cls, 
        tool_name: str, 
        arguments: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        验证并尝试修复参数
        
        某些情况下可以自动修复参数，例如：
        - 去除路径中的多余空格
        - 规范化路径分隔符
        
        Args:
            tool_name: 工具名称
            arguments: 参数字典
            
        Returns:
            (修复后的参数, 错误信息或 None)
        """
        if not arguments:
            error = cls.validate(tool_name, arguments)
            return arguments, error
        
        fixed_args = arguments.copy()
        
        # 尝试修复常见问题
        for key, value in list(fixed_args.items()):
            if isinstance(value, str):
                # 去除首尾空格
                fixed_value = value.strip()
                
                # 修复路径中的反斜杠（Windows 风格）
                if key in ("file_path", "path"):
                    fixed_value = fixed_value.replace("\\", "/")
                
                fixed_args[key] = fixed_value
        
        # 验证修复后的参数
        error = cls.validate(tool_name, fixed_args)
        
        return fixed_args, error
    
    @classmethod
    def get_usage_hint(cls, tool_name: str) -> str:
        """
        获取工具的正确用法提示
        
        Args:
            tool_name: 工具名称
            
        Returns:
            用法提示字符串
        """
        hints = {
            "write_file": "write_file(file_path='path/to/file.py', content='文件内容')",
            "read_file": "read_file(file_path='path/to/file.py')",
            "append_file": "append_file(file_path='path/to/file.py', content='追加内容')",
            "write_file_chunks": "write_file_chunks(file_path='path/to/file.py', chunks=['第一段','第二段'])",
            "append_file_chunks": "append_file_chunks(file_path='path/to/file.py', chunks=['续写第一段','续写第二段'])",
            "delete_file": "delete_file(file_path='path/to/file.py')",
            "run_shell": "run_shell(command='ls -la')",
            "search_code": "search_code(pattern='def function_name')",
            "search_files": "search_files(pattern='*.py')",
            "task": "task(description='任务描述', prompt='详细指令', subagent_type='explore')",
        }
        
        return hints.get(tool_name, f"{tool_name}(参数=实际值)")
