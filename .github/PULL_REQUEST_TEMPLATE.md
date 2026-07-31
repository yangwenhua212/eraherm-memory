## Summary

<!-- 用 1～3 句话说明「为什么」需要这个改动 -->

-

## Test plan

- [ ] `python -m pytest -q`
- [ ] 若触及召回 / 反馈 / 图谱 / 整理：`python -m evals.harness`
- [ ] 若触及纠正闭环：`python examples/correct_to_evolve.py`（需本地 API 已启动，或说明跳过原因）
- [ ] 文档 / `CHANGELOG.md` `[Unreleased]` 已按需更新

## Notes

- 是否破坏 `/v1` 契约？
- 是否需要新 ADR？
- 关联 Issue：
