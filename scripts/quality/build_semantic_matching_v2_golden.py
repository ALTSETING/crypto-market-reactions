"""Materialize the fixed, manually curated Semantic Matching V2 oracle.

The selection is pinned by production event_id after headline-by-headline
review. The script performs one bounded read-only snapshot, verifies every
curated id still resolves, then stores immutable raw fields plus conservative
manual labels. It never uses candidate matcher output to select an event.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.quality.semantic_matching_v2_audit import (
    DEFAULT_GOLDEN,
    EXPECTED_BUCKETS,
    _production_rows,
    extract_amounts_usd,
    magnitude_class,
)


CURATED_IDS: dict[str, tuple[str, ...]] = {
    "large_investment": (
        "bf3-0dd8ae084aeed1735905", "bf3-5d84c8d6a28b844368b2", "bf3-a39a71af7e15a5014b1a",
        "bf3-c8177016ec93648e3b44", "evt18-01cdfb4c53c98d387691", "evt18-0dd07c239e902c333696",
        "evt18-1208c2d644ec4838889b", "evt18-227627368802547814c4", "evt18-25ef67c912a71a56a912",
        "evt18-3399ef235b33b9383800", "evt18-385f3ac41cd3b160d76b", "evt18-3e1b5ed3b5ea967c3c7f",
        "evt18-47bbf6224352188073bf", "evt18-48e098465dd507f864d5", "evt18-49f563cc4d59415e0e44",
        "evt18-4a98f06a63c3b83a2ef7", "evt18-4d9457b70f345b3028d3", "evt18-51a2a65a6b2ed60a69bb",
        "evt18-56959277f094ec3478d1", "evt18-70de44ad0ac84366f344", "evt18-730ad7ea5ead0bc2d1c6",
        "evt18-77d0128efddbc612a3e9", "evt18-8e170de5a0c4fe004abc", "evt18-8e403921f85fe4a540a9",
        "evt18-8f2ac9eaf6b293ddac4a", "evt18-95c96e5aa33b4a444fa2", "evt18-b37da6e3e147630c31eb",
        "evt18-b5bc4203b5f674af67aa", "evt18-b6e3d0b15663ed5a994e", "evt18-b8bb9164d0222ef1ced6",
    ),
    "institutional_purchase": (
        "bf3-1e87e26fd5d94c022992", "evt18-00dee9e3f1180cd0a233", "evt18-15e0ad71297ced8dfda5",
        "evt18-21e574aa7f9cc359f663", "evt18-34ec9fcec30853741e28", "evt18-3c7af2f3fefe33dbd15a",
        "evt18-6bf76287496c466cbd4b", "evt18-6c1421f0dfd1b34edb49", "evt18-8b2940cd708b5dda55ff",
        "evt18-8bc46e924f7753376712", "evt18-8c09febab39061b5ac60", "evt18-908c7fe83f10fd9360a9",
        "evt18-916858ac98ad697ee216", "evt18-ba18635ff7853e9bdacc", "evt18-c225dca72a96a6be898c",
        "evt18-c63d0636ba7933aace8f", "evt18-db8a050a6c2c22812d95", "evt18-db8ccd8bc1bebaab15a8",
        "evt18-dd82b3bdce51e6f4eea6", "evt18-ebb79f59f425199fb247",
    ),
    "institutional_selling": (
        "bf3-0b43df3069da6a2a7033", "bf3-b9bc8685e5315d198056", "bf3-bc863625ce9aa14571fd",
        "evt18-0d42f5c801b0e7896c6c", "evt18-13f9b02b39f5eb6bfacd", "evt18-17f50a7868798f94b09b",
        "evt18-18fb82224d4f22f00017", "evt18-1bdc789b9171fb73a92b", "evt18-20c429c67f29f21ec1ed",
        "evt18-25b7056cf488c7c82096", "evt18-2901c122fccb5670490b", "evt18-2c0fce2680726ac362e6",
        "evt18-2ecf12ba98ba4002452e", "evt18-30267161dfa8473e8706", "evt18-4c4fa83215dc96835eac",
        "evt18-5607d8b7a1d0e1e9f678", "evt18-5b5ef82afe2d6549d136", "evt18-61b489a5c034d807fee5",
        "evt18-69e2b771f0b1cbacf2af", "evt18-5efd560e402b7ae204b0",
    ),
    "etf": (
        "bf3-211517a47d34b9bd1f7a", "bf3-258c2d3dfcb8e0695192", "bf3-288e1ab0951e1c2c679b",
        "bf3-2da0c97423322b395265", "bf3-3218cb8e7ba08855bfbd", "bf3-4be551a9e8df4ff23a72",
        "bf3-55402667a832b48f3de0", "bf3-611878a4874c4e80d8ac", "bf3-729cad36a8a6cee4a1de",
        "bf3-891e50c017b843692f0a", "bf3-8a549d2a4bd951d561f4", "bf3-964717783db0da0e7f86",
        "bf3-a9b76d38c5ec63f6d6ef", "bf3-d097c515d8b625aac96f", "bf3-d42f5ea90deea8ac2085",
        "bf3-f0ecf95b4ccf6416247d", "bf3-f84614306fdc5dfdfa84", "bf3-fc1fbdef9badcf75bed9",
        "bf3-eee0a92cb495117e0239", "bf3-757a42cf0ab7ab2562a1",
    ),
    "sec": (
        "bf3-13c379e8bcc3c32adfe1", "bf3-1e7b774ffc6caa288f98", "bf3-2f3e47a9352e1a6ffcbe",
        "bf3-36e6bfc5417d8fdb2825", "bf3-3742b5537fa9e10ca301", "bf3-4c3e309c425cc2bf4a24",
        "bf3-4cdf4bdbb3d77b3da054", "bf3-56f2989aac53c21b6a89", "bf3-5c39c6c7f17a41d99dc9",
        "bf3-5d6567aecd4d112b625a", "bf3-607ffdc5890df5990742", "bf3-645c4a7a4a8290dd3423",
        "bf3-6e53f4df775a9298d9a9", "bf3-717d931239b574ad298f", "bf3-85dc3213c113e54ddd5f",
        "bf3-996cb761a5a1e7cbb56a", "bf3-9b8fef1ce6e712e71092", "bf3-9ea86b026ab2fb5fe31d",
        "bf3-a8305fc9b68b17ba2d99", "bf3-b7fffe64dcc573bf4a32",
    ),
    "hack": (
        "bf3-017b1fb810c8c78d2350", "bf3-e59b0f0cc006d1229bfc", "bf3-220f9ce376591cab3181",
        "bf3-2acb449014f3125ba020", "bf3-2cf581dbe5a42ead5437", "bf3-3038ebc7503964fea9f5",
        "bf3-392dd400b7ea2e9affdf", "bf3-60129d29973f157ab8bd", "bf3-610eccbb7ee4d00ab38a",
        "bf3-6fe490146c17180edc9e", "bf3-72365f568306bc9026ed", "bf3-72764b5186743fcf6519",
        "bf3-7619d5dc21ac99f15fd2", "bf3-7f82602fdb4f73b80a14", "bf3-be366ff64175a5699936",
        "bf3-8c8aee1b686795bfbcea", "bf3-937e69dfd040cc8f3a11", "bf3-aab96aaa09f2cdbcd726",
        "bf3-b2b9fcabe5044ff074cf", "bf3-cbcde057a83c36b08e98",
    ),
    "negative_control": (
        "evt18-320dc083832eecf11ac1", "evt18-3b31d6f97ca3796d03a4", "evt18-40dfcd31e89d861dd55c",
        "evt18-5da892d2321582570fdd", "evt18-af71ab6f691fbdf8b72f", "evt18-a9f952ec15484d299a31",
        "evt18-c759327145a295621a88", "evt18-fb53640d32e0bbd3dd68", "bf3-6366ef0c780779242130",
        "bf3-27a2d1fe608418a4cbf9", "evt18-911131a45d403c1f8fa3", "evt18-82dcfea33523e6b5a54e",
        "evt18-df9b81fbbff1a8ed74b7", "evt18-b9c68794073a0f9e14cf", "bf3-a213510dadbd74ca179a",
        "bf3-8ebbdef6978304330d1a", "evt18-c1e581d10539b3137c1d", "evt18-1174504f4ded7a7ead9f",
        "evt18-cffb5caf61c8e1e7044d", "bf3-1fcd3f14e4fb482ccf5f",
    ),
}

ASSET_RE = {
    "BTC": re.compile(r"\b(?:BTC|Bitcoin)\b", re.I),
    "ETH": re.compile(r"\b(?:ETH|Ether|Ethereum)\b", re.I),
    "SOL": re.compile(r"\b(?:SOL|Solana)\b", re.I),
}
ASSET_OVERRIDES = {
    # The headline contrasts BTC selling with a passive Ether-funds mention;
    # the audited action target is BTC, irrespective of related_assets order.
    "bf3-b9bc8685e5315d198056": "BTC",
    # Harvard reduced BTC ETF exposure but added Ether exposure; this cohort
    # audits the institutional purchase target, so ETH is the correct side.
    "evt18-34ec9fcec30853741e28": "ETH",
    # Both headlines mention Bitcoin only in a later market-analysis clause;
    # the completed treasury purchase itself is explicitly Ethereum.
    "evt18-0dd07c239e902c333696": "ETH",
    "evt18-b37da6e3e147630c31eb": "ETH",
}


def audited_asset(row: dict[str, Any]) -> str:
    assets = [asset for asset in (row.get("related_assets") or []) if asset in ASSET_RE]
    override = ASSET_OVERRIDES.get(str(row["event_id"]))
    if override:
        if override not in assets:
            raise ValueError(f"curated asset override is not related: {row['event_id']}")
        return override
    direct = [asset for asset in assets if ASSET_RE[asset].search(str(row["title"]))]
    if not assets:
        raise ValueError(f"curated event has no audited asset: {row['event_id']}")
    return direct[0] if direct else assets[0]


def actor_label(title: str, bucket: str) -> str:
    if bucket == "etf" or re.search(r"\bETF", title, re.I): return "ETF"
    if bucket == "sec" or re.search(r"\bSEC\b", title): return "regulator"
    if re.search(r"\b(?:fund|funds)\b", title, re.I): return "fund"
    if re.search(r"\b(?:institution|institutional|bank|endowment|treasury|Strategy|MicroStrategy|BlackRock|Grayscale)\b", title, re.I): return "institution"
    if re.search(r"\b(?:company|corporation|corp\.?|Inc\.?|Ltd\.?)\b", title, re.I): return "company"
    if re.search(r"\bwhales?\b", title, re.I): return "whale"
    if re.search(r"\binvestors?\b", title, re.I): return "investor"
    if re.search(r"\b(?:exchange|Binance|Coinbase|Kraken|OKX)\b", title, re.I): return "exchange"
    return "unknown"


def action_label(title: str, bucket: str) -> str:
    if bucket == "large_investment" or bucket == "institutional_purchase": return "buy"
    if bucket == "institutional_selling":
        return "withdraw" if re.search(r"\b(?:outflow|redemption|yank)\w*\b", title, re.I) else "sell"
    if bucket == "hack": return "exploit" if re.search(r"\bexploit\w*\b", title, re.I) else "hack"
    if bucket == "sec":
        for action, pattern in (("approve", r"\bapprov"), ("reject", r"\breject"), ("file", r"\bfil"), ("sue", r"\b(?:sue|lawsuit)")):
            if re.search(pattern, title, re.I): return action
    return "unknown"


def build(env_path: Path, output: Path) -> list[dict[str, Any]]:
    snapshot = {str(row["event_id"]): row for row in _production_rows(env_path)}
    curated = [event_id for ids in CURATED_IDS.values() for event_id in ids]
    if len(curated) != len(set(curated)):
        raise ValueError("curated event ids overlap between cohorts")
    missing = sorted(set(curated) - set(snapshot))
    if missing:
        raise ValueError(f"curated production events missing: {missing}")
    output_rows: list[dict[str, Any]] = []
    sequence = 0
    for bucket, ids in CURATED_IDS.items():
        if len(ids) != EXPECTED_BUCKETS[bucket]:
            raise ValueError(f"{bucket}: expected {EXPECTED_BUCKETS[bucket]}, got {len(ids)}")
        for event_id in ids:
            sequence += 1
            row = snapshot[event_id]
            title = str(row["title"])
            asset = audited_asset(row)
            positive = bucket != "negative_control"
            amounts = extract_amounts_usd(title)
            amount = max(amounts) if amounts else None
            direction = "inflow" if bucket in {"large_investment", "institutional_purchase"} else "outflow" if bucket == "institutional_selling" else "neutral" if positive else "unknown"
            notes = {
                "large_investment": "Manual headline review: completed crypto-asset purchase/addition with explicit amount at or above USD 50M.",
                "institutional_purchase": "Manual headline review: institution, company, fund, or treasury directly purchased/added the audited crypto asset.",
                "institutional_selling": "Manual headline review: institution, ETF, fund, investor, or whale directly sold/redeemed the audited crypto asset.",
                "etf": "Manual headline review: the headline directly concerns a crypto exchange-traded fund.",
                "sec": "Manual headline review: the headline directly concerns an SEC action, filing, position, or proceeding.",
                "hack": "Manual headline review: the headline reports an actual hack, exploit, breach, or its concrete aftermath.",
                "negative_control": "Manual headline review: hard negative; wording refers to stock/share buybacks or ratings, paused/skipped buying, a denied/prevented incident, or non-crypto-asset support.",
            }[bucket]
            output_rows.append({
                "id": f"golden-{sequence:03d}", "event_id": event_id,
                "provenance": "production_readonly_manual_curation_2026-08-26", "title": title,
                "assets": list(row.get("related_assets") or []), "primary_asset": row.get("primary_asset"),
                "category": str(row.get("category") or "other"), "asset": asset,
                "audit_bucket": bucket, "relevant": positive,
                "asset_relevance": "primary" if ASSET_RE[asset].search(title) else "secondary",
                "actor_type": actor_label(title, bucket), "action": action_label(title, bucket),
                "direction": direction,
                "magnitude_class": "large" if bucket == "large_investment" else magnitude_class(amount, title),
                "amount_usd": amount, "expected_topic": bucket if positive else None,
                "label_notes": notes,
            })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output_rows), encoding="utf-8")
    return output_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-env", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_GOLDEN)
    args = parser.parse_args()
    rows = build(args.production_env, args.output)
    print(json.dumps({"rows": len(rows), "output": str(args.output), "production_writes": "NO"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
