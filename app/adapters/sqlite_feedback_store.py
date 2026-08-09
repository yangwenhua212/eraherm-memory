# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from typing import Optional, Sequence

from sqlmodel import Session, SQLModel, select

from app.models import FeedbackEventRow, ReflectionRecordRow


class SqliteFeedbackStore:
    def __init__(self, engine) -> None:
        self.engine = engine
        SQLModel.metadata.create_all(self.engine)

    def create_feedback(self, row: FeedbackEventRow) -> FeedbackEventRow:
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    def get_feedback(self, feedback_id: str) -> Optional[FeedbackEventRow]:
        with Session(self.engine) as db:
            row = db.get(FeedbackEventRow, feedback_id)
            if row is not None:
                db.expunge(row)
            return row

    def create_reflection(self, row: ReflectionRecordRow) -> ReflectionRecordRow:
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    def get_reflection_by_feedback(self, feedback_id: str) -> Optional[ReflectionRecordRow]:
        with Session(self.engine) as db:
            stmt = select(ReflectionRecordRow).where(ReflectionRecordRow.feedback_id == feedback_id)
            row = db.exec(stmt).first()
            if row is not None:
                db.expunge(row)
            return row

    def save_reflection(self, row: ReflectionRecordRow) -> ReflectionRecordRow:
        with Session(self.engine) as db:
            merged = db.merge(row)
            db.commit()
            db.refresh(merged)
            db.expunge(merged)
            return merged


def dumps_ids(ids: Sequence[str] | None) -> str:
    return json.dumps(list(ids or []), ensure_ascii=False)


def loads_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    data = json.loads(raw)
    return [str(x) for x in data]
