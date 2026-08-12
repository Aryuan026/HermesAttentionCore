from __future__ import annotations

import unittest
from pathlib import Path


class CapabilityBoundaryTest(unittest.TestCase):
    def test_attention_core_has_no_tool_or_mcp_registry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = "\n".join(
            (root / "src" / "hermes_attention" / name).read_text(encoding="utf-8")
            for name in ("attention.py", "inbox.py", "runtime.py")
        )
        for forbidden in (
            "enabled_toolsets",
            "tool_schema",
            "mcp_servers",
            "hermes tools enable",
            "hermes tools disable",
        ):
            self.assertNotIn(forbidden, source)

    def test_generic_installer_does_not_reconfigure_native_capabilities(self) -> None:
        root = Path(__file__).resolve().parents[1]
        installer = (root / "scripts" / "install_hermes.py").read_text(encoding="utf-8")
        self.assertNotIn('"mcp", "add"', installer)
        self.assertNotIn('"tools", "disable"', installer)
        self.assertNotIn('"tools", "enable"', installer)


if __name__ == "__main__":
    unittest.main()
