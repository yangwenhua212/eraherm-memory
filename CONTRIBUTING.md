# 贡献指南

感谢关注 EraHerm-Memory。本仓库是 **可嵌入的记忆内核**，不是完整 Agent 框架（见 [ADR 0001](docs/adr/0001-kernel-not-full-agent.md)）。

欢迎提 Issue / PR。不会写代码也可以从 **文档与示例** 开始（见下方 Good First Issue）。

## 许可（请先读）

- 项目默认许可证：**[MIT](LICENSE)**——可自由使用、修改、分发、商用，只需保留版权声明与许可声明。
- 注意：上层完整产品（如 HxSync）仍保留 AGPL-3.0 保护；本仓库作为底层模块采用 MIT 扩散。

提交 Pull Request 即表示你同意：

1. 你的贡献以 **MIT** 授权给项目及下游用户。

## 5 分钟跑通

要求：Python **≥ 3.12**

```bash
git clone https://github.com/yangwenhua212/eraherm-memory.git
cd eraherm-memory
python -m pip install -e ".[dev,mcp]"
cp .env.example .env          # Windows: copy .env.example .env
alembic upgrade head
python -m pytest -q
python -m evals.harness
```

可选 Demo：

```bash
uvicorn app.main:app --reload --port 8000
# 浏览器 http://localhost:8000/demo/
python examples/correct_to_evolve.py
```

不要提交 `.env`、数据库文件、`storage/` 下的运行时数据。

新增 `.py` 文件请保留文件头：

```python
# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT
```

（可用 `python scripts/add_license_headers.py` 批量补齐。）

## Good First Issue（适合第一次贡献）

在 Issues 里筛选标签 **`good first issue`**，或用模板「Good first issue / Docs」开新题。方向示例：

| 方向 | 例子 | 验收 |
|------|------|------|
| 文档 | README / MCP.md 笔误、过时路径、缺一步安装说明 | 按文档能从零跑通 |
| 示例 | 补一段 Hermes / MCP 配置注释、修正 `mcp.json` 示例路径 | 示例可复制即用 |
| 测试 | 给边界召回加 1 条 eval case（`evals/cases.json`） | `python -m evals.harness` 绿 |
| 文案 | 把含糊错误信息改清楚（不改 API 字段名） | 单测仍过 |

更完整的待办清单草稿：[docs/community/GOOD_FIRST_ISSUES.md](docs/community/GOOD_FIRST_ISSUES.md)（维护者可据此批量开 Issue）。

## 提交前检查

1. `python -m pytest -q` 通过  
2. 改了召回 / 反馈 / 图谱 / 整理时：再跑 `python -m evals.harness`（建议再跑 `python examples/correct_to_evolve.py`）  
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
