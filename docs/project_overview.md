# CodeMate AI 项目概览

## 项目简介

**CodeMate AI** 是一个基于 **Function Calling** 范式的智能代码分析助手。该项目使用智谱 AI GLM-4 模型构建，通过原生的 Function Calling API 实现代码理解、项目分析和重构建议等功能。

### 核心特性

- ✅ **原生 Function Calling**: 使用 OpenAI 兼容的 API，无需解析文本
- ✅ **模块化工具系统**: 工具按类别组织（文件/搜索/Shell）
- ✅ **Pydantic 数据验证**: 所有数据模型使用 Pydantic 进行验证
- ✅ **简洁的 CLI**: 基于 Rich 的美观命令行界面
- ✅ **三层日志架构**:
  - 运行时日志 (Rich 美化输出)
  - Trace 轨迹日志 (JSONL + Markdown 双格式)
  - Metrics 统计 (Token、成本、性能指标)
- ✅ **Token 统计**: 跟踪 API 使用量和预估成本

## 项目目标

CodeMate AI 的目标是帮助开发者：
1. 快速理解陌生项目的代码结构
2. 搜索和分析代码内容
3. 获取重构建议和最佳实践
4. 自动化代码审查流程

## 核心模块

### 1. Agent 核心模块 (`codemate_agent/agent/`)

**文件**: `codemate_agent/agent/agent.py`

这是整个项目的核心模块，实现了基于 Function Calling 的 Agent 循环：

**主要功能**:
- 接收用户输入
- 调用 LLM（带上工具列表）
- 如果 LLM 请求调用工具，执行工具并获取结果
- 将工具结果返回给 LLM
- 重复上述过程，直到 LLM 给出最终答案

**关键类**: `CodeMateAgent`

**与传统 ReAct 的区别**:
- ReAct: 解析 LLM 输出的文本（Action: ...），容易出错
- Function Calling: LLM 直接返回结构化的 tool_calls，更可靠

### 2. LLM 客户端模块 (`codemate_agent/llm/`)

**文件**: `codemate_agent/llm/client.py`

负责与智谱 GLM API 进行通信：

**主要功能**:
- 管理 API 密钥和连接
- 处理 Function Calling 请求
- Token 使用统计
- 错误处理和重试

**关键类**: `GLMClient`

### 3. 工具系统 (`codemate_agent/tools/`)

**文件**: `codemate_agent/tools/registry.py`, `codemate_agent/tools/base.py`

模块化的工具系统，管理所有可用的工具：

**工具分类**:
- **文件工具** (`file/`): 读取、写入、删除文件，列出目录
- **搜索工具** (`search/`): 搜索代码内容，查找定义
- **Shell 工具** (`shell/`): 执行命令行操作
- **Todo 工具** (`todo/`): 任务列表管理
- **Task 工具** (`task/`): 子代理委托

**关键类**: `ToolRegistry`, `Tool`

### 4. 数据模型 (`codemate_agent/schema.py`)

定义了整个 Agent 系统的数据结构：

**核心模型**:
- `Message`: 聊天消息（system/user/assistant/tool）
- `ToolCall`: 工具调用详情
- `LLMResponse`: LLM 响应结构
- `TokenUsage`: Token 使用统计
- `AgentState`: Agent 状态

### 5. 日志系统 (`codemate_agent/logging/`)

**文件**: `codemate_agent/logging/logger.py`, `codemate_agent/logging/trace_logger.py`, `codemate_agent/logging/metrics.py`

三层日志架构：

1. **运行时日志**: 基于 Rich 的彩色终端输出
2. **Trace 轨迹日志**: 记录完整的 Agent 执行过程，支持会话回放
3. **Metrics 统计**: Token、成本、性能指标

**关键类**: `TraceLogger`, `SessionMetrics`

### 6. CLI 入口 (`codemate_agent/cli.py`)

**文件**: `codemate_agent/cli.py`

命令行交互入口：

**主要功能**:
- 交互模式：持续对话
- 单次查询模式：一次性问答
- 配置管理：加载环境变量和配置文件
- 用户确认：危险操作需要用户确认

**关键函数**: `run_interactive()`, `run_single_prompt()`, `main()`

### 7. 任务规划器 (`codemate_agent/planner/`)

**文件**: `codemate_agent/planner/planner.py`

负责检测复杂任务并生成执行计划：

**主要功能**:
- 判断查询是否需要规划（复杂度判断）
- 生成执行计划（调用 LLM）
- 管理计划状态

**关键类**: `TaskPlanner`

### 8. 持久化系统 (`codemate_agent/persistence/`)

负责会话和记忆的持久化存储：

**主要功能**:
- 会话存储：保存对话历史
- 记忆管理：长期记忆存储
- 会话索引：快速检索历史会话

**关键类**: `SessionStorage`, `MemoryManager`, `SessionIndex`

### 9. 上下文压缩 (`codemate_agent/context/`)

**文件**: `codemate_agent/context/compressor.py`, `codemate_agent/context/truncator.py`

处理长对话的上下文压缩：

**主要功能**:
- 检测上下文长度
- 压缩历史消息
- 截断工具输出

