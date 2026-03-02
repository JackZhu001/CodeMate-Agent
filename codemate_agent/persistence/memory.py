"""
长期记忆管理 - 跨会话的持久化记忆

管理用户偏好、项目上下文等长期信息。
"""

from pathlib import Path
from typing import Optional
import math
import re


class MemoryManager:
    """
    长期记忆管理器

    存储和检索跨会话的持久化信息。
    """

    # 记忆文件名
    USER_PREFERENCES = "user_preferences.md"
    PROJECT_CONTEXT = "project_context.md"
    CODE_SNIPPETS = "code_snippets.md"
    CUSTOM_MEMORY = "custom_memory.md"
    CODEMATE_FILE = "codemate.md"

    def __init__(self, memory_dir: Path):
        """
        初始化 MemoryManager

        Args:
            memory_dir: 记忆存储目录
        """
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 初始化默认记忆文件
        self._init_default_files()

    def _init_default_files(self) -> None:
        """初始化默认的记忆文件"""
        # 用户偏好
        if not (self.memory_dir / self.USER_PREFERENCES).exists():
            self.save_user_preferences(self._default_user_preferences())

        # 项目上下文
        if not (self.memory_dir / self.PROJECT_CONTEXT).exists():
            self.save_project_context(self._default_project_context())

        # 代码片段
        if not (self.memory_dir / self.CODE_SNIPPETS).exists():
            self.save_code_snippets(self._default_code_snippets())

    def _default_user_preferences(self) -> str:
        """默认用户偏好模板"""
        return """# 用户偏好

> 此文件记录您的使用偏好，帮助 Agent 更好地为您服务。

## 编码风格
- （示例）使用 4 空格缩进
- （示例）变量命名用 snake_case

## 沟通风格
- （示例）回答要简洁，不要啰嗦
- （示例）优先给出代码，少解释原理

## 项目约定
- （示例）测试文件命名以 test_ 开头
- （示例）日志用 loguru 而不是 logging

## 常用模式
- （示例）写类时优先用 dataclass
"""

    def _default_project_context(self) -> str:
        """默认项目上下文模板"""
        return """# 项目上下文

> 此文件记录当前项目的背景信息。

## 项目概述
- 项目名称：
- 主要技术栈：
- 项目类型：Web 应用 / CLI 工具 / 库 / 其他

## 项目结构
```
src/
├── main.py
└── ...
```

## 重要约定
- （记录项目特定的编码约定）
"""

    def _default_code_snippets(self) -> str:
        """默认代码片段模板"""
        return """# 代码片段知识库

> 此文件记录常用的代码模式和解决方案。

## 数据处理
```python
# （示例）常用数据处理模式
```

## 错误处理
```python
# （示例）常用的错误处理模式
```
"""

    # ==================== 用户偏好 ====================

    def load_user_preferences(self) -> str:
        """加载用户偏好"""
        path = self.memory_dir / self.USER_PREFERENCES
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return self._default_user_preferences()

    def save_user_preferences(self, content: str) -> None:
        """保存用户偏好"""
        path = self.memory_dir / self.USER_PREFERENCES
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def update_user_preference(self, key: str, value: str) -> None:
        """
        更新单个用户偏好

        Args:
            key: 偏好键（如 "编码风格"）
            value: 偏好值
        """
        content = self.load_user_preferences()
        lines = content.split("\n")

        # 查找并更新
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"## {key}") or line.strip().startswith(f"- {key}"):
                # 找到位置，在下一行添加
                lines.insert(i + 1, f"- {value}")
                updated = True
                break

        if not updated:
            # 没找到，添加到对应分类或末尾
            lines.append(f"\n## {key}\n- {value}")

        self.save_user_preferences("\n".join(lines))

    # ==================== 项目上下文 ====================

    def load_project_context(self) -> str:
        """加载项目上下文"""
        path = self.memory_dir / self.PROJECT_CONTEXT
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return self._default_project_context()

    def save_project_context(self, content: str) -> None:
        """保存项目上下文"""
        path = self.memory_dir / self.PROJECT_CONTEXT
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ==================== 代码片段 ====================

    def load_code_snippets(self) -> str:
        """加载代码片段"""
        path = self.memory_dir / self.CODE_SNIPPETS
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return self._default_code_snippets()

    def save_code_snippets(self, content: str) -> None:
        """保存代码片段"""
        path = self.memory_dir / self.CODE_SNIPPETS
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ==================== 自定义记忆 ====================

    def load_custom_memory(self) -> str:
        """加载自定义记忆"""
        path = self.memory_dir / self.CUSTOM_MEMORY
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return "# 自定义记忆\n\n> 在此添加任何您希望 Agent 记住的信息。\n"

    def save_custom_memory(self, content: str) -> None:
        """保存自定义记忆"""
        path = self.memory_dir / self.CUSTOM_MEMORY
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ==================== 组合加载 ====================

    def load_all_memory(self) -> str:
        """
        加载所有记忆内容

        Returns:
            合并后的记忆文本
        """
        parts = []

        user_prefs = self.load_user_preferences()
        if user_prefs.strip() and not user_prefs.startswith("# 用户偏好\n\n> 此文件"):
            parts.append(f"## 用户偏好\n{user_prefs}")

        project_ctx = self.load_project_context()
        if project_ctx.strip() and not project_ctx.startswith("# 项目上下文\n\n> 此文件"):
            parts.append(f"## 项目上下文\n{project_ctx}")

        code_snippets = self.load_code_snippets()
        if code_snippets.strip() and not code_snippets.startswith("# 代码片段知识库\n\n> 此文件"):
            parts.append(f"## 代码片段知识库\n{code_snippets}")

        custom = self.load_custom_memory()
        if custom.strip() and not custom.startswith("# 自定义记忆\n\n> 在此"):
            parts.append(f"## 自定义记忆\n{custom}")

        if parts:
            return "\n\n---\n\n".join(parts)

        return "# 长期记忆\n\n暂无记忆内容。"

    def retrieve_relevant_memory(self, query: str, top_k: int = 3) -> str:
        """
        基于 BM25 进行关键词检索，返回最相关的长期记忆片段。

        说明：
            - BM25 不需要向量库
            - 适合先做轻量关键词召回，再按需扩展到向量检索
        """
        query = (query or "").strip()
        if not query:
            return self.load_all_memory()

        documents = self._build_memory_documents()
        if not documents:
            return "# 长期记忆\n\n暂无可检索内容。"

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return self.load_all_memory()

        scored = self._bm25_rank(documents, query_tokens)
        top_docs = [doc for doc, score in scored[:top_k] if score > 0]
        if not top_docs:
            return self.load_all_memory()

        parts = []
        for doc in top_docs:
            snippet = doc["content"][:800]
            parts.append(f"### {doc['title']} ({doc['source']})\n{snippet}")
        return "# 长期记忆（关键词召回）\n\n" + "\n\n---\n\n".join(parts)

    def load_codemate_file(self, workspace_dir: Path) -> str:
        """加载项目 codemate.md（若存在）"""
        path = Path(workspace_dir) / self.CODEMATE_FILE
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def init_codemate_file(self, workspace_dir: Path, tools: Optional[list[str]] = None) -> Path:
        """初始化 codemate.md（若不存在）"""
        path = Path(workspace_dir) / self.CODEMATE_FILE
        if path.exists():
            return path

        tools = tools or []
        tools_text = ", ".join(tools[:20]) if tools else "（待补充）"
        template = f"""# CodeMate 项目记忆

> 这个文件会在每轮对话中注入上下文，可手动维护项目事实、偏好、约束。

## 项目功能摘要
- 这是一个 AI Agent 项目，支持多轮工具调用与上下文压缩。
- 当前目标：持续提升稳定性、可观测性、记忆召回质量。

## 项目特点
- 工具驱动执行（Function Calling）
- 长短期记忆管理
- 上下文压缩与会话持久化

## 可用工具（自动生成）
- {tools_text}

## 用户画像与偏好（请按需补充）
- 沟通风格：
- 代码风格：
- 约束偏好：

## 关键约定（请按需补充）
- 
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(template)
        return path

    def _build_memory_documents(self) -> list[dict]:
        """将长期记忆文件拆分为可检索文档片段"""
        docs = []
        files = [
            self.USER_PREFERENCES,
            self.PROJECT_CONTEXT,
            self.CODE_SNIPPETS,
            self.CUSTOM_MEMORY,
        ]
        for filename in files:
            path = self.memory_dir / filename
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            sections = re.split(r"(?m)^##\s+", content)
            if len(sections) <= 1:
                docs.append({
                    "source": filename,
                    "title": filename,
                    "content": content,
                    "tokens": self._tokenize(content),
                })
                continue
            for sec in sections:
                sec = sec.strip()
                if not sec:
                    continue
                lines = sec.splitlines()
                title = lines[0].strip("# ").strip() if lines else filename
                body = "\n".join(lines[1:]).strip()
                text = body or sec
                docs.append({
                    "source": filename,
                    "title": title,
                    "content": text,
                    "tokens": self._tokenize(text),
                })
        return docs

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", text.lower())

    def _bm25_rank(self, docs: list[dict], query_tokens: list[str]) -> list[tuple[dict, float]]:
        k1 = 1.5
        b = 0.75
        n_docs = len(docs)
        avg_len = sum(len(d["tokens"]) for d in docs) / max(n_docs, 1)

        df = {}
        for d in docs:
            for t in set(d["tokens"]):
                df[t] = df.get(t, 0) + 1

        scored = []
        for d in docs:
            tf = {}
            for t in d["tokens"]:
                tf[t] = tf.get(t, 0) + 1
            dl = len(d["tokens"]) or 1
            score = 0.0
            for q in query_tokens:
                if q not in tf:
                    continue
                n_q = df.get(q, 0)
                idf = math.log(1 + (n_docs - n_q + 0.5) / (n_q + 0.5))
                freq = tf[q]
                denom = freq + k1 * (1 - b + b * dl / max(avg_len, 1))
                score += idf * (freq * (k1 + 1)) / denom
            scored.append((d, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def get_memory_files_info(self) -> dict[str, dict]:
        """
        获取所有记忆文件的信息

        Returns:
            文件信息字典 {filename: {exists, size, path}}
        """
        files = [
            self.USER_PREFERENCES,
            self.PROJECT_CONTEXT,
            self.CODE_SNIPPETS,
            self.CUSTOM_MEMORY,
        ]

        info = {}
        for filename in files:
            path = self.memory_dir / filename
            info[filename] = {
                "exists": path.exists(),
                "size": path.stat().st_size if path.exists() else 0,
                "path": str(path),
            }

        return info

    def __repr__(self) -> str:
        return f"MemoryManager(dir={self.memory_dir})"
