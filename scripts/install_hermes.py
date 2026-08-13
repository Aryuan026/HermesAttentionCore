#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


CRON_NAME = "hermes-attention-heartbeat"
GENERIC_SKILLS = (
    "attention-steward",
    "attention-arrange",
    "attention-runtime-setup",
)


def default_hermes_home() -> Path:
    return Path(
        os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
    ).expanduser()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Install or upgrade the portable Hermes Attention Runtime."
    )
    root.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    root.add_argument(
        "--install-root",
        type=Path,
        default=Path.home() / ".local" / "share" / "hermes-attention-runtime",
    )
    root.add_argument("--hermes-home", type=Path, default=default_hermes_home())
    root.add_argument(
        "--attention-db",
        type=Path,
        help="Canonical Attention SQLite file (default: <hermes-home>/attention/attention.sqlite3)",
    )
    root.add_argument("--bin-dir", type=Path, default=Path.home() / ".local" / "bin")
    root.add_argument("--install-cron", action="store_true")
    root.add_argument("--deliver", help="Hermes delivery platform for this installation")
    root.add_argument("--schedule", default="*/15 * * * *")
    root.add_argument("--empty-wake-min-gap-minutes", type=int, default=120)
    root.add_argument("--empty-wake-jitter-seconds", type=int, default=3600)
    root.add_argument("--empty-wake-timezone", default="Asia/Shanghai")
    root.add_argument("--empty-wake-sleep-start-hour", type=int, default=1)
    root.add_argument("--empty-wake-sleep-end-hour", type=int, default=8)
    root.add_argument("--workdir", type=Path, default=Path.home())
    root.add_argument("--attach-to-session", action="store_true")
    root.add_argument("--origin-platform")
    root.add_argument("--origin-chat-id")
    root.add_argument("--origin-chat-name")
    root.add_argument("--origin-user-id")
    root.add_argument("--origin-thread-id")
    return root


