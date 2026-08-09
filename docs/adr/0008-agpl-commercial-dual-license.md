# ADR 0008：AGPL-3.0 与商业双许可

- 状态：Superseded（被 [ADR 0009](0009-mit-license.md) 取代：许可改为 MIT）
- 日期：2026-07-29

## 上下文

EraHerm-Memory 面向开源采用与 Hermes 等 Host 集成；同时希望对「闭源商用 / 不愿履行 Affero 义务」的使用保留收费权。

MIT/Apache 无法约束 SaaS 白嫖；纯 AGPL 又可免费用于完全开源的下游。

## 决策

1. 公开分发默认使用 **AGPL-3.0-only**（含网络交互条款）。  
2. 另提供 **商业许可**（见 `COMMERCIAL.md`），由版权方签约授权闭源使用。  
3. 贡献者须接受贡献可被纳入商业再许可（见 `CONTRIBUTING.md`），否则双许可不可持续。

## 后果

- 正面：开源传播与商业授权路径清晰；SaaS 闭源需谈商业许可。  
- 负面：部分公司对 AGPL 敏感，集成意愿下降；需明确版权归属与联系邮箱。  
- 跟进：商业询价见 GitHub [@yangwenhua212](https://github.com/yangwenhua212) / 仓库 Issues。
