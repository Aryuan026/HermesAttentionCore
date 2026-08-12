from __future__ import annotations

import json
import math
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
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]+|"
    r"((?:api[_-]?key|access[_-]?token|token|secret|password|authorization|"
    r"signature|sig)\s*[=:]\s*)[^\s&#]+"
)
MAX_PAYLOAD_DEPTH = 6
MAX_CONTAINER_ITEMS = 32
MAX_PAYLOAD_NODES = 256
MAX_PAYLOAD_BYTES = 16_384
MAX_SOURCE_REFS = 32
MAX_CAPABILITY_HINTS = 16
IDENTITY_LIMITS = {
    "provider_id": 120,
    "provider_event_id": 240,
    "event_kind": 120,
    "subject_ref": 240,
    "coalesce_key": 240,
    "followup_of": 240,
}


def _identity(value: Any, label: str, *, required: bool = False) -> str:
    normalized = "" if value is None else str(value).strip()
    if required and not normalized:
        raise ValueError(f"{label} is required")
    limit = IDENTITY_LIMITS[label]
    if len(normalized) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    return normalized


def _title(value: Any) -> str:
    return " ".join(str(value).split())[:240]


def _safe_value(
    value: Any,
    *,
    depth: int = 0,
    budget: list[int] | None = None,
) -> Any:
    if budget is None:
        budget = [MAX_PAYLOAD_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("compact_payload exceeds the node limit")
    if depth > MAX_PAYLOAD_DEPTH:
        raise ValueError("compact_payload exceeds the depth limit")
    if isinstance(value, Mapping):
        if len(value) > MAX_CONTAINER_ITEMS:
            raise ValueError("compact_payload mapping has too many keys")
        return {
            str(key)[:120]: (
                "[redacted]"
                if _SECRET_KEYS.search(str(key))
                else _safe_value(item, depth=depth + 1, budget=budget)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_CONTAINER_ITEMS:
            raise ValueError("compact_payload list has too many items")
        return [
            _safe_value(item, depth=depth + 1, budget=budget) for item in value
        ]
    if isinstance(value, str):
        return _SECRET_VALUES.sub(lambda match: (match.group(1) or match.group(2) or "") + "[redacted]", value)[:2000]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("compact_payload contains an unsupported value")


def _safe_strings(
    values: Sequence[str],
    *,
    label: str,
    limit: int,
    item_limit: int,
) -> list[str]:
    if isinstance(values, (str, bytes)) or len(values) > limit:
        raise ValueError(f"{label} exceeds its item limit")
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{label} must contain strings")
        result.append(_safe_value(value)[:item_limit])
    return result


def _safe_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    safe = _safe_value(value)
    encoded = canonical_json(safe).encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError("compact_payload exceeds the encoded size limit")
    return safe


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
        return stable_id(
            "event",
            _identity(self.provider_id, "provider_id", required=True),
            _identity(self.provider_event_id, "provider_event_id", required=True),
        )

    @property
    def source_version(self) -> str:
        return stable_id(
            "version",
            _identity(self.event_kind, "event_kind", required=True),
            _title(self.title),
            canonical_json(_safe_payload(self.compact_payload)),
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

    def expired_claim_status(self, row: sqlite3.Row) -> str:
        return "superseded" if row["superseded_by"] else self.available_status

    def claim_block_reason(self, row: sqlite3.Row) -> str | None:
        return "source_superseded" if row["superseded_by"] else None

    def invalidate_blocked_claim_in_tx(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        now: datetime,
    ) -> None:
        connection.execute(
            """UPDATE agent_events
                  SET status = 'superseded', claim_token = '', claim_until = '',
                      claimed_review_version = '', updated_at = ?
                WHERE event_id = ? AND status = 'claimed'""",
            (iso(now), row["event_id"]),
        )

    def ingest(self, event: AgentEvent, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or utc_now()
        priority = event.priority_hint if event.priority_hint in PRIORITIES else "normal"
        expires = event.expires_at or (event.event_at + timedelta(days=7))
        provider_id = _identity(event.provider_id, "provider_id", required=True)
        provider_event_id = _identity(
            event.provider_event_id, "provider_event_id", required=True
        )
        event_kind = _identity(event.event_kind, "event_kind", required=True)
        subject_ref = _identity(event.subject_ref, "subject_ref")
        coalesce_key = _identity(event.coalesce_key, "coalesce_key")
        followup_of = _identity(event.followup_of, "followup_of")
        title = _title(event.title)
        safe_payload = _safe_payload(event.compact_payload)
        safe_refs = _safe_strings(
            event.source_refs,
            label="source_refs",
            limit=MAX_SOURCE_REFS,
            item_limit=1000,
        )
        safe_hints = _safe_strings(
            event.capability_hints,
            label="capability_hints",
            limit=MAX_CAPABILITY_HINTS,
            item_limit=80,
        )
        event_id = stable_id("event", provider_id, provider_event_id)
        source_version = stable_id(
            "version",
            event_kind,
            title,
            canonical_json(safe_payload),
            iso(event.event_at),
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT event_id FROM agent_events WHERE provider_id = ? AND provider_event_id = ?",
                (provider_id, provider_event_id),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return {"inserted": False, "event_id": str(existing["event_id"])}
            if coalesce_key:
                connection.execute(
                    """
                    UPDATE agent_events
                       SET status = CASE WHEN status = 'pending'
                                         THEN 'superseded' ELSE status END,
                           superseded_by = ?, updated_at = ?
                     WHERE provider_id = ? AND coalesce_key = ?
                       AND status IN ('pending', 'claimed')
                    """,
                    (event_id, iso(current), provider_id, coalesce_key),
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
                    event_id, provider_id, provider_event_id,
                    source_version, event_kind, title,
                    canonical_json(safe_payload), canonical_json(safe_refs),
                    canonical_json(safe_hints), subject_ref,
                    coalesce_key, followup_of, priority, iso(event.event_at),
                    iso(current), iso(expires), iso(current), iso(current),
                ),
            )
            connection.commit()
        return {"inserted": True, "event_id": event_id}

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
