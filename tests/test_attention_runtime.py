from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from hermes_attention.cli import main as cli_main
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
        self.assertEqual(ingested["event_id"], self.event().event_id)

        built = self.stores.attention.build(now=self.now)

        self.assertEqual(built["schema"], "attention_opportunity_set.v1")
        self.assertEqual(built["eligible_count"], 1)
        row = built["opportunities"][0]
        self.assertEqual(row["source_kind"], "provider_event")
        self.assertEqual(row["source_version"], self.event().source_version)
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
            candidate["source_kind"], candidate["source_id"], "wrong",
            candidate["review_version"], now=self.now
        )
        self.assertEqual(wrong["reason"], "source_version_changed")
        claim = self.stores.attention.claim_exact(
            candidate["source_kind"], candidate["source_id"],
            candidate["source_version"], candidate["review_version"], now=self.now
        )
        self.assertTrue(claim["claimed"])
        settled = self.stores.attention.settle(
            "provider_event", claim["claim_token"], "acted",
            result={"receipt": "action-1"}, now=self.now,
        )
        self.assertTrue(settled["settled"])

    def test_focus_open_cli_carries_review_version_into_claim(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        candidate = self.stores.attention.build(now=self.now)["opportunities"][0]
        output = StringIO()
        with patch.dict(
            "os.environ", {"HERMES_ATTENTION_DB": str(self.path)}, clear=False
        ), redirect_stdout(output):
            status = cli_main(
                [
                    "focus",
                    "open",
                    "--source-kind",
                    candidate["source_kind"],
                    "--source-id",
                    candidate["source_id"],
                    "--source-version",
                    candidate["source_version"],
                    "--review-version",
                    candidate["review_version"],
                    "--now",
                    self.now.isoformat(),
                ]
            )
        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(result["claimed"])
        self.assertEqual(result["review_version"], candidate["review_version"])

    def test_provider_and_subject_diversity_cap_prompt_not_full_membership(self) -> None:
        for number in range(1, 6):
            self.stores.inbox.ingest(self.event(number), now=self.now)
        built = self.stores.attention.build(now=self.now, limit=12)
        self.assertEqual(built["eligible_count"], 5)
        self.assertEqual(built["prompt_count"], 2)
        self.assertEqual(len(built["eligible_membership"]), 5)
        self.assertEqual(len(built["review_membership"]), 2)
        self.assertNotIn("review_version", built["eligible_membership"][0])
        self.assertIn("review_version", built["review_membership"][0])

    def test_select_none_quiets_exact_review_set_and_does_not_rewake(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        self.stores.tasks.create(kind="standing", title="整理知识库", now=self.now)
        built = self.stores.attention.build(now=self.now)
        self.assertEqual(built["eligible_count"], 2)
        settled = self.stores.attention.quiet_set(
            built["set_id"], built["review_id"], now=self.now
        )
        self.assertTrue(settled["settled"])
        self.assertEqual(settled["member_count"], 2)
        self.assertEqual(len(settled["receipt_ids"]), 2)
        self.assertEqual(self.stores.attention.build(now=self.now)["eligible_count"], 0)

    def test_quiet_set_rejects_changed_membership_without_partial_settlement(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        built = self.stores.attention.build(now=self.now)
        self.stores.inbox.ingest(self.event(2, subject="sample-2"), now=self.now)
        settled = self.stores.attention.quiet_set(
            built["set_id"], built["review_id"], now=self.now
        )
        self.assertFalse(settled["settled"])
        self.assertEqual(settled["reason"], "set_changed")
        self.assertEqual(len(self.stores.database.receipts()), 0)

    def test_quiet_set_closes_only_candidates_fully_shown_to_agent(self) -> None:
        for number in range(1, 6):
            self.stores.inbox.ingest(self.event(number), now=self.now)
        built = self.stores.attention.build(now=self.now)
        settled = self.stores.attention.quiet_set(
            built["set_id"], built["review_id"], now=self.now
        )
        self.assertTrue(settled["settled"])
        self.assertEqual(settled["scope"], "review_membership")
        self.assertEqual(settled["member_count"], 2)
        self.assertEqual(
            self.stores.attention.build(now=self.now)["eligible_count"], 3
        )

    def test_quiet_set_requires_exact_review_identity(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        built = self.stores.attention.build(now=self.now)
        settled = self.stores.attention.quiet_set(
            built["set_id"], "review_wrong", now=self.now
        )
        self.assertFalse(settled["settled"])
        self.assertEqual(settled["reason"], "review_changed")
        self.assertEqual(len(self.stores.database.receipts()), 0)

    def test_warning_review_cannot_quiet_task_after_it_becomes_overdue(self) -> None:
        due = self.now + timedelta(minutes=1)
        created = self.stores.tasks.create(
            kind="scheduled",
            title="一分钟后提交",
            due_at=due,
            warn_hours=1,
            now=self.now,
        )
        warning = self.stores.attention.build(now=self.now)
        self.assertEqual(
            warning["opportunities"][0]["context"]["attention_reason"], "warning"
        )
        self.assertEqual(
            warning["opportunities"][0]["review_version"], "warning"
        )
        overdue_at = due + timedelta(minutes=1)
        rejected = self.stores.attention.quiet_set(
            warning["set_id"], warning["review_id"], now=overdue_at
        )
        self.assertFalse(rejected["settled"])
        self.assertEqual(rejected["reason"], "review_changed")
        self.assertEqual(len(self.stores.database.receipts()), 0)
        current = self.stores.attention.build(now=overdue_at)
        self.assertEqual(current["opportunities"][0]["source_id"], created["task_id"])
        self.assertEqual(
            current["opportunities"][0]["context"]["attention_reason"], "overdue"
        )
        self.assertEqual(
            current["opportunities"][0]["review_version"], "overdue"
        )

    def test_old_warning_review_cannot_open_focus_after_task_becomes_overdue(self) -> None:
        due = self.now + timedelta(minutes=1)
        self.stores.tasks.create(
            kind="scheduled", title="一分钟后提交", due_at=due,
            warn_hours=1, now=self.now,
        )
        warning = self.stores.attention.build(now=self.now)["opportunities"][0]

        rejected = self.stores.attention.claim_exact(
            "ongoing",
            warning["source_id"],
            warning["source_version"],
            warning["review_version"],
            now=due + timedelta(minutes=1),
        )

        self.assertFalse(rejected["claimed"])
        self.assertEqual(rejected["reason"], "semantic_changed")
        self.assertEqual(len(self.stores.database.receipts()), 0)
        current = self.stores.attention.build(now=due + timedelta(minutes=1))
        self.assertEqual(
            current["opportunities"][0]["context"]["attention_reason"], "overdue"
        )

    def test_claimed_warning_focus_becomes_invalid_when_task_becomes_overdue(self) -> None:
        due = self.now + timedelta(minutes=1)
        self.stores.tasks.create(
            kind="scheduled", title="一分钟后提交", due_at=due,
            warn_hours=1, now=self.now,
        )
        warning = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "ongoing",
            warning["source_id"],
            warning["source_version"],
            warning["review_version"],
            now=self.now,
        )
        self.assertTrue(claim["claimed"])
        self.assertEqual(claim["review_version"], "warning")
        with self.stores.database.connect() as connection:
            stored = connection.execute(
                "SELECT claimed_review_version FROM hermes_tasks WHERE task_id = ?",
                (warning["source_id"],),
            ).fetchone()["claimed_review_version"]
        self.assertEqual(stored, "warning")

        overdue_at = due + timedelta(minutes=1)
        invalid = self.stores.attention.validate_claim(
            "ongoing", claim["claim_token"], now=overdue_at
        )
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["reason"], "semantic_changed")
        acted = self.stores.attention.settle(
            "ongoing", claim["claim_token"], "acted", now=overdue_at
        )
        self.assertFalse(acted["settled"])
        self.assertEqual(acted["reason"], "claim_not_current")
        self.assertEqual(len(self.stores.database.receipts()), 0)
        current = self.stores.attention.build(now=overdue_at)
        self.assertEqual(
            current["opportunities"][0]["context"]["attention_reason"], "overdue"
        )

    def test_direct_settle_rejects_claimed_warning_after_it_becomes_overdue(self) -> None:
        due = self.now + timedelta(minutes=1)
        self.stores.tasks.create(
            kind="scheduled", title="一分钟后提交", due_at=due,
            warn_hours=1, now=self.now,
        )
        warning = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "ongoing", warning["source_id"], warning["source_version"],
            warning["review_version"], now=self.now,
        )

        rejected = self.stores.attention.settle(
            "ongoing", claim["claim_token"], "acted",
            now=due + timedelta(minutes=1),
        )

        self.assertFalse(rejected["settled"])
        self.assertEqual(rejected["reason"], "semantic_changed")
        self.assertEqual(len(self.stores.database.receipts()), 0)

    def test_direct_defer_rejects_claimed_warning_after_it_becomes_overdue(self) -> None:
        due = self.now + timedelta(minutes=1)
        self.stores.tasks.create(
            kind="scheduled", title="一分钟后提交", due_at=due,
            warn_hours=1, now=self.now,
        )
        warning = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "ongoing", warning["source_id"], warning["source_version"],
            warning["review_version"], now=self.now,
        )
        overdue_at = due + timedelta(minutes=1)

        rejected = self.stores.attention.defer(
            "ongoing", claim["claim_token"], goal="以后再做", stage="等待重审",
            due_at=overdue_at + timedelta(hours=1), now=overdue_at,
        )

        self.assertFalse(rejected["deferred"])
        self.assertEqual(rejected["reason"], "semantic_changed")
        self.assertEqual(len(self.stores.database.receipts()), 0)
        with self.stores.database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM agent_continuations"
            ).fetchone()["n"]
        self.assertEqual(count, 0)

    def test_quiet_set_rolls_back_every_owner_when_one_owner_hook_fails(self) -> None:
        continuation = self.stores.continuations.create(
            goal="继续一项跨 owner 工作",
            stage="现在处理",
            due_at=self.now + timedelta(seconds=1),
            now=self.now,
        )
        task = self.stores.tasks.create(
            kind="standing", title="维护知识库", now=self.now
        )
        current = self.now + timedelta(seconds=1)
        built = self.stores.attention.build(now=current)
        with patch.object(
            self.stores.tasks,
            "after_settle",
            side_effect=RuntimeError("injected owner hook failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected owner hook failure"):
                self.stores.attention.quiet_set(
                    built["set_id"], built["review_id"], now=current
                )
        with self.stores.database.connect() as connection:
            continuation_status = connection.execute(
                "SELECT status FROM agent_continuations WHERE continuation_id = ?",
                (continuation["continuation_id"],),
            ).fetchone()["status"]
            task_row = connection.execute(
                "SELECT status, attention_seen_version FROM hermes_tasks WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
        self.assertEqual(continuation_status, "pending")
        self.assertEqual(task_row["status"], "active")
        self.assertEqual(task_row["attention_seen_version"], "")
        self.assertEqual(len(self.stores.database.receipts()), 0)

    def test_set_identity_ignores_time_varying_rank_order(self) -> None:
        self.stores.continuations.create(
            goal="继续一项旧工作",
            stage="已经可以开始",
            due_at=self.now + timedelta(seconds=1),
            now=self.now,
        )
        self.stores.tasks.create(
            kind="scheduled",
            title="三天后提交",
            due_at=self.now + timedelta(hours=72),
            warn_hours=72,
            now=self.now,
        )
        early = self.stores.attention.build(now=self.now + timedelta(seconds=1))
        late = self.stores.attention.build(now=self.now + timedelta(hours=73))
        self.assertEqual(early["eligible_membership"], late["eligible_membership"])
        self.assertNotEqual(
            [item["source_kind"] for item in early["opportunities"]],
            [item["source_kind"] for item in late["opportunities"]],
        )
        self.assertEqual(early["set_id"], late["set_id"])
        self.assertNotEqual(early["review_id"], late["review_id"])

    def test_expired_claim_recovery_runs_before_heartbeat_build(self) -> None:
        self.stores.inbox.ingest(self.event(), now=self.now)
        candidate = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "provider_event",
            candidate["source_id"],
            candidate["source_version"],
            candidate["review_version"],
            now=self.now,
        )
        self.assertTrue(claim["claimed"])
        later = self.now + timedelta(seconds=300)
        self.assertEqual(self.stores.attention.build(now=later)["eligible_count"], 0)
        recovered = heartbeat(self.stores, now=later)
        self.assertEqual(recovered["maintenance"]["expired_claims_recovered"], 1)
        self.assertEqual(recovered["attention"]["eligible_count"], 1)

    def test_claimed_inbox_predecessor_fails_freshness_after_coalesce(self) -> None:
        first = AgentEvent(**{**self.event(1).__dict__, "coalesce_key": "sample-1"})
        second = AgentEvent(
            **{
                **self.event(2).__dict__,
                "coalesce_key": "sample-1",
                "subject_ref": "sample-1",
            }
        )
        self.stores.inbox.ingest(first, now=self.now)
        candidate = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "provider_event",
            candidate["source_id"],
            candidate["source_version"],
            candidate["review_version"],
            now=self.now,
        )
        self.stores.inbox.ingest(second, now=self.now + timedelta(seconds=1))
        stale = self.stores.attention.validate_claim(
            "provider_event", claim["claim_token"], now=self.now + timedelta(seconds=1)
        )
        self.assertFalse(stale["valid"])
        self.assertEqual(stale["reason"], "source_superseded")
        rejected = self.stores.attention.settle(
            "provider_event",
            claim["claim_token"],
            "acted",
            result={"action": "must not become canonical"},
            now=self.now + timedelta(seconds=1),
        )
        self.assertFalse(rejected["settled"])
        self.assertEqual(rejected["reason"], "claim_not_current")
        self.assertEqual(len(self.stores.database.receipts()), 0)
        current = self.stores.attention.build(now=self.now + timedelta(seconds=1))
        self.assertEqual(current["eligible_count"], 1)
        self.assertEqual(current["opportunities"][0]["source_id"], second.event_id)

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
            "provider_event", candidate["source_id"], candidate["source_version"],
            candidate["review_version"], now=self.now
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
