from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .db import RuntimeDatabase, as_utc, iso, parse_time, stable_id, utc_now


DEFAULT_MIN_GAP_MINUTES = 120
DEFAULT_JITTER_SECONDS = 3600
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_SLEEP_START_HOUR = 1
DEFAULT_SLEEP_END_HOUR = 8
STATE_ID = "routine_presence"


class PresenceCadenceStore:
    """Bound empty-pool Agent wakes without turning actions into candidates."""

    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def open_empty_wake(
        self,
        *,
        now: datetime | None = None,
        min_gap_minutes: int = DEFAULT_MIN_GAP_MINUTES,
        jitter_seconds: int = DEFAULT_JITTER_SECONDS,
        timezone_name: str = DEFAULT_TIMEZONE,
        sleep_start_hour: int = DEFAULT_SLEEP_START_HOUR,
        sleep_end_hour: int = DEFAULT_SLEEP_END_HOUR,
    ) -> dict[str, Any]:
        current = as_utc(now or utc_now())
        gap = max(15, min(int(min_gap_minutes), 10_080))
        jitter = max(0, min(int(jitter_seconds), 86_400))
        zone = ZoneInfo(timezone_name)
        start = _hour(sleep_start_hour)
        end = _hour(sleep_end_hour)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM routine_presence_state WHERE state_id = ?",
                (STATE_ID,),
            ).fetchone()
            generation = int(row["generation"] or 0) if row else 0
            due_at = parse_time(row["next_due_at"]) if row else current
            due_at = _coalesce_sleep(
                due_at or current,
                zone=zone,
                start_hour=start,
                end_hour=end,
                seed=f"{STATE_ID}|{generation}|initial",
            )
            if row is None:
                connection.execute(
                    """INSERT INTO routine_presence_state (
                           state_id, generation, last_opened_at, next_due_at,
                           last_reason, updated_at
                       ) VALUES (?, 0, '', ?, '', ?)""",
                    (STATE_ID, iso(due_at), iso(current)),
                )
            elif iso(due_at) != str(row["next_due_at"] or ""):
                connection.execute(
                    """UPDATE routine_presence_state
                       SET next_due_at = ?, updated_at = ? WHERE state_id = ?""",
                    (iso(due_at), iso(current), STATE_ID),
                )
            if current < due_at:
                connection.commit()
                return {
                    "opened": False,
                    "reason": "routine_presence_throttled",
                    "next_eligible_at": iso(due_at),
                }
            opened_generation = generation + 1
            next_due = _next_due(
                current,
                generation=opened_generation,
                gap_minutes=gap,
                jitter_seconds=jitter,
                zone=zone,
                start_hour=start,
                end_hour=end,
            )
            occurrence_id = stable_id(
                "presence", STATE_ID, opened_generation, iso(due_at)
            )
            connection.execute(
                """UPDATE routine_presence_state
                   SET generation = ?, last_opened_at = ?, next_due_at = ?,
                       last_reason = 'empty_pool', updated_at = ?
                   WHERE state_id = ?""",
                (
                    opened_generation,
                    iso(current),
                    iso(next_due),
                    iso(current),
                    STATE_ID,
                ),
            )
            connection.commit()
        return {
            "opened": True,
            "reason": "routine_presence_due",
            "occurrence_id": occurrence_id,
            "opened_at": iso(current),
            "next_eligible_at": iso(next_due),
        }

    def note_populated_wake(
        self,
        *,
        now: datetime | None = None,
        min_gap_minutes: int = DEFAULT_MIN_GAP_MINUTES,
        jitter_seconds: int = DEFAULT_JITTER_SECONDS,
        timezone_name: str = DEFAULT_TIMEZONE,
        sleep_start_hour: int = DEFAULT_SLEEP_START_HOUR,
        sleep_end_hour: int = DEFAULT_SLEEP_END_HOUR,
    ) -> dict[str, Any]:
        """Make a real attention wake the anchor for the next free wake."""

        current = as_utc(now or utc_now())
        gap = max(15, min(int(min_gap_minutes), 10_080))
        jitter = max(0, min(int(jitter_seconds), 86_400))
        zone = ZoneInfo(timezone_name)
        start = _hour(sleep_start_hour)
        end = _hour(sleep_end_hour)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT generation FROM routine_presence_state WHERE state_id = ?",
                (STATE_ID,),
            ).fetchone()
            generation = int(row["generation"] or 0) + 1 if row else 1
            next_due = _next_due(
                current,
                generation=generation,
                gap_minutes=gap,
                jitter_seconds=jitter,
                zone=zone,
                start_hour=start,
                end_hour=end,
            )
            connection.execute(
                """INSERT INTO routine_presence_state (
                       state_id, generation, last_opened_at, next_due_at,
                       last_reason, updated_at
                   ) VALUES (?, ?, ?, ?, 'populated_pool', ?)
                   ON CONFLICT(state_id) DO UPDATE SET
                       generation = excluded.generation,
                       last_opened_at = excluded.last_opened_at,
                       next_due_at = excluded.next_due_at,
                       last_reason = excluded.last_reason,
                       updated_at = excluded.updated_at""",
                (STATE_ID, generation, iso(current), iso(next_due), iso(current)),
            )
            connection.commit()
        return {"anchored": True, "next_eligible_at": iso(next_due)}


def _next_due(
    anchor: datetime,
    *,
    generation: int,
    gap_minutes: int,
    jitter_seconds: int,
    zone: ZoneInfo,
    start_hour: int,
    end_hour: int,
) -> datetime:
    offset = _stable_offset(
        f"{STATE_ID}|{generation}|{iso(anchor)}", jitter_seconds
    )
    due = anchor + timedelta(minutes=gap_minutes, seconds=offset)
    return _coalesce_sleep(
        due,
        zone=zone,
        start_hour=start_hour,
        end_hour=end_hour,
        seed=f"{STATE_ID}|{generation}|morning",
    )


def _coalesce_sleep(
    due: datetime,
    *,
    zone: ZoneInfo,
    start_hour: int,
    end_hour: int,
    seed: str,
) -> datetime:
    local = as_utc(due).astimezone(zone)
    if start_hour == end_hour or not _in_sleep(local.hour, start_hour, end_hour):
        return as_utc(due)
    resume_day = local.date()
    if start_hour > end_hour and local.hour >= start_hour:
        resume_day = (local + timedelta(days=1)).date()
    resume = local.replace(
        year=resume_day.year,
        month=resume_day.month,
        day=resume_day.day,
        hour=end_hour,
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(seconds=_stable_offset(seed, 20 * 60))
    return as_utc(resume)


def _in_sleep(hour: int, start: int, end: int) -> bool:
    return start <= hour < end if start < end else hour >= start or hour < end


def _stable_offset(seed: str, window_seconds: int) -> int:
    window = max(0, int(window_seconds))
    if window <= 0:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (window + 1)


def _hour(value: int) -> int:
    return max(0, min(23, int(value)))
