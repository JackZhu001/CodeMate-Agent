"""
智能工具输出截断器

核心策略：
1. 首尾保留 - 开头和结尾通常包含重要信息
2. 中间摘要 - 对省略部分生成统计摘要
3. 工具定制 - 不同工具采用不同截断策略
4. 结构感知 - 识别代码、目录等结构，智能保留

对比暴力截断：
- 暴力截断: 342KB → 25KB，丢失 92%，只保留前 N 行
- 智能截断: 342KB → 25KB，保留首尾 + 中间摘要，信息保留率 40%+
"""

from typing import Optional
from dataclasses import dataclass
from enum import Enum
import re
from collections import Counter


class TruncationStrategy(Enum):
    """截断策略"""
    HEAD_TAIL = "head_tail"      # 首尾保留（默认）
    HEAD_ONLY = "head_only"      # 只保留开头
    TAIL_ONLY = "tail_only"      # 只保留结尾（适合日志）
    SAMPLE = "sample"            # 采样保留（适合列表）
    STRUCTURE = "structure"      # 结构感知（适合目录树）


@dataclass
class TruncationConfig:
    """截断配置"""
    strategy: TruncationStrategy = TruncationStrategy.HEAD_TAIL
    max_chars: int = 25000           # 最大字符数
    head_ratio: float = 0.4          # 头部保留比例
    tail_ratio: float = 0.2          # 尾部保留比例
    sample_interval: int = 10        # 采样间隔
    generate_summary: bool = True    # 是否生成统计摘要


# 工具专属配置
TOOL_CONFIGS: dict[str, TruncationConfig] = {
    # 目录列表：结构感知，保留目录层级
    "list_dir": TruncationConfig(
        strategy=TruncationStrategy.STRUCTURE,
        max_chars=20000,
        head_ratio=0.3,
        tail_ratio=0.1,
    ),
    # 文件搜索：采样保留，显示代表性结果
    "search_files": TruncationConfig(
        strategy=TruncationStrategy.SAMPLE,
        max_chars=15000,
        sample_interval=5,
    ),
    # 代码搜索：首尾保留
    "search_code": TruncationConfig(
        strategy=TruncationStrategy.HEAD_TAIL,
        max_chars=20000,
        head_ratio=0.5,
        tail_ratio=0.2,
    ),
    # Shell 命令：尾部更重要（错误信息在最后）
    "run_shell": TruncationConfig(
        strategy=TruncationStrategy.TAIL_ONLY,
        max_chars=20000,
    ),
    # 读取文件：首尾保留
    "read_file": TruncationConfig(
        strategy=TruncationStrategy.HEAD_TAIL,
        max_chars=30000,
        head_ratio=0.5,
        tail_ratio=0.2,
    ),
}

# 默认配置
DEFAULT_CONFIG = TruncationConfig()


