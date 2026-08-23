"""Poll one recorded Stage 9 batch and finalize it without submitting or retrying."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_stage9_eth_batch import FINAL_PATH, finalize, status, write_json

ROOT = Path(__file__).resolve().parents[1]
WATCH_PATH = ROOT / "reports" / "stage9_eth_batch_watcher.json"
TERMINAL = {"completed", "failed", "expired", "cancelled"}


def main() -> None:
    started = datetime.now(timezone.utc)
    while True:
        state = status()
        write_json(WATCH_PATH, {
            "watcher_pid": __import__("os").getpid(), "started_at": started.isoformat(),
            "checked_at": datetime.now(timezone.utc).isoformat(), "batch_id": state["batch_id"],
            "status": state["status"], "request_counts": state.get("request_counts"),
            "creates_batches": False, "automatic_retries": False,
        })
        if state["status"] in TERMINAL:
            break
        time.sleep(300)
    if state["status"] == "completed":
        report = finalize()
        pytest_root = ROOT / "reports" / "pytest_stage9_batch_finalize"
        pytest_root.mkdir(parents=True, exist_ok=True)
        test = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests", "-p", "no:cacheprovider",
             f"--basetemp={pytest_root / 'run'}"],
            cwd=ROOT, capture_output=True, text=True,
        )
        report["pytest_exit_code"] = test.returncode
        report["pytest_summary"] = (test.stdout + "\n" + test.stderr).strip()[-2000:]
        if test.returncode != 0:
            report["status"] = "FAIL"
        write_json(FINAL_PATH, report)
    else:
        write_json(FINAL_PATH, {"status": "FAIL", "batch_id": state["batch_id"],
                                "batch_status": state["status"], "reason": "Batch ended without completion"})


if __name__ == "__main__":
    main()
