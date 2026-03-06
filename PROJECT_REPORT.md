# CodeMate Agent 项目报告（2026 刷新版）

## 1. 项目定位

CodeMate Agent 是一个面向真实代码仓库的终端工程助手，强调“可执行、可追踪、可恢复”的多轮开发流程。
当前默认模型与运行配置以 **MiniMax-M2** 为核心，并保留多提供商兼容能力。

## 2. 当前核心能力

- 原生 Function Calling + 工具注册器
- 任务规划（复杂任务自动生成 TODO）
- 心跳与看门狗（长任务可观测）
- 上下文工程（微压缩 / 自动压缩 / 手动 `/compact`）
- 长期记忆（BM25 检索）+ 项目记忆（`/init` 生成 `codemate.md`）
- 多会话持久化（trace / metrics / session）

## 3. 架构概览

```text
CLI (codemate_agent/cli.py)
  -> CodeMateAgent (agent/agent.py)
    -> LLMClient (llm/client.py)
    -> ToolRegistry (tools/registry.py)
    -> Planner (planner/planner.py)
    -> ContextCompressor (context/compressor.py)
    -> MemoryManager (persistence/memory.py)
    -> Trace/Metrics (logging/)
```

## 4. MiniMax 兼容策略（当前实现）

为提升 MiniMax 稳定性，已引入以下机制：

1. 多 `system` 消息规整：仅保留首条 system，后续转为用户说明文本。
2. 工具历史混合保留：最近 2 轮保留结构化 tool_call，旧轮降级为文本上下文。
3. 文本协议兼容：支持从 MiniMax 返回的 `<minimax:tool_call><invoke ...>` 内容中恢复工具调用。
4. 多级降级重试：tools -> text-only -> minimal -> single-user prompt。

## 5. 运行与配置

最小 `.env`：

```bash
API_PROVIDER=minimax
BASE_URL=https://api.minimax.chat/v1
API_KEY=your_api_key_here
MODEL=MiniMax-M2
MAX_ROUNDS=50
```

启动：

```bash
python -m codemate_agent.cli
```

## 6. 测试状态

当前主分支本地回归：

- `pytest -q`
- 46 passed

## 7. 后续建议

- 将“MiniMax 结构化历史保留轮数”开放为环境变量
- 增加 heartbeat/催办策略参数的发布文档示例（超时、轮询、开关）
- 补充端到端回归（复杂网页生成 / MCP 失败降级 / 多工具链路）
