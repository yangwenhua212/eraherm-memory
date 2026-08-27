# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""敏感内容防护回归测试：LLM 抽取/反射的输入命中敏感词 → 绝不调用外部 LLM。

铁律：记忆含敏感内容（秘密/红线/私事），内容出网 = 泄露。
命中敏感词的内容必须走本地规则/heuristic，外部 LLM 一次都不许碰。
"""

from __future__ import annotations

import pytest

from app.adapters.heuristic_reflection import HeuristicReflectionPipeline
from app.adapters.llm_graph_extractor import FallbackGraphExtractor, LLMGraphExtractor
from app.adapters.llm_reflection import LLMReflectionPipeline
from app.adapters.openai_llm import OpenAICompatibleLLM
from app.graph.extractor import RuleGraphExtractor
from app.sensitive import contains_sensitive


class _BoomLLM(OpenAICompatibleLLM):
    """一被调用就炸——敏感内容走到它=泄露，测试必须让它永远不触发。"""

    def __init__(self) -> None:
        super().__init__(api_key="sk-test", base_url="http://127.0.0.1:1")
        self.called = 0

    def complete_json(self, *, system: str, user: str) -> dict:
        self.called += 1
        raise AssertionError("LLM must NOT be called for sensitive content")


class _FakeLLM(OpenAICompatibleLLM):
    def __init__(self) -> None:
        super().__init__(api_key="sk-test", base_url="http://127.0.0.1:1")
        self.called = 0

    def complete_json(self, *, system: str, user: str) -> dict:
        self.called += 1
        return {
            "entities": [
                {"name": "杨文华", "entity_type": "person"},
                {"name": "EraHerm", "entity_type": "project"},
            ],
            "relations": [
                {
                    "from_name": "杨文华",
                    "to_name": "EraHerm",
                    "relation_type": "owned_by",
                    "confidence": 0.9,
                }
            ],
        }


SENSITIVE_TEXT = "这件事是秘密，绝对不提考研两个字，不要告诉任何人。"
NORMAL_TEXT = "杨文华开发了 EraHerm 记忆系统。"


# ---------- FallbackGraphExtractor ----------

def test_sensitive_text_skips_llm_extractor() -> None:
    llm = _BoomLLM()
    extractor = FallbackGraphExtractor(
        LLMGraphExtractor(llm), fallback=RuleGraphExtractor()
    )
    result = extractor.extract(SENSITIVE_TEXT)
    assert llm.called == 0  # 敏感内容一次 LLM 都不许调
    assert isinstance(result, object)  # 规则抽取器正常返回


def test_normal_text_calls_llm_extractor() -> None:
    llm = _FakeLLM()
    extractor = FallbackGraphExtractor(
        LLMGraphExtractor(llm), fallback=RuleGraphExtractor()
    )
    result = extractor.extract(NORMAL_TEXT)
    assert llm.called == 1
    assert result.relations[0].from_name == "杨文华"
    assert result.relations[0].to_name == "EraHerm"


# ---------- LLMReflectionPipeline ----------

def test_sensitive_reflection_skips_llm() -> None:
    llm = _BoomLLM()
    pipe = LLMReflectionPipeline(llm)
    draft = pipe.reflect(
        feedback_type="correct",
        correction_text="这是秘密，不要告诉别人",
        answer_text="旧答案",
        related_contents=["某个秘密事实"],
    )
    assert llm.called == 0
    # 结果来自 heuristic fallback：normalize 后的干净事实句
    assert draft.summary  # 非空即可，具体内容由 heuristic 决定


def test_normal_reflection_calls_llm() -> None:
    llm = _FakeLLM()
    pipe = LLMReflectionPipeline(llm)
    pipe.reflect(
        feedback_type="correct",
        correction_text="数据库实际用 PostgreSQL",
        answer_text="旧答案",
        related_contents=["数据库使用 MySQL"],
    )
    assert llm.called == 1


# ---------- contains_sensitive 公共函数 ----------

@pytest.mark.parametrize(
    "text",
    [
        "这是秘密",
        "碰到红线就停",
        "绝对不提那个词",
        "不要告诉任何人",
        "别让他知道这件事",
        "这事要保密",
        "只告诉你一个人",
        "私下处理",
        "考试的事不能提",
    ],
)
def test_contains_sensitive_hits(text: str) -> None:
    assert contains_sensitive(text)


@pytest.mark.parametrize(
    "text",
    ["正常记忆：杨文华开发了 EraHerm", "", None, "考研在六月启动", "今天吃了西红柿炒鸡蛋"],
)
def test_contains_sensitive_misses(text: str | None) -> None:
    assert not contains_sensitive(text)


def test_heuristic_reflection_unaffected() -> None:
    """启发式反射不需要防护（本地执行），但必须仍然可用。"""
    pipe = HeuristicReflectionPipeline()
    draft = pipe.reflect(
        feedback_type="correct",
        correction_text="数据库使用 PostgreSQL",
        answer_text="数据库用 MySQL",
        related_contents=["数据库使用 MySQL"],
    )
    assert draft.summary
