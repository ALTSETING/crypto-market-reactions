"""Export every SOL assignment with its explicit evidence and relevance score."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from high_impact_sources.parsers.crypto_relevance_detector import detect_crypto_relevance
from scripts.database.import_events import make_unique_slugs
from scripts.processing.build_website_dataset import (
    INVENTORY_PATH,
    MIN_BODY_ASSET_RELEVANCE,
    PARQUET_OUTPUT,
    ROOT,
)


OUTPUT = ROOT / "reports" / "sol_asset_review.csv"
SOL_EVIDENCE = re.compile(r"(?i)(?:\bsolana\b|\$SOL\b|\bSOL\b)")


def evidence_excerpt(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    match = SOL_EVIDENCE.search(compact)
    if not match:
        return ""
    start = max(0, match.start() - 70)
    end = min(len(compact), match.end() + 130)
    return compact[start:end][:limit]


def main() -> int:
    events = pd.read_parquet(PARQUET_OUTPUT)
    events["slug"] = make_unique_slugs(events)
    events["asset_list"] = events.related_assets.map(json.loads)
    sol_events = events[events.asset_list.map(lambda assets: "SOL" in assets)].copy()

    inventory = pd.read_parquet(INVENTORY_PATH)
    rows: list[dict[str, object]] = []
    for event in sol_events.itertuples(index=False):
        group = inventory[inventory.canonical_event_id.eq(event.event_id)]
        representative = group.sort_values(["priority", "member_id", "asset"]).iloc[0]
        title = str(representative.title or "")
        body = str(representative.body or "")
        title_assets = detect_crypto_relevance(title)[0]
        scores = group.groupby("asset").sem_asset_relevance.max().dropna()
        sol_relevance = scores.get("SOL")
        if "SOL" in title_assets:
            reason = "explicit SOL/Solana evidence in title"
            excerpt = evidence_excerpt(title)
        else:
            reason = (
                "explicit SOL/Solana evidence in body; semantic relevance "
                f">= {MIN_BODY_ASSET_RELEVANCE:.2f}"
            )
            excerpt = evidence_excerpt(body)
        rows.append(
            {
                "slug": event.slug,
                "title": event.title,
                "source": event.source,
                "related_assets": event.related_assets,
                "sol_relevance": None if pd.isna(sol_relevance) else float(sol_relevance),
                "assignment_reason": reason,
                "evidence_excerpt": excerpt,
            }
        )

    review = pd.DataFrame(rows).sort_values(["source", "title", "slug"])
    generic_coinbase = review[
        review.source.eq("sec")
        & review.title.str.match(r"^Coinbase Global .+ filing [0-9-]+$", na=False)
    ]
    if not generic_coinbase.empty:
        raise RuntimeError("Generic Coinbase filing remains in SOL review")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(OUTPUT, index=False, encoding="utf-8")
    print(
        json.dumps(
            {
                "rows": len(review),
                "sources": review.source.value_counts().to_dict(),
                "generic_coinbase_filings": len(generic_coinbase),
                "output": str(OUTPUT.relative_to(ROOT)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
