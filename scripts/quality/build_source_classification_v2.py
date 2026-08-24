"""Build the frozen DZ14 event-level source-classification manifest.

The classifier accepts only stable event identity, URL/domain, and verified
source provenance. Legacy production record_type/source_type values are never
loaded or consulted. The 107 medium-confidence IDs are frozen decisions from
the reviewed DZ13 audit, keyed only by immutable event_id.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATASET = (
    ROOT
    / "data/website/release_candidates/news_quality_v3/events_release_candidate.parquet"
)
OUTPUT = ROOT / "reports/SOURCE_CLASSIFICATION_V2_MANIFEST.csv"
SUMMARY = ROOT / "reports/SOURCE_CLASSIFICATION_V2_MANIFEST.json"
EXPECTED_ROWS = 9_073
VERSION = "dz13-source-class-v2"
NEWS_DOMAINS = {"coindesk.com", "decrypt.co", "cointelegraph.com"}
GITHUB_SOURCES = {"btc_github", "eth_github", "ethereum_github", "sol_github"}
MEDIUM_CONFIDENCE_EVENT_IDS = frozenset(
    {
        "evt18-016c0710f2ac9b4fb513",
        "evt18-01c1050db8864fc00b51",
        "evt18-05580c290ff2056ce545",
        "evt18-0ec666d8b9f0c2867661",
        "evt18-139c64254bec7d9910f2",
        "evt18-13b6195163f4416d544e",
        "evt18-16323e959d16f8f74e51",
        "evt18-1785d4f629411ad6d5e0",
        "evt18-2245db3794c29aecc174",
        "evt18-286df48f73b457ad00ae",
        "evt18-2bb2aab1e007864965a0",
        "evt18-35148849d3c8400c46e8",
        "evt18-363c20806447ac41f573",
        "evt18-36cda2e851578d5b469a",
        "evt18-380e485f1887e5321282",
        "evt18-3c6e6112be42e0f407f6",
        "evt18-3daf6ae9f14b6dfe0ef2",
        "evt18-4b6cfb68a5f534d6b6ab",
        "evt18-4d106e37b84a11511ff0",
        "evt18-4dd4ae11be7382787bc4",
        "evt18-50f670a6b9eaed982254",
        "evt18-54dbff7d61eccf5f66d1",
        "evt18-5604a0f0875cfcf6f909",
        "evt18-567a5be9f65506cc245b",
        "evt18-56d4f4a20dc200c157a7",
        "evt18-576ae912227240792b79",
        "evt18-5a80e3a98b84568a027b",
        "evt18-5c42ae1721db977bd203",
        "evt18-5c6a8319d3f2370effa3",
        "evt18-61989f2aeced9c6c908d",
        "evt18-6352dc7977d02c0b462d",
        "evt18-675b307bcd0d3a9560c6",
        "evt18-6a0a1e671222f047b05e",
        "evt18-6a81f40ece910b59e459",
        "evt18-6c3001180ae12aa7eace",
        "evt18-6d680df320c6090f3ca6",
        "evt18-6de03d7c7f02f9f905d7",
        "evt18-6ed3847be19da3e3ae6e",
        "evt18-7048065c2c3ff8e321cf",
        "evt18-723010dbb4de11c47539",
        "evt18-731e73cfa1b73b344c54",
        "evt18-7409451d30dd7d25fe30",
        "evt18-7790ffb9ad1fca9a2ed0",
        "evt18-7aab790aad0b4dc9f850",
        "evt18-7b32a649c6375c6aaef2",
        "evt18-7c6582223ef4b6fdd3ad",
        "evt18-7e1cade8508fa2e96628",
        "evt18-7ed8e8d36a010146156c",
        "evt18-852b96f2ff2549061bae",
        "evt18-8708c63572c47739fa1e",
        "evt18-8ad2b5dda16b6cde250c",
        "evt18-8d6f2c41758f0004d7d9",
        "evt18-8e1205acbe3b0201af91",
        "evt18-8e9149c0bc66a89fde0e",
        "evt18-8f3a0488093a790d855a",
        "evt18-8f760bdbb15bdf120381",
        "evt18-9c625387064e657c1472",
        "evt18-9c9b8a0572950dcfdcca",
        "evt18-9e2326bb419734d4a675",
        "evt18-9e337de263a293020f69",
        "evt18-a0de824f64c5ddac9f65",
        "evt18-a4227f5429742fbdbb8b",
        "evt18-a4458b698d37f6bfabdf",
        "evt18-a4ad65a0cc963b15290e",
        "evt18-a5200aa1f9b9e40e5df7",
        "evt18-a870568067407c9bbcc9",
        "evt18-a91754a2b280fee038b2",
        "evt18-ac058cc7d026872aa93f",
        "evt18-aeaaeb6a37f67f7c7c6a",
        "evt18-b0bf2ba6855b7f63fc38",
        "evt18-b12208168e88f6a8a416",
        "evt18-b1c74b9ddd6ac518d36f",
        "evt18-b58fcc78bc5810226bc7",
        "evt18-b78d8d8aee0b588ccdc0",
        "evt18-b91b7308705760f9c89d",
        "evt18-be75357670b98aa5bc04",
        "evt18-bf96d28e2985c64a1a7b",
        "evt18-c12b2984e631b21a435b",
        "evt18-c1e6f7bebb4b197e9da3",
        "evt18-c29caddfcc3cce2e73ff",
        "evt18-c2a3bdc7c5c12c13fead",
        "evt18-c34957bd4e6d02130ecd",
        "evt18-c45d9837e89599a630fe",
        "evt18-c689813dc7400d18691b",
        "evt18-c6eb3e81cf3c2f9efdbb",
        "evt18-c962a6df62672c5f9ce7",
        "evt18-cb75725bc2cf32bfc8cb",
        "evt18-d5d9fd68ba962ef61608",
        "evt18-d9f734d3050f2e5ad806",
        "evt18-e180439a2d9db28454ea",
        "evt18-e373f8064541750bab12",
        "evt18-e63cd1c1f47a486f8436",
        "evt18-e75a737cf58d77d5f35f",
        "evt18-e762fd29fbfd81657bd0",
        "evt18-e954221f26ddcc18d042",
        "evt18-e9f733cfaa6c2d581a64",
        "evt18-ea583cf92c3583c4866d",
        "evt18-ec4c0c7dceaa891d8123",
        "evt18-ed835e9d1001d01e0e58",
        "evt18-ee632082eff900aac793",
        "evt18-ee6c19a909b1e02475f9",
        "evt18-f13c3c91cf1d7b1f9d3f",
        "evt18-f3f4dab31568d3e6e9da",
        "evt18-f6344efa1d2227aae920",
        "evt18-f98af883fa9bf95b2597",
        "evt18-fbef7407f28d6b304df6",
        "evt18-fef98ba92fb515031056",
    }
)


@dataclass(frozen=True)
class SourceClassification:
    source_class_v2: str
    document_class_v2: str
    source_class_confidence_v2: str
    classification_rule: str


def normalized_domain(value: str) -> str:
    host = (urlparse(value).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify(event_id: str, source_url: str, verified_provenance: str) -> SourceClassification:
    domain = normalized_domain(source_url)
    path = urlparse(source_url).path.lower()
    provenance = verified_provenance.lower()
    if domain in NEWS_DOMAINS:
        confidence = "medium" if event_id in MEDIUM_CONFIDENCE_EVENT_IDS else "high"
        return SourceClassification(
            "news_media",
            "news_article",
            confidence,
            "reviewed publisher domain plus frozen DZ13 event-level confidence decision",
        )
    if domain == "sec.gov":
        return SourceClassification(
            "primary_document", "regulatory_filing", "high", "official SEC domain"
        )
    if domain == "github.com" and provenance in GITHUB_SOURCES:
        if "/releases/" in path:
            return SourceClassification(
                "official_announcement",
                "protocol_announcement",
                "high",
                "verified project GitHub release URL",
            )
        return SourceClassification(
            "primary_document", "other", "high", "verified project GitHub provenance"
        )
    if domain == "blog.ethereum.org":
        return SourceClassification(
            "official_announcement",
            "protocol_announcement",
            "high",
            "official Ethereum publication domain",
        )
    return SourceClassification(
        "unknown", "other", "low", "stable domain/provenance registry has no match"
    )


def mapping_sha256(frame: pd.DataFrame) -> str:
    columns = [
        "event_id",
        "source_class_v2",
        "document_class_v2",
        "source_class_confidence_v2",
        "source_classification_version",
    ]
    digest = hashlib.sha256()
    for row in frame.sort_values("event_id")[columns].itertuples(index=False, name=None):
        digest.update(("|".join(map(str, row)) + "\n").encode("utf-8"))
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> tuple[pd.DataFrame, dict[str, object]]:
    stable = pd.read_parquet(
        DATASET, columns=["event_id", "source", "source_url"]
    ).sort_values("event_id")
    if len(stable) != EXPECTED_ROWS or stable.event_id.nunique() != EXPECTED_ROWS:
        raise RuntimeError("Release identity is not the frozen 9,073-event set")
    rows: list[dict[str, object]] = []
    for item in stable.itertuples(index=False):
        decision = classify(item.event_id, item.source_url, item.source)
        rows.append(
            {
                "event_id": item.event_id,
                "normalized_source_domain": normalized_domain(item.source_url),
                "source_url_sha256": hashlib.sha256(item.source_url.encode("utf-8")).hexdigest(),
                "verified_provenance": item.source,
                **asdict(decision),
                "source_classification_version": VERSION,
            }
        )
    manifest = pd.DataFrame(rows).sort_values("event_id").reset_index(drop=True)
    source_counts = manifest.source_class_v2.value_counts().to_dict()
    confidence_counts = manifest.source_class_confidence_v2.value_counts().to_dict()
    if source_counts != {
        "news_media": 8_046,
        "primary_document": 736,
        "official_announcement": 291,
    }:
        raise RuntimeError(f"Source classification counts changed: {source_counts}")
    if confidence_counts != {"high": 8_966, "medium": 107}:
        raise RuntimeError(f"Confidence classification counts changed: {confidence_counts}")
    if set(manifest.loc[manifest.source_class_confidence_v2.eq("medium"), "event_id"]) != MEDIUM_CONFIDENCE_EVENT_IDS:
        raise RuntimeError("Frozen medium-confidence event identity set changed")
    mapping_hash = mapping_sha256(manifest)
    manifest.to_csv(OUTPUT, index=False, encoding="utf-8", lineterminator="\n")
    summary = {
        "version": "SOURCE_CLASSIFICATION_V2_MANIFEST_V1",
        "source_classification_version": VERSION,
        "rows": len(manifest),
        "unique_event_ids": int(manifest.event_id.nunique()),
        "source_counts": {**source_counts, "unknown": 0},
        "document_counts": manifest.document_class_v2.value_counts().to_dict(),
        "confidence_counts": {**confidence_counts, "low": 0},
        "event_level_mapping_sha256": mapping_hash,
        "stable_input_sha256": hashlib.sha256(
            "".join(
                f"{row.event_id}|{row.normalized_source_domain}|{row.source_url_sha256}|{row.verified_provenance}\n"
                for row in manifest.itertuples(index=False)
            ).encode("utf-8")
        ).hexdigest(),
        "legacy_record_type_used": False,
        "legacy_source_type_used": False,
        "paid_ai_api_used": False,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary["manifest_file_sha256"] = file_sha256(OUTPUT)
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return manifest, summary


def main() -> int:
    _, summary = build()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
