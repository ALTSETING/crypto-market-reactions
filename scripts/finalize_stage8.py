"""Wait for Stage 8 crawlers, then run reactions, audit, and tests."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

CRAWLER_PROCESS_IDS = (12216, 17228)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"
FINALIZE_STDOUT = LOGS_DIR / "stage8_finalize.stdout.log"
FINALIZE_STDERR = LOGS_DIR / "stage8_finalize.stderr.log"


def process_exists(process_id: int) -> bool:
    """Return whether a Windows process is still active."""

    process = ctypes.windll.kernel32.OpenProcess(0x100000, False, process_id)
    if not process:
        return False
    ctypes.windll.kernel32.CloseHandle(process)
    return True


def run_step(arguments: list[str], stdout, stderr, *, env=None) -> float:
    """Run one required finalization command and return elapsed seconds."""

    started = time.monotonic()
    subprocess.run(
        [sys.executable, "-m", *arguments],
        cwd=PROJECT_ROOT,
        stdout=stdout,
        stderr=stderr,
        env=env,
        check=True,
    )
    return time.monotonic() - started


def main() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    watcher_started_at = datetime.now(timezone.utc)

    with FINALIZE_STDOUT.open("a", encoding="utf-8") as stdout, FINALIZE_STDERR.open(
        "a", encoding="utf-8"
    ) as stderr:
        try:
            stdout.write(
                f"{watcher_started_at.isoformat()} waiting for crawler PIDs "
                f"{CRAWLER_PROCESS_IDS}\n"
            )
            stdout.flush()
            while any(process_exists(process_id) for process_id in CRAWLER_PROCESS_IDS):
                time.sleep(30)

            crawls_finished_at = datetime.now(timezone.utc)
            stdout.write(f"{crawls_finished_at.isoformat()} crawlers finished\n")
            stdout.flush()

            stdout.write(f"{datetime.now(timezone.utc).isoformat()} starting reactions\n")
            stdout.flush()
            reactions_seconds = run_step(
                [
                    "scripts.calculate_reactions",
                    "--start",
                    "2023-01-01",
                    "--end",
                    "2026-07-01",
                    "--symbols",
                    "BTCUSDT",
                    "ETHUSDT",
                    "SOLUSDT",
                    "--resume",
                ],
                stdout,
                stderr,
            )
            stdout.write(
                f"{datetime.now(timezone.utc).isoformat()} reactions complete "
                f"({reactions_seconds:.3f}s)\n"
            )
            stdout.flush()
            stdout.write(f"{datetime.now(timezone.utc).isoformat()} starting audit\n")
            stdout.flush()
            audit_seconds = run_step(
                [
                    "scripts.audit_dataset",
                    "--start",
                    "2023-01-01",
                    "--end",
                    "2026-07-01",
                    "--symbols",
                    "BTCUSDT",
                    "ETHUSDT",
                    "SOLUSDT",
                ],
                stdout,
                stderr,
            )
            stdout.write(
                f"{datetime.now(timezone.utc).isoformat()} audit complete "
                f"({audit_seconds:.3f}s)\n"
            )
            stdout.flush()

            pytest_temp = REPORTS_DIR / (
                "pytest_tmp_stage8_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            )
            pytest_temp.mkdir(parents=True, exist_ok=False)
            pytest_env = os.environ.copy()
            pytest_env["TMP"] = str(pytest_temp)
            pytest_env["TEMP"] = str(pytest_temp)
            stdout.write(f"{datetime.now(timezone.utc).isoformat()} starting pytest\n")
            stdout.flush()
            pytest_seconds = run_step(
                [
                    "pytest",
                    "-q",
                    "tests",
                    "-p",
                    "no:cacheprovider",
                    f"--basetemp={pytest_temp / 'run'}",
                ],
                stdout,
                stderr,
                env=pytest_env,
            )
            stdout.write(
                f"{datetime.now(timezone.utc).isoformat()} pytest complete "
                f"({pytest_seconds:.3f}s)\n"
            )
            stdout.flush()
            finalized_at = datetime.now(timezone.utc)
            process_times = {
                "watcher_started_at": watcher_started_at.isoformat(),
                "crawls_finished_at": crawls_finished_at.isoformat(),
                "reactions_seconds": reactions_seconds,
                "audit_seconds": audit_seconds,
                "pytest_seconds": pytest_seconds,
                "finalized_at": finalized_at.isoformat(),
            }
            (REPORTS_DIR / "stage8_process_times.json").write_text(
                json.dumps(process_times, indent=2), encoding="utf-8"
            )
            stdout.write(f"{finalized_at.isoformat()} Stage 8 finalization complete\n")
            stdout.flush()
        except Exception:
            traceback.print_exc(file=stderr)
            stderr.flush()
            raise


if __name__ == "__main__":
    main()
