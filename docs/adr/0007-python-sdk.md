# ADR 0007：提供 Python HTTP SDK

- 状态：Accepted
- 日期：2026-07-29

## 上下文

Host Agent 需要便捷集成，但不希望复制内核业务逻辑。

## 决策

在 `sdk/eraherm_memory` 提供薄封装 `MemoryClient`，仅调用 `/v1` HTTP API；不内嵌调度/抽取逻辑。

## 后果

- 正面：任意语言仍可用 HTTP；Python 体验体验。
- 负面：SDK 与 API 版本需同步维护。
