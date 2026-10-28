# ADR 0014：敏感内容 × 远端 embedding —— 把「绝不出网」变成真的

- 状态：Accepted
- 日期：2026-10-09
- 影响：`app/sensitive.py`、`app/memory/service.py`、`app/consolidate/service.py`、
  `app/ports/embedding.py` 及各 embedding 适配器

## 上下文

`.env.example` 与 `docs/DEPLOYMENT.md` 都推荐生产使用
`ERAHERM_EMBEDDING_BACKEND=openai`，同时 `.env.example` 写着：

> 敏感内容（含 秘密/红线/不要告诉 等词）自动拦截走本地，**绝不出网**（app/sensitive.py）

这句话在 0.10.1 之前是**假的**。`app/sensitive.py` 的词表只被三处调用：

1. `FallbackGraphExtractor`（LLM 图谱抽取）
2. `LLMReflectionPipeline`（LLM 纠正反射）
3. watchdog 的推送过滤

而 embedding 路径**完全不经过它**。也就是说：

- 用 `openai` embedding 时，每一条记忆正文都会被原样 POST 到外部服务
  —— 包括写着「这是秘密」的那条。**「绝不出网」只覆盖了 LLM 抽取/反射，不覆盖 embedding。**
- `LLMSummarizer`（整理时的 LLM 压缩）是第三个出网点，也是唯一**漏掉**守卫的一处。
- `llm_reflection` 的 `answer_text` 进了 prompt 却没被探测。

一句话：**我们承诺了一个我们没有实现的保证，而且是关于数据泄漏的保证。**

## 决策

### 1. 新增 `EmbeddingClient.is_remote`

三个内置适配器：`OpenAICompatibleEmbeddingClient.is_remote = True`，
`HashingEmbeddingClient` / `FastEmbedEmbeddingClient` = `False`。
Port 里作为协议属性声明，服务层用 `getattr(client, "is_remote", False)` 容错。

### 2. 远端 embedding + 敏感内容 = **拒绝**（fail-closed）

`app/sensitive.py` 新增 `remote_embedding_block_reason()` /
`assert_remote_embedding_allowed()`，在三处调用：

| 位置 | 时机 |
|---|---|
| `MemoryService.remember` | L2 落库**之前**（拒绝时不会留下没有向量的半条数据） |
| `MemoryService.recall` | 查询 embedding 之前（查询本身也可能含秘密） |
| `ConsolidationService._embed_in_batches` / 摘要写入前 | 聚类与摘要进入向量库之前 |

开关：`ERAHERM_SENSITIVE_REQUIRES_LOCAL_EMBEDDING`（默认 `true`）。
设 `false` 表示调用方**显式接受**"敏感正文会离开本机"这个风险。

行为：命中即返回 `400 validation_error`，错误信息直接给出两条出路
（换本地 embedding / 关掉开关）。

### 3. 词表只作为「最好努力」的过滤，不作为边界

我们在文档里改写措辞：这是**中文关键词匹配**，不是 DLP。
它拦得住"这是秘密"，拦不住"我的密码是 hunter2"、"the secret is …"、
身份证号或 API key。真正的边界只有一个：**本地 embedding**。

为了让这个认知不被悄悄忘掉，`tests/test_sensitive_policy.py` 里有一条
"反测试"：断言 `hunter2` / `the secret is …` **不被**识别为敏感 ——
谁要是把词表扩到能拦住它们，那条测试会失败，逼他去读本 ADR 的边界说明。

## 后果

### 正面

- 「敏感内容不出网」从**未实现的承诺**变成**可执行的保证**：
  在远端 embedding 下，敏感内容根本进不了入库路径。
- 三个出网点（LLM 抽取、LLM 反射、LLM 压缩）现在**全部**有守卫；
  `LLMSummarizer` 命中敏感词时回落本地启发式摘要。
- 选择权交给调用方，而且是显式的、要写进配置的。

### 负面 / 已知限制

- **功能代价**：远端 embedding + 默认开关下，含中文敏感词的记忆会被**拒绝入库**。
  这是刻意的取舍 —— 我们选择"拒绝写入"而不是"静默外发"。
- 词表是中文的，英文记忆基本不受保护；词典覆盖决定保护范围。
- 关键词匹配会有误伤（例如正常内容里出现"保密"会被拒），
  出错信息里给了关开关的办法。
- 仍**没有**真正的 DLP：不检测密钥格式、证件号、不成文的私密内容。
  如果部署场景要求这个，正确做法是本地模型 + 出口审计，而不是加词。

## 参考

- 实现：`app/sensitive.py`、`app/memory/service.py`（`_assert_embeddable`）、
  `app/consolidate/service.py`（`_embed_in_batches`、`LLMSummarizer`）
- 测试：`tests/test_sensitive_policy.py`
- 相关：[SECURITY.md](../../SECURITY.md)、[KNOWN_ISSUES.md](../KNOWN_ISSUES.md)