**关键类**: `ContextCompressor`, `ObservationTruncator`

### 10. Skill 系统 (`codemate_agent/skill/`)

支持预定义的专业任务流程：

**可用 Skills**:
- `code-review`: 全面代码审查，检查安全漏洞、代码质量和最佳实践

**关键类**: `SkillManager`

### 11. 子代理系统 (`codemate_agent/subagent/`)

支持将任务委托给子代理处理：

**子代理类型**:
- `general`: 通用任务处理
- `explore`: 代码探索、文件搜索
- `plan`: 生成实现计划
- `summary`: 总结和提炼信息

**关键类**: `TaskTool`

### 12. 验证模块 (`codemate_agent/validation/`)

**文件**: `codemate_agent/validation/argument_validator.py`

统一验证工具调用参数：

**主要功能**:
- 参数类型验证
- 参数值检查
- 提供使用提示

**关键类**: `ArgumentValidator`

## 主要功能

### 1. 代码分析

- 读取和理解代码文件
- 分析项目结构
- 识别关键模块和依赖关系

### 2. 代码搜索

- 搜索特定的代码模式
- 查找函数/类定义
- 全文搜索代码内容

### 3. 代码审查

- 检查安全漏洞
- 代码质量评估
- 最佳实践建议

### 4. 重构建议

- 代码优化建议
- 结构改进方案
- 性能优化提示

### 5. 任务规划

- 自动分解复杂任务
- 生成执行计划
- 进度跟踪

## 项目结构

```
codemate-agent/
├── codemate_agent/           # 主包
│   ├── agent/                # Agent 核心实现
│   │   ├── agent.py          # 主要 Agent 类
│   │   └── loop_detector.py  # 循环检测
│   ├── llm/                  # LLM 客户端
│   │   └── client.py         # GLM API 客户端
│   ├── tools/                # 工具系统
│   │   ├── base.py           # 工具基类
│   │   ├── registry.py       # 工具注册器
│   │   ├── file/             # 文件工具
│   │   ├── search/           # 搜索工具
│   │   ├── shell/            # Shell 工具
│   │   ├── todo/             # Todo 工具
│   │   └── task/             # Task 工具
│   ├── logging/              # 日志系统
│   │   ├── logger.py         # 运行时日志
│   │   ├── trace_logger.py   # Trace 日志
│   │   └── metrics.py        # Metrics 统计
│   ├── persistence/           # 持久化系统
│   │   ├── session.py        # 会话存储
│   │   ├── memory.py         # 记忆管理
│   │   └── index.py          # 会话索引
│   ├── context/              # 上下文管理
│   │   ├── compressor.py     # 上下文压缩
│   │   └── truncator.py      # 输出截断
│   ├── planner/              # 任务规划器
│   │   └── planner.py        # TaskPlanner 类
│   ├── skill/                # Skill 系统
│   │   └── __init__.py       # SkillManager
│   ├── subagent/             # 子代理系统
│   │   └── __init__.py       # TaskTool
│   ├── validation/           # 验证模块
│   │   └── argument_validator.py  # 参数验证
│   ├── prompts/              # 提示词
│   │   └── system_prompt.py  # 系统提示词
│   ├── ui/                   # 用户界面
│   │   ├── display.py        # 显示组件
│   │   └── progress.py       # 进度显示
│   ├── commands/             # 命令处理
│   │   └── handler.py        # 命令处理器
│   ├── schema.py             # 数据模型
│   ├── config.py             # 配置管理
│   └── cli.py                # CLI 入口
├── logs/                     # 日志输出
│   ├── traces/               # Trace 轨迹文件
│   └── sessions/             # Metrics 统计文件
├── tests/                    # 单元测试
├── examples/                 # 示例项目
├── skills/                   # Skill 定义
│   └── code-review/          # 代码审查 Skill
│       └── SKILL.md
├── docs/                     # 文档
├── README.md                 # 项目说明
├── pyproject.toml            # 项目配置
├── requirements.txt          # 依赖列表
└── run.sh                    # 启动脚本
```

## 技术栈

- **Python** 3.10+
- **GLM-4** API (智谱 AI)
- **Pydantic** 2.x - 数据验证
- **Rich** - 终端 UI
- **prompt-toolkit** - 交互式输入
- **python-dotenv** - 环境变量管理

## 入口文件

1. **CLI 入口**: `codemate_agent/cli.py` - 命令行入口
2. **主 Agent 类**: `codemate_agent/agent/agent.py` - 核心逻辑
3. **启动脚本**: `run.sh` - 快速启动
4. **配置文件**: `pyproject.toml` - 项目配置

## 依赖关系

```
cli.py (入口)
  ├── GLMClient (LLM 客户端)
  ├── CodeMateAgent (核心 Agent)
  │   ├── ToolRegistry (工具注册)
  │   ├── TraceLogger (日志)
  │   ├── SessionMetrics (统计)
  │   ├── TaskPlanner (任务规划)
  │   ├── ContextCompressor (上下文压缩)
  │   └── SkillManager (Skill 管理)
  └── get_all_tools (工具加载)
```

## 版本信息

当前版本: **0.3.0** (见 `codemate_agent/__init__.py`)
