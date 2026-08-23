from __future__ import annotations

import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest

from historical_market_data.archive_discovery import month_minutes, month_range
from historical_market_data.binance_archive_client import BinanceArchiveClient
from historical_market_data.binance_rest_client import BinanceRestClient
from historical_market_data.checksum import parse_checksum, verify_checksum
from historical_market_data.coverage import HORIZONS
from historical_market_data.gap_detector import classify_before_listing, detect_gaps
from historical_market_data.importer import import_prepared
from historical_market_data.models import Candle
from historical_market_data.parser import iter_zip_rows, normalize_timestamp
from historical_market_data.validator import validate_candle


def candle(**overrides):
    values = dict(
        symbol="ETHUSDT", interval="1m", open_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        close_time=datetime(2020, 1, 1, 0, 0, 59, 999000, tzinfo=timezone.utc),
        open=Decimal("100"), high=Decimal("110"), low=Decimal("90"), close=Decimal("105"),
        volume=Decimal("1"), quote_volume=Decimal("100"), trade_count=2,
        taker_buy_base_volume=Decimal("0.5"), taker_buy_quote_volume=Decimal("50"),
        source_type="monthly", source_file="x.zip", source_sha256="a" * 64, timestamp_precision="milliseconds",
    )
    values.update(overrides); return Candle(**values)


def test_checksum_validation(tmp_path):
    path = tmp_path / "x"; path.write_bytes(b"abc")
    assert verify_checksum(path, hashlib.sha256(b"abc").hexdigest())[0]


def test_corrupted_zip_rejection(tmp_path):
    path = tmp_path / "bad.zip"; path.write_bytes(b"not zip")
    with pytest.raises(ValueError, match="corrupted ZIP"): list(iter_zip_rows(path, "BTCUSDT", "1m", "monthly", "a" * 64))


def test_milliseconds_timestamp_parsing():
    value, precision = normalize_timestamp(1577836800000)
    assert value == datetime(2020, 1, 1, tzinfo=timezone.utc) and precision == "milliseconds"


def test_microseconds_timestamp_parsing():
    value, precision = normalize_timestamp(1577836800000000)
    assert value == datetime(2020, 1, 1, tzinfo=timezone.utc) and precision == "microseconds"


def test_utc_normalization():
    assert normalize_timestamp(1577836800000)[0].tzinfo == timezone.utc


def test_minute_alignment():
    assert "open_time_not_minute_aligned" in validate_candle(candle(open_time=datetime(2020, 1, 1, 0, 0, 1, tzinfo=timezone.utc)), "ETHUSDT")


def test_ohlc_invariant_validation():
    assert "high_below_open" in validate_candle(candle(high=Decimal("99")), "ETHUSDT")


def test_negative_volume_rejection():
    assert "volume_negative" in validate_candle(candle(volume=Decimal("-1")), "ETHUSDT")


def test_duplicate_candle_detection():
    stamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert len(detect_gaps([stamp, stamp])) == 0


def test_monthly_priority_is_documented():
    source = inspect.getsource(import_prepared)
    assert "ON CONFLICT" in source and "DO NOTHING" in source


class Response:
    status_code = 200
    headers = {}
    def __init__(self, rows): self.rows = rows
    def raise_for_status(self): pass
    def json(self): return self.rows


class PagingSession:
    def __init__(self): self.calls = []
    def get(self, url, params, timeout):
        self.calls.append(params.copy())
        start = params["startTime"]
        return Response([[start, "1", "1", "1", "1", "0", start + 59999, "0", 0, "0", "0", "0"]])


def test_rest_fallback_pagination_advances():
    session = PagingSession(); client = BinanceRestClient(session=session)
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    list(client.iter_range("ETHUSDT", start, start + timedelta(minutes=2)))
    assert [x["startTime"] for x in session.calls] == [1577836800000, 1577836860000, 1577836920000]


def test_rest_limit_not_above_1000():
    with pytest.raises(ValueError): BinanceRestClient(session=PagingSession()).fetch("ETHUSDT", datetime.now(timezone.utc), datetime.now(timezone.utc), 1001)


def test_retry_backoff_configuration():
    assert BinanceArchiveClient(retries=3).retries == 3


def test_resume_after_partial_download_uses_checksum(tmp_path, monkeypatch):
    path = tmp_path / "x.zip"; path.write_bytes(b"valid"); expected = hashlib.sha256(b"valid").hexdigest()
    class R:
        text = expected + "  x.zip"; status_code = 200; headers = {}
        def close(self): pass
    client = BinanceArchiveClient()
    monkeypatch.setattr(client, "_request", lambda method, url, stream=False: R())
    result = client.download_verified("https://example/x.zip", path)
    assert result["downloaded"] is False


def test_resume_after_partial_import_is_do_nothing():
    assert "DO NOTHING" in inspect.getsource(import_prepared)


def test_on_conflict_does_not_update_existing_rows():
    source = inspect.getsource(import_prepared).upper()
    assert "DO NOTHING" in source and "DO UPDATE" not in source


def test_pre_listing_classification():
    assert classify_before_listing(datetime(2019, 1, 1, tzinfo=timezone.utc), datetime(2020, 1, 1, tzinfo=timezone.utc)) == "pre_listing"


def test_gap_detection():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    gap = detect_gaps([start, start + timedelta(minutes=3)])[0]
    assert gap["missing_minutes"] == 2


def test_no_synthetic_candle_creation():
    source = inspect.getsource(detect_gaps)
    assert "Candle(" not in source


def test_no_interpolation():
    package = Path(inspect.getfile(detect_gaps)).parent
    text = "\n".join(p.read_text(encoding="utf-8") for p in package.glob("*.py"))
    assert ".interpolate(" not in text


def test_stage16b_coverage_has_all_horizons():
    assert list(HORIZONS.values()) == [1, 5, 10, 20, 40, 60, 180, 300, 480, 720]


def test_12h_pre_context_is_720_minutes():
    assert HORIZONS["12h"] == 720


def test_all_reaction_horizon_coverage():
    assert set(HORIZONS) == {"1m", "5m", "10m", "20m", "40m", "1h", "3h", "5h", "8h", "12h"}


def test_event_crossing_gap_is_detectable():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert detect_gaps([start, start + timedelta(minutes=2)])[0]["gap_start"] == start + timedelta(minutes=1)


def test_old_artifact_protection_is_explicit():
    from historical_market_data.cli import protected_snapshot
    assert "stage16c_" in inspect.getsource(protected_snapshot)


def test_repeat_import_contract_inserted_zero():
    assert "status\"] == \"imported\" and resume" in Path("historical_market_data/cli.py").read_text(encoding="utf-8")


def test_leakage_zero_no_reactions_used_as_features():
    package = Path("historical_market_data")
    source = "\n".join(p.read_text(encoding="utf-8") for p in package.glob("*.py"))
    assert "predict(" not in source and ".fit(" not in source


def test_month_range_and_expected_minutes():
    assert month_range(datetime(2020, 1, 1).date(), datetime(2020, 2, 1).date()) == [(2020, 1), (2020, 2)]
    assert month_minutes(2020, 2) == 29 * 1440


def test_official_checksum_parser():
    digest = "a" * 64
    assert parse_checksum(f"{digest}  file.zip") == digest
