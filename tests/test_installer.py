from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InstallerTest(unittest.TestCase):
    @property
    def repository(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def install(self, root: Path, *extra: str, env=None, check=True):
        return subprocess.run(
            [
                sys.executable,
                str(self.repository / "scripts" / "install_hermes.py"),
                "--source-root", str(self.repository),
                "--install-root", str(root / "runtime"),
                "--hermes-home", str(root / ".hermes"),
                "--bin-dir", str(root / "bin"),
                *extra,
            ],
            env=env,
            check=check,
            capture_output=True,
            text=True,
        )

    def test_blank_home_install_initializes_private_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.install(root)
            self.assertIn("cron=not requested", result.stdout)
            self.assertTrue((root / "bin" / "hermes-attention").exists())
            self.assertTrue((root / ".hermes" / "attention" / "attention.sqlite3").exists())
            for name in (
                "attention-steward", "attention-arrange", "attention-runtime-setup"
            ):
                self.assertTrue((root / ".hermes" / "skills" / name / "SKILL.md").exists())

    def test_upgrade_tightens_existing_attention_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attention = root / ".hermes" / "attention"
            attention.mkdir(parents=True)
            attention.chmod(0o775)

            self.install(root)

            self.assertEqual(stat.S_IMODE(attention.stat().st_mode), 0o700)

    def test_custom_database_is_pinned_across_installed_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            canonical = root / "custody" / "attention" / "canonical.sqlite3"
            decoy = root / "decoy.sqlite3"

            result = self.install(
                root,
                "--attention-db", str(canonical),
            )

            self.assertIn(f"attention_db={canonical}", result.stdout)
            self.assertTrue(canonical.exists())
            self.assertFalse((root / ".hermes" / "attention" / "attention.sqlite3").exists())
            for wrapper in (
                root / "bin" / "hermes-attention",
                root / ".hermes" / "scripts" / "hermes_attention_heartbeat.sh",
            ):
                content = wrapper.read_text(encoding="utf-8")
                self.assertIn(f"export HERMES_ATTENTION_DB={canonical}", content)
                self.assertIn(f"export HERMES_HOME={root / '.hermes'}", content)
            heartbeat_wrapper = (
                root / ".hermes" / "scripts" / "hermes_attention_heartbeat.sh"
            ).read_text(encoding="utf-8")
            self.assertIn(
                "HERMES_ATTENTION_EMPTY_WAKE_MIN_GAP_MINUTES=120",
                heartbeat_wrapper,
            )
            self.assertIn(
                "HERMES_ATTENTION_EMPTY_WAKE_JITTER_SECONDS=3600",
                heartbeat_wrapper,
            )

            environment = dict(os.environ)
            environment["HERMES_ATTENTION_DB"] = str(decoy)
            subprocess.run(
                [str(root / "bin" / "hermes-attention"), "init"],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse(decoy.exists())

    def test_heartbeat_refuses_to_invent_an_unconfigured_database(self) -> None:
        environment = dict(os.environ)
        environment.pop("HERMES_ATTENTION_DB", None)
        result = subprocess.run(
            [sys.executable, str(self.repository / "scripts" / "hermes_attention_heartbeat.py")],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HERMES_ATTENTION_DB is required", result.stderr)

    def test_cli_refuses_to_invent_an_unconfigured_database(self) -> None:
        environment = dict(os.environ)
        environment.pop("HERMES_ATTENTION_DB", None)
        environment["PYTHONPATH"] = str(self.repository / "src")
        result = subprocess.run(
            [sys.executable, "-m", "hermes_attention.cli", "init"],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HERMES_ATTENTION_DB is required", result.stderr)

    def test_legacy_transcript_hook_is_archived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / ".hermes" / "hooks" / "attention-transcript"
            active.mkdir(parents=True)
            (active / "HOOK.yaml").write_text("active\n", encoding="utf-8")
            archived = root / ".hermes" / "disabled-hooks" / "attention-transcript"
            archived.mkdir(parents=True)
            (archived / "HOOK.yaml").write_text("older\n", encoding="utf-8")
            self.install(root)
            self.assertFalse(active.exists())
            self.assertEqual((archived / "HOOK.yaml").read_text(), "older\n")
            self.assertTrue(archived.with_name("attention-transcript.1").exists())

    def test_upgrade_removes_retired_owned_files_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.install(root)
            stale_module = root / "runtime" / "src" / "hermes_attention" / "retired.py"
            stale_module.write_text("retired\n", encoding="utf-8")
            stale_skill = root / ".hermes" / "skills" / "attention-steward" / "retired.md"
            stale_skill.write_text("retired\n", encoding="utf-8")
            extension = root / ".hermes" / "skills" / "private-domain" / "SKILL.md"
            extension.parent.mkdir(parents=True)
            extension.write_text("extension\n", encoding="utf-8")
            self.install(root)
            self.assertFalse(stale_module.exists())
            self.assertFalse(stale_skill.exists())
            self.assertTrue(extension.exists())

    def test_existing_no_agent_cron_is_edited_to_agent_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            log = root / "hermes.log"
            hermes = fake_bin / "hermes"
            hermes.write_text(
                "#!/bin/sh\n"
                "if [ \"$1 $2\" = \"cron list\" ]; then\n"
                "  printf '  4336e0f611c8 [active]\\n    Name:      hermes-attention-heartbeat\\n'\n"
                "  exit 0\n"
                "fi\n"
                f"printf '%s\\n' \"$*\" >> {log}\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{fake_bin}:{environment.get('PATH', '')}"
            result = self.install(
                root, "--install-cron", "--deliver", "mobile", env=environment
            )
            args = log.read_text(encoding="utf-8")
            self.assertIn("cron=updated", result.stdout)
            self.assertIn("--agent", args)
            self.assertNotIn("--no-agent", args)
            self.assertEqual(args.count("--skill attention-steward"), 1)

    def test_blank_cron_uses_positional_schedule_and_default_agent_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            log = root / "hermes.log"
            hermes = fake_bin / "hermes"
            hermes.write_text(
                "#!/bin/sh\n"
                'if [ "$1 $2" = "cron list" ]; then\n'
                f"  if [ -f {log} ]; then\n"
                "    printf '  4336e0f611c8 [active]\\n    Name:      hermes-attention-heartbeat\\n'\n"
                "  fi\n  exit 0\nfi\n"
                f'printf \'%s\\n\' "$@" > {log}\n',
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{fake_bin}:{environment.get('PATH', '')}"
            result = self.install(
                root, "--install-cron", "--deliver", "local", env=environment
            )
            args = log.read_text().splitlines()
            self.assertIn("cron=created", result.stdout)
            self.assertEqual(args[:3], ["cron", "create", "*/15 * * * *"])
            self.assertNotIn("--schedule", args)
            self.assertNotIn("--agent", args)
            self.assertNotIn("--no-agent", args)

    @unittest.skipUnless(
        os.environ.get("HERMES_ATTENTION_TEST_HOST_ROOT"),
        "set HERMES_ATTENTION_TEST_HOST_ROOT to an actual Hermes checkout",
    )
    def test_real_host_cron_create_bind_and_edit_preserve_one_job(self) -> None:
        host = Path(os.environ["HERMES_ATTENTION_TEST_HOST_ROOT"]).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "host-bin"
            bin_dir.mkdir()
            hermes = bin_dir / "hermes"
            hermes.write_text(
                "#!/bin/sh\n"
                f'exec {shlex.quote(sys.executable)} -B -m hermes_cli.main "$@"\n',
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            environment = dict(os.environ)
            environment["HOME"] = str(root)
            environment["HERMES_HOME"] = str(root / ".hermes")
            environment["PATH"] = f"{bin_dir}:{environment.get('PATH', '')}"
            environment["PYTHONPATH"] = f"{host}{os.pathsep}{environment.get('PYTHONPATH', '')}"
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            created = self.install(
                root, "--install-cron", "--deliver", "local",
                "--workdir", str(root), env=environment, check=False,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            self.assertIn("cron=created", created.stdout)

            def read_job():
                stored = json.loads((root / ".hermes" / "cron" / "jobs.json").read_text())
                jobs = stored["jobs"] if isinstance(stored, dict) else stored
                self.assertEqual(len(jobs), 1)
                return jobs[0]

            first = read_job()
            self.assertFalse(first.get("no_agent", False))
            self.assertEqual(first["skills"], ["attention-steward"])
            self.assertEqual(first["script"], "hermes_attention_heartbeat.sh")
            helper = root / "runtime" / "scripts" / "hermes_attention_bind_cron.py"
            for args in (
                ["--probe-only"],
                ["--job-id", first["id"], "--platform", "qqbot", "--chat-id", "fixture-chat"],
            ):
                subprocess.run(
                    [sys.executable, "-B", str(helper), *args], env=environment,
                    check=True, capture_output=True, text=True, timeout=30,
                )
            bound = read_job()
            self.assertTrue(bound["attach_to_session"])
            self.assertEqual(bound["origin"]["chat_id"], "fixture-chat")
            subprocess.run(
                [sys.executable, "-B", "-c",
                 "from cron.jobs import update_job; import sys; "
                 "update_job(sys.argv[1], {'no_agent': True})", first["id"]],
                env=environment, check=True, capture_output=True, text=True, timeout=30,
            )
            updated = self.install(
                root, "--install-cron", "--deliver", "local",
                "--schedule", "*/30 * * * *", "--workdir", str(root), env=environment,
            )
            self.assertIn("cron=updated", updated.stdout)
            final = read_job()
            self.assertEqual(final["id"], first["id"])
            self.assertFalse(final["no_agent"])
            self.assertEqual(final["schedule"]["expr"], "*/30 * * * *")
            self.assertTrue(final["attach_to_session"])
            self.assertEqual(final["origin"], bound["origin"])

    def test_cron_can_attach_delivery_to_native_foreground_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            hermes = fake_bin / "hermes"
            hermes.write_text(
                "#!/bin/sh\n"
                "if [ \"$1 $2\" = \"cron list\" ]; then\n"
                "  printf '  4336e0f611c8 [active]\\n    Name:      hermes-attention-heartbeat\\n'\n"
                "fi\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            agent = root / ".hermes" / "hermes-agent"
            cron = agent / "cron"
            cron.mkdir(parents=True)
            (cron / "__init__.py").write_text("", encoding="utf-8")
            (cron / "jobs.py").write_text(
                "import json, os\n"
                "from pathlib import Path\n"
                "STATE = {'id': '4336e0f611c8'}\n"
                "def get_job(job_id):\n"
                "    return dict(STATE) if job_id == STATE['id'] else None\n"
                "def update_job(job_id, updates):\n"
                "    STATE.update(updates)\n"
                "    Path(os.environ['BIND_LOG']).write_text(json.dumps({'job_id': job_id, 'updates': updates}))\n"
                "    return dict(STATE)\n",
                encoding="utf-8",
            )
            venv_bin = agent / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            os.symlink(sys.executable, venv_bin / "python")
            bind_log = root / "bind.json"
            environment = dict(os.environ)
            environment["PATH"] = f"{fake_bin}:{environment.get('PATH', '')}"
            environment["BIND_LOG"] = str(bind_log)
            result = self.install(
                root,
                "--install-cron", "--deliver", "qqbot",
                "--attach-to-session",
                "--origin-platform", "qqbot",
                "--origin-chat-id", "private-chat",
                env=environment,
            )
            self.assertIn("session_continuity=attached", result.stdout)
            written = json.loads(bind_log.read_text(encoding="utf-8"))
            self.assertEqual(written["job_id"], "4336e0f611c8")
            self.assertTrue(written["updates"]["attach_to_session"])
            self.assertEqual(written["updates"]["origin"]["chat_id"], "private-chat")
            self.assertIsNone(written["updates"]["origin"]["user_id"])

    def test_native_session_bind_fails_closed_when_hermes_api_drifted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cron = root / "cron"
            cron.mkdir()
            (cron / "__init__.py").write_text("", encoding="utf-8")
            (cron / "jobs.py").write_text(
                "def update_job(job_id, updates):\n"
                "    return {'id': job_id, **updates}\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.repository / "scripts" / "hermes_attention_bind_cron.py"),
                    "--job-id", "job-1",
                    "--platform", "mobile",
                    "--chat-id", "chat-1",
                ],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("get_job/update_job required", result.stderr)

    def test_attach_probe_fails_before_any_cron_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            cron_log = root / "cron-mutations.log"
            hermes = fake_bin / "hermes"
            hermes.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {cron_log}\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            agent = root / ".hermes" / "hermes-agent"
            cron = agent / "cron"
            cron.mkdir(parents=True)
            (cron / "__init__.py").write_text("", encoding="utf-8")
            (cron / "jobs.py").write_text(
                "def update_job(job_id, updates):\n"
                "    return {'id': job_id, **updates}\n",
                encoding="utf-8",
            )
            venv_bin = agent / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            os.symlink(sys.executable, venv_bin / "python")
            environment = dict(os.environ)
            environment["PATH"] = f"{fake_bin}:{environment.get('PATH', '')}"
            result = self.install(
                root,
                "--install-cron", "--deliver", "mobile",
                "--attach-to-session",
                "--origin-platform", "mobile",
                "--origin-chat-id", "chat-1",
                env=environment,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("get_job/update_job required", result.stderr)
            self.assertFalse(cron_log.exists())


if __name__ == "__main__":
    unittest.main()
