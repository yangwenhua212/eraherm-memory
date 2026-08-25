# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""图谱实体抽取质量回归：虚词/否定残留/碎片必须被过滤。

背景：2026-08-25 生产库 13 个实体里 9 个是垃圾——
「然后」「不」「方式」「不是 MySQL」「把两个完全不同的东西混在一起说了」
等虚词/否定残留/碎片被抽成实体，污染 impact 查询与图谱质量。
根因：主语正则无停用词过滤、宾语切分未清否定残留、无实体质量门槛。
"""

from __future__ import annotations

from app.graph.extractor import RuleGraphExtractor


def _names(result) -> set[str]:
    return {e.name for e in result.entities}


def test_extract_skips_stopwords_and_fragments() -> None:
    ex = RuleGraphExtractor()
    # 真实场景句（来自生产库历史垃圾实体）：
    # 「然后」当主语、「不是 MySQL」当宾语、「不」当主语
    text = (
        "数据库使用 PostgreSQL，不是 MySQL。"
        "然后 Hermes 使用 EraHerm。"
        "不，直接通过 HTTP 调用。"
    )
    result = ex.extract(text)
    names = _names(result)

    assert "PostgreSQL" in names
    assert "Hermes" in names
    assert "EraHerm" in names
    # 垃圾必须全部被过滤
    assert "不" not in names
    assert "然后" not in names
    assert "不是 MySQL" not in names
    assert "直接通过 HTTP 调用" not in names


def test_extract_keeps_valid_relations() -> None:
    ex = RuleGraphExtractor()
    result = ex.extract("A服务依赖B服务和Redis。C服务依赖A服务。")
    names = _names(result)
    assert {"A服务", "B服务", "Redis", "C服务"} <= names
    assert len(result.relations) >= 2


def test_extract_filters_single_char_noise() -> None:
    ex = RuleGraphExtractor()
    # 主语是单字虚词（不/就/也）或标点必须跳过
    result = ex.extract("不，A服务依赖B服务。")
    names = _names(result)
    assert "不" not in names
    assert "A服务" in names
