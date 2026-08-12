from __future__ import annotations

import json
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from hermes_attention.adapters import (
    load_adapter_polls,
    read_adapter_specs,
    register_adapter,
    remove_adapter,
)
from hermes_attention.inbox import AgentEvent
from hermes_attention.runtime import heartbeat, open_runtime, render_cron_preflight


class AdapterRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.config = root / "adapters.json"
        self.stores = open_runtime(str(root / "attention.sqlite3"))
        self.now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registry_is_idempotent_private_and_removable(self) -> None:
        register_adapter(
            name="ai-forum", module="example.forum_attention", path=self.config
        )
        register_adapter(
            name="ai-forum", module="example.forum_v2", path=self.config
        )
        self.assertEqual(
            read_adapter_specs(self.config),
            [{"name": "ai-forum", "module": "example.forum_v2", "factory": "build_poll"}],
        )
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.assertTrue(remove_adapter("ai-forum", self.config)["removed"])
        self.assertEqual(read_adapter_specs(self.config), [])

    def test_runtime_database_and_parent_are_private(self) -> None:
        database = self.stores.database.path
        self.assertEqual(stat.S_IMODE(database.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

    def test_external_forum_message_reaches_frontstage_as_context_not_authority(self) -> None:
        event = AgentEvent(
            provider_id="ai-forum",
            provider_event_id="thread-42-reply-7",
            event_kind="forum_thread_updated",
            title="协作讨论有一条新回复",
            event_at=self.now,
            compact_payload={"thread_id": "42", "topic": "拆分下一步任务"},
            source_refs=("forum:thread:42", "forum:reply:7"),
            subject_ref="forum:thread:42",
            capability_hints=("communication",),
        )

        class ForumModule:
            @staticmethod
            def build_poll(stores):
                return lambda: stores.inbox.ingest(event, now=self.now)

        register_adapter(
            name="ai-forum", module="example.forum_attention", path=self.config
        )
        with patch(
            "hermes_attention.adapters.importlib.import_module",
            return_value=ForumModule,
        ):
            result = heartbeat(
                self.stores,
                adapter_polls=load_adapter_polls(self.stores, self.config),
                now=self.now,
            )
        packet = render_cron_preflight(result)
        self.assertTrue(result["adapter_results"][0]["ok"])
        self.assertIn('"provider_id": "ai-forum"', packet)
        self.assertIn('"event_kind": "forum_thread_updated"', packet)
        self.assertIn('"source_refs": ["forum:thread:42", "forum:reply:7"]', packet)
        self.assertIn('"capability_hints": ["communication"]', packet)
        self.assertIn('"attention_hints_are_not_tool_authority": true', packet)

    def test_inbox_sanitizes_refs_and_rejects_unbounded_payloads(self) -> None:
        event = AgentEvent(
            provider_id="ai-forum",
            provider_event_id="unsafe-ref",
            event_kind="forum_thread_updated",
            title="一条外部消息",
            event_at=self.now,
            compact_payload={"topic": "正常内容"},
            source_refs=("https://example.test/thread?signature=must-not-leak&view=1",),
        )
        self.stores.inbox.ingest(event, now=self.now)
        built = self.stores.attention.build(now=self.now)
        encoded = json.dumps(built, ensure_ascii=False)
        self.assertNotIn("must-not-leak", encoded)
        self.assertIn("signature=[redacted]", encoded)

        oversized = AgentEvent(
            **{
                **event.__dict__,
                "provider_event_id": "too-many-keys",
                "compact_payload": {f"key-{number}": number for number in range(33)},
            }
        )
        with self.assertRaisesRegex(ValueError, "too many keys"):
            self.stores.inbox.ingest(oversized, now=self.now)

    def test_identity_fields_reject_overlength_instead_of_aliasing(self) -> None:
        prefix = "x" * 240
        for suffix in ("a", "b"):
            event = AgentEvent(
                provider_id="ai-forum",
                provider_event_id=prefix + suffix,
                event_kind="forum_thread_updated",
                title="一条外部消息",
                event_at=self.now,
            )
            with self.assertRaisesRegex(
                ValueError, "provider_event_id exceeds 240 characters"
            ):
                self.stores.inbox.ingest(event, now=self.now)
            with self.assertRaisesRegex(
                ValueError, "provider_event_id exceeds 240 characters"
            ):
                _ = event.event_id
        with self.stores.database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM agent_events"
            ).fetchone()["count"]
        self.assertEqual(count, 0)

    def test_routing_identity_fields_are_never_silently_truncated(self) -> None:
        base = AgentEvent(
            provider_id="ai-forum",
            provider_event_id="event-1",
            event_kind="forum_thread_updated",
            title="一条外部消息",
            event_at=self.now,
        )
        cases = (
            ("provider_id", "p" * 121, 120),
            ("event_kind", "k" * 121, 120),
            ("subject_ref", "s" * 241, 240),
            ("coalesce_key", "c" * 241, 240),
            ("followup_of", "f" * 241, 240),
        )
        for field, value, limit in cases:
            event = AgentEvent(**{**base.__dict__, field: value})
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    ValueError, rf"{field} exceeds {limit} characters"
                ):
                    self.stores.inbox.ingest(event, now=self.now)

    def test_broken_adapter_is_reported_without_blocking_another_owner(self) -> None:
        self.stores.calendar.schedule(
            title="检查实验结果", due_at=self.now, now=self.now
        )
        register_adapter(
            name="broken", module="missing.adapter", path=self.config
        )
        with patch(
            "hermes_attention.adapters.importlib.import_module",
            side_effect=ModuleNotFoundError("missing.adapter"),
        ):
            result = heartbeat(
                self.stores,
                adapter_polls=load_adapter_polls(self.stores, self.config),
                now=self.now,
            )
        self.assertTrue(result["wake_agent"])
        self.assertFalse(result["adapter_results"][0]["ok"])
        self.assertEqual(result["adapter_results"][0]["name"], "broken")

    def test_broken_registry_is_reported_without_blocking_due_reminder(self) -> None:
        self.config.write_text("{not-json", encoding="utf-8")
        self.stores.calendar.schedule(
            title="检查实验结果", due_at=self.now, now=self.now
        )
        result = heartbeat(
            self.stores,
            adapter_polls=load_adapter_polls(self.stores, self.config),
            now=self.now,
        )
        self.assertTrue(result["wake_agent"])
        self.assertFalse(result["adapter_results"][0]["ok"])
        self.assertEqual(result["adapter_results"][0]["name"], "adapter-registry")


if __name__ == "__main__":
    unittest.main()
