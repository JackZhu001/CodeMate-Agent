"""
循环检测器

检测 Agent 是否陷入重复行为模式。
"""

from typing import List
from collections import deque


class LoopDetector:
    """
    循环检测器
    
    通过分析最近的工具调用模式，检测 Agent 是否陷入循环。
    
    检测策略：
    1. 重复调用：最近 5 次调用中只有 1-2 种不同的调用
    2. 交替模式：A-B-A-B-A 的交替调用
    """
    
    def __init__(self, window_size: int = 10):
        """
        Args:
            window_size: 保留的最近调用数量
        """
        self._recent_calls: deque = deque(maxlen=window_size)
        self._window_size = window_size
    
    def record_call(self, tool_name: str, arguments: dict) -> None:
        """
        记录一次工具调用
        
        Args:
            tool_name: 工具名称
            arguments: 调用参数
        """
        # 生成调用签名（用于比较）
        signature = self._get_call_signature(tool_name, arguments)
        self._recent_calls.append(signature)
    
    def is_stuck(self) -> bool:
        """
        检测是否陷入循环
        
        Returns:
            是否陷入循环
        """
        if len(self._recent_calls) < 5:
            return False
        
        recent = list(self._recent_calls)[-5:]
        
        # 检查重复：只有 1-2 种不同的调用
        unique_count = len(set(recent))
        if unique_count <= 2:
            return True
        
        # 检查交替模式：A-B-A-B-A
        if recent[0] == recent[2] == recent[4] and recent[1] == recent[3]:
            return True
        
        return False
    
    def get_loop_info(self) -> str:
        """
        获取循环信息描述
        
        Returns:
            循环模式的描述
        """
        if len(self._recent_calls) < 5:
            return "调用次数不足，无法分析"
        
        recent = list(self._recent_calls)[-5:]
        unique = set(recent)
        
        if len(unique) == 1:
            return f"重复调用同一操作: {recent[0]}"
        elif len(unique) == 2:
            return f"在两种操作间循环: {list(unique)}"
        else:
            return f"最近调用: {recent}"
    
    def _get_call_signature(self, tool_name: str, arguments: dict) -> str:
        """
        生成调用签名
        
        对于某些工具，只使用部分关键参数生成签名，
        避免相似调用被视为不同。
        """
        # 关键参数映射
        key_params = {
            "read_file": ["file_path"],
            "write_file": ["file_path"],
            "list_dir": ["path"],
            "run_shell": ["command"],
            "search_files": ["pattern"],
        }
        
        if tool_name in key_params:
            key_args = {k: arguments.get(k) for k in key_params[tool_name]}
            return f"{tool_name}({key_args})"
        
        return f"{tool_name}({arguments})"
    
    def reset(self) -> None:
        """重置检测器"""
        self._recent_calls.clear()
    
    @property
    def recent_calls(self) -> List[str]:
        """获取最近的调用列表"""
        return list(self._recent_calls)
