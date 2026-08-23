from __future__ import annotations

import ast
from pathlib import Path

import joblib
import numpy as np
import pytest

from analysis.stage18a_forensic import (
    array_hash, distribution, net_trade_return, probability_columns,
    raw_return_percent, replay_signals, signal_metrics, target_from_percent,
    trade_return,
)


ROOT=Path(__file__).resolve().parents[1]


def test_18a_01_class_order_from_model(): assert probability_columns(["DOWN","NEUTRAL","UP"])=={"UP":2,"DOWN":0,"NEUTRAL":1}
def test_18a_02_class_set_guard():
    with pytest.raises(ValueError): probability_columns(["DOWN","UP"])
def test_18a_03_raw_argmax_mapping():
    r=replay_signals(np.array([[.6,.1,.3]]),["DOWN","NEUTRAL","UP"]);assert r.raw_argmax_class.iloc[0]=="DOWN"
def test_18a_04_directional_mapping():
    r=replay_signals(np.array([[.2,.5,.3]]),["DOWN","NEUTRAL","UP"]);assert r.directional_winner.iloc[0]=="UP"
def test_18a_05_confidence_filter():
    r=replay_signals(np.array([[.35,.31,.34]]),["DOWN","NEUTRAL","UP"],.4);assert r.after_confidence.iloc[0]=="NO_SIGNAL"
def test_18a_06_target_up(): assert target_from_percent(.10001)=="UP"
def test_18a_07_target_down(): assert target_from_percent(-.10001)=="DOWN"
def test_18a_08_target_neutral(): assert target_from_percent(.1)=="NEUTRAL"
def test_18a_09_percent_formula(): assert raw_return_percent(100,101)==pytest.approx(1)
def test_18a_10_long_sign(): assert trade_return(-1,"LONG")==-1
def test_18a_11_short_sign(): assert trade_return(-1,"SHORT")==1
def test_18a_12_cost_subtracted(): assert net_trade_return(-1,"SHORT",.2)==pytest.approx(.8)
def test_18a_13_array_hash_deterministic(): assert array_hash(np.array([1,2]))==array_hash(np.array([1,2]))
def test_18a_14_distribution(): assert distribution(__import__('pandas').Series([1,2,3]))['median']==2
def test_18a_15_signal_metrics(): assert signal_metrics(["DOWN"],["SHORT"],[-1])["accuracy"]==1


def test_18a_16_forensic_script_has_no_fit_calls():
    path=ROOT/'scripts'/'run_stage18a_forensic.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'fit','partial_fit','fit_transform'}]
    assert calls==[]


@pytest.mark.parametrize('name',["a","b"])
def test_18a_17_frozen_model_available(name):
    payload=joblib.load(ROOT/'models'/f'stage18_pattern_{name}_v2.joblib');assert set(payload['model'].named_steps['model'].classes_)=={"UP","DOWN","NEUTRAL"}


def test_18a_18_stage18_predictions_available(): assert (ROOT/'reports'/'stage18_prediction_level_results.parquet').exists()
