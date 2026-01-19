---
name: code-review
description: |
  全面代码审查，检查安全漏洞、代码质量和最佳实践。
  使用场景：
  - "code review" / "代码审查" / "审查代码" / "review 一下"
  - "检查代码质量" / "代码有什么问题"
  - "安全审查" / "找漏洞"
---

# Code Review

执行系统化代码审查。

## 核心流程

### 1. 收集代码
```
Grep(pattern="def |class |function ", output_mode="count")  # 评估规模
Glob(pattern="**/*.py")  # 找到所有文件
```

### 2. 安全检查
按 [references/security.md](references/security.md) 清单逐项检查。

### 3. 质量检查
按 [references/quality.md](references/quality.md) 规则分析。

### 4. 输出报告
使用 [references/report-template.md](references/report-template.md) 格式。

## 快速决策

| 文件数 | 策略 |
|--------|------|
| 1-5 | 直接读取全部 |
| 6-20 | 采样核心文件 |
| 20+ | 先 grep 高风险模式，再定向审查 |

## ⚠️ 长报告写入策略

报告内容可能超过单次输出限制。**必须分段写入**：

```
write_file("report.md", "# 报告标题\n\n## 第一部分\n...")
append_file("report.md", "\n## 第二部分\n...")
append_file("report.md", "\n## 第三部分\n...")
```

每次写入控制在 2000 字以内，确保不被截断。

## 输出格式

```markdown
# 代码审查报告

## 概览
| 🔴 严重 | 🟠 高 | 🟡 中 | 🟢 低 |
|---------|-------|-------|-------|
| X       | X     | X     | X     |

## 问题列表
| 级别 | 文件:行 | 问题 | 建议 |
|------|---------|------|------|
| ...  | ...     | ...  | ...  |

## 优先行动
1. 先修 🔴 严重
2. ...
```
