import numpy as np
import pandas as pd
import pytest

from analysis.stage11_models import _classification_models, _fit_evaluate, feature_sets


def test_feature_sets_separate_market_and_ai_and_reject_targets():
    frame=pd.DataFrame({"pre_eth_return_1h":[1.],"metadata_hour_utc":[1],"ai9_sentiment":[10.],"target_abnormal_return_1h":[2.]})
    sets=feature_sets(frame)
    assert sets["A_market_only"]==["metadata_hour_utc","pre_eth_return_1h"]
    assert sets["B_stage9_ai_only"]==["ai9_sentiment"]
    assert "target_abnormal_return_1h" not in sets["C_market_plus_stage9_ai"]


def test_fit_evaluate_classification_uses_train_and_eval_separately():
    frame=pd.DataFrame({"pre_x":np.arange(60,dtype=float),"target":(["negative","neutral","positive"]*20)})
    spec={"target":"target","task":"classification","family":"test"}
    metrics,_=_fit_evaluate(frame.iloc[:45],frame.iloc[45:],["pre_x"],spec,"logistic",_classification_models()["logistic_regression"])
    assert metrics["n_train"]==45 and metrics["n_eval"]==15
    assert 0 <= metrics["balanced_accuracy"] <= 1
