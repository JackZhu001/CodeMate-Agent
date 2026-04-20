# Oh-My-Claw 项目报告（2026-04-21）

## 1. 项目定位

Oh-My-Claw 是一个终端优先的工程型 AI Agent，目标是将大模型能力稳定落地到真实代码仓库任务中。  
项目强调：

- **执行闭环**：任务必须通过工具落地，而非只生成建议文本。
- **长链路稳定**：面对复杂任务，提供压缩、检索、重试和失败纠偏。
- **过程可审计**：任务、事件、会话和产物都有结构化记录。

## 2. 当前能力概览

### 2.1 Agent 执行层

- Function Calling 主循环
- 工具注册与统一参数验证
- LoopGuard/LoopDetector 防止空转、重复失败、提前结束
- 兼容 MiniMax 工具协议与降级重试链路

### 2.2 上下文与记忆层

- 三层压缩：Micro / Auto / Manual (`/compact`)
- RepoRAG：按 query 召回 memory、根目录文档、`docs/`、代码片段
- Repo Map：先给仓库骨架摘要，再给局部代码片段
- Query Router：按 query 类型选择检索路径
- Python symbol-first chunking：优先函数 / 类 / 方法切块
- 工具输出截断：按工具类型保留高价值上下文
- 会话与 transcript 持久化

### 2.3 团队协作层

- TeamRuntime + Coordinator + Executor
- 角色分工：`lead/researcher/builder/reviewer`
- TaskBoard + MessageBus + RequestTracker + EventLog
- strict 模式阶段约束（researcher -> builder -> reviewer）

### 2.4 观测与运维层

- 心跳与看门狗超时告警
- trace / metrics / session 持久化
- CLI 实时进度展示

### 2.5 Skill 层

- Skill 渐进式加载与自动触发
- Skill Draft 自动沉淀（重复成功流程 -> 草稿）
- 草稿校验与显式发布流程

## 3. 核心工程价值

1. **从“回答器”升级为“执行器”**  
通过工具链完成真实读写和命令执行，缩小建议与落地之间的鸿沟。

2. **从“短会话”升级为“可持续工程流”**  
在长任务里依靠压缩 + 检索 + 状态管理维持上下文一致性。

3. **从“单体 Agent”升级为“角色化协作”**  
在团队模式下将调研、实现、验收分层，减少单轮决策噪声。

## 4. 当前风险与技术债

- 上游模型（尤其 MiniMax）在高负载场景下仍可能出现 500/520/超时。
- Team 任务成功判定目前偏依赖成员摘要，后验产物校验仍需持续增强。
- `.tasks` 持久化任务在异常中断后的回收策略仍有优化空间。
- RepoRAG 在大仓库下仍存在每轮扫描与 symbol 提取的性能压力。
- Query Router 目前仍是规则路由，尚未接入更细的 localization 流程。
- Skill 自动沉淀当前仍以草稿为主，不会自动发布。

## 5. 近期改进重点（建议）

1. 强化 team 成员执行安全边界（高风险 shell 命令策略隔离）
2. 增加任务租约过期回收机制，避免 in_progress 僵尸任务
3. 在 coordinator 层增加“产物验收谓词”，减少假阳性完成
4. 优化 RepoRAG / Repo Map 索引缓存，降低重复扫描成本
5. 将 `scope_exploration` 接入显式 localization / shortlist 流程

## 6. 运行与验证

最小启动配置：

```bash
API_PROVIDER=minimax
API_KEY=your_api_key
MODEL=MiniMax-M2
BASE_URL=https://api.minimax.chat/v1
```

本地回归命令：

```bash
pytest -q
```

当前本地结果（2026-04-21）：

```text
182 passed, 1 warning
```

---

结论：项目已形成完整工程闭环，适合进入“稳定性与交付质量优先”的下一阶段迭代。
