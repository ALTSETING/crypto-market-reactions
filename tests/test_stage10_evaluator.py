import pandas as pd
from analysis.stage10_evaluator import bh_adjust, classification_metrics, direction_target, time_splits


def test_direction_target_respects_neutral_band():
    values=pd.Series([-0.3,-0.1,0,0.1,0.3])
    assert direction_target(values,.1).tolist()==["negative","neutral","neutral","neutral","positive"]


def test_perfect_classification_metrics():
    labels=["negative","neutral","positive"]
    result=classification_metrics(labels,labels)
    assert result["accuracy"]==1 and result["balanced_accuracy"]==1
    assert result["mcc"]==1 and result["cohen_kappa"]==1


def test_time_split_is_chronological_and_complete():
    frame=pd.DataFrame({"news_id":range(8),"published_at":pd.date_range("2024-01-01",periods=8,tz="UTC")})
    split=time_splits(frame)
    assert split.tolist()==["train"]*4+["validation"]*2+["test"]*2


def test_bh_adjust_is_monotone_in_rank():
    adjusted=bh_adjust([.01,.04,.03,None])
    assert adjusted[0] <= adjusted[2] <= adjusted[1]
    assert adjusted[3] is None
