from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Mapping

from .db import RuntimeDatabase, canonical_json, iso, parse_time, stable_id, utc_now


OUTCOMES = {"quiet", "acted", "scheduled", "reported", "deferred", "failed"}


class ClaimStore:
    """Shared mechanics for source-owned exact claims.

    Subclasses provide their table and identifier. Attention never writes these
    rows; it routes the selected source/version back to the owning store.
    """

    table: str
    id_column: str
    available_status = "pending"
    settled_status = "settled"

    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def _release_expired(self, connection: sqlite3.Connection, now: datetime) -> None:
        connection.execute(
            f"""
            UPDATE {self.table}
               SET status = ?, claim_token = '', claim_until = '', updated_at = ?
             WHERE status = 'claimed' AND claim_until != '' AND claim_until <= ?
            """,
            (self.available_status, iso(now), iso(now)),
        )

    def claim_exact(
        self,
        source_id: str,
        source_version: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._release_expired(connection, current)
            row = connection.execute(
                f"SELECT * FROM {self.table} WHERE {self.id_column} = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return {"claimed": False, "reason": "not_found"}
            actual_version = self.source_version(row)
            if actual_version != source_version:
                connection.rollback()
                return {"claimed": False, "reason": "source_version_changed"}
            if row["status"] != self.available_status:
                connection.rollback()
                return {"claimed": False, "reason": f"not_pending:{row['status']}"}
            if not self.is_due(row, current):
                connection.rollback()
                return {"claimed": False, "reason": "not_due"}
            generation = int(row["claim_generation"]) + 1
            token = f"claim_{secrets.token_urlsafe(24)}"
            claim_until = iso(current + timedelta(seconds=max(30, lease_seconds)))
            cursor = connection.execute(
                f"""
                UPDATE {self.table}
                   SET status = 'claimed', claim_token = ?, claim_generation = ?,
                       claim_until = ?, updated_at = ?
                 WHERE {self.id_column} = ? AND status = ?
                """,
                (token, generation, claim_until, iso(current), source_id, self.available_status),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return {"claimed": False, "reason": "claim_race"}
            connection.commit()
        return {
            "claimed": True,
            "source_id": source_id,
            "source_version": source_version,
            "claim_token": token,
            "claim_generation": generation,
            "claim_until": claim_until,
        }

    def settle(
        self,
        claim_token: str,
        outcome: str,
        *,
        result: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if outcome not in OUTCOMES:
            raise ValueError("invalid outcome")
        current = now or utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT * FROM {self.table} WHERE claim_token = ? AND status = 'claimed'",
                (claim_token,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return {"settled": False, "reason": "claim_not_current"}
            claim_until = parse_time(row["claim_until"])
            if claim_until is not None and claim_until < current:
                connection.rollback()
                return {"settled": False, "reason": "claim_expired"}
            source_id = str(row[self.id_column])
            target_status = self.settlement_status(row, outcome)
            receipt_id = stable_id(
                "receipt", self.source_kind, source_id, outcome, str(row["claim_generation"])
            )
            connection.execute(
                """
                INSERT INTO source_receipts (
                    receipt_id, source_kind, source_id, outcome, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id, self.source_kind, source_id, outcome,
                    canonical_json(dict(result or {})), iso(current),
                ),
            )
            connection.execute(
                f"""
                UPDATE {self.table}
                   SET status = ?, outcome = ?, claim_token = '',
                       claim_until = '', updated_at = ?
                 WHERE {self.id_column} = ? AND claim_token = ?
                """,
                (target_status, outcome, iso(current), source_id, claim_token),
            )
            self.after_settle(connection, row, outcome, current)
            connection.commit()
        return {
            "settled": True,
            "source_id": source_id,
            "receipt_id": receipt_id,
            "source_kind": self.source_kind,
            "outcome": outcome,
            "result": dict(result or {}),
        }

    def settlement_status(self, row: sqlite3.Row, outcome: str) -> str:
        return self.settled_status

    def after_settle(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        outcome: str,
        now: datetime,
    ) -> None:
        return None

    @property
    def source_kind(self) -> str:
        raise NotImplementedError

    def source_version(self, row: sqlite3.Row) -> str:
        raise NotImplementedError

    def is_due(self, row: sqlite3.Row, now: datetime) -> bool:
        raise NotImplementedError
