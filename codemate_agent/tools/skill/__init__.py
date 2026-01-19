"""
Skill 工具 - 渐进式加载 Skill 内容

对标 Claude Code 官方实现：
- Layer 1 (索引): 启动时只加载 name + description
- Layer 2 (SKILL.md): 通过此工具按需加载完整内容
- Layer 3 (references): 通过此工具按需加载参考文档
"""

from .skill_tool import SkillTool

__all__ = ["SkillTool"]
