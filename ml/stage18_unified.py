"""Pure, reusable helpers for Stage 18 unified offline reanalysis.

The module deliberately contains no database writes and no external API calls.
Market outcomes are accepted only by the target/path helpers; model feature
selection is separately guarded by :func:`assert_no_future_features`.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import numpy as np
import pandas as pd


HORIZONS = {
    "5m": 5, "10m": 10, "20m": 20, "40m": 40, "1h": 60,
    "90m": 90, "2h": 120, "3h": 180, "4h": 240, "5h": 300,
    "6h": 360, "8h": 480, "10h": 600, "12h": 720,
    "18h": 1080, "24h": 1440,
}
PRIMARY_HORIZON = "12h"
PRIMARY_MINUTES = HORIZONS[PRIMARY_HORIZON]
NEUTRAL_THRESHOLD_PERCENT = 0.10
ENTRY_LATENCY_MINUTES = 1
PRE_CONTEXT_MINUTES = 1440
POST_CONTEXT_MINUTES = 1440
BASE_COST_PERCENT = 0.20
API_HARD_LIMIT_USD = 2.00
API_SAFETY_STOP_USD = 1.90
PREDICTIVE_PREFIXES = ("target_", "future_", "post_", "mfe", "mae", "return_5m", "return_10m")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value.strip())
        host = parsed.netloc.lower().removeprefix("www.")
        path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source", "fbclid", "gclid"}]
        return urlunsplit((parsed.scheme.lower() or "https", host, path, urlencode(sorted(query)), ""))
    except ValueError:
        return value.strip().lower()


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def text_fingerprint(title: str | None, body: str | None) -> str:
    normalized = f"{normalize_text(title)}\n{normalize_text(body)[:4000]}"
    return hashlib.sha256(normalized.encode()).hexdigest() if normalized.strip() else ""


def official_identifier(url: str | None, external_id: str | None = None) -> str:
    if external_id:
        return normalize_text(external_id)
    value = normalize_url(url)
    sec = re.search(r"/archives/edgar/data/\d+/([0-9-]+)", value)
    if sec:
        return f"sec:{sec.group(1).replace('-', '')}"
    github = re.search(r"github\.com/([^/]+/[^/]+)/(?:pull|issues|commit|releases/tag)/([^/?#]+)", value)
    if github:
        return f"github:{github.group(1)}:{github.group(2)}".lower()
    return ""


class UnionFind:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def duplicate_components(frame: pd.DataFrame) -> tuple[dict[str, str], pd.DataFrame]:
    """Return connected duplicate roots and auditable pair-level reasons."""
    ids = frame["member_id"].astype(str).tolist()
    union = UnionFind(ids)
    pairs: list[dict[str, Any]] = []
    keys = ("normalized_url", "official_id", "content_hash", "text_fingerprint")
    for key in keys:
        for value, part in frame[frame[key].fillna("").ne("")].groupby(key):
            members = part.member_id.astype(str).tolist()
            for other in members[1:]:
                union.union(members[0], other)
                pairs.append({"left_member_id": members[0], "right_member_id": other,
                              "reason": key, "match_value": value})
    titled = frame[frame.normalized_title.fillna("").ne("")].copy()
    titled["minute"] = pd.to_datetime(titled.published_at, utc=True).dt.floor("min")
    for title, part in titled.groupby("normalized_title"):
        part = part.sort_values("minute")
        rows = list(part.itertuples(index=False))
        for i in range(1, len(rows)):
            if abs((rows[i].minute - rows[i - 1].minute).total_seconds()) <= 300:
                left, right = str(rows[i - 1].member_id), str(rows[i].member_id)
                union.union(left, right)
                pairs.append({"left_member_id": left, "right_member_id": right,
                              "reason": "normalized_title_within_5m", "match_value": title})
    roots = {value: union.find(value) for value in ids}
    return roots, pd.DataFrame(pairs, columns=["left_member_id", "right_member_id", "reason", "match_value"])


def chronological_split(frame: pd.DataFrame, external_mask: pd.Series) -> pd.Series:
    """70/15/15 event-level split; all rows of an event remain together."""
    events = (frame.loc[~external_mask, ["canonical_event_id", "published_at"]]
              .drop_duplicates("canonical_event_id").sort_values(["published_at", "canonical_event_id"]))
    n = len(events)
    train_end, validation_end = int(math.floor(n * .70)), int(math.floor(n * .85))
    mapping = {event: ("train" if i < train_end else "validation" if i < validation_end else "test")
               for i, event in enumerate(events.canonical_event_id)}
    result = frame.canonical_event_id.map(mapping).astype("object")
    result.loc[external_mask] = "historical_external"
    return result


def next_full_minute(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.floor("min") + pd.Timedelta(minutes=1)


def entry_timestamp(value: Any, latency_minutes: int = ENTRY_LATENCY_MINUTES) -> pd.Timestamp:
    return next_full_minute(value) + pd.Timedelta(minutes=latency_minutes)


def required_window(value: Any, lookback_minutes: int = PRE_CONTEXT_MINUTES,
                    post_minutes: int = POST_CONTEXT_MINUTES) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    entry = entry_timestamp(value)
    return entry - pd.Timedelta(minutes=lookback_minutes), entry, entry + pd.Timedelta(minutes=post_minutes)


def validate_candles(frame: pd.DataFrame) -> pd.Series:
    timestamps = pd.to_datetime(frame.open_time, utc=True)
    aligned = timestamps.dt.second.eq(0) & timestamps.dt.microsecond.eq(0)
    return (pd.to_numeric(frame.open, errors="coerce").gt(0)
            & frame.high.ge(frame.open) & frame.high.ge(frame.close)
            & frame.low.le(frame.open) & frame.low.le(frame.close)
            & frame.high.ge(frame.low) & frame.close.gt(0) & frame.volume.ge(0) & aligned)


def gap_minutes(minutes: np.ndarray, start: int, end: int) -> np.ndarray:
    expected = np.arange(start, end + 1, dtype=np.int64)
    lo, hi = np.searchsorted(minutes, [start, end + 1])
    return np.setdiff1d(expected, minutes[lo:hi], assume_unique=True)


def endpoint_return(entry_price: float, endpoint_open: float) -> float:
    return (float(endpoint_open) / float(entry_price) - 1.0) * 100.0


def signed_return(raw_return_percent: float, signal: str) -> float:
    if signal == "LONG":
        return float(raw_return_percent)
    if signal == "SHORT":
        return -float(raw_return_percent)
    return math.nan


def mfe_mae(high_returns: np.ndarray, low_returns: np.ndarray, signal: str) -> tuple[float, float, int, int]:
    if signal == "LONG":
        return float(np.max(high_returns)), float(np.min(low_returns)), int(np.argmax(high_returns)), int(np.argmin(low_returns))
    if signal == "SHORT":
        return float(-np.min(low_returns)), float(-np.max(high_returns)), int(np.argmin(low_returns)), int(np.argmax(high_returns))
    return math.nan, math.nan, -1, -1


def directional_target(values: pd.Series, threshold: float = NEUTRAL_THRESHOLD_PERCENT) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(np.select([numeric > threshold, numeric < -threshold], ["UP", "DOWN"], default="NEUTRAL"), index=values.index)


def assert_no_future_features(columns: Iterable[str]) -> None:
    violations = [column for column in columns if column.lower().startswith(PREDICTIVE_PREFIXES)
                  or any(token in column.lower() for token in ("future", "post_event", "reaction", "target", "mfe", "mae"))]
    if violations:
        raise ValueError(f"future/leakage features: {sorted(set(violations))}")


SEMANTIC_SCALE_DIVISORS = {
    "zero_one": 1.0,
    "zero_ten": 10.0,
    "zero_hundred": 100.0,
    "minus_one_one": 1.0,
    "minus_ten_ten": 10.0,
    "minus_hundred_hundred": 100.0,
}


def semantic_score(value: Any, scale_hint: str) -> float:
    """Normalize a documented semantic scale without guessing or clipping.

    Unsigned scales map to 0..1 and signed valence scales map to -1..1.  A
    value outside its declared range is rejected so upstream schema bugs stay
    visible instead of being hidden by clipping.
    """
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return math.nan
    if scale_hint not in SEMANTIC_SCALE_DIVISORS:
        raise ValueError(f"unknown semantic scale: {scale_hint}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("semantic value must be finite")
    signed = scale_hint.startswith("minus_")
    divisor = SEMANTIC_SCALE_DIVISORS[scale_hint]
    lower, upper = (-divisor, divisor) if signed else (0.0, divisor)
    if number < lower or number > upper:
        raise ValueError(f"semantic value {number} outside declared range {lower}..{upper}")
    return number / divisor


def add_missing_flags(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[f"{column}_missing"] = result[column].isna().astype("int8")
    return result


def budget_allows(current_cost: float, projected_cost: float,
                  safety_stop: float = API_SAFETY_STOP_USD, hard_limit: float = API_HARD_LIMIT_USD) -> bool:
    return current_cost + projected_cost <= safety_stop and current_cost + projected_cost <= hard_limit


def economic_metrics(returns: Iterable[float], cost_percent: float = BASE_COST_PERCENT) -> dict[str, float | None]:
    gross = np.asarray(list(returns), dtype=float)
    gross = gross[np.isfinite(gross)]
    if not len(gross):
        return {"signals": 0, "gross_expectancy": None, "net_expectancy": None, "profit_factor": None,
                "cumulative_net_return": None, "maximum_drawdown": None, "win_rate": None}
    net = gross - cost_percent
    equity = np.cumsum(net)
    peaks = np.maximum.accumulate(np.r_[0.0, equity])[1:]
    profit, loss = net[net > 0].sum(), -net[net < 0].sum()
    return {"signals": int(len(net)), "gross_expectancy": float(gross.mean()), "net_expectancy": float(net.mean()),
            "profit_factor": float(profit / loss) if loss > 0 else None,
            "cumulative_net_return": float(net.sum()), "maximum_drawdown": float((equity - peaks).min()),
            "win_rate": float((net > 0).mean())}


def wilson_interval(correct: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = correct / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return center - margin, center + margin


@dataclass(frozen=True)
class FrozenRule:
    pattern_id: str
    primary_horizon: str
    neutral_threshold: float
    confidence_threshold: float
    latency_minutes: int

    def digest(self) -> str:
        return canonical_hash(self.__dict__)
