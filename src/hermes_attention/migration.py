from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .db import RuntimeDatabase, canonical_json, iso, parse_time, stable_id, utc_now


MIGRATION_ID = "legacy_opportunities_to_owner_stores.v1"


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def migrate_legacy_opportunities(
    database: RuntimeDatabase,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Move only unambiguous legacy state; archive guesses instead of replaying.

    Settled rows stay untouched for audit. Pending channel transcripts and
    provider/self-life rows are archived because turning them into present
    intentions or replaying provider events would invent product semantics.
    """
    current = now or utc_now()
    result = {
        "applied": False,
        "continuations_migrated": 0,
        "channel_rows_archived": 0,
        "provider_rows_archived": 0,
        "unknown_rows_archived": 0,
    }
    with database.connect() as connection:
        if not _table_exists(connection, "opportunities"):
            return {**result, "reason": "legacy_table_absent"}
        previous = connection.execute(
            "SELECT result_json FROM runtime_migrations WHERE migration_id = ?",
            (MIGRATION_ID,),
        ).fetchone()
        if previous is not None:
            return {**json.loads(previous["result_json"]), "applied": False, "reason": "already_applied"}

        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT * FROM opportunities WHERE status = 'pending' ORDER BY created_at, opportunity_id"
        ).fetchall()
        for row in rows:
            kind = str(row["source_kind"])
            if kind == "continuation":
                due = parse_time(row["due_at"])
                if due is not None:
                    payload = json.loads(row["payload_json"] or "{}")
                    continuation_id = stable_id("continuation", "legacy", row["opportunity_id"])
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO agent_continuations (
                            continuation_id, causal_root_id, parent_ref, goal, stage,
                            capability_refs_json, source_refs_json, due_at, timezone,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, '[]', ?, ?, 'Asia/Shanghai', ?, ?)
                        """,
                        (
                            continuation_id,
                            str(payload.get("causal_opportunity_id") or ""),
                            str(row["opportunity_id"]),
                            str(row["title"]),
                            str(row["summary"]),
                            canonical_json([f"legacy:{row['opportunity_id']}"]),
                            iso(due),
                            str(row["created_at"] or iso(current)),
                            iso(current),
                        ),
                    )
                    result["continuations_migrated"] += 1
                archive_outcome = "migrated_to_continuation_store"
            elif kind == "chat_transcript":
                result["channel_rows_archived"] += 1
                archive_outcome = "legacy_channel_context_not_migrated"
            elif kind in {"self_life", "provider_event"}:
                result["provider_rows_archived"] += 1
                archive_outcome = "legacy_provider_event_not_replayed"
            else:
                result["unknown_rows_archived"] += 1
                archive_outcome = "legacy_semantics_not_guessed"
            connection.execute(
                """UPDATE opportunities SET status = 'archived', outcome = ?, updated_at = ?
                   WHERE opportunity_id = ? AND status = 'pending'""",
                (archive_outcome, iso(current), row["opportunity_id"]),
            )
        result["applied"] = True
        connection.execute(
            "INSERT INTO runtime_migrations (migration_id, result_json, applied_at) VALUES (?, ?, ?)",
            (MIGRATION_ID, canonical_json(result), iso(current)),
        )
        connection.commit()
    return result
