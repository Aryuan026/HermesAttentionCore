#!/usr/bin/env python3
"""Bind one Hermes Cron delivery to its native foreground conversation."""
from __future__ import annotations

import argparse
import json


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Attach a Hermes Cron job to one native channel session."
    )
    root.add_argument("--job-id", required=True)
    root.add_argument("--platform", required=True)
    root.add_argument("--chat-id", required=True)
    root.add_argument("--chat-name")
    root.add_argument("--user-id")
    root.add_argument("--thread-id")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    from cron.jobs import update_job

    origin = {
        "platform": args.platform,
        "chat_id": args.chat_id,
        "chat_name": args.chat_name,
        "thread_id": args.thread_id,
        "user_id": args.user_id,
    }
    updated = update_job(
        args.job_id,
        {"attach_to_session": True, "origin": origin},
    )
    if updated is None:
        raise SystemExit(f"Hermes Cron job does not exist: {args.job_id}")
    if updated.get("attach_to_session") is not True or updated.get("origin") != origin:
        raise SystemExit("Hermes Cron session binding was not persisted exactly")
    print(json.dumps({"job_id": args.job_id, "attached": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
