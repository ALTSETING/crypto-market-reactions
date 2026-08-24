# Historical backfill V2 local artifact audit

- Source records inspected: **2,909**.
- Accepted 2017–2022 records: **334**.
- Accepted records already represented by URL or canonical source mapping: **332**.
- New local QA candidates: **2**.
- Previously rejected records retained: **2,545**; they were not promoted.

The candidate artifact is `data/backfill_v2/candidate_events.parquet`. Candidates remain `needs_review`; no production import occurred. Most apparent URL differences were alternate source records already grouped into canonical events. The remaining candidates are SEC records with generic titles and require factual display-title/timestamp verification before inclusion.
