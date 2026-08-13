#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


repository = Path(
    os.environ.get("HERMES_ATTENTION_REPO", str(Path(__file__).resolve().parents[1]))
).resolve()
sys.path.insert(0, str(repository / "src"))

from hermes_attention.adapters import load_adapter_polls
from hermes_attention.runtime import heartbeat, open_runtime, render_cron_preflight


configured_database = os.environ.get("HERMES_ATTENTION_DB", "").strip()
if not configured_database:
    raise SystemExit(
        "HERMES_ATTENTION_DB is required; run the installed heartbeat wrapper"
    )
database = Path(configured_database)
stores = open_runtime(str(database))
result = heartbeat(stores, adapter_polls=load_adapter_polls(stores))
for adapter in result["adapter_results"]:
    if not adapter["ok"]:
        # Optional-source failure is visible in operator logs but cannot block
        # another owner's due reminder/task or fabricate user-facing speech.
        print(
            f"attention adapter failed: {adapter['error_type']}: {adapter['error']}",
            file=sys.stderr,
        )

print(render_cron_preflight(result))
