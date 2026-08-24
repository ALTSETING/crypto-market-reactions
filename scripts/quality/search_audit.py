"""Metadata-only 50-query search audit for Data Quality V2."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data" / "quality_v2" / "events_quality_v2_staging.parquet"
REPORT = ROOT / "reports" / "SEARCH_QUALITY_V2_AUDIT.csv"
DOC = ROOT / "docs" / "SEARCH_QUALITY_V2_AUDIT.md"
QUERIES = [
    "ethereum etf", "bitcoin etf", "sec ethereum", "solana hack", "binance hack",
    "coinbase sec", "blackrock bitcoin", "merge", "ethereum upgrade", "bitcoin halving",
    "ftx collapse", "terra luna", "spot bitcoin etf", "spot ethereum etf", "coinbase filing",
    "solana outage", "solana validator", "ethereum foundation", "bitcoin core release", "ethereum github",
    "sec filing", "regulatory filing", "protocol release", "official announcement", "github commit",
    "bitcoin mining", "ethereum staking", "solana network", "crypto regulation", "stablecoin regulation",
    "market manipulation", "exchange exploit", "wallet hack", "defi exploit", "token launch",
    "institutional bitcoin", "ether price", "btc price", "sol price", "crypto custody",
    "cointelegraph bitcoin", "coindesk ethereum", "decrypt solana", "sec coinbase", "ethereum merge",
    "bitcoin taproot", "ethereum shanghai", "ethereum dencun", "solana firedancer", "bitcoin ordinals",
]


def main() -> int:
    events = pd.read_parquet(DATASET)
    assets = events.related_assets.fillna("").astype(str)
    metadata = (
        events.display_title.fillna(events.title).astype(str) + " "
        + events.title.fillna("").astype(str) + " "
        + events.source.fillna("").astype(str) + " "
        + events.category.fillna("").astype(str) + " "
        + events.record_type.fillna("").astype(str) + " "
        + assets
    )
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
    matrix = vectorizer.fit_transform(metadata)
    query_matrix = vectorizer.transform(QUERIES)
    rows = []
    for query_index, query in enumerate(QUERIES):
        scores = (matrix @ query_matrix[query_index].T).toarray().ravel()
        top = scores.argsort()[::-1][:10]
        nonzero = int((scores > 0).sum())
        for rank, index in enumerate(top, 1):
            if scores[index] <= 0:
                continue
            event = events.iloc[index]
            rows.append({
                "query": query, "rank": rank, "score": scores[index], "event_id": event.event_id,
                "title": event.display_title, "source": event.source, "record_type": event.record_type,
                "related_assets": event.related_assets, "heuristic_relevance": "review_pending",
            })
        if nonzero == 0:
            rows.append({"query": query, "rank": None, "score": 0, "event_id": None, "title": None, "source": None, "record_type": None, "related_assets": None, "heuristic_relevance": "no_metadata_match"})
    result = pd.DataFrame(rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(REPORT, index=False)
    missing = sorted(set(QUERIES) - set(result.loc[result.event_id.notna(), "query"]))
    DOC.write_text(
        "# Search Quality V2 audit\n\n"
        f"Queries: **{len(QUERIES)}**. Metadata-only candidate index fields: title, display title, source, category, record type, and related assets. "
        "Article bodies were not indexed.\n\n"
        f"Queries with no metadata match: **{len(missing)}** ({json.dumps(missing)}). "
        "Ranked top-10 candidates and manual-review placeholders are in `reports/SEARCH_QUALITY_V2_AUDIT.csv`.\n",
        encoding="utf-8",
    )
    print(json.dumps({"queries": len(QUERIES), "result_rows": len(result), "queries_without_match": missing}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
