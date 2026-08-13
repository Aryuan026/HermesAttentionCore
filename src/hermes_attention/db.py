from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return as_utc(value).isoformat(timespec="microseconds")


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return as_utc(parsed)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:length]}"


class RuntimeDatabase:
    """One private SQLite file with separate owner tables.

    Sharing a file is a deployment convenience. Each source store remains the
    only writer of its own rows; Attention only reads them and routes exact
    claims back to their owner.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_events (
                    event_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    provider_event_id TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    compact_payload_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    capability_hints_json TEXT NOT NULL DEFAULT '[]',
                    subject_ref TEXT NOT NULL,
                    coalesce_key TEXT NOT NULL,
                    followup_of TEXT NOT NULL,
                    priority_hint TEXT NOT NULL,
                    event_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    superseded_by TEXT NOT NULL DEFAULT '',
                    claim_token TEXT NOT NULL DEFAULT '',
                    claim_generation INTEGER NOT NULL DEFAULT 0,
                    claim_until TEXT NOT NULL DEFAULT '',
                    claimed_review_version TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(provider_id, provider_event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_events_due
                    ON agent_events(status, event_at, expires_at);

                CREATE TABLE IF NOT EXISTS agent_continuations (
                    continuation_id TEXT PRIMARY KEY,
                    causal_root_id TEXT NOT NULL,
                    parent_ref TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    capability_refs_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    claim_token TEXT NOT NULL DEFAULT '',
                    claim_generation INTEGER NOT NULL DEFAULT 0,
                    claim_until TEXT NOT NULL DEFAULT '',
                    claimed_review_version TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_continuations_due
                    ON agent_continuations(status, due_at);

                CREATE TABLE IF NOT EXISTS calendar_items (
                    item_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    context_note TEXT NOT NULL,
                    capability_refs_json TEXT NOT NULL DEFAULT '[]',
                    due_at TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    claim_token TEXT NOT NULL DEFAULT '',
                    claim_generation INTEGER NOT NULL DEFAULT 0,
                    claim_until TEXT NOT NULL DEFAULT '',
                    claimed_review_version TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_calendar_due
                    ON calendar_items(status, due_at);

                CREATE TABLE IF NOT EXISTS hermes_tasks (
                    task_id TEXT PRIMARY KEY,
                    parent_task_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    due_at TEXT NOT NULL DEFAULT '',
                    recurrence TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL,
                    warn_hours REAL NOT NULL DEFAULT 72,
                    grace_hours REAL NOT NULL DEFAULT 24,
                    next_check_at TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    form_schema_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    outcome TEXT NOT NULL DEFAULT '',
                    attention_seen_version TEXT NOT NULL DEFAULT '',
                    attention_seen_reason TEXT NOT NULL DEFAULT '',
                    claim_token TEXT NOT NULL DEFAULT '',
                    claim_generation INTEGER NOT NULL DEFAULT 0,
                    claim_until TEXT NOT NULL DEFAULT '',
                    claimed_review_version TEXT NOT NULL DEFAULT '',
                    semantic_changed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hermes_tasks_attention
                    ON hermes_tasks(status, kind, due_at, next_check_at);

                CREATE TABLE IF NOT EXISTS hermes_task_cycles (
                    cycle_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    cycle_ref TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    attention_seen_at TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, cycle_ref),
                    FOREIGN KEY(task_id) REFERENCES hermes_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS source_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_migrations (
                    migration_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routine_presence_state (
                    state_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL DEFAULT 0,
                    last_opened_at TEXT NOT NULL DEFAULT '',
                    next_due_at TEXT NOT NULL DEFAULT '',
                    last_reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )
            for table in (
                "agent_events",
                "agent_continuations",
                "calendar_items",
                "hermes_tasks",
            ):
                columns = {
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if "claimed_review_version" not in columns:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN "
                        "claimed_review_version TEXT NOT NULL DEFAULT ''"
                    )

    def receipts(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM source_receipts ORDER BY created_at, receipt_id"
            ).fetchall()
        return [
            {**dict(row), "result": json.loads(row["result_json"])} for row in rows
        ]
