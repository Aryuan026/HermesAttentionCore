from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Sequence

from .claims import ClaimStore
from .db import RuntimeDatabase, canonical_json, iso, parse_time, stable_id, utc_now


class CalendarStore(ClaimStore):
    table = "calendar_items"
    id_column = "item_id"

    @property
    def source_kind(self) -> str:
        return "calendar"

    def source_version(self, row: sqlite3.Row) -> str:
        return stable_id(
            "version", row["title"], row["context_note"], row["due_at"],
            row["capability_refs_json"],
        )

    def is_due(self, row: sqlite3.Row, now: datetime) -> bool:
        due = parse_time(row["due_at"])
        return due is not None and due <= now

    def schedule(
        self,
        *,
        title: str,
        due_at: datetime,
        context_note: str = "",
        capability_refs: Sequence[str] = (),
        timezone_name: str = "Asia/Shanghai",
        item_id: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        identifier = item_id or stable_id("calendar", title, iso(due_at), context_note)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO calendar_items (
                    item_id, title, context_note, capability_refs_json, due_at,
                    timezone, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier, title.strip(), context_note.strip(),
                    canonical_json(list(capability_refs)), iso(due_at), timezone_name,
                    iso(current), iso(current),
                ),
            )
        return {"created": cursor.rowcount == 1, "item_id": identifier}

    def due_direct(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or utc_now()
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM calendar_items
                    WHERE status = 'pending' AND due_at <= ?
                    ORDER BY due_at, item_id""",
                (iso(current),),
            ).fetchall()
        return [
            {
                **dict(row),
                "capability_refs": json.loads(row["capability_refs_json"]),
                "source_version": self.source_version(row),
            }
            for row in rows
        ]
