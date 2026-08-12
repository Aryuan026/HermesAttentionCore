from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hermes_attention.inbox import AgentEvent
from hermes_attention.runtime import heartbeat, open_runtime, render_cron_preflight


class AttentionRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "attention.sqlite3"
        self.stores = open_runtime(str(self.path))
        self.now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def event(self, number: int = 1, *, provider: str = "lab-monitor", subject: str = "sample-1") -> AgentEvent:
        return AgentEvent(
            provider_id=provider,
            provider_event_id=f"event-{number}",
            event_kind="sample_changed",
            title=f"第 {number} 份样本有变化",
            event_at=self.now,
            compact_payload={
                "sample": number,
                "token": "must-not-leak",
                "note": "Authorization was Bearer must-not-leak-either",
            },
            subject_ref=subject,
            priority_hint="high",
            capability_hints=("leisure",),
        )

    def test_external_fact_enters_inbox_then_generic_provider_candidate(self) -> None:
        ingested = self.stores.inbox.ingest(self.event(), now=self.now)
        self.assertTrue(ingested["inserted"])

        built = self.stores.attention.build(now=self.now)

        self.assertEqual(built["schema"], "attention_opportunity_set.v1")
        self.assertEqual(built["eligible_count"], 1)
        row = built["opportunities"][0]
        self.assertEqual(row["source_kind"], "provider_event")
        self.assertEqual(row["provider_id"], "lab-monitor")
        self.assertEqual(row["capability_hints"], ["leisure"])
        self.assertNotIn("tool", row)
        self.assertEqual(row["context"]["compact_payload"]["token"], "[redacted]")
        self.assertNotIn("must-not-leak-either", row["context"]["compact_payload"]["note"])
        self.assertEqual(built["weights"]["provider_priority"], 0.04)

    def test_provider_event_is_idempotent_and_coalesces_older_pending_state(self) -> None:
        first = self.event(1)
        second = AgentEvent(
            **{**first.__dict__, "provider_event_id": "event-2", "coalesce_key": "sample-1"}
        )
        first = AgentEvent(**{**first.__dict__, "coalesce_key": "sample-1"})
        self.assertTrue(self.stores.inbox.ingest(first, now=self.now)["inserted"])
        self.assertFalse(self.stores.inbox.ingest(first, now=self.now)["inserted"])
        self.assertTrue(self.stores.inbox.ingest(second, now=self.now)["inserted"])
        self.assertEqual(self.stores.attention.build(now=self.now)["eligible_count"], 1)

    def test_direct_reminder_bypasses_competition_but_wakes_live_agent(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        reminder = self.stores.calendar.schedule(
            title="去看实验结果",
            due_at=self.now,
            context_note="根据当前状态重新判断说什么",
            now=self.now,
        )
        result = heartbeat(self.stores, now=self.now)
        direct = result["attention"]["direct_trigger"]
        self.assertEqual(direct["source_id"], reminder["item_id"])
        self.assertEqual(direct["reason"], "schedule_due")
        rendered = render_cron_preflight(result)
        self.assertIn('"live_frontstage_decides_action_and_speech": true', rendered)
        self.assertTrue(rendered.endswith('{"wakeAgent": true}'))
        self.assertNotIn("final_message", rendered)

    def test_empty_heartbeat_does_not_wake_or_deliver(self) -> None:
        rendered = render_cron_preflight(heartbeat(self.stores, now=self.now))
        self.assertEqual(rendered, '{"wakeAgent": false}')

    def test_optional_adapter_failure_does_not_block_another_owner(self) -> None:
        self.stores.continuations.create(
            goal="继续已经到期的工作", stage="现在处理", due_at=self.now + timedelta(seconds=1), now=self.now
        )

        def broken_adapter():
            raise RuntimeError("provider unavailable")

        result = heartbeat(
            self.stores, adapter_polls=[broken_adapter], now=self.now + timedelta(seconds=1)
        )
        self.assertTrue(result["wake_agent"])
        self.assertFalse(result["adapter_results"][0]["ok"])
        self.assertEqual(result["attention"]["opportunities"][0]["source_kind"], "continuation")

    def test_model_choice_is_exact_claimed_at_source_owner(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        candidate = self.stores.attention.build(now=self.now)["opportunities"][0]
        wrong = self.stores.attention.claim_exact(
            candidate["source_kind"], candidate["source_id"], "wrong", now=self.now
        )
        self.assertEqual(wrong["reason"], "source_version_changed")
        claim = self.stores.attention.claim_exact(
            candidate["source_kind"], candidate["source_id"], candidate["source_version"], now=self.now
        )
        self.assertTrue(claim["claimed"])
        settled = self.stores.attention.settle(
            "provider_event", claim["claim_token"], "acted",
            result={"receipt": "action-1"}, now=self.now,
        )
        self.assertTrue(settled["settled"])

    def test_provider_and_subject_diversity_cap_prompt_not_full_membership(self) -> None:
        for number in range(1, 6):
            self.stores.inbox.ingest(self.event(number), now=self.now)
        built = self.stores.attention.build(now=self.now, limit=12)
        self.assertEqual(built["eligible_count"], 5)
        self.assertEqual(built["prompt_count"], 2)
        self.assertEqual(len(built["eligible_membership"]), 5)

    def test_select_none_quiets_exact_full_set_and_does_not_rewake(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        self.stores.tasks.create(kind="standing", title="整理知识库", now=self.now)
        built = self.stores.attention.build(now=self.now)
        self.assertEqual(built["eligible_count"], 2)
        settled = self.stores.attention.quiet_set(built["set_id"], now=self.now)
        self.assertTrue(settled["settled"])
        self.assertEqual(settled["member_count"], 2)
        self.assertEqual(len(settled["receipt_ids"]), 2)
        self.assertEqual(self.stores.attention.build(now=self.now)["eligible_count"], 0)

    def test_quiet_set_rejects_changed_membership_without_partial_settlement(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        built = self.stores.attention.build(now=self.now)
        self.stores.inbox.ingest(self.event(2, subject="sample-2"), now=self.now)
        settled = self.stores.attention.quiet_set(built["set_id"], now=self.now)
        self.assertFalse(settled["settled"])
        self.assertEqual(settled["reason"], "set_changed")
        self.assertEqual(len(self.stores.database.receipts()), 0)

    def test_foreground_intention_can_create_continuation_without_chat_ingest(self) -> None:
        created = self.stores.continuations.create(
            goal="整理实验记录",
            stage="等数据导出后继续",
            due_at=self.now + timedelta(hours=2),
            now=self.now,
        )
        self.assertTrue(created["created"])
        self.assertEqual(self.stores.attention.build(now=self.now)["eligible_count"], 0)
        later = self.stores.attention.build(now=self.now + timedelta(hours=2))
        self.assertEqual(later["opportunities"][0]["source_kind"], "continuation")

    def test_defer_atomically_settles_focus_and_creates_one_continuation(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        candidate = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "provider_event", candidate["source_id"], candidate["source_version"], now=self.now
        )
        deferred = self.stores.attention.defer(
            "provider_event", claim["claim_token"], goal="下一批数据到齐后再看",
            stage="等待外部数据变化", due_at=self.now + timedelta(hours=3), now=self.now,
        )
        self.assertTrue(deferred["deferred"])
        self.assertEqual(len(self.stores.database.receipts()), 1)
        with self.stores.database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) AS n FROM agent_continuations").fetchone()["n"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
