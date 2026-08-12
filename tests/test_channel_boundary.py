from __future__ import annotations

import unittest
from pathlib import Path

from hermes_attention.cli import parser


class ChannelBoundaryTest(unittest.TestCase):
    def test_no_conversation_channel_hook_or_transcript_command_exists(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        self.assertFalse((repository / "integrations" / "hermes-hook" / "handler.py").exists())
        help_text = parser().format_help()
        self.assertNotIn("ingest-transcript", help_text)
        self.assertNotIn("qqbot", help_text)

    def test_heartbeat_does_not_launch_second_agent_or_deliver_output(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        script = (repository / "scripts" / "hermes_attention_heartbeat.py").read_text()
        self.assertNotIn("subprocess", script)
        self.assertNotIn("hermes -z", script)
        self.assertNotIn("HERMES_ATTENTION_AGENT_CLI", script)


if __name__ == "__main__":
    unittest.main()
