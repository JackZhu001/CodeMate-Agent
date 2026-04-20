"""
Skill 自动沉淀

V1 只做“生成可审核草稿，不自动发布”：
- 记录成功轨迹
- 检测重复成功模式
- 生成 SKILL.md / metadata.json / examples.json 草稿
- 提供静态校验和显式发布接口
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from codemate_agent.tools.registry import ToolRegistry


TASK_TYPE_PATTERN = re.compile(r"\[\s*task_type\s*:\s*([A-Za-z0-9_.-]+)\s*\]", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"\b(?:sk|rk|pk|token|api[_-]?key)[-_A-Za-z0-9]{8,}\b", re.IGNORECASE)
UUID_PATTERN = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE)
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:(?:/Users|/home|/tmp|/var|/private|/etc|/opt)/[^\s`]+)|(?:[A-Za-z]:\\[^\s`]+)"
)


@dataclass
class SkillCaptureRecord:
    """单次成功执行的结构化记录。"""

    run_id: str
    task_type: str
    goal: str
    inputs: dict[str, Any]
    steps: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    artifacts: list[str]
    outputs: dict[str, Any]
    success: bool
    manual_intervention: bool
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillCaptureRecord":
        return cls(**data)


@dataclass
class SkillDraftMetadata:
    """Skill 草稿元数据。"""

    name: str
    task_type: str
    source_runs: list[str]
    confidence: float
    created_at: str
    status: str
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillDraftMetadata":
        return cls(
            name=data["name"],
            task_type=data["task_type"],
            source_runs=list(data.get("source_runs", [])),
            confidence=float(data.get("confidence", 0.0)),
            created_at=data["created_at"],
            status=data.get("status", "draft"),
            validation_errors=list(data.get("validation_errors", [])),
        )


@dataclass
class SkillDraftValidationResult:
    valid: bool
    errors: list[str]


@dataclass
class SkillDraftSummary:
    name: str
    task_type: str
    status: str
    confidence: float
    created_at: str
    source_run_count: int
    primary_tool_chain: list[str]
    artifact_types: list[str]
    validation_errors: list[str] = field(default_factory=list)


class SkillCaptureManager:
    """Skill 自动沉淀管理器。"""

    REQUIRED_SECTIONS = (
        "## 何时使用",
        "## 前置条件",
        "## 输入参数",
        "## 推荐步骤",
        "## 允许工具",
        "## 成功判定",
        "## 常见失败处理",
    )

    def __init__(
        self,
        workspace_dir: Path,
        *,
        tool_registry: Optional[ToolRegistry] = None,
        llm_client: Any | None = None,
        skills_dir: Path | None = None,
        drafts_dir: Path | None = None,
        capture_dir: Path | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.tool_registry = tool_registry
        self.llm = llm_client
        self.skills_dir = Path(skills_dir) if skills_dir else self.workspace_dir / "skills"
        self.drafts_dir = Path(drafts_dir) if drafts_dir else self.workspace_dir / ".agents" / "skills-drafts"
        self.capture_dir = Path(capture_dir) if capture_dir else self.workspace_dir / ".agents" / "skill-capture"
        self.records_path = self.capture_dir / "records.jsonl"
        self.publish_log_path = self.capture_dir / "publish-log.jsonl"

    @staticmethod
    def extract_task_type(query: str) -> tuple[Optional[str], str]:
        """从用户输入中提取显式 task_type 标记。"""
        text = query or ""
        match = TASK_TYPE_PATTERN.search(text)
        if not match:
            return None, text
        task_type = match.group(1).strip().lower()
        cleaned = TASK_TYPE_PATTERN.sub("", text, count=1).strip()
        return task_type, cleaned

    def suggest_task_type(self, query: str) -> Optional[str]:
        """根据 query 做轻量 task_type 自动建议。"""
        text = (query or "").lower()
        rules = (
            ("ci_bugfix", ("ci", "pipeline", "github actions", "workflow", "构建", "流水线", "日志解析", "测试挂了", "报错", "失败")),
            ("doc_refresh", ("readme", "文档", "说明文档", "快速开始", "安装说明", "docs", "介绍页")),
            ("test_fix", ("测试", "test", "pytest", "单测", "回归", "断言")),
            ("refactor_small", ("重构", "refactor", "整理代码", "抽取", "简化实现")),
            ("ui_build", ("ui", "页面", "landing", "网页", "响应式", "hero", "frontend", "组件样式")),
        )
        best_task_type = None
        best_hits = 0
        for task_type, keywords in rules:
            hits = sum(1 for keyword in keywords if keyword in text)
            if hits > best_hits:
                best_hits = hits
                best_task_type = task_type
        return best_task_type if best_hits > 0 else None

    def capture_successful_run(
        self,
        *,
        run_id: str,
        task_type: str | None,
        goal: str,
        inputs: dict[str, Any],
        steps: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        artifacts: list[str],
        outputs: dict[str, Any],
        success: bool,
        manual_intervention: bool,
    ) -> Optional[Path]:
        """记录一次成功执行，并在满足阈值时生成草稿。"""
        if not success or not task_type:
            return None

        record = SkillCaptureRecord(
            run_id=run_id,
            task_type=task_type,
            goal=goal.strip(),
            inputs=inputs,
            steps=steps,
            tool_calls=tool_calls,
            artifacts=sorted({artifact for artifact in artifacts if artifact}),
            outputs=outputs,
            success=success,
            manual_intervention=manual_intervention,
            timestamp=self._now_iso(),
        )
        self.record_successful_run(record)
        candidate_records = self.detect_repeated_successes(task_type)
        if not candidate_records:
            return None
        return self.generate_skill_draft(candidate_records)

    def record_successful_run(self, record: SkillCaptureRecord) -> None:
        """写入成功轨迹。"""
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        existing_ids = {item.run_id for item in self.load_records()}
        if record.run_id in existing_ids:
            return
        with open(self.records_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def load_records(self) -> list[SkillCaptureRecord]:
        """加载历史成功轨迹。"""
        if not self.records_path.exists():
            return []
        records: list[SkillCaptureRecord] = []
        with open(self.records_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(SkillCaptureRecord.from_dict(json.loads(line)))
        return records

    def detect_repeated_successes(self, task_type: str, *, now: datetime | None = None) -> list[SkillCaptureRecord]:
        """根据 V1 规则找出重复成功候选。"""
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        eligible = []
        for record in self.load_records():
            if record.task_type != task_type:
                continue
            if not record.success or record.manual_intervention:
                continue
            if self._parse_time(record.timestamp) < cutoff:
                continue
            eligible.append(record)

        if len(eligible) < 3:
            return []

        anchor = eligible[-1]
        anchor_artifacts = self._artifact_signature(anchor.artifacts)
        selected = []
        for record in reversed(eligible):
            if self._artifact_signature(record.artifacts) != anchor_artifacts:
                continue
            similarity = self._tool_sequence_similarity(anchor.tool_calls, record.tool_calls)
            if similarity < 0.8:
                continue
            selected.append(record)
            if len(selected) == 3:
                break

        if len(selected) < 3:
            return []
        return list(reversed(selected))

    def generate_skill_draft(self, records: list[SkillCaptureRecord]) -> Path:
        """根据成功记录生成 skill 草稿目录。"""
        if len(records) < 3:
            raise ValueError("生成草稿至少需要 3 条成功记录")

        task_type = records[-1].task_type
        skill_name = self._slugify(task_type)
        draft_dir = self.drafts_dir / skill_name
        draft_dir.mkdir(parents=True, exist_ok=True)

        parameters = self._extract_parameter_names(records)
        allowed_tools = sorted({call.get("tool", "") for record in records for call in record.tool_calls if call.get("tool")})
        skill_markdown = self._render_skill_markdown(
            skill_name=skill_name,
            task_type=task_type,
            records=records,
            parameters=parameters,
            allowed_tools=allowed_tools,
        )
        confidence = self._compute_confidence(records)
        metadata = SkillDraftMetadata(
            name=skill_name,
            task_type=task_type,
            source_runs=[record.run_id for record in records],
            confidence=confidence,
            created_at=self._now_iso(),
            status="draft",
        )
        examples = self._build_examples(records)

        (draft_dir / "SKILL.md").write_text(skill_markdown, encoding="utf-8")
        (draft_dir / "examples.json").write_text(
            json.dumps(examples, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (draft_dir / "metadata.json").write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        validation = self.validate_skill_draft(draft_dir)
        if not validation.valid:
            metadata.status = "rejected"
            metadata.validation_errors = validation.errors
            (draft_dir / "metadata.json").write_text(
                json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return draft_dir

    def list_drafts(self) -> list[SkillDraftMetadata]:
        """列出所有草稿。"""
        if not self.drafts_dir.exists():
            return []
        drafts: list[SkillDraftMetadata] = []
        for draft_dir in sorted(self.drafts_dir.iterdir()):
            if not draft_dir.is_dir():
                continue
            metadata_path = draft_dir / "metadata.json"
            if not metadata_path.exists():
                continue
            with open(metadata_path, "r", encoding="utf-8") as f:
                drafts.append(SkillDraftMetadata.from_dict(json.load(f)))
        return drafts

    def list_draft_summaries(self) -> list[SkillDraftSummary]:
        """列出带工具链和产物信息的草稿摘要。"""
        summaries: list[SkillDraftSummary] = []
        for metadata in self.list_drafts():
            draft_dir = self.drafts_dir / metadata.name
            examples_path = draft_dir / "examples.json"
            examples = []
            if examples_path.exists():
                with open(examples_path, "r", encoding="utf-8") as f:
                    examples = json.load(f)
            primary_tool_chain = examples[0].get("tool_sequence", []) if examples else []
            artifact_types = self._collect_artifact_types_from_examples(examples)
            summaries.append(
                SkillDraftSummary(
                    name=metadata.name,
                    task_type=metadata.task_type,
                    status=metadata.status,
                    confidence=metadata.confidence,
                    created_at=metadata.created_at,
                    source_run_count=len(metadata.source_runs),
                    primary_tool_chain=primary_tool_chain,
                    artifact_types=artifact_types,
                    validation_errors=metadata.validation_errors,
                )
            )
        return summaries

    def validate_skill_draft(self, draft: str | Path) -> SkillDraftValidationResult:
        """校验草稿的完整性和安全性。"""
        draft_dir = self._resolve_draft_dir(draft)
        errors: list[str] = []

        metadata_path = draft_dir / "metadata.json"
        skill_path = draft_dir / "SKILL.md"
        examples_path = draft_dir / "examples.json"

        if not skill_path.exists():
            errors.append("缺少 SKILL.md")
        if not examples_path.exists():
            errors.append("缺少 examples.json")

        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        else:
            errors.append("缺少 metadata.json")

        skill_text = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
        for section in self.REQUIRED_SECTIONS:
            if section not in skill_text:
                errors.append(f"缺少必填段落: {section}")

        if metadata and len(metadata.get("source_runs", [])) < 3:
            errors.append("source_runs 少于 3 条")

        frontmatter = self._parse_frontmatter(skill_text)
        allowed_tools = [item.strip() for item in frontmatter.get("allowed_tools", "").split("\n") if item.strip()]
        if self.tool_registry is not None:
            for tool_name in allowed_tools:
                if self.tool_registry.get(tool_name) is None:
                    errors.append(f"引用了不存在的工具: {tool_name}")

        if skill_text.count("{{") == 0:
            errors.append("未检测到参数槽位")

        findings = (
            (EMAIL_PATTERN, "检测到邮箱地址"),
            (TOKEN_PATTERN, "检测到疑似密钥或 token"),
            (UUID_PATTERN, "检测到临时 ID"),
            (ABSOLUTE_PATH_PATTERN, "检测到绝对路径"),
        )
        for pattern, message in findings:
            if pattern.search(skill_text):
                errors.append(message)

        return SkillDraftValidationResult(valid=not errors, errors=errors)

    def publish_skill_draft(self, draft_name: str) -> Path:
        """发布草稿到正式 skills 目录。"""
        draft_dir = self._resolve_draft_dir(draft_name)
        validation = self.validate_skill_draft(draft_dir)
        if not validation.valid:
            raise ValueError("草稿校验失败: " + "; ".join(validation.errors))

        metadata_path = draft_dir / "metadata.json"
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = SkillDraftMetadata.from_dict(json.load(f))
        if metadata.status != "draft":
            raise ValueError(f"只允许发布 draft 状态草稿，当前状态: {metadata.status}")

        target_dir = self.skills_dir / metadata.name
        if target_dir.exists():
            raise ValueError(f"目标 Skill 已存在: {metadata.name}")

        self.skills_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(draft_dir), str(target_dir))

        metadata.status = "published"
        with open(target_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata.to_dict(), f, ensure_ascii=False, indent=2)

        self.capture_dir.mkdir(parents=True, exist_ok=True)
        with open(self.publish_log_path, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "skill": metadata.name,
                        "task_type": metadata.task_type,
                        "published_at": self._now_iso(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        return target_dir

    def _resolve_draft_dir(self, draft: str | Path) -> Path:
        path = Path(draft)
        if path.is_absolute():
            return path
        return self.drafts_dir / str(draft)

    def _render_skill_markdown(
        self,
        *,
        skill_name: str,
        task_type: str,
        records: list[SkillCaptureRecord],
        parameters: list[str],
        allowed_tools: list[str],
    ) -> str:
        generated = self._generate_with_llm(skill_name, task_type, records, parameters, allowed_tools)
        if generated:
            return generated
        return self._render_fallback_markdown(skill_name, task_type, records, parameters, allowed_tools)

    def _generate_with_llm(
        self,
        skill_name: str,
        task_type: str,
        records: list[SkillCaptureRecord],
        parameters: list[str],
        allowed_tools: list[str],
    ) -> Optional[str]:
        if self.llm is None:
            return None
        samples = []
        for record in records:
            samples.append(
                {
                    "goal": record.goal,
                    "tool_sequence": [call.get("tool", "") for call in record.tool_calls],
                    "artifacts": record.artifacts,
                }
            )
        prompt = f"""请根据以下重复成功执行记录，生成一个可审核的 SKILL.md。

