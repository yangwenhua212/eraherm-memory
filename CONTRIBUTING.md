# 贡献指南

感谢关注 EraHerm-Memory。本仓库是 **可嵌入的记忆内核**，不是完整 Agent 框架（见 [ADR 0001](docs/adr/0001-kernel-not-full-agent.md)）。

## 许可（请先读）

- 项目默认许可证：**[AGPL-3.0-only](LICENSE)**
- 闭源商用另见：**[COMMERCIAL.md](COMMERCIAL.md)**（双许可）

提交 Pull Request 即表示你同意：

1. 你的贡献以 **AGPL-3.0-only** 授权给项目及下游用户；并且  
2. 授予版权方将你的贡献纳入 **商业再许可** 的非独占权利（维持双许可所必需）。

若不能接受第 2 点，请在 PR 描述中写明；该贡献可能无法合入主干。

## 开发环境

要求：Python **≥ 3.12**

```bash
python -m pip install -e ".[dev,mcp,scheduler]"
copy .env.example .env   # Windows；Unix: cp .env.example .env
alembic upgrade head
python -m pytest -q
python -m evals.harness
```

不要提交 `.env`、数据库文件、`storage/` 下的运行时数据。

新增 `.py` 文件请保留文件头：

```python
# Copyright (c) 2026 EraHerm-Memory Authors.
# SPDX-License-Identifier: AGPL-3.0-only
# Commercial licensing: see COMMERCIAL.md
```

（可用 `python scripts/add_license_headers.py` 批量补齐。）

## 提交前检查

1. `python -m pytest -q` 通过  
2. `python -m evals.harness` 全绿（改了召回/反馈/图谱/整理时必跑）  
3. 公共 API 变更同步：`docs/specs/API.md`、必要时 `CHANGELOG.md` `[Unreleased]`  
4. 架构取舍写 ADR（`docs/adr/`），不要只改代码不留决策  

## PR 范围建议

| 欢迎 | 请先开 Issue 讨论 |
|------|-------------------|
| Bugfix、测试、文档、Adapter | 换掉三大支柱语义 |
| 新可选后端（Port 已有） | 把编排/Chat UI 塞进内核 |
| Hermes/Host 示例增强 | 无触发条件的分布式大重构 |

## 代码约定

- 业务只依赖 `app/ports/*`；存储/模型走 Adapter + `container.py`  
- 默认保持「单机零额外中间件可跑」；重依赖放 optional extras  
- 回复/文档默认中文亦可；代码标识符与 API 字段用英文  

## 安全问题

请勿在公开 Issue 里贴可利用细节；见 [SECURITY.md](SECURITY.md)。
