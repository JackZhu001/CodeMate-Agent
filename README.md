# Oh-My-Claw

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Agent](https://img.shields.io/badge/Agent-Team_Runtime-0ea5e9)
![Architecture](https://img.shields.io/badge/Pattern-Function_Calling-22c55e)
![Tests](https://img.shields.io/badge/tests-local%20passing-16a34a)
![Status](https://img.shields.io/badge/Focus-Engineering_Execution-f97316)

> 一只会写代码、会看日志、会盯进度的工程猫爪助手。  
> 目标不是“聊得精彩”，而是“把任务做完”。

---

## 为什么会有 Oh-My-Claw

我们反复看到同一种失败模式：  
很多 Agent 在演示里很聪明，但在真实仓库里会卡在“最后一公里”。

- 能给建议，不能稳定落地改动
- 能跑一两步，长任务就上下文漂移
- 结果“看起来完成了”，但缺少可复核证据

**Oh-My-Claw 的定位叙事只有一句话：**  
把 AI 从“回答器”拉回“执行器”。

---

## 它和常见 Agent 的差异

| 维度 | 常见做法 | Oh-My-Claw |
|---|---|---|
| 目标 | 生成高质量回答 | 交付可验证结果 |
| 任务推进 | 单轮对话驱动 | 任务分阶段推进（可追踪） |
| 长任务稳定性 | 依赖上下文窗口 | 压缩 + RepoRAG + 持久化记忆 |
| 协作方式 | 单体 Agent | `lead / researcher / builder / reviewer` |
| 验收 | 文本“看起来成功” | 产物、事件、日志三重证据 |

---

## 一分钟判断适不适合你

如果你在做下面这些事，这个项目会很对口：

- 在陌生大仓库里排查复杂问题
- 需要“调研 -> 实现 -> 验收”的工程流程
- 希望每一步都能复盘，而不是只看最终一句回答

<details>
<summary><strong>一个典型使用场景（点击展开）</strong></summary>

同一天内要完成：定位线上 bug、跨多文件改动、补测试、整理发布说明。  
Oh-My-Claw 的作用不是“多给建议”，而是把任务拆成阶段并推进到可验收状态。

</details>

---

## 为什么现在值得做这件事

过去一年，代码 Agent 的能力上限在快速抬升，但真实落地的短板也更明显了：  
不是“模型不聪明”，而是“工程链路不完整”。

- 任务规模从“单文件建议”升级到“跨模块改造”
- 团队预期从“回答参考”升级到“可交付结果”
- 评估标准从“会不会说”升级到“能不能稳定完成并可复盘”

Oh-My-Claw 就是针对这组变化设计的：  
把核心投入放在执行闭环、长任务稳定、可审计交付，而不是堆更多花哨能力。

## 为什么这套方案可信

我们更看重“工程证据”而不是“口号描述”：

- 有清晰执行路径：`LLM -> Tool -> Result -> LLM`
- 有失败保护：参数校验、循环检测、超时告警、协议修复
- 有过程证据：任务板、事件日志、会话持久化、产物归档
- 有长期可维护性：角色分工明确，模块边界清晰
- 有回归保障：本地当前回归结果 `182 passed`（2026-04-21）

这意味着它不是一次性 demo，而是一条可以持续迭代、可被团队使用和复核的工程路线。

---

## 项目定位

Oh-My-Claw 聚焦三件事：

- 可执行：模型决策和工具调用形成闭环，真实读写项目文件并推进任务
- 可持续：长任务靠压缩、检索和状态管理维持稳定
- 可追溯：任务、事件、会话和关键决策都可审计

适用场景：

- 大仓库改造、跨文件重构、回归修复
- 需要“先调研 -> 再实现 -> 再验收”的工程流程
- 需要可恢复、可审计的 AI 协作执行链路

---

## 核心能力

### 1) Agent 执行闭环

- 原生 Function Calling（LLM -> Tool -> Result -> LLM）
- 参数校验与自动修复（避免空参数/错误格式循环）
- 连续失败与循环保护（LoopGuard + LoopDetector）
- 工具协议异常自动修复（MiniMax 协议链兼容处理）

### 2) 上下文与记忆工程

- Micro / Auto / Manual (`/compact`) 三层压缩
- RepoRAG 检索注入（memory + 根目录文档 + docs + 代码片段）
- 新增 `Repo Map`：先给仓库骨架，再给相关代码片段
- 新增 `Query Router`：区分 `symbol_lookup / concept_lookup / scope_exploration`
- Python 代码切块升级为 `symbol-first`（函数 / 类 / 方法优先）
- 工具输出按类型截断（避免上下文被冗余输出占满）
- 会话与 transcript 落盘，支持历史回读

### 3) Team 协作模式

- 角色：`lead / researcher / builder / reviewer`
- 严格顺序（可开关）：`researcher -> builder -> reviewer`
- 任务板、请求跟踪、inbox、事件日志
- 委托执行与产物归档（`.team/artifacts`）

### 4) Skill 系统

- Skill 渐进式加载：索引层轻量注入，正文按需加载
- 支持手动 `/skill-name` 调用与意图自动触发
- 新增 Skill Draft 自动沉淀：重复成功流程生成待审核草稿
- 草稿目录：`.agents/skills-drafts/`
- 发布命令：`/publish-skill-draft <name>`

### 5) 可观测性

- 心跳与看门狗（超时告警）
- 结构化 trace 与 metrics
- CLI 可视化进度输出（阶段、行动、观察）

---

## 架构总览

```mermaid
flowchart TB
  U["CLI User"] --> A["CodeMateAgent"]
  A --> L["LLMClient"]
  A --> Q["Query Router"]
  Q --> RM["Repo Map"]
  Q --> R["RepoRAG"]
  A --> C["ContextCompressor"]
  A --> G["LoopGuard / LoopDetector"]
  A --> H["HeartbeatMonitor"]
  A --> T["ToolRegistry"]

  T --> F["File/Search Tools"]
  T --> S["Shell Tools"]
  T --> K["Task Tool"]
  T --> M["Memory Tools"]

  K --> TR["TeamRuntime"]
  TR --> TB["TaskBoard (.tasks)"]
  TR --> MB["MessageBus (.team/inbox)"]
  TR --> EV["Event Log (.team/events.jsonl)"]
  TR --> CO["TeamCoordinator"]
  CO --> EX["AgentExecutor"]
```

---

## 快速开始

### 1) 安装依赖

```bash
git clone https://github.com/JackZhu001/CodeMate-Agent.git
cd CodeMate-Agent
pip install -r requirements.txt
```

> 说明：仓库名与 Python 包名仍保留 `codemate_*` 以兼容历史脚本；对外展示品牌已统一为 **Oh-My-Claw**。

### 2) 配置 `.env`

```bash
API_PROVIDER=minimax
API_KEY=your_api_key
MODEL=MiniMax-M2
BASE_URL=https://api.minimax.chat/v1
```

可选轻量模型分流：

```bash
LIGHT_MODEL=...
LIGHT_API_KEY=...
LIGHT_BASE_URL=...
```

### 3) 启动

```bash
python -m codemate_agent.cli
```

或者：

```bash
./run.sh
```

安装后也可使用新命令名：

```bash
ohmyclaw
```

---

## 常用命令

- `/help`：查看命令帮助
- `/reset`：重置当前会话状态
- `/init`：初始化项目记忆文件（`codemate.md`）
- `/compact`：手动触发上下文压缩
- `/rag <query>`：查看 RepoRAG 召回片段
- `/heartbeat`：查看心跳与超时状态
- `/team`：查看团队运行时状态
- `/inbox`：查看团队 inbox
- `/tasks`：查看任务板
- `/stats`：查看会话统计
- `/tools`：查看当前工具列表
- `/skills`：查看技能列表
- `/skill-drafts`：查看待审核的 Skill 草稿
- `/publish-skill-draft <name>`：发布 Skill 草稿
- `/sessions`：查看历史会话索引
- `/history <id>`：加载历史会话
- `/memory`：查看长期记忆
- `/save`：持久化当前会话

---

## Team 模式（推荐给复杂任务）

### 开启 Team 模式

```bash
export TEAM_AGENT_ENABLED=true
export TEAM_STRICT_MODE=true
export TEAM_AGENT_NAME=lead
export TEAM_AGENT_ROLE=lead
```

### 推荐委托方式

```text
task(agent_id="researcher", description="收集事实", prompt="阅读 README 和 docs")
task(agent_id="builder", description="实现页面", prompt="分块写入 docs/welcome.html")
task(agent_id="reviewer", description="一致性校验", prompt="检查标题与文档一致性")
```

---

## 关键环境变量

### 运行与模型

- `API_PROVIDER` / `API_KEY` / `MODEL` / `BASE_URL`
- `LIGHT_MODEL` / `LIGHT_API_KEY` / `LIGHT_BASE_URL`
- `MAX_ROUNDS`

### 压缩与上下文

- `CONTEXT_WINDOW`
- `COMPRESSION_THRESHOLD`
- `TOKEN_THRESHOLD`
- `MICRO_COMPACT_KEEP`
- `MICRO_SOFT_TRIM_RATIO`
- `MICRO_HARD_CLEAR_RATIO`

### RepoRAG

- `REPO_RAG_ENABLED`
- `REPO_RAG_TOP_K`
- `REPO_RAG_CHAR_BUDGET`
- `REPO_RAG_CODE_ENABLED`
- `REPO_RAG_MAP_ENABLED`
- `REPO_RAG_CODE_ROOTS`
- `REPO_RAG_CODE_EXTENSIONS`

当前检索策略不是“无脑搜一遍仓库”，而是：

1. 先判断 query 属于 `symbol_lookup / concept_lookup / scope_exploration`
2. 决定是否先注入 `Repo Map`
3. 再用 BM25 召回文档、记忆和 symbol-first 代码片段
4. 最后在字符预算内拼装上下文

### Team 与观测

- `TEAM_AGENT_ENABLED`
- `TEAM_STRICT_MODE`
- `TEAM_GLOBAL_MAX_CONCURRENCY`
- `HEARTBEAT_ENABLED`
- `HEARTBEAT_TIMEOUT_SECONDS`
- `HEARTBEAT_POLL_SECONDS`

---

## 目录结构（核心）

```text
codemate_agent/
├── agent/          # 主循环、heartbeat、loop_guard、team_runtime
├── commands/       # CLI slash command 处理
├── context/        # 压缩与截断
├── llm/            # LLM 客户端与协议兼容
├── retrieval/      # RepoRAG + RepoMap + QueryRouter + BM25
├── team/           # coordinator/executor/task board/inbox/protocol
├── tools/          # file/search/shell/task/memory/todo 等工具
├── skill/          # Skill 管理 + Skill Draft 自动沉淀
└── ui/             # 终端显示与进度输出
```

---

## 测试与质量

运行全量测试：

```bash
pytest -q
```

启用仓库 hooks（可选）：

```bash
git config core.hooksPath .githooks
```

---

## 常见问题

### 1) `TEAM_STRICT_MODE` 下 lead 不能直接 `run_shell`/写文件

这是设计行为，不是 bug。  
strict 模式要求 lead 只负责调度，执行动作应委托给 team 成员。

### 2) MiniMax 偶发 500/520 或超时

框架已做多层重试和协议兼容降级，但上游服务波动仍可能导致中断。  
建议提高超时阈值并开启轻量模型分流，降低长链路失败概率。

### 3) 任务板看起来“历史任务很多”

`.tasks` 是持久化任务板，建议定期使用 `task_cleanup` 清理测试命名空间。

---

## 文档索引

- [项目报告](PROJECT_REPORT.md)
- [项目分析](PROJECT_ANALYSIS.md)
- [工作流说明](WORKFLOW.md)
- [记忆与上下文工程](docs/memory_context_design.md)

## 许可证

MIT
