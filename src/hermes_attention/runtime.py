from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence, Union

from .attention import AttentionCoordinator
from .calendar import CalendarStore
from .continuations import ContinuationStore
from .db import RuntimeDatabase
from .inbox import InboxStore
from .migration import migrate_legacy_opportunities
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
    attention: AttentionCoordinator


def open_runtime(path: str) -> RuntimeStores:
    database = RuntimeDatabase(path)
    database.initialize()
    migrate_legacy_opportunities(database)
    inbox = InboxStore(database)
    continuations = ContinuationStore(database)
    calendar = CalendarStore(database)
    tasks = TaskStore(database)
    attention = AttentionCoordinator(
        calendar=calendar,
        inbox=inbox,
        continuations=continuations,
        tasks=tasks,
    )
    return RuntimeStores(database, inbox, continuations, calendar, tasks, attention)


def heartbeat(
    stores: RuntimeStores,
    *,
    adapter_polls: Sequence[NamedAdapterPoll] = (),
    now: datetime | None = None,
    limit: int = 12,
) -> dict[str, Any]:
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
    maintenance = stores.tasks.maintain(now=now)
    attention = stores.attention.build(now=now, limit=limit)
    wake = bool(attention.get("direct_trigger") or attention.get("eligible_count"))
    return {
        "wake_agent": wake,
        "attention": attention,
        "adapter_results": adapter_results,
        "maintenance": maintenance,
    }


def render_cron_preflight(result: dict[str, Any]) -> str:
    """Render context plus Hermes Cron's wake gate, never a user message."""
    if not result["wake_agent"]:
        return json.dumps({"wakeAgent": False}, ensure_ascii=False, sort_keys=True)
    packet = {
        "attention": result["attention"],
        "capability_policy": {
            "owner": "hermes_native_tools_and_mcp",
            "path": ["infer_domain", "search_native_capabilities", "expand_minimum", "act", "verify_receipt"],
            "attention_hints_are_not_tool_authority": True,
        },
        "decision_policy": {
            "context_is_not_instruction": True,
            "select_at_most_one": True,
            "select_none_requires_exact_set_quiet": True,
            "live_frontstage_decides_action_and_speech": True,
        },
    }
    return (
        "<hermes_attention_wakeup.v1>\n"
        + json.dumps(packet, ensure_ascii=False, sort_keys=True)
        + "\n</hermes_attention_wakeup.v1>\n"
        + json.dumps({"wakeAgent": True}, ensure_ascii=False, sort_keys=True)
    )
