# CodeMate Agent

> 一个面向真实代码仓库的终端 AI 工程助手：能读、能查、能改、能追踪上下文。

## Why CodeMate

CodeMate 借鉴了 Claude Code / Codex / Aider 在 GitHub README 的优秀表达方式：  
- **开门见山**：先说你能解决什么问题  
- **快速上手**：3 步可跑起来  
- **可验证能力**：明确核心能力与命令  

如果你在做复杂仓库开发，CodeMate 的目标是：**降低上下文丢失、减少重复解释、把多轮开发状态稳定带下去**。

---

## ✨ Highlights

- **三层上下文工程**：微压缩 / 自动压缩 / 手动 `/compact`
- **短时记忆可控**：默认保留近 3 轮完整上下文
- **工具输出微压缩**：旧工具输出可占位替代，支持白名单工具不压缩
- **会话可追溯**：压缩前 transcript 落盘，可随时回读
- **长期记忆管理**：支持查看跨会话记忆（`/memory`）
- **交互式终端 UI**：Rich + prompt-toolkit，支持历史与可视化输出

---

## 🚀 Quick Start

### 1) 安装依赖

```bash
git clone https://github.com/JackZhu001/CodeMate-Agent.git
cd CodeMate-Agent
pip install -r requirements.txt
```

### 2) 配置环境变量

创建 `.env`（可参考 `.env.example`），至少提供：

```bash
API_KEY=your_api_key_here
MODEL=glm-4-flash
```

### 3) 启动

```bash
./run.sh
```

---

## 🖥️ CLI 体验

启动后可用命令：

- `/help` 查看帮助
- `/reset` 重置会话状态
- `/compact` 手动压缩当前上下文
- `/stats` 查看统计
- `/tools` 查看工具
- `/skills` 查看技能
- `/sessions` 查看历史会话
- `/history <id>` 加载历史会话
- `/memory` 查看长期记忆
- `/save` 保存当前会话

---

## 🧠 记忆与上下文（当前实现）

### 1) 短时记忆（会话上下文）
- 通过消息历史维护当前任务状态
- 默认保留近 3 轮完整轮次（用户/助手/工具）

### 2) 工作记忆（任务进度）
- Todo 状态可注入压缩结果，避免丢失关键执行状态

### 3) 长时记忆（跨会话）
- 历史会话与记忆文件持久化
- `/memory` 可查看长期记忆内容

---

## ⚙️ 压缩策略（当前实现）

### Micro Compact（每轮）
- 针对 `role="tool"` 的旧工具输出做占位压缩
- 默认保留最近 3 轮工具输出
- 支持白名单（例如 `todo_write`）不压缩

### Auto Compact（超阈值）
- 默认阈值：`context_window * 0.75`（默认窗口 200k）
- 行为：保留 `system + 最近 3 轮`，更早历史摘要化
- 同时落盘 transcript 并在摘要中提示“可回读”

### Manual Compact（手动）
- 用户可用 `/compact` 随时触发自动压缩逻辑

---

## 📚 详细文档

- [记忆与上下文工程详细说明](docs/memory_context_design.md)
- [工作流说明](WORKFLOW.md)
- [项目分析报告](PROJECT_ANALYSIS.md)

---

## 🧪 开发与测试

```bash
python -m pytest -q
```

---

## 许可证

MIT
