#!/usr/bin/env python3
"""Bind one Hermes Cron delivery to its native foreground conversation."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Attach a Hermes Cron job to one native channel session."
    )
    root.add_argument("--probe-only", action="store_true")
    root.add_argument("--job-id")
    root.add_argument("--platform")
    root.add_argument("--chat-id")
    root.add_argument("--chat-name")
    root.add_argument("--user-id")
    root.add_argument("--thread-id")
    return root


def native_cron_api():
    try:
        jobs = importlib.import_module("cron.jobs")
    except (ImportError, ModuleNotFoundError) as exc:
        raise SystemExit(
            "Hermes native Cron API is unavailable; update Hermes or use a "
            "compatible Attention release"
        ) from exc
    get_job = getattr(jobs, "get_job", None)
    update_job = getattr(jobs, "update_job", None)
    if not callable(get_job) or not callable(update_job):
        raise SystemExit(
            "Hermes native Cron API is incompatible: get_job/update_job required"
        )
    try:
        get_parameters = inspect.signature(get_job).parameters
        update_parameters = inspect.signature(update_job).parameters
    except (TypeError, ValueError) as exc:
        raise SystemExit(
            "Hermes native Cron API is incompatible: signatures are not inspectable"
        ) from exc
    if len(get_parameters) < 1 or len(update_parameters) < 2:
        raise SystemExit(
            "Hermes native Cron API is incompatible: unexpected function signatures"
        )
    return get_job, update_job


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    get_job, update_job = native_cron_api()
    if args.probe_only:
        print(json.dumps({"compatible": True}, sort_keys=True))
        return 0
    if not args.job_id or not args.platform or not args.chat_id:
        raise SystemExit("--job-id, --platform, and --chat-id are required")

    if get_job(args.job_id) is None:
        raise SystemExit(f"Hermes Cron job does not exist: {args.job_id}")

    origin = {
        "platform": args.platform,
        "chat_id": args.chat_id,
        "chat_name": args.chat_name,
        "thread_id": args.thread_id,
        "user_id": args.user_id,
    }
    update_job(
        args.job_id,
        {"attach_to_session": True, "origin": origin},
    )
    persisted = get_job(args.job_id)
    if persisted is None:
        raise SystemExit(f"Hermes Cron job disappeared during update: {args.job_id}")
    if persisted.get("attach_to_session") is not True or persisted.get("origin") != origin:
        raise SystemExit("Hermes Cron session binding was not persisted exactly")
    print(json.dumps({"job_id": args.job_id, "attached": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
