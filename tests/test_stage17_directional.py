import numpy as np
import pandas as pd

from analysis.stage17_directional import (
    canonical_hash, directional_metrics, directional_target,
    predictions_from_probabilities, wilson_interval,
)


def test_directional_target_respects_neutral_band():
    result=directional_target(pd.Series([.11,.10,0,-.10,-.11]),.10)
    assert result.tolist()==["UP","NEUTRAL","NEUTRAL","NEUTRAL","DOWN"]


def test_no_signal_is_excluded_from_directional_accuracy():
    rows=pd.DataFrame({"event_id":[1,2,3,4],"predicted_direction":["UP","NO_SIGNAL","DOWN","UP"],
                       "actual_direction":["UP","DOWN","DOWN","NEUTRAL"]})
    metrics=directional_metrics(rows)
    assert metrics["predictions"]==3
    assert metrics["correct"]==2 and metrics["incorrect"]==1
    assert metrics["accuracy"]==2/3
    assert metrics["coverage"]==.75


def test_probability_threshold_controls_no_signal_without_using_target():
    probabilities=np.array([[.45,.05,.50],[.20,.20,.60]])
    predicted,confidence=predictions_from_probabilities(probabilities,["DOWN","NEUTRAL","UP"],.55)
    assert predicted.tolist()==["NO_SIGNAL","UP"]
    assert confidence.tolist()==[.50,.60]


def test_wilson_interval_and_lock_hash_are_stable():
    low,high=wilson_interval(60,100)
    assert low<.60<high and low>.50
    left={"horizon":"1h","threshold":.1,"features":["a","b"]}
    right={"features":["a","b"],"threshold":.1,"horizon":"1h"}
    assert canonical_hash(left)==canonical_hash(right)
