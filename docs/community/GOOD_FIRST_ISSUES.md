# Good First Issues（维护者草稿）

把下面几条复制到 GitHub Issues，并打上标签：`good first issue`、`help wanted`（文档类再加 `documentation`）。

---

## 1. README：补一行「Windows / Linux 复制 .env」对照

**标签：** `documentation` `good first issue`

**任务：** 在 README「3 分钟 MCP」或「HTTP 快速开始」里，明确写出：

- Windows：`copy .env.example .env`
- Unix：`cp .env.example .env`

并确认路径与当前仓库一致。

**验收：** 按 README 从零 clone 的读者不会卡在复制配置文件这一步。

---

## 2. mcp.json：把绝对路径改成占位说明

**标签：** `documentation` `good first issue`

**任务：** 根目录 [`mcp.json`](../../mcp.json) 里的 `cwd` 仍是本机绝对路径。改成注释/文档说明「请改成你的 clone 路径」，并在 [docs/MCP.md](../MCP.md) 加一句警告。

**验收：** 新人复制配置后知道必须改 `cwd`，不会直接连到 `D:/bk/agent`。

---

## 3. evals：加一条「无关查询应为空」case

**标签：** `good first issue` `help wanted`

**任务：** 在 [`evals/cases.json`](../../evals/cases.json) 增加用例：用户有一条数据库事实，查询「今晚吃啥」，期望 `items` 为空或至少不含该事实（与 `ERAHERM_RECALL_MIN_SCORE` 行为一致）。必要时扩展 harness 支持 `expect_empty` / `expect_none_contains`。

**验收：** `python -m evals.harness` 全绿。

---

## 4. Demo：纠正闭环引导文案

**标签：** `documentation` `good first issue`

**任务：** 在 [`demo/index.html`](../../demo/index.html) 反馈页加 3 步短指引：「写入 → 故意写错并纠正 → 再召回」，链到 `examples/correct_to_evolve.py`。

**验收：** 打开 `/demo/` 的人能不看源码走完闭环。

---

## 5. CHANGELOG：Unreleased 条目链接到相关文档小节

**标签：** `documentation` `good first issue`

**任务：** 在 [CHANGELOG.md](../../CHANGELOG.md) 里给召回门禁 / reembed / Hermes Tools 等条目补文档相对链接（DEPLOYMENT / HERMES_INTEGRATION / MCP）。

**验收：** 从 CHANGELOG 一点能跳到对应说明。
