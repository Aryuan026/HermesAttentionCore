from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from .claims import ClaimStore
from .db import RuntimeDatabase, canonical_json, iso, parse_time, stable_id, utc_now


PRIORITIES = {"low", "normal", "high", "urgent", "critical"}
_SECRET_KEYS = re.compile(r"token|secret|password|authorization|cookie|api.?key", re.I)
_SECRET_VALUES = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]+|((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+"
)


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if _SECRET_KEYS.search(str(key)) else _safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUES.sub(lambda match: (match.group(1) or match.group(2) or "") + "[redacted]", value)[:2000]
    return value


@dataclass(frozen=True)
class AgentEvent:
    provider_id: str
    provider_event_id: str
    event_kind: str
    title: str
    event_at: datetime
    compact_payload: Mapping[str, Any] = field(default_factory=dict)
    source_refs: Sequence[str] = field(default_factory=tuple)
    subject_ref: str = ""
    coalesce_key: str = ""
    followup_of: str = ""
    priority_hint: str = "normal"
    expires_at: datetime | None = None
    capability_hints: Sequence[str] = field(default_factory=tuple)

    @property
    def event_id(self) -> str:
        return stable_id("event", self.provider_id, self.provider_event_id)

    @property
    def source_version(self) -> str:
        return stable_id(
            "version",
            self.event_kind,
            self.title,
            canonical_json(_safe_value(self.compact_payload)),
            iso(self.event_at),
        )


class InboxStore(ClaimStore):
    table = "agent_events"
    id_column = "event_id"

    @property
    def source_kind(self) -> str:
        return "provider_event"

    def source_version(self, row: sqlite3.Row) -> str:
        return str(row["source_version"])

    def is_due(self, row: sqlite3.Row, now: datetime) -> bool:
        expires = parse_time(row["expires_at"])
        return expires is None or expires > now

    def ingest(self, event: AgentEvent, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or utc_now()
        priority = event.priority_hint if event.priority_hint in PRIORITIES else "normal"
        expires = event.expires_at or (event.event_at + timedelta(days=7))
        safe_payload = _safe_value(event.compact_payload)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT event_id FROM agent_events WHERE provider_id = ? AND provider_event_id = ?",
                (event.provider_id, event.provider_event_id),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return {"inserted": False, "event_id": str(existing["event_id"])}
            if event.coalesce_key:
                connection.execute(
                    """
                    UPDATE agent_events
                       SET status = 'superseded', superseded_by = ?, updated_at = ?
                     WHERE provider_id = ? AND coalesce_key = ? AND status = 'pending'
                    """,
                    (event.event_id, iso(current), event.provider_id, event.coalesce_key),
                )
            connection.execute(
                """
                INSERT INTO agent_events (
                    event_id, provider_id, provider_event_id, source_version,
                    event_kind, title, compact_payload_json, source_refs_json,
                    capability_hints_json, subject_ref, coalesce_key, followup_of,
                    priority_hint, event_at, observed_at, expires_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id, event.provider_id, event.provider_event_id,
                    event.source_version, event.event_kind, " ".join(event.title.split())[:240],
                    canonical_json(safe_payload), canonical_json(list(event.source_refs)),
                    canonical_json(list(event.capability_hints)), event.subject_ref,
                    event.coalesce_key, event.followup_of, priority, iso(event.event_at),
                    iso(current), iso(expires), iso(current), iso(current),
                ),
            )
            connection.commit()
        return {"inserted": True, "event_id": event.event_id}

    def due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or utc_now()
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_events
                 WHERE status = 'pending' AND event_at <= ?
                   AND (expires_at = '' OR expires_at > ?)
                 ORDER BY event_at, event_id
                """,
                (iso(current), iso(current)),
            ).fetchall()
        return [
            {
                **dict(row),
                "compact_payload": json.loads(row["compact_payload_json"]),
                "source_refs": json.loads(row["source_refs_json"]),
                "capability_hints": json.loads(row["capability_hints_json"]),
            }
            for row in rows
        ]
