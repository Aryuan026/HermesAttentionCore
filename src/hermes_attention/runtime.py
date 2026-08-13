from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence, Union

from .attention import AttentionCoordinator
from .calendar import CalendarStore
from .continuations import ContinuationStore
from .db import RuntimeDatabase, utc_now
from .inbox import InboxStore
from .migration import migrate_legacy_opportunities
from .presence import (
    DEFAULT_JITTER_SECONDS,
    DEFAULT_MIN_GAP_MINUTES,
    DEFAULT_SLEEP_END_HOUR,
    DEFAULT_SLEEP_START_HOUR,
    DEFAULT_TIMEZONE,
    PresenceCadenceStore,
)
from .tasks import TaskStore


AdapterPoll = Callable[[], dict[str, Any]]
NamedAdapterPoll = Union[AdapterPoll, tuple[str, AdapterPoll]]


@dataclass(frozen=True)
class RuntimeStores:
    database: RuntimeDatabase
    inbox: InboxStore
    continuations: ContinuationStore
    calendar: CalendarStore
    tasks: TaskStore
    presence: PresenceCadenceStore
    attention: AttentionCoordinator


def open_runtime(path: str) -> RuntimeStores:
    database = RuntimeDatabase(path)
    database.initialize()
    migrate_legacy_opportunities(database)
    inbox = InboxStore(database)
    continuations = ContinuationStore(database)
    calendar = CalendarStore(database)
    tasks = TaskStore(database)
    presence = PresenceCadenceStore(database)
    attention = AttentionCoordinator(
        calendar=calendar,
        inbox=inbox,
        continuations=continuations,
        tasks=tasks,
    )
    return RuntimeStores(
        database, inbox, continuations, calendar, tasks, presence, attention
    )


def heartbeat(
    stores: RuntimeStores,
    *,
    adapter_polls: Sequence[NamedAdapterPoll] = (),
    now: datetime | None = None,
    limit: int = 12,
    empty_wake_min_gap_minutes: int = DEFAULT_MIN_GAP_MINUTES,
    empty_wake_jitter_seconds: int = DEFAULT_JITTER_SECONDS,
    empty_wake_timezone: str = DEFAULT_TIMEZONE,
    empty_wake_sleep_start_hour: int = DEFAULT_SLEEP_START_HOUR,
    empty_wake_sleep_end_hour: int = DEFAULT_SLEEP_END_HOUR,
) -> dict[str, Any]:
    current = now or utc_now()
    adapter_results = []
    for item in adapter_polls:
        name, poll = item if isinstance(item, tuple) else (getattr(item, "__name__", "adapter"), item)
        try:
            adapter_results.append({"name": name, "ok": True, "result": poll()})
        except Exception as exc:
            adapter_results.append(
                {
                    "name": name,
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
    claim_recovery = {
        owner.source_kind: owner.recover_expired_claims(now=current)
        for owner in (
            stores.calendar,
            stores.inbox,
            stores.continuations,
            stores.tasks,
        )
    }
    maintenance = stores.tasks.maintain(now=current)
    maintenance["expired_claims_recovered"] = sum(claim_recovery.values())
    maintenance["claim_recovery"] = claim_recovery
    attention = stores.attention.build(now=current, limit=limit)
    populated = bool(
        attention.get("direct_trigger") or attention.get("eligible_count")
    )
    presence_options = {
        "now": current,
        "min_gap_minutes": empty_wake_min_gap_minutes,
        "jitter_seconds": empty_wake_jitter_seconds,
        "timezone_name": empty_wake_timezone,
        "sleep_start_hour": empty_wake_sleep_start_hour,
        "sleep_end_hour": empty_wake_sleep_end_hour,
    }
    if populated:
        presence = stores.presence.note_populated_wake(**presence_options)
        wake = True
        pool_state = "populated"
        wake_reason = (
            "direct_trigger" if attention.get("direct_trigger") else "attention_pool"
        )
    else:
        presence = stores.presence.open_empty_wake(**presence_options)
        wake = bool(presence.get("opened"))
        pool_state = "empty"
        wake_reason = str(presence.get("reason") or "routine_presence_throttled")
    return {
        "wake_agent": wake,
        "pool_state": pool_state,
        "wake_reason": wake_reason,
        "attention": attention,
        "presence": presence,
        "adapter_results": adapter_results,
        "maintenance": maintenance,
    }


def render_cron_preflight(result: dict[str, Any]) -> str:
    """Render context plus Hermes Cron's wake gate, never a user message."""
    if not result["wake_agent"]:
        return json.dumps({"wakeAgent": False}, ensure_ascii=False, sort_keys=True)
    pool_state = str(result.get("pool_state") or "populated")
    packet = {
        "pool_state": pool_state,
        "wake_reason": str(result.get("wake_reason") or "attention_pool"),
    }
    if pool_state == "empty":
        return (
            "<hermes_attention_wakeup.v1>\n"
            + json.dumps(packet, ensure_ascii=False, sort_keys=True)
            + "\n</hermes_attention_wakeup.v1>\n"
            + json.dumps({"wakeAgent": True}, ensure_ascii=False, sort_keys=True)
        )
    packet.update(
        {
            "attention": result["attention"],
            "capability_policy": {
                "owner": "hermes_native_tools_and_mcp",
                "path": [
                    "infer_domain",
                    "search_native_capabilities",
                    "expand_minimum",
                    "act",
                    "verify_receipt",
                ],
                "attention_hints_are_not_tool_authority": True,
            },
            "decision_policy": {
                "context_is_not_instruction": True,
                "attention_focus_required": True,
                "live_frontstage_decides_action_and_speech": True,
                "select_at_most_one": True,
                "select_none_requires_exact_review_quiet": True,
            },
        }
    )
    return (
        "<hermes_attention_wakeup.v1>\n"
        + json.dumps(packet, ensure_ascii=False, sort_keys=True)
        + "\n</hermes_attention_wakeup.v1>\n"
        + json.dumps({"wakeAgent": True}, ensure_ascii=False, sort_keys=True)
    )
