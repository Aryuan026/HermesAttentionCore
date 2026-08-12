from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from hermes_attention.runtime import open_runtime


class MigrationTest(unittest.TestCase):
    def test_only_explicit_pending_continuation_migrates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attention.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE opportunities (
                    opportunity_id TEXT PRIMARY KEY, source_kind TEXT, source_id TEXT,
                    source_version TEXT, title TEXT, summary TEXT, event_at TEXT,
                    due_at TEXT, payload_json TEXT, status TEXT, outcome TEXT,
                    created_at TEXT, updated_at TEXT
                );
                """
            )
            timestamp = "2026-08-12T01:00:00+00:00"
            rows = [
                ("old-cont", "continuation", "c1", "v1", "继续整理", "等导出后", timestamp,
                 "2026-08-12T12:00:00+00:00", json.dumps({"causal_opportunity_id": "root"}), "pending", "", timestamp, timestamp),
                ("old-chat", "chat_transcript", "q1", "v1", "群聊", "普通聊天", timestamp,
                 "", "{}", "pending", "", timestamp, timestamp),
                ("old-provider", "self_life", "m1", "v1", "外部事件", "旧事件", timestamp,
                 "", "{}", "pending", "", timestamp, timestamp),
                ("settled-provider", "self_life", "m2", "v1", "外部事件", "已完成", timestamp,
                 "", "{}", "settled", "acted", timestamp, timestamp),
            ]
            connection.executemany(
                "INSERT INTO opportunities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
            connection.commit()
            connection.close()

            stores = open_runtime(str(path))
            with stores.database.connect() as connection:
                migrated = connection.execute("SELECT COUNT(*) AS n FROM agent_continuations").fetchone()["n"]
                status = {
                    row["opportunity_id"]: (row["status"], row["outcome"])
                    for row in connection.execute("SELECT opportunity_id, status, outcome FROM opportunities")
                }
            self.assertEqual(migrated, 1)
            self.assertEqual(status["old-chat"], ("archived", "legacy_channel_context_not_migrated"))
            self.assertEqual(status["old-provider"], ("archived", "legacy_provider_event_not_replayed"))
            self.assertEqual(status["settled-provider"], ("settled", "acted"))
            open_runtime(str(path))
            with stores.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM agent_continuations").fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
