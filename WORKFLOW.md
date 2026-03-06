# CodeMate Agent 工作流（2026 刷新版）

## 1. 主循环

1. 接收用户输入
2. 判断是否需要任务规划（Planner）
3. 注入系统提示（基础提示 + 记忆召回 + 工具说明）
4. 调用 LLM（优先 function calling）
5. 若有工具调用：执行工具并回填 `tool` 消息
6. 若无工具调用：输出最终答案
7. 记录 trace / metrics / heartbeat

## 2. 复杂任务路径

复杂任务（如“生成项目介绍网页”）会触发：

- 自动计划生成
- `todo_write` 进度追踪
- 多轮工具调用（读文档、查目录、写文件）
- 失败检测与干预提示

## 3. 上下文工程路径

- **Micro Compact**：每轮对可裁剪历史做轻量压缩
- **Auto Compact**：达到阈值后压缩历史并保留最近关键轮次
- **Manual Compact**：`/compact` 手动触发

可裁剪工具输出支持 Soft Trim / Hard Clear 分级策略，并受保护规则约束（最近轮次、图片输出、白名单等）。

## 4. 心跳与看门狗

- 关键阶段心跳：round_start / llm_request / tool_call
- 超时看门狗：对 LLM 与工具执行时间告警
- `/heartbeat`：查看当前状态

## 5. MiniMax 兼容分支

当 provider=minimax：

- 历史消息做协议安全规整（system/tool/tool_calls）
- 兼容解析 `<minimax:tool_call>` 文本协议
- 若接口返回 2013 类错误，逐级降级重试

## 6. 失败处理策略

- 参数验证失败：返回明确错误 + 用法提示
- 连续失败阈值：注入干预消息，促使更换策略
- 循环检测：识别重复工具签名并告警/打断
