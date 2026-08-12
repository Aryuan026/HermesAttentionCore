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

    def row_id(self, row: sqlite3.Row) -> str:
        return str(row[self.id_column])

    def review_version(self, row: sqlite3.Row, now: datetime) -> str:
        """Return the discrete semantics presented for one review decision."""
        return "source"

    def expired_claim_status(self, row: sqlite3.Row) -> str:
        return self.available_status

    def recover_expired_claims_in_tx(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> int:
        rows = connection.execute(
            f"""SELECT * FROM {self.table}
                 WHERE status = 'claimed' AND claim_until != '' AND claim_until <= ?""",
            (iso(now),),
        ).fetchall()
        recovered = 0
        for row in rows:
            cursor = connection.execute(
                f"""UPDATE {self.table}
                       SET status = ?, claim_token = '', claim_until = '',
                           claimed_review_version = '', updated_at = ?
                     WHERE {self.id_column} = ? AND status = 'claimed'
                       AND claim_until != '' AND claim_until <= ?""",
                (
                    self.expired_claim_status(row),
                    iso(now),
                    self.row_id(row),
                    iso(now),
                ),
            )
            recovered += cursor.rowcount
        return recovered

    def recover_expired_claims(self, *, now: datetime | None = None) -> int:
        current = now or utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            recovered = self.recover_expired_claims_in_tx(connection, current)
            connection.commit()
        return recovered

    def claim_block_reason(self, row: sqlite3.Row) -> str | None:
        return None

    def invalidate_blocked_claim_in_tx(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        now: datetime,
    ) -> None:
        return None

    def current_claim_in_tx(
        self,
        connection: sqlite3.Connection,
        claim_token: str,
        now: datetime,
    ) -> tuple[sqlite3.Row | None, str | None]:
        row = connection.execute(
            f"SELECT * FROM {self.table} WHERE claim_token = ? AND status = 'claimed'",
            (claim_token,),
        ).fetchone()
        if row is None:
            return None, "claim_not_current"
        claim_until = parse_time(row["claim_until"])
        if claim_until is not None and claim_until <= now:
            connection.execute(
                f"""UPDATE {self.table}
                       SET status = ?, claim_token = '', claim_until = '',
                           claimed_review_version = '', updated_at = ?
                     WHERE {self.id_column} = ? AND claim_token = ?""",
                (
                    self.expired_claim_status(row),
                    iso(now),
                    self.row_id(row),
                    claim_token,
                ),
            )
            return None, "claim_expired"
        blocked = self.claim_block_reason(row)
        if blocked:
            self.invalidate_blocked_claim_in_tx(connection, row, now)
            return None, blocked
        if self.review_version(row, now) != str(row["claimed_review_version"]):
            connection.execute(
                f"""UPDATE {self.table}
                       SET status = ?, claim_token = '', claim_until = '',
                           claimed_review_version = '', updated_at = ?
                     WHERE {self.id_column} = ? AND claim_token = ?""",
                (
                    self.expired_claim_status(row),
                    iso(now),
                    self.row_id(row),
                    claim_token,
                ),
            )
            return None, "semantic_changed"
        return row, None

    def validate_claim(
        self,
        claim_token: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row, reason = self.current_claim_in_tx(connection, claim_token, current)
            connection.commit()
        if row is None:
            return {"valid": False, "reason": reason}
        return {
            "valid": True,
            "source_kind": self.source_kind,
            "source_id": self.row_id(row),
            "source_version": self.source_version(row),
            "review_version": str(row["claimed_review_version"]),
            "claim_generation": int(row["claim_generation"]),
            "claim_until": str(row["claim_until"]),
        }

    def freeze_available_in_tx(
        self,
        connection: sqlite3.Connection,
        source_id: str,
        source_version: str,
        review_version: str,
        now: datetime,
    ) -> tuple[sqlite3.Row | None, str | None]:
        row = connection.execute(
            f"SELECT * FROM {self.table} WHERE {self.id_column} = ?",
            (source_id,),
        ).fetchone()
        if row is None or row["status"] != self.available_status:
            return None, "review_member_not_current"
        if self.source_version(row) != source_version:
            return None, "review_member_version_changed"
        if not self.is_due(row, now):
            return None, "review_member_not_due"
        if self.review_version(row, now) != review_version:
            return None, "review_member_semantic_changed"
        return row, None

    def settle_row_in_tx(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        outcome: str,
        *,
        result: Mapping[str, Any],
        receipt_scope: str,
        now: datetime,
        increment_generation: bool = False,
    ) -> str:
        if outcome not in OUTCOMES:
            raise ValueError("invalid outcome")
        source_id = self.row_id(row)
        generation = int(row["claim_generation"]) + int(increment_generation)
        receipt_id = stable_id(
            "receipt", self.source_kind, source_id, outcome, receipt_scope
        )
        connection.execute(
            """INSERT INTO source_receipts (
                   receipt_id, source_kind, source_id, outcome, result_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                receipt_id,
                self.source_kind,
                source_id,
                outcome,
                canonical_json(dict(result)),
                iso(now),
            ),
        )
        connection.execute(
            f"""UPDATE {self.table}
                   SET status = ?, outcome = ?, claim_token = '',
                       claim_generation = ?, claim_until = '',
                       claimed_review_version = '', updated_at = ?
                 WHERE {self.id_column} = ?""",
            (
                self.settlement_status(row, outcome),
                outcome,
                generation,
                iso(now),
                source_id,
            ),
        )
        self.after_settle(connection, row, outcome, now)
        return receipt_id

    def claim_exact(
        self,
        source_id: str,
        source_version: str,
        review_version: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.recover_expired_claims_in_tx(connection, current)
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
            if self.review_version(row, current) != review_version:
                connection.rollback()
                return {"claimed": False, "reason": "semantic_changed"}
            generation = int(row["claim_generation"]) + 1
            token = f"claim_{secrets.token_urlsafe(24)}"
            claim_until = iso(current + timedelta(seconds=max(30, lease_seconds)))
            cursor = connection.execute(
                f"""
                UPDATE {self.table}
                   SET status = 'claimed', claim_token = ?, claim_generation = ?,
                       claim_until = ?, claimed_review_version = ?, updated_at = ?
                 WHERE {self.id_column} = ? AND status = ?
                """,
                (
                    token,
                    generation,
                    claim_until,
                    review_version,
                    iso(current),
                    source_id,
                    self.available_status,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return {"claimed": False, "reason": "claim_race"}
            connection.commit()
        return {
            "claimed": True,
            "source_id": source_id,
            "source_version": source_version,
            "review_version": review_version,
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
            row, reason = self.current_claim_in_tx(connection, claim_token, current)
            if row is None:
                connection.commit()
                return {"settled": False, "reason": reason}
            source_id = self.row_id(row)
            receipt_id = self.settle_row_in_tx(
                connection,
                row,
                outcome,
                result=dict(result or {}),
                receipt_scope=str(row["claim_generation"]),
                now=current,
            )
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
