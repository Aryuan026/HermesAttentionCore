from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .adapters import read_adapter_specs, register_adapter, remove_adapter
from .db import parse_time
from .runtime import open_runtime


def database_path() -> Path:
    configured = os.environ.get("HERMES_ATTENTION_DB", "").strip()
    hermes_home = Path(
        os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
    ).expanduser()
    return Path(configured) if configured else hermes_home / "attention" / "attention.sqlite3"


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def required_time(value: str) -> datetime:
    parsed = parse_time(value)
    if parsed is None:
        raise SystemExit("a valid ISO-8601 time is required")
    return parsed


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="hermes-attention")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("receipts")

    build = commands.add_parser("build")
    build.add_argument("--now", default="")
    build.add_argument("--limit", type=int, default=12)

    arrange = commands.add_parser("arrange", help="Turn a foreground intention into owned future state")
    arrange_sub = arrange.add_subparsers(dest="arrange_kind", required=True)
    reminder = arrange_sub.add_parser("reminder")
    reminder.add_argument("--title", required=True)
    reminder.add_argument("--due-at", required=True)
    reminder.add_argument("--context", default="")
    reminder.add_argument("--capability", action="append", default=[])

    continuation = arrange_sub.add_parser("continuation")
    continuation.add_argument("--goal", required=True)
    continuation.add_argument("--stage", required=True)
    continuation.add_argument("--due-at", required=True)
    continuation.add_argument("--causal-root", default="")
    continuation.add_argument("--parent-ref", default="")
    continuation.add_argument("--capability", action="append", default=[])

    task = arrange_sub.add_parser("task")
    task.add_argument("--kind", choices=["scheduled", "standing", "periodic"], required=True)
    task.add_argument("--title", required=True)
    task.add_argument("--summary", default="")
    task.add_argument("--due-at", default="")
    task.add_argument("--recurrence", default="")
    task.add_argument("--next-check-at", default="")
    task.add_argument("--parent-task-id", default="")
    task.add_argument("--pinned", action="store_true")

    task_update = arrange_sub.add_parser("task-update")
    task_update.add_argument("--task-id", required=True)
    task_update.add_argument("--summary")
    task_update.add_argument("--due-at", default="")
    task_update.add_argument("--next-check-at", default="")
    task_update.add_argument("--pinned", action=argparse.BooleanOptionalAction, default=None)
    task_update.add_argument("--blocked", action=argparse.BooleanOptionalAction, default=None)
    task_update.add_argument("--form-json", default="")

    task_complete = arrange_sub.add_parser("task-complete")
    task_complete.add_argument("--task-id", required=True)
    task_complete.add_argument("--result-json", default="{}")

    adapters = commands.add_parser(
        "adapters", help="Manage trusted external Inbox adapter modules"
    )
    adapters_sub = adapters.add_subparsers(dest="adapter_command", required=True)
    adapters_sub.add_parser("list")
    adapter_register = adapters_sub.add_parser("register")
    adapter_register.add_argument("--name", required=True)
    adapter_register.add_argument("--module", required=True)
    adapter_register.add_argument("--factory", default="build_poll")
    adapter_remove = adapters_sub.add_parser("remove")
    adapter_remove.add_argument("--name", required=True)

    focus = commands.add_parser("focus", help="One conceptual lifecycle for a selected source")
    focus_sub = focus.add_subparsers(dest="focus_command", required=True)
    focus_open = focus_sub.add_parser("open")
    focus_open.add_argument("--source-kind", required=True)
    focus_open.add_argument("--source-id", required=True)
    focus_open.add_argument("--source-version", required=True)
    focus_open.add_argument("--now", default="")

    focus_close = focus_sub.add_parser("close")
    focus_close.add_argument("--source-kind", required=True)
    focus_close.add_argument("--claim-token", required=True)
    focus_close.add_argument(
        "--outcome", required=True,
        choices=["quiet", "acted", "reported", "failed"],
    )
    focus_close.add_argument("--result-json", default="{}")
    focus_close.add_argument("--now", default="")

    focus_defer = focus_sub.add_parser("defer")
    focus_defer.add_argument("--source-kind", required=True)
    focus_defer.add_argument("--claim-token", required=True)
    focus_defer.add_argument("--goal", required=True)
    focus_defer.add_argument("--stage", required=True)
    focus_defer.add_argument("--due-at", required=True)
    focus_defer.add_argument("--now", default="")
    focus_quiet_set = focus_sub.add_parser("quiet-set")
    focus_quiet_set.add_argument("--set-id", required=True)
    focus_quiet_set.add_argument("--now", default="")
    return root


