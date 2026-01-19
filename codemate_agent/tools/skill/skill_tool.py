"""
Skill 工具 - 让 LLM 按需加载 Skill 完整内容

渐进式披露策略：
1. 系统提示词只包含 skill 索引（name + description）
2. LLM 决定使用某个 skill 时，调用此工具加载完整内容
3. 执行过程中，可通过 load_reference 加载参考文档
"""

from typing import Any, Dict, Optional
from pathlib import Path

from codemate_agent.tools.base import Tool
from codemate_agent.skill import SkillManager


class SkillTool(Tool):
    """
    Skill 加载工具
    
    支持两种操作：
    - load: 加载 skill 的完整 SKILL.md 内容
    - load_reference: 加载 skill 的参考文档
    - list_resources: 列出 skill 的可用资源（references, scripts）
    """
    
    def __init__(self, skill_manager: SkillManager = None):
        """初始化 Skill 工具"""
        self._skill_manager = skill_manager or SkillManager()
    
    @property
    def name(self) -> str:
        return "skill"
    
    @property
    def description(self) -> str:
        return """加载 Skill 的完整内容或参考文档。

操作类型：
- load: 加载 skill 的完整指令（SKILL.md）
- load_reference: 加载 skill 的参考文档
- list_resources: 列出 skill 的可用资源

参数：
- action: 操作类型 (load | load_reference | list_resources)
- skill_name: skill 名称（必填）
- reference_name: 参考文档名称（仅 load_reference 时需要）

使用流程：
1. 查看系统提示词中的 skill 索引，找到匹配的 skill
2. 调用 skill(action="load", skill_name="xxx") 加载完整内容
3. 按照 skill 内容执行任务
4. 如需更多信息，调用 load_reference 加载参考文档"""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["load", "load_reference", "list_resources"],
                    "description": "操作类型"
                },
                "skill_name": {
                    "type": "string",
                    "description": "skill 名称"
                },
                "reference_name": {
                    "type": "string",
                    "description": "参考文档名称（仅 load_reference 时需要）"
                }
            },
            "required": ["action", "skill_name"]
        }
    
    def run(self, **kwargs) -> str:
        """执行 skill 操作"""
        action = kwargs.get("action", "load")
        skill_name = kwargs.get("skill_name", "")
        reference_name = kwargs.get("reference_name", "")
        
        if not skill_name:
            return self._error("缺少必填参数: skill_name")
        
        # 检查 skill 是否存在
        if not self._skill_manager.skill_exists(skill_name):
            available = self._skill_manager.get_available_skills()
            return self._error(
                f"Skill '{skill_name}' 不存在。\n"
                f"可用的 Skills: {', '.join(available) if available else '无'}"
            )
        
        if action == "load":
            return self._load_skill(skill_name)
        elif action == "load_reference":
            return self._load_reference(skill_name, reference_name)
        elif action == "list_resources":
            return self._list_resources(skill_name)
        else:
            return self._error(f"未知操作: {action}")
    
    def _load_skill(self, skill_name: str) -> str:
        """加载 skill 的完整内容"""
        skill = self._skill_manager.load(skill_name)
        if not skill:
            return self._error(f"无法加载 Skill: {skill_name}")
        
        # 构建响应
        lines = [
            f"# Skill: {skill_name}",
            "",
            f"**描述**: {skill.description[:200]}..." if len(skill.description) > 200 else f"**描述**: {skill.description}",
            "",
            "---",
            "",
            skill.content,
        ]
        
        # 添加可用资源提示
        resources = self._skill_manager.get_skill_resources(skill_name)
        if resources["references"] or resources["scripts"]:
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("## 可用资源")
            if resources["references"]:
                lines.append(f"- **References**: {', '.join(resources['references'])}")
                lines.append("  (使用 `skill(action='load_reference', skill_name='...', reference_name='...')` 加载)")
            if resources["scripts"]:
                lines.append(f"- **Scripts**: {', '.join(resources['scripts'])}")
                lines.append("  (使用 `run_shell` 执行脚本)")
        
        return "\n".join(lines)
    
    def _load_reference(self, skill_name: str, reference_name: str) -> str:
        """加载 skill 的参考文档"""
        if not reference_name:
            return self._error("缺少参数: reference_name")
        
        content = self._skill_manager.load_reference(skill_name, reference_name)
        if not content:
            # 列出可用的 references
            resources = self._skill_manager.get_skill_resources(skill_name)
            return self._error(
                f"Reference '{reference_name}' 不存在。\n"
                f"可用的 References: {', '.join(resources['references']) if resources['references'] else '无'}"
            )
        
        return f"# Reference: {reference_name}\n\n{content}"
    
    def _list_resources(self, skill_name: str) -> str:
        """列出 skill 的可用资源"""
        resources = self._skill_manager.get_skill_resources(skill_name)
        
        lines = [
            f"# Skill '{skill_name}' 的可用资源",
            "",
        ]
        
        if resources["references"]:
            lines.append("## References（参考文档）")
            for ref in resources["references"]:
                lines.append(f"- {ref}")
            lines.append("")
        else:
            lines.append("## References: 无")
            lines.append("")
        
        if resources["scripts"]:
            lines.append("## Scripts（可执行脚本）")
            for script in resources["scripts"]:
                lines.append(f"- {script}")
            lines.append("")
            lines.append("提示: 使用 `run_shell` 执行脚本，脚本输出不占用上下文")
        else:
            lines.append("## Scripts: 无")
        
        return "\n".join(lines)
    
    def _error(self, message: str) -> str:
        """返回错误信息"""
        return f"❌ Skill 工具错误: {message}"
