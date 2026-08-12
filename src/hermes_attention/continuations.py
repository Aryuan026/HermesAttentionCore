from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Sequence

from .claims import ClaimStore
from .db import RuntimeDatabase, canonical_json, iso, parse_time, stable_id, utc_now


class ContinuationStore(ClaimStore):
    table = "agent_continuations"
    id_column = "continuation_id"

    @property
    def source_kind(self) -> str:
        return "continuation"

    def source_version(self, row: sqlite3.Row) -> str:
        return stable_id(
            "version", row["goal"], row["stage"], row["due_at"],
            row["capability_refs_json"], row["source_refs_json"],
        )

    def is_due(self, row: sqlite3.Row, now: datetime) -> bool:
        due = parse_time(row["due_at"])
        return due is not None and due <= now

    def create(
        self,
        *,
        goal: str,
        stage: str,
        due_at: datetime,
        causal_root_id: str = "",
        parent_ref: str = "",
        capability_refs: Sequence[str] = (),
        source_refs: Sequence[str] = (),
        timezone_name: str = "Asia/Shanghai",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        if due_at <= current:
            raise ValueError("due_at must be in the future")
        continuation_id = stable_id(
            "continuation", causal_root_id, parent_ref, goal, stage, iso(due_at)
        )
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO agent_continuations (
                    continuation_id, causal_root_id, parent_ref, goal, stage,
                    capability_refs_json, source_refs_json, due_at, timezone,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    continuation_id, causal_root_id, parent_ref, goal, stage,
                    canonical_json(list(capability_refs)), canonical_json(list(source_refs)),
                    iso(due_at), timezone_name, iso(current), iso(current),
                ),
            )
        return {"created": cursor.rowcount == 1, "continuation_id": continuation_id}

    def due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or utc_now()
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM agent_continuations
                    WHERE status = 'pending' AND due_at <= ?
                    ORDER BY due_at, continuation_id""",
                (iso(current),),
            ).fetchall()
        return [
            {
                **dict(row),
                "capability_refs": json.loads(row["capability_refs_json"]),
                "source_refs": json.loads(row["source_refs_json"]),
                "source_version": self.source_version(row),
            }
            for row in rows
        ]
