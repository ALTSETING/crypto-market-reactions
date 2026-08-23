import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def test_stage135_manifest_and_hashes_are_reproducible():
    manifest = json.loads((ROOT / "reports/stage135_dataset_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["file_hashes_sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_stage135_variants_have_same_events_and_splits():
    core = pd.read_parquet(ROOT / "data/stage135/market_core.parquet", columns=["event_key", "split"])
    for name in ("market_futures", "market_futures_primary_timing"):
        frame = pd.read_parquet(ROOT / f"data/stage135/{name}.parquet", columns=["event_key", "split"])
        assert frame.equals(core)


def test_stage135_targets_are_separate_and_complete():
    target = pd.read_parquet(ROOT / "data/stage135/targets.parquet")
    predictors = pd.read_parquet(ROOT / "data/stage135/market_futures_primary_timing.parquet")
    assert len(target) == len(predictors) == 6851
    assert not any(column.startswith("target_") for column in predictors)
    assert target.event_key.is_unique and predictors.event_key.is_unique