要求：
1. 必须输出完整 Markdown，且包含以下段落：
## 何时使用
## 前置条件
## 输入参数
## 推荐步骤
## 允许工具
## 成功判定
## 常见失败处理
2. 使用 YAML frontmatter，至少包含 name、description、allowed_tools。
3. 输入参数请使用 {{{{name}}}} 形式的槽位，不要写死实例值。
4. 不要包含绝对路径、邮箱、token、临时 ID。
5. 语言使用简洁中文。

skill_name: {skill_name}
task_type: {task_type}
parameters: {parameters}
allowed_tools: {allowed_tools}
samples:
{json.dumps(samples, ensure_ascii=False, indent=2)}
"""
        try:
            from codemate_agent.schema import Message

            response = self.llm.complete(messages=[Message(role="user", content=prompt)], tools=None)
            content = (response.content or "").strip()
            return content or None
        except Exception:
            return None

    def _render_fallback_markdown(
        self,
        skill_name: str,
        task_type: str,
        records: list[SkillCaptureRecord],
        parameters: list[str],
        allowed_tools: list[str],
    ) -> str:
        description = f"用于重复执行 {task_type} 类型任务，并按照稳定成功流程产出一致结果。"
        parameter_lines = "\n".join(
            f"- `{{{{{name}}}}}`: 运行时提供的输入参数"
            for name in parameters
        ) or "- `{{target_request}}`: 运行时的目标说明"
        tool_lines = "\n".join(f"- `{tool}`" for tool in allowed_tools) or "- 无"
        step_lines = []
        tool_sequence = [call.get("tool", "") for call in records[-1].tool_calls if call.get("tool")]
        for index, tool_name in enumerate(tool_sequence, start=1):
            step_lines.append(f"{index}. 使用 `{tool_name}` 推进当前任务。")
        if not step_lines:
            step_lines.append("1. 按照当前任务目标执行稳定成功的操作步骤。")

        success_examples = ", ".join(filter(None, (", ".join(record.artifacts) for record in records if record.artifacts)))
        return "\n".join(
            [
                "---",
                f"name: {skill_name}",
                f"description: {description}",
                "allowed_tools: |",
                *[f"  - {tool}" for tool in allowed_tools],
                "---",
                "",
                f"# {skill_name}",
                "",
                "## 何时使用",
                f"- 当任务被明确标注为 `{task_type}`，且目标与历史成功案例一致时使用。",
                "- 适用于重复出现、工具链稳定、输出产物类型一致的任务。",
                "",
                "## 前置条件",
                "- 需要在当前工作区中运行。",
                "- 相关工具和依赖已可用。",
                "- 用户提供了必要的输入参数。",
                "",
                "## 输入参数",
                parameter_lines,
                "",
                "## 推荐步骤",
                *step_lines,
                "",
                "## 允许工具",
                tool_lines,
                "",
                "## 成功判定",
                f"- 任务完成后应产生与历史一致的结果类型。示例产物：{success_examples or '无显式产物'}。",
                "- 最终输出应给出可复核的结果摘要。",
                "",
                "## 常见失败处理",
                "- 如果关键工具失败，优先检查输入参数和工作区路径是否正确。",
                "- 如果输入信息不足，先澄清缺失参数，再继续执行。",
            ]
        )

    def _build_examples(self, records: list[SkillCaptureRecord]) -> list[dict[str, Any]]:
        examples = []
        for record in records:
            examples.append(
                {
                    "run_id": record.run_id,
                    "goal": record.goal,
                    "inputs_summary": self._redact_object(record.inputs),
                    "tool_sequence": [call.get("tool", "") for call in record.tool_calls if call.get("tool")],
                    "artifacts_summary": record.artifacts,
                    "outputs_summary": self._redact_object(record.outputs),
                }
            )
        return examples

    def _extract_parameter_names(self, records: list[SkillCaptureRecord]) -> list[str]:
        names: set[str] = set()
        for record in records:
            names.update(str(key) for key in record.inputs.keys())
        sanitized = [self._slugify(name).replace("-", "_") for name in names if name]
        sanitized = [name for name in sanitized if name]
        return sorted(set(sanitized))

    def _compute_confidence(self, records: list[SkillCaptureRecord]) -> float:
        count_score = min(1.0, len(records) / 5.0)
        anchor = records[-1]
        similarities = [
            self._tool_sequence_similarity(anchor.tool_calls, record.tool_calls)
            for record in records
        ]
        sequence_score = sum(similarities) / len(similarities) if similarities else 0.0
        artifact_score = 1.0 if len({self._artifact_signature(record.artifacts) for record in records}) == 1 else 0.0
        confidence = (count_score * 0.35) + (sequence_score * 0.45) + (artifact_score * 0.20)
        return round(confidence, 3)

    def _artifact_signature(self, artifacts: list[str]) -> tuple[str, ...]:
        extensions = []
        for artifact in artifacts:
            suffix = Path(artifact).suffix.lower() or "<none>"
            extensions.append(suffix)
        return tuple(sorted(extensions)) or ("<none>",)

    def _collect_artifact_types_from_examples(self, examples: list[dict[str, Any]]) -> list[str]:
        types: set[str] = set()
        for example in examples:
            for artifact in example.get("artifacts_summary", []):
                suffix = Path(artifact).suffix.lower() or "<none>"
                types.add(suffix)
        return sorted(types)

    def _tool_sequence_similarity(
        self,
        left_calls: list[dict[str, Any]],
        right_calls: list[dict[str, Any]],
    ) -> float:
        left = [call.get("tool", "") for call in left_calls if call.get("tool")]
        right = [call.get("tool", "") for call in right_calls if call.get("tool")]
        if not left and not right:
            return 1.0
        return SequenceMatcher(a=left, b=right).ratio()

    def _parse_frontmatter(self, text: str) -> dict[str, str]:
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not match:
            return {}
        result: dict[str, str] = {}
        current_key: Optional[str] = None
        current_value: list[str] = []
        for line in match.group(1).splitlines():
            if line and not line.startswith((" ", "\t")) and ":" in line:
                if current_key is not None:
                    result[current_key] = "\n".join(current_value).strip()
                key, value = line.split(":", 1)
                current_key = key.strip()
                value = value.strip()
                current_value = [] if value == "|" else [value]
            elif current_key is not None and (line.startswith((" ", "\t")) or line.strip().startswith("-")):
                current_value.append(line.strip().lstrip("- "))
        if current_key is not None:
            result[current_key] = "\n".join(current_value).strip()
        return result

    def _redact_object(self, payload: Any) -> Any:
        text = json.dumps(payload, ensure_ascii=False)
        text = EMAIL_PATTERN.sub("<redacted-email>", text)
        text = TOKEN_PATTERN.sub("<redacted-token>", text)
        text = UUID_PATTERN.sub("<redacted-id>", text)
        text = ABSOLUTE_PATH_PATTERN.sub("<redacted-path>", text)
        return json.loads(text)

    def _slugify(self, value: str) -> str:
        text = (value or "").strip().lower()
        text = re.sub(r"[^a-z0-9._-]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-")
        return text or "captured-skill"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _parse_time(self, value: str) -> datetime:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
