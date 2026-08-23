import numpy as np
import pandas as pd

from analysis.stage17b_bidirectional import (
    directional_target,
    economic_metrics,
    rejection_reasons,
    signal_from_probabilities,
    signal_metrics,
)


def test_neutral_is_not_correct_for_long_or_short():
    rows = pd.DataFrame({
        "signal": ["LONG", "SHORT", "NO_SIGNAL"],
        "actual_direction": ["NEUTRAL", "NEUTRAL", "UP"],
        "future_return": [0.01, -0.01, 1.0],
        "event_id": [1, 2, 3],
        "published_at": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"], utc=True),
        "source": ["a", "b", "c"],
    })
    metrics = signal_metrics(rows)
    assert metrics["combined_signals"] == 2
    assert metrics["combined_correct"] == 0
    assert metrics["combined_accuracy"] == 0


def test_directional_target_uses_strict_thresholds():
    result = directional_target(pd.Series([0.10, 0.11, -0.10, -0.11]), 0.10)
    assert result.tolist() == ["NEUTRAL", "UP", "NEUTRAL", "DOWN"]


def test_short_gross_return_has_inverse_sign():
    rows = pd.DataFrame({
        "signal": ["SHORT"],
        "actual_direction": ["DOWN"],
        "future_return": [-1.0],
        "event_id": [1],
        "published_at": pd.to_datetime(["2025-01-01"], utc=True),
        "source": ["a"],
    })
    metrics = economic_metrics(rows, 0.20)
    assert metrics["gross_expectancy_percent"] == 1.0
    assert metrics["net_expectancy_percent"] == 0.8


def test_directional_expectancies_are_reported_separately():
    rows = pd.DataFrame({
        "signal": ["LONG", "SHORT"],
        "actual_direction": ["UP", "DOWN"],
        "future_return": [0.6, -0.4],
        "event_id": [1, 2],
        "published_at": pd.to_datetime(["2025-01-01", "2025-02-01"], utc=True),
        "source": ["a", "b"],
    })
    metrics = signal_metrics(rows)
    assert metrics["long_gross_expectancy_percent"] == 0.6
    assert metrics["short_gross_expectancy_percent"] == 0.4


def test_probability_mapping_is_not_stage17_inversion():
    probabilities = np.array([[0.7, 0.1, 0.2], [0.1, 0.2, 0.7], [0.35, 0.34, 0.31]])
    signal, confidence = signal_from_probabilities(probabilities, ["DOWN", "NEUTRAL", "UP"], 0.5)
    assert signal.tolist() == ["SHORT", "LONG", "NO_SIGNAL"]
    assert confidence.tolist() == [0.7, 0.7, 0.35]


def test_candidate_rejects_direction_dominance_and_small_sample():
    validation = {
        "combined_signals": 19,
        "coverage": 0.3,
        "dominant_direction_share": 1.0,
        "combined_accuracy": 0.7,
        "strongest_baseline": 0.5,
        "gross_expectancy_percent": 0.2,
        "source_max_share": 0.5,
        "month_max_share": 0.5,
    }
    train = {"combined_signals": 29, "gross_expectancy_percent": 0.2}
    reasons = rejection_reasons(validation, train)
    assert "train_signals_below_30" in reasons
    assert "validation_predictions_below_20" in reasons
    assert "dominant_direction_above_80pct" in reasons


def test_no_signal_does_not_enter_economic_metrics():
    rows = pd.DataFrame({
        "signal": ["NO_SIGNAL"],
        "actual_direction": ["UP"],
        "future_return": [4.0],
        "event_id": [1],
        "published_at": pd.to_datetime(["2025-01-01"], utc=True),
        "source": ["a"],
    })
    assert economic_metrics(rows)["signals"] == 0
