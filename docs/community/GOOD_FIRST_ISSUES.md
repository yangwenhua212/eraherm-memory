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

## 2. mcp.json：把绝对路径改成占位说明 ✅ 已完成（0.10.2）

**标签：** `documentation` `good first issue`

**已完成：** 根目录 [`mcp.json`](../../mcp.json) 的 `cwd` 已改为占位值
`D:/path/to/eraherm-memory`，并移除了原先泄漏的本机路径；
[docs/MCP.md](../MCP.md) 也加了「必须改成你自己的 clone 路径」的警告。

**验收：** 新人复制配置后知道必须改 `cwd`。

---

## 3. evals：加一条「无关查询应为空」case ✅ 已完成（0.10.2）

**标签：** `good first issue` `help wanted`

**已完成：** [`evals/cases.json`](../../evals/cases.json) 已有两条负例
（`no_hard_pull_on_unrelated_query_identity` / `..._project`），
harness 也支持了 `expect_empty`、`expect_top1_contains`、`expect_max_items`
与 `recall@k`/`MRR`/p50/p95 指标。

**验收：** `python -m evals.harness` 全绿 —— 已满足（16/16）。

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
