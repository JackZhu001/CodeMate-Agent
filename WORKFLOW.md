# Oh-My-Claw 工作流说明（2026-04-21）

## 1. 主循环（ReAct + Function Calling）

1. 接收用户输入
2. 注入系统上下文（身份约束 + 记忆 + Repo Map + RepoRAG 片段）
3. 判断是否需要规划（Planner）
4. 调用 LLM 获取回答或工具调用
5. 若触发工具：执行 -> 回填 `tool` 消息 -> 继续下一轮
6. 若无工具：进行完成判定（计划/团队阶段/防提前结束）
7. 输出结果并落盘会话与观测数据

## 2. 复杂任务执行路径

复杂任务通常遵循：

1. `todo_write` 建立可追踪阶段
2. 读取代码与文档事实
3. 实施修改（必要时分块写入）
4. 运行验证/检查
5. 复核与总结输出

关键保护机制：

- 连续失败干预
- 工具参数校验与修复
- 重复调用检测与打断
- 非最终答案识别（避免只输出“思考中”）

## 3. 上下文工程路径

### 3.1 Micro Compact（每轮）

- 针对旧 `tool` 输出做轻量收缩
- 保留最近关键轮次，裁剪低价值历史噪声

### 3.2 Auto Compact（阈值触发）

- 上下文接近阈值时自动压缩
- 压缩前 transcript 落盘，保证可回放

### 3.3 Manual Compact（手动）

- 用户通过 `/compact` 强制压缩
- 常用于长任务切阶段或进入大文件改造前

## 4. RepoRAG 路径

1. 先用 Query Router 判断 query 类型：
   `symbol_lookup / concept_lookup / scope_exploration`
2. 若需要全局结构感，先生成 `Repo Map`
3. 再从记忆、根目录文档、`docs/`、代码文件中召回片段
4. Python 代码优先按 `function / class / method` 做 symbol-first 切块
5. 在预算内拼装上下文注入 system prompt
6. 再进入主循环决策

作用：减少“无关历史”对当前任务的干扰，同时避免把所有问题都退化成纯字符串搜索。

## 4.1 Skill 自动沉淀路径

1. 任务执行完成后，记录成功轨迹（goal / tools / artifacts / outputs）
2. 若有显式或自动建议的 `task_type`，则写入 skill capture 记录
3. 同类任务在最近窗口内重复成功达到阈值后，生成 Skill 草稿
4. 草稿写入 `.agents/skills-drafts/<skill_name>/`
5. 人工通过 `/publish-skill-draft <name>` 发布到正式 `skills/`

## 5. Team 模式工作流

## 5.1 角色

- `lead`：调度与收敛
- `researcher`：事实采集
- `builder`：实现改动
- `reviewer`：验收与缺漏检查

## 5.2 strict 模式阶段约束

默认顺序：

1. researcher
2. builder
3. reviewer

若顺序不满足，coordinator 会拒绝委托并返回约束错误。

## 5.3 关键状态载体

- `.tasks/`：任务状态与依赖
- `.team/inbox/`：成员消息
- `.team/events.jsonl`：结构化运行事件
- `.team/artifacts/`：成员产物与 manifest

## 6. 心跳与超时看门狗

覆盖阶段：

- round_start
- llm_request / llm_response
- tool_call_start / tool_call_end

当单次 LLM 或工具执行超时，会发出 heartbeat alert 并写入事件。

## 7. 失败处理策略

- 参数错误：给出工具正确用法提示
- 工具不存在：返回可用工具列表
- 连续失败：注入“更换策略”干预
- 协议链损坏：重建消息历史并继续
- LLM 临时故障：重试与降级

## 8. 推荐执行规范

1. 改动任务优先“读事实 -> 写改动 -> 验证”
2. 大文本写入优先 `write_file_chunks/append_file_chunks`
3. Team strict 模式下，lead 只调度不直接落地写入
4. 输出结论前必须有可复核证据（文件、命令、测试）
