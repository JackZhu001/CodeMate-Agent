"""
Repo map utilities for lightweight repository structure summaries.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

from .bm25 import bm25_rank, tokenize_text

logger = logging.getLogger(__name__)


@dataclass
class SymbolSummary:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str


@dataclass
class FileSummary:
    path: str
    summary: str
    imports: list[str]
    symbols: list[SymbolSummary]
    tokens: list[str]


@dataclass
class RepoMapContext:
    query: str
    files: list[FileSummary]
    total_chars: int

    def is_empty(self) -> bool:
        return not self.files

    def to_prompt_text(self) -> str:
        if not self.files:
            return ""

        parts = ["## Repo Map", ""]
        for file_summary in self.files:
            parts.append(f"### {file_summary.path}")
            parts.append(file_summary.summary)
            if file_summary.imports:
                imports_text = ", ".join(file_summary.imports[:6])
                parts.append(f"imports: {imports_text}")
            if file_summary.symbols:
                parts.append("symbols:")
                for symbol in file_summary.symbols[:8]:
                    signature = symbol.signature or symbol.name
                    parts.append(
                        f"- {symbol.kind} `{signature}` "
                        f"(lines {symbol.start_line}-{symbol.end_line})"
                    )
            parts.append("")
        return "\n".join(parts).strip()


class RepoMap:
    """Build and query a lightweight symbol-aware repository map."""

    def __init__(
        self,
        *,
        workspace_dir: Path,
        max_files: int = 180,
        max_file_bytes: int = 200_000,
        char_budget: int = 900,
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.char_budget = max(300, char_budget)
        self._cache: list[FileSummary] | None = None

    def query(self, query: str, top_k: int = 4) -> RepoMapContext:
        text = (query or "").strip()
        if not text:
            return RepoMapContext(query=text, files=[], total_chars=0)

        summaries = self._load_or_build()
        if not summaries:
            return RepoMapContext(query=text, files=[], total_chars=0)

        query_tokens = tokenize_text(text)
        if not query_tokens:
            return RepoMapContext(query=text, files=[], total_chars=0)

        docs = [
            {
                "summary": item,
                "tokens": item.tokens,
            }
            for item in summaries
        ]
        scored = bm25_rank(docs, query_tokens)

        selected: list[FileSummary] = []
        total_chars = 0
        for doc, score in scored:
            if score <= 0:
                continue
            summary = doc["summary"]
            rendered = self._render_file_summary(summary)
            if not rendered:
                continue
            remaining = self.char_budget - total_chars
            if remaining <= 0:
                break
            if len(rendered) > remaining:
                if remaining < 120:
                    continue
                rendered = rendered[: remaining - 3].rstrip() + "..."
            selected.append(
                FileSummary(
                    path=summary.path,
                    summary=summary.summary if len(summary.summary) <= len(rendered) else rendered,
                    imports=summary.imports,
                    symbols=summary.symbols,
                    tokens=summary.tokens,
                )
            )
            total_chars += len(rendered)
            if len(selected) >= top_k:
                break

        return RepoMapContext(query=text, files=selected, total_chars=total_chars)

    def _load_or_build(self) -> list[FileSummary]:
        if self._cache is None:
            self._cache = self._build()
        return self._cache

    def _build(self) -> list[FileSummary]:
        summaries: list[FileSummary] = []
        count = 0
        for path in sorted(self.workspace_dir.rglob("*.py")):
            if count >= self.max_files:
                break
            if self._should_skip(path):
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.debug("读取 repo map 文件失败 %s: %s", path, exc)
                continue

            parsed = self._summarize_python_file(path, text)
            if parsed is None:
                continue
            summaries.append(parsed)
            count += 1
        return summaries

    def _should_skip(self, path: Path) -> bool:
        parts = set(path.parts)
        denylist = {
            ".git",
            ".hg",
            ".svn",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "node_modules",
            "dist",
            "build",
            ".venv",
            "venv",
        }
        return bool(parts & denylist)

    def _summarize_python_file(self, path: Path, text: str) -> FileSummary | None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None

        imports: list[str] = []
        symbols: list[SymbolSummary] = []
        module_doc = ast.get_docstring(tree) or ""
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(module)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(self._build_function_symbol(node))
            elif isinstance(node, ast.ClassDef):
                symbols.append(self._build_class_symbol(node))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = f"{node.name}.{child.name}"
                        symbols.append(self._build_function_symbol(child, override_name=method_name))

        rel_path = path.relative_to(self.workspace_dir).as_posix()
        summary = self._render_summary(rel_path, module_doc, imports, symbols)
        tokens = tokenize_text("\n".join([rel_path, summary, " ".join(imports), " ".join(s.name for s in symbols)]))
        return FileSummary(
            path=rel_path,
            summary=summary,
            imports=imports,
            symbols=symbols,
            tokens=tokens,
        )

    def _build_function_symbol(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        override_name: str | None = None,
    ) -> SymbolSummary:
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        signature = f"{override_name or node.name}({', '.join(args)})"
        return SymbolSummary(
            name=override_name or node.name,
            kind="async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=signature,
        )

    def _build_class_symbol(self, node: ast.ClassDef) -> SymbolSummary:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        suffix = f"({', '.join(bases)})" if bases else ""
        return SymbolSummary(
            name=node.name,
            kind="class",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=f"{node.name}{suffix}",
        )

    def _render_summary(
        self,
        rel_path: str,
        module_doc: str,
        imports: list[str],
        symbols: list[SymbolSummary],
    ) -> str:
        top_symbols = ", ".join(symbol.signature for symbol in symbols[:6]) or "no exported symbols"
        imports_text = ", ".join(imports[:6]) or "no imports"
        module_line = module_doc.strip().splitlines()[0] if module_doc.strip() else "no module docstring"
        return (
            f"{rel_path}: {module_line}. "
            f"Top symbols: {top_symbols}. "
            f"Imports: {imports_text}."
        )

    def _render_file_summary(self, summary: FileSummary) -> str:
        parts = [summary.path, summary.summary]
        if summary.imports:
            parts.append(f"imports: {', '.join(summary.imports[:6])}")
        if summary.symbols:
            parts.append(
                "symbols: " + ", ".join(symbol.signature for symbol in summary.symbols[:8])
            )
        return "\n".join(parts)
