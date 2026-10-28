# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

"""Optional APScheduler for nightly memory consolidation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger("eraherm.consolidate")

if TYPE_CHECKING:
    from app.consolidate.service import ConsolidationService
    from app.config import Settings


def start_consolidation_scheduler(
    consolidation: ConsolidationService,
    settings: Settings,
):
    """Start BackgroundScheduler if enabled. Returns scheduler or None."""
    if not settings.consolidation_enabled:
        return None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "ERAHERM_CONSOLIDATION_ENABLED=true but apscheduler not installed; "
            "pip install 'eraherm-memory[scheduler]'"
        )
        return None

    scheduler = BackgroundScheduler()

    def _job() -> None:
        try:
            # consolidate_all 带跨进程锁：多 worker 部署时只有一个进程真正执行，
            # 其余进程记一条 skipped 后返回（以前每个 worker 各跑一遍 → 重复摘要 + 重复删原文）。
            reports = consolidation.consolidate_all()
            skipped = [r for r in reports if r.skipped_reason]
            if skipped and len(skipped) == len(reports):
                logger.info("consolidation_skipped reason=%s", skipped[0].skipped_reason)
                return
            logger.info(
                "consolidation_done users=%s forgotten=%s compressed=%s",
                len(reports),
                sum(r.forgotten for r in reports),
                sum(r.compressed_clusters for r in reports),
            )
        except Exception:  # noqa: BLE001
            logger.exception("consolidation_job_failed")

    scheduler.add_job(
        _job,
        CronTrigger(
            hour=settings.consolidation_cron_hour,
            minute=settings.consolidation_cron_minute,
        ),
        id="memory_consolidation",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "consolidation_scheduler_started cron=%02d:%02d",
        settings.consolidation_cron_hour,
        settings.consolidation_cron_minute,
    )
    return scheduler
