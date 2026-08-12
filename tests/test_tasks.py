from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from hermes_attention.runtime import open_runtime


class TaskStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.stores = open_runtime(str(Path(self.temporary.name) / "runtime.sqlite3"))
        self.now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_scheduled_warning_uses_local_due_proximity_not_global_weight(self) -> None:
        self.stores.tasks.create(
            kind="scheduled", title="交阶段报告",
            due_at=self.now + timedelta(hours=24), warn_hours=72, now=self.now,
        )
        built = self.stores.attention.build(now=self.now)
        task = built["opportunities"][0]
        self.assertEqual(task["context"]["attention_reason"], "warning")
        self.assertEqual(built["weights"]["provider_priority"], 0.04)
        self.assertNotIn("due_proximity", built["weights"])

    def test_failed_scheduled_phase_does_not_spam_but_later_phase_can_surface(self) -> None:
        due = self.now + timedelta(hours=24)
        self.stores.tasks.create(
            kind="scheduled", title="交阶段报告", due_at=due,
            warn_hours=72, grace_hours=24, now=self.now,
        )
        warning = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "ongoing", warning["source_id"], warning["source_version"], now=self.now
        )
        self.stores.attention.settle(
            "ongoing", claim["claim_token"], "failed", result={"error": "source unavailable"}, now=self.now
        )
        self.assertEqual(self.stores.attention.build(now=self.now)["eligible_count"], 0)
        overdue = self.stores.attention.build(now=due)
        self.assertEqual(overdue["opportunities"][0]["context"]["attention_reason"], "overdue")

    def test_standing_task_does_not_repeat_after_attention_settlement(self) -> None:
        created = self.stores.tasks.create(
            kind="standing", title="维护知识库", now=self.now
        )
        candidate = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "ongoing", candidate["source_id"], candidate["source_version"], now=self.now
        )
        self.stores.attention.settle("ongoing", claim["claim_token"], "quiet", now=self.now)
        self.assertEqual(self.stores.attention.build(now=self.now)["eligible_count"], 0)
        with self.stores.database.connect() as connection:
            status = connection.execute(
                "SELECT status FROM hermes_tasks WHERE task_id = ?", (created["task_id"],)
            ).fetchone()["status"]
        self.assertEqual(status, "active")

    def test_task_settlement_rolls_back_receipt_and_release_if_owner_hook_fails(self) -> None:
        self.stores.tasks.create(kind="standing", title="维护知识库", now=self.now)
        candidate = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "ongoing", candidate["source_id"], candidate["source_version"], now=self.now
        )
        with patch.object(
            self.stores.tasks,
            "after_settle",
            side_effect=RuntimeError("injected owner update failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected owner update failure"):
                self.stores.attention.settle(
                    "ongoing", claim["claim_token"], "acted", now=self.now
                )
        with self.stores.database.connect() as connection:
            task = connection.execute(
                "SELECT status, claim_token FROM hermes_tasks WHERE task_id = ?",
                (candidate["source_id"],),
            ).fetchone()
            receipts = connection.execute(
                "SELECT COUNT(*) AS count FROM source_receipts"
            ).fetchone()["count"]
        self.assertEqual(task["status"], "claimed")
        self.assertEqual(task["claim_token"], claim["claim_token"])
        self.assertEqual(receipts, 0)

    def test_meaningful_standing_update_surfaces_once(self) -> None:
        created = self.stores.tasks.create(
            kind="standing", title="维护知识库", now=self.now
        )
        first = self.stores.attention.build(now=self.now)["opportunities"][0]
        claim = self.stores.attention.claim_exact(
            "ongoing", first["source_id"], first["source_version"], now=self.now
        )
        self.stores.attention.settle("ongoing", claim["claim_token"], "quiet", now=self.now)
        changed_at = self.now + timedelta(hours=1)
        self.assertTrue(
            self.stores.tasks.update(
                created["task_id"], blocked=True, summary="等待单位账号", now=changed_at
            )["updated"]
        )
        changed = self.stores.attention.build(now=changed_at)["opportunities"][0]
        self.assertEqual(changed["context"]["attention_reason"], "blocked")
        claim = self.stores.attention.claim_exact(
            "ongoing", changed["source_id"], changed["source_version"], now=changed_at
        )
        self.stores.attention.settle("ongoing", claim["claim_token"], "quiet", now=changed_at)
        self.assertEqual(self.stores.attention.build(now=changed_at)["eligible_count"], 0)
        self.stores.tasks.update(created["task_id"], blocked=False, now=changed_at + timedelta(minutes=1))
        unblocked = self.stores.attention.build(now=changed_at + timedelta(minutes=1))
        self.assertEqual(unblocked["opportunities"][0]["context"]["attention_reason"], "changed")

    def test_periodic_maintenance_creates_new_cycle_outside_aos_build(self) -> None:
        created = self.stores.tasks.create(
            kind="periodic", title="月度整理", recurrence="monthly", now=self.now
        )
        before = self.stores.tasks.current_cycle(created["task_id"])
        next_month = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
        self.stores.tasks.maintain(now=next_month)
        after = self.stores.tasks.current_cycle(created["task_id"])
        self.assertNotEqual(before["cycle_id"], after["cycle_id"])
        with self.stores.database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM hermes_task_cycles WHERE task_id = ?",
                (created["task_id"],),
            ).fetchone()["count"]
        self.assertEqual(count, 2)

    def test_periodic_cycle_has_a_real_completion_path(self) -> None:
        created = self.stores.tasks.create(
            kind="periodic", title="月度整理", recurrence="monthly", now=self.now
        )
        completed = self.stores.tasks.complete_cycle(
            created["task_id"], result={"summary": "本月已归档"}, now=self.now
        )
        self.assertTrue(completed["completed"])
        cycle = self.stores.tasks.current_cycle(created["task_id"])
        self.assertEqual(cycle["status"], "completed")
        self.assertEqual(cycle["result_json"], '{"summary":"本月已归档"}')
        self.assertEqual(self.stores.attention.build(now=self.now)["eligible_count"], 0)
        repeated = self.stores.tasks.complete_cycle(
            created["task_id"], result={"summary": "不应覆写"}, now=self.now
        )
        self.assertFalse(repeated["completed"])
        self.assertEqual(repeated["reason"], "cycle_not_active")
        cycle = self.stores.tasks.current_cycle(created["task_id"])
        self.assertEqual(cycle["result_json"], '{"summary":"本月已归档"}')


if __name__ == "__main__":
    unittest.main()
