"""Generate CSV and JSON quality reports for the historical dataset."""
import argparse
from database.db import session_scope
from analysis.dataset_quality import build_quality_report, export_quality_report

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start"); parser.add_argument("--end"); parser.add_argument("--source")
    parser.add_argument("--symbols", nargs="+"); parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    with session_scope() as session: report = build_quality_report(session, args.start, args.end, args.source, args.symbols)
    csv_path, json_path = export_quality_report(report, args.output_dir)
    print(f"{report['status']}: {csv_path}, {json_path}")

if __name__ == "__main__": main()