class SmartTruncator:
    """
    智能截断器
    
    特点：
    1. 首尾保留 - 不丢失开头和结尾的关键信息
    2. 中间摘要 - 对省略部分生成有意义的统计
    3. 工具定制 - 根据工具类型选择最佳策略
    4. 结构感知 - 识别目录树、代码块等结构
    """
    
    def __init__(self, default_max_chars: int = 25000):
        self.default_max_chars = default_max_chars
    
    def truncate(self, content: str, tool_name: str = "") -> str:
        """
        智能截断工具输出
        
        Args:
            content: 工具输出内容
            tool_name: 工具名称
            
        Returns:
            截断后的内容（保留关键信息 + 中间摘要）
        """
        if not content:
            return content
        
        # 获取工具配置
        config = TOOL_CONFIGS.get(tool_name, DEFAULT_CONFIG)
        
        # 检查是否需要截断
        if len(content) <= config.max_chars:
            return content
        
        # 根据策略截断
        if config.strategy == TruncationStrategy.HEAD_TAIL:
            return self._truncate_head_tail(content, config)
        elif config.strategy == TruncationStrategy.HEAD_ONLY:
            return self._truncate_head_only(content, config)
        elif config.strategy == TruncationStrategy.TAIL_ONLY:
            return self._truncate_tail_only(content, config)
        elif config.strategy == TruncationStrategy.SAMPLE:
            return self._truncate_sample(content, config)
        elif config.strategy == TruncationStrategy.STRUCTURE:
            return self._truncate_structure(content, config)
        else:
            return self._truncate_head_tail(content, config)
    
    def _truncate_head_tail(self, content: str, config: TruncationConfig) -> str:
        """首尾保留策略"""
        head_size = int(config.max_chars * config.head_ratio)
        tail_size = int(config.max_chars * config.tail_ratio)
        summary_budget = config.max_chars - head_size - tail_size
        
        head = content[:head_size]
        tail = content[-tail_size:] if tail_size > 0 else ""
        middle = content[head_size:-tail_size] if tail_size > 0 else content[head_size:]
        
        # 生成中间部分摘要
        if config.generate_summary:
            summary = self._generate_summary(middle, summary_budget)
        else:
            summary = f"\n... [省略 {len(middle):,} 字符] ...\n"
        
        return f"{head}\n{summary}\n{tail}"
    
    def _truncate_head_only(self, content: str, config: TruncationConfig) -> str:
        """只保留开头"""
        head = content[:config.max_chars - 200]
        omitted = len(content) - len(head)
        return f"{head}\n\n⚠️ [输出过长，省略后续 {omitted:,} 字符。源文件完整无损]"
    
    def _truncate_tail_only(self, content: str, config: TruncationConfig) -> str:
        """只保留结尾（适合日志、错误输出）"""
        tail = content[-(config.max_chars - 200):]
        omitted = len(content) - len(tail)
        return f"⚠️ [输出过长，省略前面 {omitted:,} 字符。源文件完整无损]\n\n{tail}"
    
    def _truncate_sample(self, content: str, config: TruncationConfig) -> str:
        """采样保留（适合大量重复结构）"""
        lines = content.split("\n")
        
        if len(lines) <= 100:
            return content
        
        # 采样策略：首 20 行 + 每隔 N 行采样 + 尾 20 行
        head_lines = lines[:20]
        tail_lines = lines[-20:]
        middle_lines = lines[20:-20]
        
        sampled = []
        for i, line in enumerate(middle_lines):
            if i % config.sample_interval == 0:
                sampled.append(line)
        
        total_lines = len(lines)
        sampled_count = len(head_lines) + len(sampled) + len(tail_lines)
        
        result_lines = (
            head_lines + 
            [f"\n... [采样显示，共 {total_lines} 行，显示 {sampled_count} 行] ...\n"] +
            sampled +
            ["\n... [尾部] ...\n"] +
            tail_lines
        )
        
        result = "\n".join(result_lines)
        
        # 再次检查长度
        if len(result) > config.max_chars:
            return self._truncate_head_tail(result, config)
        
        return result
    
    def _truncate_structure(self, content: str, config: TruncationConfig) -> str:
        """结构感知截断（适合目录树）"""
        lines = content.split("\n")
        
        # 识别目录结构的深度
        def get_depth(line: str) -> int:
            # 通过缩进或路径深度判断
            indent = len(line) - len(line.lstrip())
            path_depth = line.count("/")
            return max(indent // 2, path_depth)
        
        # 优先保留浅层目录（更重要）
        shallow_lines = []  # depth <= 2
        deep_lines = []     # depth > 2
        
        for line in lines:
            if get_depth(line) <= 2:
                shallow_lines.append(line)
            else:
                deep_lines.append(line)
        
        # 统计深层目录
        deep_summary = self._summarize_paths(deep_lines) if deep_lines else ""
        
        # 拼接结果
        result = "\n".join(shallow_lines)
        if deep_lines:
            result += f"\n\n--- 深层目录摘要 ({len(deep_lines)} 项) ---\n{deep_summary}"
        
        # 最终长度检查
        if len(result) > config.max_chars:
            return self._truncate_head_tail(result, config)
        
        return result
    
    def _generate_summary(self, content: str, max_length: int = 2000) -> str:
        """生成中间部分的统计摘要"""
        if not content:
            return "[空内容]"
        
        lines = content.split("\n")
        
        # 基础统计
        stats = {
            "字符数": f"{len(content):,}",
            "行数": f"{len(lines):,}",
        }
        
        # 识别文件类型
        file_extensions = Counter()
        dir_count = 0
        
        for line in lines:
            # 匹配文件扩展名
            ext_match = re.search(r'\.([a-zA-Z0-9]{1,10})(?:\s|$|:)', line)
            if ext_match:
                file_extensions[f".{ext_match.group(1)}"] += 1
            
            # 匹配目录
            if "/" in line or "\\" in line:
                dir_count += 1
        
        if file_extensions:
            top_5 = file_extensions.most_common(5)
            stats["文件类型"] = ", ".join(f"{ext}({cnt})" for ext, cnt in top_5)
        
        if dir_count > 0:
            stats["路径数"] = str(dir_count)
        
        # 识别代码模式
        code_patterns = {
            "函数定义": r'\bdef\s+\w+|function\s+\w+',
            "类定义": r'\bclass\s+\w+',
            "导入语句": r'^import\s+|^from\s+\w+\s+import',
            "TODO/FIXME": r'TODO|FIXME|XXX|HACK',
        }
        
        for name, pattern in code_patterns.items():
            matches = len(re.findall(pattern, content, re.MULTILINE))
            if matches > 0:
                stats[name] = str(matches)
        
        # 格式化摘要
        summary_lines = [
            "",
            "╔══════════════════════════════════════════════════════════╗",
            "║  ⚠️ 以下内容因过长被省略显示（源文件完整无损）           ║",
            "║  📊 省略部分统计：                                       ║",
            "╠══════════════════════════════════════════════════════════╣",
        ]
        
        for key, value in stats.items():
            summary_lines.append(f"║  {key}: {value}")
        
        summary_lines.extend([
            "╠══════════════════════════════════════════════════════════╣",
            "║  💡 如需查看完整内容，请指定具体行号范围                 ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
        ])
        
        summary = "\n".join(summary_lines)
        
        # 确保不超过预算
        if len(summary) > max_length:
            summary = summary[:max_length - 50] + "\n... [摘要已截断]"
        
        return summary
    
    def _summarize_paths(self, lines: list[str]) -> str:
        """对路径列表生成摘要"""
        if not lines:
            return ""
        
        # 提取顶级目录
        top_dirs = Counter()
        for line in lines:
            parts = line.strip().split("/")
            if len(parts) > 1:
                top_dirs[parts[0]] += 1
        
        if not top_dirs:
            return f"共 {len(lines)} 个深层项目"
        
        summary_parts = []
        for dir_name, count in top_dirs.most_common(10):
            summary_parts.append(f"  {dir_name}/: {count} 项")
        
        if len(top_dirs) > 10:
            summary_parts.append(f"  ... 还有 {len(top_dirs) - 10} 个目录")
        
        return "\n".join(summary_parts)
    
    def should_skip_truncation(self, tool_name: str) -> bool:
        """判断是否跳过截断"""
        no_truncate_tools = {
            "ask_user",
            "confirm", 
            "get_input",
            "todo_read",
            "todo_write",
        }
        return tool_name in no_truncate_tools


# 兼容旧接口
class ObservationTruncator(SmartTruncator):
    """兼容旧版 API"""
    
    DEFAULT_MAX_LINES = 2000
    DEFAULT_MAX_BYTES = 51200
    
    def __init__(
        self,
        max_lines: int = DEFAULT_MAX_LINES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ):
        # 转换为字符限制（估算：1行 ≈ 80字符）
        max_chars = min(max_lines * 80, max_bytes)
        super().__init__(default_max_chars=max_chars)


# 全局默认截断器
_default_truncator: Optional[SmartTruncator] = None


def get_truncator() -> SmartTruncator:
    """获取默认截断器"""
    global _default_truncator
    if _default_truncator is None:
        _default_truncator = SmartTruncator()
    return _default_truncator
