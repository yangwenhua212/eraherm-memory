# ADR 0009：许可改为 MIT

- 状态：Accepted
- 日期：2026-08-09
- 取代：[ADR 0008](0008-agpl-commercial-dual-license.md)（AGPL-3.0 与商业双许可，Superseded）

## 上下文

EraHerm-Memory 定位是**可嵌入的记忆内核**——基础设施组件，不是完整产品。别人要把它集成进自己的系统。

用 AGPL v3 时，大公司会绕道走；用 MIT，他们可以直接 `pip install eraherm-memory` 集成，不需要任何法务评估。我们积累的是**生态**，而不仅仅是代码。

上层完整产品（HxSync 等）继续用 AGPL v3 保护。一个守，一个攻，互补不冲突。

## 决策

1. EraHerm-Memory 公开分发默认使用 **MIT License**（见 `LICENSE`），可自由使用、修改、分发、商用，只需保留版权声明与许可声明。
2. 删除 `COMMERCIAL.md` 与双许可机制（MIT 已允许一切商业使用，不再需要另售商业许可）。
3. 源码文件头统一为 `SPDX-License-Identifier: MIT`。
4. 上层完整产品（如 HxSync）仍保留 AGPL-3.0；本决策只影响 eraherm-memory 底层模块。

## 后果

- 正面：集成门槛降到零，生态扩散更快；GitHub 上 MIT 是开发者最熟悉、最友好的协议。
- 正面：MIT 不意味着放弃著作权——版权人仍保留署名权与版权声明要求。
- 负面：无法约束 SaaS 白嫖行为（AGPL 可以）；这是「要生态」的代价，接受。
- 跟进：保持 LICENSE 与 pyproject.toml 的 license 声明一致；README 中说明与 HxSync（AGPL）的区分。
