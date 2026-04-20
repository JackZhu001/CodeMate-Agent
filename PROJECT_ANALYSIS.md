# Oh-My-Claw 项目分析（2026-04-21）

## 1. 总体成熟度判断

从架构和实现完整度看，Oh-My-Claw 已经不是“玩具型聊天助手”，而是具备工程执行链路的 Agent 框架：

- 有明确主循环与工具闭环
- 有上下文治理与记忆策略
- 有 team 协作与任务协议
- 有观测、日志、指标与持久化

整体成熟度可评为：**可用于复杂开发任务的工程化原型（Production-leaning）**。

## 2. 架构分层分析

### 2.1 决策层（Agent + Planner）

- `CodeMateAgent` 负责调度、消息编排、工具执行、异常修复
- Planner 将复杂用户需求拆为可执行阶段
- strict/team 约束通过系统提示和运行时规则双层实施

### 2.2 执行层（Tooling）

- 文件、检索、shell、task、memory、todo 工具覆盖完整
- 参数校验器统一拦截高频工具调用错误
- 工具输出进入标准化消息流，支持后续压缩和审计

### 2.3 协作层（Team Runtime）

- `TeamCoordinator` 负责任务分发与阶段约束
- `AgentExecutor` 执行成员任务并写入产物清单
- `TaskBoard`/`RequestTracker`/`MessageBus` 提供状态可视化与回放能力

### 2.4 记忆层（Memory + RepoRAG）

- 长期记忆负责跨会话事实保留
- RepoRAG 负责 query-aware 片段召回
- Repo Map 负责提供仓库骨架级结构摘要
- Query Router 负责按 query 类型路由检索策略
- 压缩器负责“已进入会话内容”的体量控制

### 2.5 Skill 层（Skill + Skill Draft）

- `SkillManager` 负责 Skill 索引和正文按需加载
- `SkillCaptureManager` 负责成功轨迹记录、草稿生成、静态校验与发布
- 当前策略是“自动生成草稿，不自动上线”，工程上更稳

### 2.5 观测层（Trace + Metrics + Heartbeat）

- 心跳提供超时告警
- trace 提供执行事件回放
- metrics 提供工具调用统计与错误计数

## 3. 关键优势

1. **执行可靠性优先**  
不是追求单轮“高分回答”，而是强调任务完成路径。

2. **架构职责边界清晰**  
Planner、Tooling、Team、Memory、Observability 分层清楚，可迭代性好。

3. **对模型不稳定有容错设计**  
MiniMax 协议兼容、降级重试、参数修复、循环干预都在服务稳定交付。

## 4. 主要短板

1. **Team 成功判定仍偏“文本成功”**  
成员报告成功不等于产物真实满足约束，需强化后验校验。

2. **任务板恢复策略仍有提升空间**  
中断恢复与租约超时后自动回收需要更强一致性机制。

3. **RepoRAG / Repo Map 在大仓库性能压力偏高**  
重复扫描、symbol 提取与切分会增加每轮时延，需要增量缓存。

4. **检索路由仍偏规则化**  
当前 `symbol_lookup / concept_lookup / scope_exploration` 规则已经够用，但还没有显式接入 localization shortlist。

5. **安全策略尚可更细粒度**  
对 delegated shell 的高风险命令管理仍可更严格。

## 5. 建议路线（按优先级）

### P0（必须优先）

- Team 产物验收硬门禁（文件存在、关键标题、结构校验）
- 任务租约超时回收机制
- delegated shell 风险命令策略收紧

### P1（近期完成）

- RepoRAG / Repo Map 增量索引缓存
- `scope_exploration` 显式接入 localization / shortlist
- 任务视图默认按会话隔离，减少历史任务干扰
- 命令/阶段失败原因结构化编码，提升可观测性

### P2（中期优化）

- team 成员策略模板化（按任务类型动态组装）
- 引入端到端 benchmark（典型长任务脚本）
- 提供 release checklist 与 smoke 命令

---

结论：Oh-My-Claw 当前的架构方向正确，下一阶段应把“结果真实性保障”和“异常恢复能力”作为第一优先级。
