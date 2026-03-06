# CodeMate Agent

> 一个面向真实代码仓库的终端 AI 工程助手：能读、能查、能改、能追踪上下文。

## Why CodeMate

CodeMate 的设计重点是：  
- **开门见山**：明确可解决的问题与场景  
- **快速上手**：3 步可跑起来  
- **可验证能力**：明确核心能力与命令  

面向复杂仓库开发场景，CodeMate 的目标是：**降低上下文丢失、减少重复解释、稳定推进多轮任务**。

---

## 📖 典型工程场景

常见问题包括：
- “这个函数改哪里会影响线上？”
- “我刚刚跑过的命令输出去哪了？”
- “我们上周不是已经修过这个问题了吗？”

CodeMate 试图把这条链路打通：
1. **先理解仓库**：用工具快速扫描结构与调用关系  
2. **再执行任务**：多轮调用工具，持续推进 todo 状态  
3. **遇到长上下文自动收敛**：保留近 3 轮关键现场，旧信息摘要化并可回读  
4. **跨会话延续**：通过会话与记忆文件减少“重复解释成本”

CodeMate 聚焦“工程执行流”，而不是一次性问答。

---

## 💓 心跳机制

OpenClaw 官方文档将 heartbeat 定义为“**周期触发 agent turn**”。  
CodeMate 结合这个思路，做了面向工程任务的轻量化落地：
- 执行态心跳：关键阶段打点（round / llm / tool）
- 后台轮询心跳：每隔 `HEARTBEAT_POLL_SECONDS` 唤醒一次，检查待办（pending / in_progress）
- 看门狗告警：单次 LLM/工具调用超过 `HEARTBEAT_TIMEOUT_SECONDS` 触发超时告警
- 状态可观测：`/heartbeat` 随时查看当前状态

默认采用简化的 **task_polling** 模式（任务驱动轮询）；如需完整详细打点，可切到 `HEARTBEAT_MODE=verbose`。  
OpenClaw 参考链接：<https://github.com/openclaw/openclaw/blob/main/docs/gateway/heartbeat.md>
如需暂时关闭 todo 催办提醒，可设置 `TODO_NAG_ENABLED=false`（或 `TODO_NAG_INTERVAL=0`）。

目标是让 Agent 在长任务中的状态持续可观测、问题可定位、流程可恢复。

常见应用场景：
- 定期检查待办是否长期未推进（避免任务“挂着不动”）
- 长执行链路中发现超时/卡顿后及时提醒
- 低频巡检项目状态，仅在有异常时提示人工介入

---

## ✨ Highlights

- **三层上下文工程**：微压缩 / 自动压缩 / 手动 `/compact`
- **心跳 + 看门狗**：长任务可观测，超时可告警
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

创建 `.env`，建议提供：

```bash
API_PROVIDER=minimax
BASE_URL=https://api.minimax.chat/v1
API_KEY=your_api_key_here
MODEL=MiniMax-M2
```

### 3) 启动

```bash
python -m codemate_agent.cli
```

或使用启动脚本：

```bash
./run.sh
```

---

## 🖥️ CLI 体验

启动后可用命令：

- `/help` 查看帮助
- `/reset` 重置会话状态
- `/init` 初始化项目 `codemate.md` 记忆文件
- `/compact` 手动压缩当前上下文
- `/heartbeat` 查看心跳和看门狗状态
- `/stats` 查看统计
- `/tools` 查看工具
- `/skills` 查看技能
- `/sessions` 查看历史会话
- `/history <id>` 加载历史会话
- `/memory` 查看长期记忆
- `/save` 保存当前会话

---

## 🖼️ 界面截图（按编号）

下面 6 张图按编号展示了典型使用链路：启动与配置 → 任务执行 → 产物展示。

| 图 1：欢迎页与配置 | 图 2：会话交互 |
| --- | --- |
| ![CodeMate Screenshot 1](docs/images/readme/1.png) | ![CodeMate Screenshot 2](docs/images/readme/2.png) |

| 图 3：任务执行过程 | 图 4：项目介绍页展示 |
| --- | --- |
| ![CodeMate Screenshot 3](docs/images/readme/3.png) | ![CodeMate Screenshot 4](docs/images/readme/4.png) |

| 图 5：页面模块细节 | 图 6：页面模块细节 |
| --- | --- |
| ![CodeMate Screenshot 5](docs/images/readme/5.png) | ![CodeMate Screenshot 6](docs/images/readme/6.png) |

---

## 🎯 适用人群

- 在中大型代码库里做维护、重构、排障的开发者  
- 需要“多轮执行 + 可回溯上下文”的 AI 协作流程  
- 希望在终端内完成分析、修改、验证，而不是频繁切换工具

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
- 针对 `role="tool"` 的旧工具输出做分级处理（默认保留最近 3 轮不动）
- **Soft Trim**：保留头尾片段（默认 1500 + 1500 字符），中间折叠
- **Hard Clear**：将旧工具输出替换为占位符（保留“该处曾有工具结果”的语义）
- 触发阈值按占比计算：`MICRO_SOFT_TRIM_RATIO`（默认 0.3）、`MICRO_HARD_CLEAR_RATIO`（默认 0.5）
- Hard Clear 还要求可裁剪总量达到 `MICRO_HARD_CLEAR_MIN_CHARS`（默认 50000）
- 支持工具白/黑名单、图片结果保护与最近轮次保护

### Auto Compact（超阈值）
- 默认阈值：`context_window * 0.75`（默认窗口 200k）
- 行为：保留 `system + 最近 3 轮`，更早历史摘要化
- 同时落盘 transcript 并在摘要中提示“可回读”

### Manual Compact（手动）
- 用户可用 `/compact` 随时触发自动压缩逻辑

---

## 🧩 MiniMax 兼容说明

- 默认以 MiniMax-M2 作为主模型接入
- 针对 MiniMax 的协议约束，已加入 system/tool 历史规整策略
- 支持解析 `<minimax:tool_call>` 文本协议并恢复结构化工具调用

---

## 📚 详细文档

- [记忆与上下文工程详细说明](docs/memory_context_design.md)
- [工作流说明](WORKFLOW.md)
- [项目分析报告](PROJECT_ANALYSIS.md)
- [项目报告（刷新版）](PROJECT_REPORT.md)
- [代码审查报告（刷新版）](CODE_REVIEW_REPORT.md)

---

## 🗺️ 接下来会继续增强

- 更强的工作记忆结构化（todo/阻塞/下一步）  
- 会话摘要索引化（先召回摘要，再按需回读 transcript）  
- 用户偏好画像文档化（类似 CLAUDE.md 风格注入）

---

## 🧪 开发与测试

```bash
python -m pytest -q
```

---

## 🙏 致谢

特别感谢 **HelloAgents（Datawhale）** 社区教程的启发。  
本项目最初的 Agent 学习路径和实践方法，受到了其公开内容的直接帮助。
同时也感谢实现过程中借鉴过的工程思路：**Koder** 与 **OpenCode**。

[@DatawhaleChina](https://github.com/datawhalechina) ·
[@hello-agents](https://github.com/datawhalechina/hello-agents) ·
[@feiskyer/koder](https://github.com/feiskyer/koder) ·
[@anomalyco/opencode](https://github.com/anomalyco/opencode)

---

## 许可证

MIT
