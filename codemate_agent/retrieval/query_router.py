"""
Lightweight query routing for repository retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RetrievalPlan:
    mode: str
    use_repo_map: bool
    use_lexical: bool
    use_semantic: bool
    use_localization: bool
    top_k: int


class QueryRouter:
    """Classify queries into lightweight retrieval strategies."""

    _SYMBOL_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*\b")

    def route(self, query: str, *, default_top_k: int = 5) -> RetrievalPlan:
        text = (query or "").strip()
        lowered = text.lower()

        if self._looks_like_scope_exploration(text, lowered):
            return RetrievalPlan(
                mode="scope_exploration",
                use_repo_map=True,
                use_lexical=True,
                use_semantic=False,
                use_localization=True,
                top_k=max(default_top_k, 6),
            )

        if self._looks_like_symbol_lookup(text, lowered):
            return RetrievalPlan(
                mode="symbol_lookup",
                use_repo_map=False,
                use_lexical=True,
                use_semantic=False,
                use_localization=False,
                top_k=min(default_top_k, 4),
            )

        return RetrievalPlan(
            mode="concept_lookup",
            use_repo_map=True,
            use_lexical=True,
            use_semantic=False,
            use_localization=False,
            top_k=default_top_k,
        )

    def _looks_like_symbol_lookup(self, text: str, lowered: str) -> bool:
        symbol_markers = (
            "在哪",
            "where is",
            "定义",
            "definition",
            "函数",
            "方法",
            "class ",
            "def ",
            "symbol",
        )
        if any(marker in lowered for marker in symbol_markers):
            return True

        matches = self._SYMBOL_RE.findall(text)
        if not matches:
            return False

        camel_or_snake = any(
            ("_" in item) or ("." in item) or (item[:1].isupper() and any(ch.islower() for ch in item[1:]))
            for item in matches
        )
        return camel_or_snake and len(text) <= 80

    def _looks_like_scope_exploration(self, text: str, lowered: str) -> bool:
        scope_markers = (
            "哪些模块",
            "哪几层",
            "经过哪些组件",
            "涉及哪些",
            "overall flow",
            "which modules",
            "哪些文件",
            "哪些地方",
            "where should i look",
            "架构",
            "流程",
        )
        if any(marker in lowered for marker in scope_markers):
            return True
        return len(text) > 100
