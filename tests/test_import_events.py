from pathlib import Path

import pandas as pd
import pytest

from scripts.database.import_events import (
    DEFAULT_DATASET,
    copy_buffer,
    make_slug,
    normalize_database_url,
    parse_related_assets,
    prepare_dataset,
)


def dataset_content_available() -> bool:
    if not DEFAULT_DATASET.is_file():
        return False
    return not DEFAULT_DATASET.read_bytes()[:64].startswith(b"version https://git-lfs")


@pytest.mark.skipif(
    not dataset_content_available(),
    reason="the website dataset is a Git LFS artifact and was not downloaded",
)
def test_prepare_current_dataset_contract_and_slugs():
    frame = prepare_dataset(DEFAULT_DATASET)
    assert len(frame) == len(pd.read_parquet(DEFAULT_DATASET))
    assert frame.event_id.is_unique
    assert frame.slug.is_unique
    assert frame.slug.str.match(r"^[a-z0-9-]+$").all()
    assert frame.slug.str.len().le(180).all()
    assert frame.related_assets.map(lambda value: set(value) <= {"BTC", "ETH", "SOL"}).all()


def test_slug_is_readable_stable_and_event_based():
    timestamp = pd.Timestamp("2024-05-23T12:00:00Z")
    slug = make_slug("SEC Approves Ethereum ETF!", timestamp, "evt18-a81f2c123456")
    assert slug == "sec-approves-ethereum-etf-2024-a81f2c12"
    assert slug == make_slug("SEC Approves Ethereum ETF!", timestamp, "evt18-a81f2c123456")


def test_related_assets_json_contract():
    assert parse_related_assets('["BTC","ETH"]') == ["BTC", "ETH"]
    assert parse_related_assets("[]") == []


def test_sqlalchemy_and_legacy_urls_are_normalized_for_psycopg2():
    assert normalize_database_url("postgresql+psycopg2://u:p@host/db") == "postgresql://u:p@host/db"
    assert normalize_database_url("postgres://u:p@host/db") == "postgresql://u:p@host/db"


def test_copy_buffer_uses_postgresql_null_marker():
    frame = pd.DataFrame([["evt", None, ["ETH"], pd.NaT]])
    payload = copy_buffer(frame).read()
    assert r"\N" in payload
    assert "{ETH}" in payload
    assert "NaT" not in payload
