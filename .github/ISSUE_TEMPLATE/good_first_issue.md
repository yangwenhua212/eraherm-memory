---
name: Good first issue
about: 适合新人的小改动（文档 / 测试 / 示例）
title: "[good first issue] "
labels: ["good first issue", "help wanted"]
---

**任务一句话**


**为什么适合新人**
- [ ] 不改核心 API 语义
- [ ] 改动面小（通常 < 1～2 个文件）
- [ ] 有明确验收方式

**怎么开始**
1. Fork → 开分支  
2. `pip install -e ".[dev]"` → `python -m pytest -q`  
3. 按下方验收自测  

**验收**
- [ ] `python -m pytest -q` 通过  
- [ ] （若改召回/反馈）`python -m evals.harness` 或 `python examples/correct_to_evolve.py`  

**参考文件**
-