def optional_time(value: str) -> datetime | None:
    return parse_time(value) if value else None


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "adapters":
        if args.adapter_command == "list":
            result = {"adapters": read_adapter_specs()}
        elif args.adapter_command == "register":
            result = register_adapter(
                name=args.name, module=args.module, factory=args.factory
            )
        else:
            result = remove_adapter(args.name)
        print_json(result)
        return 0
    stores = open_runtime(str(database_path()))
    if args.command == "init":
        print_json({"ok": True, "database": str(stores.database.path)})
        return 0
    if args.command == "receipts":
        print_json({"receipts": stores.database.receipts()})
        return 0
    if args.command == "build":
        print_json(stores.attention.build(now=optional_time(args.now), limit=args.limit))
        return 0
    if args.command == "arrange":
        if args.arrange_kind == "reminder":
            result = stores.calendar.schedule(
                title=args.title, due_at=required_time(args.due_at),
                context_note=args.context, capability_refs=args.capability,
            )
        elif args.arrange_kind == "continuation":
            result = stores.continuations.create(
                goal=args.goal, stage=args.stage, due_at=required_time(args.due_at),
                causal_root_id=args.causal_root, parent_ref=args.parent_ref,
                capability_refs=args.capability,
            )
        elif args.arrange_kind == "task":
            result = stores.tasks.create(
                kind=args.kind, title=args.title, summary=args.summary,
                due_at=optional_time(args.due_at), recurrence=args.recurrence,
                next_check_at=optional_time(args.next_check_at),
                parent_task_id=args.parent_task_id, pinned=args.pinned,
            )
        elif args.arrange_kind == "task-update":
            form = json.loads(args.form_json) if args.form_json else None
            if form is not None and not isinstance(form, dict):
                raise SystemExit("form-json must be an object")
            result = stores.tasks.update(
                args.task_id, summary=args.summary,
                due_at=optional_time(args.due_at),
                next_check_at=optional_time(args.next_check_at),
                pinned=args.pinned, blocked=args.blocked, form_schema=form,
            )
        else:
            cycle_result = json.loads(args.result_json)
            if not isinstance(cycle_result, dict):
                raise SystemExit("result-json must be an object")
            result = stores.tasks.complete_cycle(
                args.task_id, result=cycle_result
            )
        print_json(result)
        return 0
    if args.command == "focus" and args.focus_command == "open":
        result = stores.attention.claim_exact(
            args.source_kind, args.source_id, args.source_version,
            now=optional_time(args.now),
        )
        print_json(result)
        return 0 if result.get("claimed") else 2
    if args.command == "focus" and args.focus_command == "close":
        result = stores.attention.settle(
            args.source_kind, args.claim_token, args.outcome,
            result=json.loads(args.result_json), now=optional_time(args.now),
        )
        print_json(result)
        return 0 if result.get("settled") else 2
    if args.command == "focus" and args.focus_command == "defer":
        result = stores.attention.defer(
            args.source_kind, args.claim_token, goal=args.goal, stage=args.stage,
            due_at=required_time(args.due_at), now=optional_time(args.now),
        )
        print_json(result)
        return 0 if result.get("deferred") else 2
    if args.command == "focus" and args.focus_command == "quiet-set":
        result = stores.attention.quiet_set(
            args.set_id, now=optional_time(args.now)
        )
        print_json(result)
        return 0 if result.get("settled") else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
