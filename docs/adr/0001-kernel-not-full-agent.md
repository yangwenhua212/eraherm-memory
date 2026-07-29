# ADR 0001：做成记忆内核而非完整 Agent 框架

- 状态：Accepted
- 日期：2026-07-29

## 上下文

Agent 产品易膨胀为「编排 + 工具 + 记忆 + UI」大一统。EraHerm-Memory 的差异化在于长期记忆、结构推理与反馈进化。

## 决策

本项目只交付 **Memory Kernel**（HTTP/SDK）：remember / recall / graph impact / feedback。  
不实现通用规划器、工具总线或完整 Chat 产品（demo UI 除外）。

## 后果

- 正面：边界清晰，可嵌入任意 Host Agent；迭代聚焦三大支柱。
- 负面：演示体验需 Host 或简易 demo 配合；不能单独冒充「全能 Agent」。
