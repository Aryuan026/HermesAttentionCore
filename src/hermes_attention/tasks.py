from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .claims import ClaimStore
from .db import RuntimeDatabase, canonical_json, iso, parse_time, stable_id, utc_now


TASK_KINDS = {"scheduled", "standing", "periodic"}

class TaskStore(ClaimStore):
    table = "hermes_tasks"
    id_column = "task_id"
    available_status = "active"
    settled_status = "active"

    @property
    def source_kind(self) -> str:
        return "ongoing"

    @staticmethod
    def _version(row: Mapping[str, Any], cycle: Mapping[str, Any]) -> str:
        return stable_id(
            "version",
            row["kind"], row["title"], row["summary"], row["due_at"],
            row["next_check_at"], row["pinned"], row["blocked"],
            row["form_schema_json"], cycle.get("cycle_ref", ""), cycle.get("status", ""),
        )

    def source_version(self, row: sqlite3.Row) -> str:
        cycle = self.current_cycle(str(row["task_id"]))
        return self._version(row, cycle)

    def is_due(self, row: sqlite3.Row, now: datetime) -> bool:
        return self._attention_reason(row, now) is not None

    def review_version(self, row: sqlite3.Row, now: datetime) -> str:
        return self._attention_reason(row, now) or ""

    def create(
        self,
        *,
        kind: str,
        title: str,
        summary: str = "",
        due_at: datetime | None = None,
        recurrence: str = "",
        next_check_at: datetime | None = None,
        parent_task_id: str = "",
        pinned: bool = False,
        form_schema: Mapping[str, Any] | None = None,
        timezone_name: str = "Asia/Shanghai",
        warn_hours: float = 72,
        grace_hours: float = 24,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if kind not in TASK_KINDS:
            raise ValueError("invalid task kind")
        if kind == "scheduled" and due_at is None:
            raise ValueError("scheduled task requires due_at")
        if kind == "periodic" and recurrence != "monthly":
            raise ValueError("periodic task currently requires monthly recurrence")
        current = now or utc_now()
        task_id = stable_id("task", kind, parent_task_id, title, iso(current))
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO hermes_tasks (
                    task_id, parent_task_id, kind, title, summary, due_at,
                    recurrence, timezone, warn_hours, grace_hours, next_check_at,
                    pinned, form_schema_json, semantic_changed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, parent_task_id, kind, title.strip(), summary.strip(),
                    iso(due_at) if due_at else "", recurrence, timezone_name,
                    max(0.0, warn_hours), max(0.0, grace_hours),
                    iso(next_check_at) if next_check_at else "", int(pinned),
                    canonical_json(dict(form_schema or {})), iso(current), iso(current), iso(current),
                ),
            )
        if kind in {"standing", "periodic"}:
            self._ensure_cycle(task_id, current)
        return {"created": True, "task_id": task_id}

    def update(
        self,
        task_id: str,
        *,
        summary: str | None = None,
        due_at: datetime | None = None,
        next_check_at: datetime | None = None,
        pinned: bool | None = None,
        blocked: bool | None = None,
        form_schema: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        changes: dict[str, Any] = {}
        if summary is not None:
            changes["summary"] = summary.strip()
        if due_at is not None:
            changes["due_at"] = iso(due_at)
        if next_check_at is not None:
            changes["next_check_at"] = iso(next_check_at)
        if pinned is not None:
            changes["pinned"] = int(pinned)
        if blocked is not None:
            changes["blocked"] = int(blocked)
        if form_schema is not None:
            changes["form_schema_json"] = canonical_json(dict(form_schema))
        if not changes:
            return {"updated": False, "reason": "no_changes"}
        assignments = ", ".join(f"{name} = ?" for name in changes)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"""UPDATE hermes_tasks SET {assignments}, semantic_changed_at = ?, updated_at = ?
                     WHERE task_id = ? AND status = 'active'""",
                (*changes.values(), iso(current), iso(current), task_id),
            )
        return {"updated": cursor.rowcount == 1, "task_id": task_id}

    def _ensure_cycle(self, task_id: str, current: datetime) -> dict[str, Any]:
        with self.database.connect() as connection:
            task = connection.execute(
                "SELECT timezone FROM hermes_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise ValueError("task not found")
            local = current.astimezone(ZoneInfo(task["timezone"]))
            cycle_ref = f"{local.year:04d}-{local.month:02d}"
            cycle_id = stable_id("cycle", task_id, cycle_ref)
            connection.execute(
                """INSERT OR IGNORE INTO hermes_task_cycles (
                       cycle_id, task_id, cycle_ref, started_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (cycle_id, task_id, cycle_ref, iso(current), iso(current)),
            )
            row = connection.execute(
                "SELECT * FROM hermes_task_cycles WHERE cycle_id = ?", (cycle_id,)
            ).fetchone()
        return dict(row)

    def current_cycle(self, task_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT * FROM hermes_task_cycles WHERE task_id = ?
                    ORDER BY cycle_ref DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
        return dict(row) if row else {}

    def maintain(self, *, now: datetime | None = None) -> dict[str, int]:
        """Create new periodic cycles outside Attention's read-only build."""
        current = now or utc_now()
        created = 0
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT task_id FROM hermes_tasks WHERE status = 'active' AND kind = 'periodic'"
            ).fetchall()
        for row in rows:
            before = self.current_cycle(row["task_id"])
            after = self._ensure_cycle(row["task_id"], current)
            created += int(not before or before.get("cycle_id") != after.get("cycle_id"))
        return {"cycles_created": created}

    def _attention_reason(self, row: sqlite3.Row, now: datetime) -> str | None:
        version = self.source_version(row)
        unseen = row["attention_seen_version"] != version
        if bool(row["pinned"]) and unseen:
            return "pinned"
        if bool(row["blocked"]) and unseen:
            return "blocked"
        next_check = parse_time(row["next_check_at"])
        if next_check is not None and next_check <= now and unseen:
            return "next_check"
        if row["kind"] == "scheduled":
            due = parse_time(row["due_at"])
            if due is not None and now >= due - timedelta(hours=float(row["warn_hours"])):
                if now > due + timedelta(hours=float(row["grace_hours"])):
                    phase = "expired"
                else:
                    phase = "overdue" if now >= due else "warning"
                return phase if row["attention_seen_reason"] != phase else None
        cycle = self.current_cycle(str(row["task_id"]))
        if (
            cycle
            and cycle.get("status") == "active"
            and not cycle.get("attention_seen_at")
        ):
            return "new_cycle"
        if row["kind"] in {"standing", "periodic"} and unseen:
            return "new" if not row["attention_seen_version"] else "changed"
        return None

    def due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or utc_now()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hermes_tasks WHERE status = 'active' ORDER BY created_at, task_id"
            ).fetchall()
        result = []
        for row in rows:
            reason = self._attention_reason(row, current)
            if reason is None:
                continue
            due = parse_time(row["due_at"])
            due_proximity = 0.0
            if due is not None:
                window = max(1.0, float(row["warn_hours"]))
                due_proximity = max(0.0, min(1.0, 1.0 - (due - current).total_seconds() / 3600 / window))
            result.append(
                {
                    **dict(row),
                    "attention_reason": reason,
                    "due_proximity": due_proximity,
                    "form_schema": json.loads(row["form_schema_json"]),
                    "source_version": self.source_version(row),
                    "review_version": self.review_version(row, current),
                }
            )
        return result

    def complete_cycle(
        self,
        task_id: str,
        *,
        result: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cycle = connection.execute(
                """SELECT * FROM hermes_task_cycles WHERE task_id = ?
                    ORDER BY cycle_ref DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
            if cycle is None:
                connection.rollback()
                return {"completed": False, "reason": "cycle_not_found"}
            cursor = connection.execute(
                """UPDATE hermes_task_cycles SET status = 'completed', result_json = ?,
                       completed_at = ?, updated_at = ?
                     WHERE cycle_id = ? AND status = 'active'""",
                (canonical_json(dict(result or {})), iso(current), iso(current), cycle["cycle_id"]),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return {
                    "completed": False,
                    "reason": "cycle_not_active",
                    "cycle_id": cycle["cycle_id"],
                }
            task = connection.execute(
                "SELECT * FROM hermes_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                connection.rollback()
                return {"completed": False, "reason": "task_not_found"}
            completed_cycle = {**dict(cycle), "status": "completed"}
            version = self._version(task, completed_cycle)
            connection.execute(
                """UPDATE hermes_tasks SET attention_seen_version = ?,
                       attention_seen_reason = 'cycle_completed', updated_at = ?
                     WHERE task_id = ?""",
                (version, iso(current), task_id),
            )
            connection.commit()
        return {"completed": True, "cycle_id": cycle["cycle_id"]}

    def settlement_status(self, row: sqlite3.Row, outcome: str) -> str:
        if row["kind"] == "scheduled" and outcome in {
            "acted", "reported", "quiet", "scheduled",
        }:
            return "settled"
        return "active"

    def after_settle(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        outcome: str,
        now: datetime,
    ) -> None:
        reason = self._attention_reason(row, now) or ""
        cycle_row = connection.execute(
            """SELECT * FROM hermes_task_cycles WHERE task_id = ?
                ORDER BY cycle_ref DESC LIMIT 1""",
            (row["task_id"],),
        ).fetchone()
        cycle = dict(cycle_row) if cycle_row is not None else {}
        connection.execute(
            """UPDATE hermes_tasks SET attention_seen_version = ?,
                   attention_seen_reason = ?, updated_at = ? WHERE task_id = ?""",
            (self._version(row, cycle), reason, iso(now), row["task_id"]),
        )
        if cycle_row is not None:
            connection.execute(
                """UPDATE hermes_task_cycles SET attention_seen_at = ?, updated_at = ?
                     WHERE cycle_id = ?""",
                (iso(now), iso(now), cycle_row["cycle_id"]),
            )