def copy_runtime(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.expanduser().resolve()
    required = [
        source / "src" / "hermes_attention",
        source / "scripts" / "hermes_attention_heartbeat.py",
        source / "scripts" / "hermes_attention_bind_cron.py",
        *(source / "skills" / name for name in GENERIC_SKILLS),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Source checkout is incomplete: {', '.join(missing)}")
    if source == target:
        return
    replace_tree(
        source / "src" / "hermes_attention",
        target / "src" / "hermes_attention",
    )
    (target / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        source / "scripts" / "hermes_attention_heartbeat.py",
        target / "scripts" / "hermes_attention_heartbeat.py",
    )
    shutil.copy2(
        source / "scripts" / "hermes_attention_bind_cron.py",
        target / "scripts" / "hermes_attention_bind_cron.py",
    )
    for name in GENERIC_SKILLS:
        replace_tree(source / "skills" / name, target / "skills" / name)


def replace_tree(source: Path, target: Path) -> None:
    """Replace one installer-owned tree without retaining retired files."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{target.name}-") as root:
        staged = Path(root) / target.name
        shutil.copytree(
            source,
            staged,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        previous = target.with_name(f".{target.name}.previous")
        if previous.exists():
            shutil.rmtree(previous)
        if target.exists():
            os.replace(target, previous)
        try:
            os.replace(staged, target)
        except Exception:
            if previous.exists() and not target.exists():
                os.replace(previous, target)
            raise
        if previous.exists():
            shutil.rmtree(previous)


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


def install_wrappers(
    install_root: Path,
    hermes_home: Path,
    attention_db: Path,
    bin_dir: Path,
    *,
    empty_wake_min_gap_minutes: int,
    empty_wake_jitter_seconds: int,
    empty_wake_timezone: str,
    empty_wake_sleep_start_hour: int,
    empty_wake_sleep_end_hour: int,
) -> None:
    runtime = shlex.quote(str(install_root))
    home = shlex.quote(str(hermes_home))
    database = shlex.quote(str(attention_db))
    write_executable(
        bin_dir / "hermes-attention",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"export HERMES_HOME={home}\n"
        f"export HERMES_ATTENTION_DB={database}\n"
        f"export PYTHONPATH={runtime}/src${{PYTHONPATH:+:${{PYTHONPATH}}}}\n"
        'exec python3 -m hermes_attention.cli "$@"\n',
    )
    write_executable(
        hermes_home / "scripts" / "hermes_attention_heartbeat.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"export HERMES_HOME={home}\n"
        f"export HERMES_ATTENTION_REPO={runtime}\n"
        f"export HERMES_ATTENTION_DB={database}\n"
        f"export HERMES_ATTENTION_EMPTY_WAKE_MIN_GAP_MINUTES={max(15, int(empty_wake_min_gap_minutes))}\n"
        f"export HERMES_ATTENTION_EMPTY_WAKE_JITTER_SECONDS={max(0, int(empty_wake_jitter_seconds))}\n"
        f"export HERMES_ATTENTION_EMPTY_WAKE_TIMEZONE={shlex.quote(str(empty_wake_timezone))}\n"
        f"export HERMES_ATTENTION_EMPTY_WAKE_SLEEP_START_HOUR={max(0, min(23, int(empty_wake_sleep_start_hour)))}\n"
        f"export HERMES_ATTENTION_EMPTY_WAKE_SLEEP_END_HOUR={max(0, min(23, int(empty_wake_sleep_end_hour)))}\n"
        f"exec python3 {runtime}/scripts/hermes_attention_heartbeat.py\n",
    )


def disable_path(source: Path, disabled_base: Path) -> Path | None:
    """Move an active legacy path aside even when an older archive exists."""
    if not source.exists():
        return None
    disabled_base.parent.mkdir(parents=True, exist_ok=True)
    destination = disabled_base
    suffix = 1
    while destination.exists():
        destination = disabled_base.with_name(f"{disabled_base.name}.{suffix}")
        suffix += 1
    shutil.move(str(source), str(destination))
    return destination


def install_hermes_assets(install_root: Path, hermes_home: Path) -> None:
    for name in GENERIC_SKILLS:
        replace_tree(install_root / "skills" / name, hermes_home / "skills" / name)
    disable_path(
        hermes_home / "hooks" / "attention-transcript",
        hermes_home / "disabled-hooks" / "attention-transcript",
    )


def command_path(name: str, *, bin_dir: Path | None = None) -> str:
    if bin_dir is not None:
        explicit = bin_dir / name
        if explicit.exists():
            return str(explicit)
    path = shutil.which(name)
    if path:
        return path
    fallback = Path.home() / ".local" / "bin" / name
    if fallback.exists():
        return str(fallback)
    raise SystemExit(f"Required command is not installed: {name}")


def initialize_store(
    hermes_home: Path,
    attention_db: Path,
    *,
    bin_dir: Path,
) -> None:
    attention_dir = attention_db.parent
    attention_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if attention_dir == hermes_home / "attention":
        attention_dir.chmod(0o700)
    environment = dict(os.environ)
    environment["HERMES_HOME"] = str(hermes_home)
    environment["HERMES_ATTENTION_DB"] = str(attention_db)
    subprocess.run(
        [command_path("hermes-attention", bin_dir=bin_dir), "init"],
        env=environment,
        check=True,
    )


def _heartbeat_job_id(listing: str) -> str | None:
    match = re.search(
        rf"(?m)^\s*([a-f0-9]+) \[[^\]]+\]\s*\n\s*Name:\s*{re.escape(CRON_NAME)}\s*$",
        listing,
    )
    return match.group(1) if match else None


def install_cron(
    hermes_home: Path,
    *,
    deliver: str | None,
    schedule: str,
    workdir: Path,
) -> tuple[str, str]:
    if not deliver:
        raise SystemExit("--deliver is required with --install-cron")
    hermes = command_path("hermes")
    environment = dict(os.environ)
    environment["HERMES_HOME"] = str(hermes_home)
    listed = subprocess.run(
        [hermes, "cron", "list"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    common = [
        "--schedule", schedule,
        "--deliver", deliver,
        "--skill", "attention-steward",
        "--script", "hermes_attention_heartbeat.sh",
        "--agent",
        "--workdir", str(workdir.expanduser().resolve()),
    ]
    if CRON_NAME not in listed.stdout:
        subprocess.run(
            [hermes, "cron", "create", "--name", CRON_NAME, *common],
            env=environment,
            check=True,
        )
        refreshed = subprocess.run(
            [hermes, "cron", "list"],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        job_id = _heartbeat_job_id(refreshed.stdout)
        if not job_id:
            raise SystemExit("Could not resolve the newly created heartbeat job ID")
        return "created", job_id
    job_id = _heartbeat_job_id(listed.stdout)
    if not job_id:
        raise SystemExit("Could not resolve the existing heartbeat job ID")
    subprocess.run(
        [hermes, "cron", "edit", job_id, *common],
        env=environment,
        check=True,
    )
    return "updated", job_id


def bind_cron_session(
    install_root: Path,
    hermes_home: Path,
    *,
    job_id: str,
    platform: str,
    chat_id: str,
    chat_name: str | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    command = [
        *_cron_binding_helper(install_root, hermes_home),
        "--job-id", job_id,
        "--platform", platform,
        "--chat-id", chat_id,
    ]
    for option, value in (
        ("--chat-name", chat_name),
        ("--user-id", user_id),
        ("--thread-id", thread_id),
    ):
        if value:
            command.extend((option, value))
    _run_cron_binding_helper(command, hermes_home)


def probe_cron_session(install_root: Path, hermes_home: Path) -> None:
    _run_cron_binding_helper(
        [*_cron_binding_helper(install_root, hermes_home), "--probe-only"],
        hermes_home,
    )


def _cron_binding_helper(install_root: Path, hermes_home: Path) -> list[str]:
    source_root = hermes_home / "hermes-agent"
    hermes_python = source_root / "venv" / "bin" / "python"
    if not source_root.is_dir() or not hermes_python.exists():
        raise SystemExit(
            "Hermes source/venv is required for native Cron session binding"
        )
    return [
        str(hermes_python),
        str(install_root / "scripts" / "hermes_attention_bind_cron.py"),
    ]


def _run_cron_binding_helper(command: list[str], hermes_home: Path) -> None:
    source_root = hermes_home / "hermes-agent"
    environment = dict(os.environ)
    environment["HERMES_HOME"] = str(hermes_home)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(source_root)
        if not existing_pythonpath
        else f"{source_root}{os.pathsep}{existing_pythonpath}"
    )
    subprocess.run(command, cwd=source_root, env=environment, check=True)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    origin_values = (
        args.origin_platform,
        args.origin_chat_id,
        args.origin_chat_name,
        args.origin_user_id,
        args.origin_thread_id,
    )
    if args.attach_to_session:
        if not args.install_cron:
            raise SystemExit("--attach-to-session requires --install-cron")
        if not args.origin_platform or not args.origin_chat_id:
            raise SystemExit(
                "--attach-to-session requires --origin-platform and --origin-chat-id"
            )
    elif any(origin_values):
        raise SystemExit("Origin fields require --attach-to-session")
    source_root = args.source_root.expanduser().resolve()
    install_root = args.install_root.expanduser().resolve()
    hermes_home = args.hermes_home.expanduser().resolve()
    attention_db = (
        args.attention_db.expanduser().resolve()
        if args.attention_db
        else hermes_home / "attention" / "attention.sqlite3"
    )
    bin_dir = args.bin_dir.expanduser().resolve()
    copy_runtime(source_root, install_root)
    install_wrappers(
        install_root,
        hermes_home,
        attention_db,
        bin_dir,
        empty_wake_min_gap_minutes=args.empty_wake_min_gap_minutes,
        empty_wake_jitter_seconds=args.empty_wake_jitter_seconds,
        empty_wake_timezone=args.empty_wake_timezone,
        empty_wake_sleep_start_hour=args.empty_wake_sleep_start_hour,
        empty_wake_sleep_end_hour=args.empty_wake_sleep_end_hour,
    )
    install_hermes_assets(install_root, hermes_home)
    initialize_store(hermes_home, attention_db, bin_dir=bin_dir)
    cron_status = "not requested"
    continuity_status = "not requested"
    if args.install_cron:
        if args.attach_to_session:
            probe_cron_session(install_root, hermes_home)
        cron_status, job_id = install_cron(
            hermes_home,
            deliver=args.deliver,
            schedule=args.schedule,
            workdir=args.workdir,
        )
        if args.attach_to_session:
            bind_cron_session(
                install_root,
                hermes_home,
                job_id=job_id,
                platform=args.origin_platform,
                chat_id=args.origin_chat_id,
                chat_name=args.origin_chat_name,
                user_id=args.origin_user_id,
                thread_id=args.origin_thread_id,
            )
            continuity_status = "attached"
    print(f"runtime={install_root}")
    print(f"hermes_home={hermes_home}")
    print(f"attention_db={attention_db}")
    print(f"cron={cron_status}")
    print(f"session_continuity={continuity_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
