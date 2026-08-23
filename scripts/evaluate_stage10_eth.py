"""Generate the read-only Stage 10 ETH effectiveness audit."""
from __future__ import annotations
import json
from pathlib import Path
from analysis.stage10_evaluator import write_reports
from database.db import session_scope

ROOT=Path(__file__).resolve().parents[1]
if __name__=="__main__":
    with session_scope() as session:
        summary=write_reports(session,ROOT/"reports")
    print(json.dumps(summary,indent=2,ensure_ascii=False))
