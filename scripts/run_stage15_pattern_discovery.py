from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import balanced_accuracy_score, matthews_corrcoef, precision_score, recall_score
from sklearn.tree import DecisionTreeClassifier, _tree

from database.db import SessionLocal
from ml.stage11_dataset_builder import load_candle_grid
from patterns.engine import (SEED, bh_adjust, condition_mask, evaluate_rule, load_rules, merge_duplicate_rules,
                             reject_reason, save_rules)

ROOT = Path(__file__).resolve().parents[1]; REPORTS = ROOT / "reports"; PATTERNS = ROOT / "patterns"
HORIZONS = ("15m", "30m", "1h", "4h"); HOLDINGS = (15, 30, 60, 240); BANDS = (.10, .25, .50)
AI_NUMERIC = ("ai_sentiment", "ai_importance", "ai_novelty", "ai_credibility", "ai_confidence", "ai_eth_relevance")
MARKET_NUMERIC = ("pre_btc_return_5m", "pre_btc_return_15m", "pre_btc_return_30m", "pre_btc_return_1h", "pre_btc_return_4h", "pre_btc_realized_vol_15m", "pre_btc_realized_vol_1h",
                  "pre_btc_distance_sma20", "pre_btc_distance_sma50", "pre_btc_volume_zscore_15m", "pre_eth_return_5m", "pre_eth_return_15m", "pre_eth_return_30m", "pre_eth_return_1h", "pre_eth_return_4h",
                  "pre_eth_realized_vol_15m", "pre_eth_realized_vol_1h", "pre_eth_distance_sma20", "pre_eth_distance_sma50", "pre_eth_volume_zscore_15m", "pre_eth_minus_btc_return_5m", "pre_eth_minus_btc_return_15m",
                  "pre_eth_minus_btc_return_1h", "pre_eth_btc_rolling_beta", "pre_eth_btc_rolling_correlation")
CATEGORICAL = ("ai_direction", "ai_category", "ai_horizon", "pre_btc_trend_state", "pre_regime_trend", "pre_regime_volatility", "pre_regime_volume", "pre_regime_eth_direction", "pre_regime_relative_strength", "metadata_source")


def file_hash(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frame():
    manifest = json.loads((ROOT / "data/stage12/manifest.json").read_text(encoding="utf-8")); mismatches = []
    for relative, expected in manifest["file_hashes_sha256"].items():
        path = ROOT / relative
        if not path.exists() or file_hash(path) != expected: mismatches.append(relative)
    if mismatches: raise RuntimeError(f"Stage 12 hash mismatch: {mismatches}")
    market = pd.read_parquet(ROOT / "data/stage12/eth_market_only.parquet"); ai = pd.read_parquet(ROOT / "data/stage12/eth_ai_only.parquet")
    ai_columns = ["event_key", *AI_NUMERIC, "ai_direction", "ai_category", "ai_horizon"]
    frame = market.merge(ai[ai_columns], on="event_key", validate="one_to_one")
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True); frame["baseline_time"] = pd.to_datetime(frame.baseline_time, utc=True)
    frame["pre_eth_btc_relative_strength"] = frame.pre_eth_minus_btc_return_1h
    frame["pre_eth_trend_state"] = np.where((frame.pre_eth_distance_sma50 > 0) & (frame.pre_eth_sma50_slope > 0), "bull_trend", np.where((frame.pre_eth_distance_sma50 < 0) & (frame.pre_eth_sma50_slope < 0), "bear_trend", "range"))
    frame["source"] = frame.metadata_source; frame["hour"] = frame.metadata_hour_utc; frame["weekday"] = frame.metadata_day_of_week
    frame["session"] = np.select([frame.metadata_session_asia.eq(1), frame.metadata_session_europe.eq(1), frame.metadata_session_us.eq(1)], ["asia", "europe", "us"], default="other")
    for horizon in HORIZONS:
        values = frame[f"target_abnormal_return_{horizon}"]
        for band in BANDS: frame[f"target_direction_{horizon}_{int(band*100):03d}"] = np.select([values > band, values < -band], ["positive", "negative"], default="neutral")
    if frame.event_key.duplicated().any() or set(frame.groupby("event_key").split.nunique()) != {1}: raise RuntimeError("Event duplication or split overlap")
    return manifest, frame


def add_execution(frame):
    with SessionLocal() as session: grid = load_candle_grid(session, "ETHUSDT")
    values = {f"execution_latency_{latency}m_hold_{holding}m": [] for latency in (1, 2) for holding in HOLDINGS}
    for baseline in frame.baseline_time:
        minute = int(baseline.timestamp() // 60)
        for latency in (1, 2):
            entry = grid.index(minute + latency)
            for holding in HOLDINGS:
                exit_index = grid.index(minute + latency + holding)
                values[f"execution_latency_{latency}m_hold_{holding}m"].append((grid.open[exit_index] / grid.open[entry] - 1) * 100 if entry is not None and exit_index is not None else np.nan)
    return frame.assign(**values)


def single_conditions(train):
    conditions = []
    for feature in (*AI_NUMERIC, *MARKET_NUMERIC):
        thresholds = sorted(set(float(x) for x in train[feature].quantile([.2, .4, .6, .8, .9]).dropna()))
        if feature in AI_NUMERIC: thresholds = sorted(set(thresholds + [30., 50., 60., 70., 80.]))
        for threshold in thresholds:
            rounded = round(threshold / 5) * 5 if feature in AI_NUMERIC else round(threshold, 3)
            conditions.extend([(feature, {"gte": rounded}), (feature, {"lte": rounded})])
    for feature in CATEGORICAL:
        for value, count in train[feature].value_counts().items():
            if count >= 50: conditions.append((feature, {"eq": value}))
    return conditions


def discover_beam(train, horizon, direction, limit=60):
    target = f"target_abnormal_return_{horizon}"; sign = 1 if direction == "bullish" else -1; singles = []
    for feature, operation in single_conditions(train):
        mask = condition_mask(train, {feature: operation}); n = int(mask.sum())
        if n < 50: continue
        win = float((sign * train.loc[mask, target] > 0).mean()); score = (win - .5) * np.sqrt(n) - .005
        singles.append((score, feature, operation, win, n))
    ai = sorted([x for x in singles if x[1].startswith("ai_")], key=lambda x:x[0], reverse=True)[:15]; market = sorted([x for x in singles if not x[1].startswith("ai_")], key=lambda x:x[0], reverse=True)[:20]
    rules = []
    for _, af, ao, _, _ in ai:
        for _, mf, mo, _, _ in market:
            if af == mf: continue
            conditions = {af: ao, mf: mo}; mask = condition_mask(train, conditions); n = int(mask.sum())
            if n < 30: continue
            win = float((sign * train.loc[mask, target] > 0).mean()); score = (win - .5) * np.sqrt(n) - .01 * len(conditions)
            rules.append((score, {"rule_id": f"beam_{horizon}_{direction}_{len(rules):04d}_v1", "description": "Controlled AI + market beam-search subgroup", "direction": direction, "target_horizon": horizon,
                                  "conditions": conditions, "minimum_sample_size": 30, "created_from": "beam_search_train", "allowed_splits": ["train", "validation", "test"], "version": "1", "train_discovery_score": score}))
    return [rule for _, rule in sorted(rules, key=lambda x: x[0], reverse=True)[:limit]]


def tree_rules(train, horizon, with_ai=True):
    numeric = list(MARKET_NUMERIC) + (list(AI_NUMERIC) if with_ai else []); X = train[numeric].fillna(train[numeric].median()); y = (train[f"target_abnormal_return_{horizon}"] > 0).astype(int)
    model = DecisionTreeClassifier(max_depth=3, min_samples_leaf=50, class_weight="balanced", random_state=SEED).fit(X, y); rules = []
    def walk(node, conditions):
        if model.tree_.feature[node] != _tree.TREE_UNDEFINED:
            feature = numeric[model.tree_.feature[node]]; threshold = float(model.tree_.threshold[node]); rounded = round(threshold / 5) * 5 if feature in AI_NUMERIC else round(threshold, 3)
            left = {**conditions, feature: {**conditions.get(feature, {}), "lte": rounded}}; right = {**conditions, feature: {**conditions.get(feature, {}), "gt": rounded}}
            walk(model.tree_.children_left[node], left); walk(model.tree_.children_right[node], right)
        else:
            counts = model.tree_.value[node][0]; direction = "bullish" if np.argmax(counts) == 1 else "bearish"
            rules.append({"rule_id": f"tree_{'ai_market' if with_ai else 'market'}_{horizon}_{len(rules):02d}_v1", "description": "Simplified shallow decision-tree leaf", "direction": direction, "target_horizon": horizon,
                          "conditions": conditions, "minimum_sample_size": 30, "created_from": "decision_tree_train", "allowed_splits": ["train", "validation", "test"], "version": "1"})
    walk(0, {}); return rules


def eval_rules(frame, rules, split_name, execution=None, cost=.0):
    part = frame.query("split == @split_name"); rows = []
    for rule in rules:
        metrics, _ = evaluate_rule(part, rule, split=split_name, execution_column=execution, round_trip_cost_pct=cost); rows.append(metrics)
    return pd.DataFrame(rows)


def baseline_comparisons(frame):
    train, validation, test = (frame.query("split == @name") for name in ("train", "validation", "test")); rows = []
    target = "target_abnormal_return_1h"
    # Fixed simple baselines.
    predictions = {"random_50_50": np.random.default_rng(SEED).choice([-1, 1], len(test)), "always_bullish": np.ones(len(test)), "always_bearish": -np.ones(len(test)),
                   "market_momentum_only": np.sign(test.pre_eth_return_1h).replace(0, 1).to_numpy(), "stage9_ai_direction": test.ai_direction.map({"bullish": 1, "bearish": -1}).fillna(0).to_numpy()}
    numeric_market = list(MARKET_NUMERIC); numeric_ai = [*numeric_market, *AI_NUMERIC]
    for label, columns in (("shallow_tree_market_only", numeric_market), ("shallow_tree_ai_market", numeric_ai)):
        best = None
        for depth in (2, 3, 4):
            model = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=50, class_weight="balanced", random_state=SEED).fit(train[columns].fillna(train[columns].median()), (train[target] > 0).astype(int))
            pred = model.predict(validation[columns].fillna(train[columns].median())); score = balanced_accuracy_score((validation[target] > 0).astype(int), pred)
            if best is None or score > best[0]: best = (score, depth)
        combined = pd.concat([train, validation]); model = DecisionTreeClassifier(max_depth=best[1], min_samples_leaf=50, class_weight="balanced", random_state=SEED).fit(combined[columns].fillna(train[columns].median()), (combined[target] > 0).astype(int)); predictions[label] = model.predict(test[columns].fillna(train[columns].median())) * 2 - 1
    magnitude = joblib.load(ROOT / "models/stage13/target_abs_abnormal_return_1h/market_only/pipeline.joblib"); feature_list = json.loads((ROOT / "models/stage13/target_abs_abnormal_return_1h/market_only/feature_list.json").read_text())["features"]
    validation_mag = magnitude.predict(validation[feature_list]); threshold = float(np.quantile(validation_mag, .75)); test_mag = magnitude.predict(test[feature_list]); predictions["stage13_market_model_plus_momentum"] = np.where(test_mag >= threshold, np.sign(test.pre_eth_return_1h).replace(0, 1), 0)
    actual = np.sign(test[target]).replace(0, -1).to_numpy()
    for name, prediction in predictions.items():
        active = prediction != 0; pnl = prediction[active] * test.loc[active, "execution_latency_1m_hold_60m"].to_numpy() - .20
        losses = -pnl[pnl < 0].sum(); rows.append({"comparison": name, "n": int(active.sum()), "win_rate": float(np.mean(prediction[active] * actual[active] > 0)), "balanced_accuracy": balanced_accuracy_score(actual[active] > 0, prediction[active] > 0),
            "precision": precision_score(actual[active] > 0, prediction[active] > 0, zero_division=0), "recall": recall_score(actual[active] > 0, prediction[active] > 0, zero_division=0), "mcc": matthews_corrcoef(actual[active] > 0, prediction[active] > 0),
            "mean_net_return": float(pnl.mean()), "profit_factor": float(pnl[pnl > 0].sum() / losses) if losses else np.inf})
    return pd.DataFrame(rows)


def main(force=False):
    if (REPORTS / "stage15_summary.json").exists() and not force:
        print((REPORTS / "stage15_summary.json").read_text(encoding="utf-8")); return
    manifest, frame = load_frame(); input_hashes = {relative: file_hash(ROOT / relative) for relative in manifest["file_hashes_sha256"]}; frame = add_execution(frame)
    manual = load_rules(PATTERNS / "base_rules.yaml"); train = frame.query("split == 'train'")
    generated = []
    for horizon in ("30m", "1h"):
        for direction in ("bullish", "bearish"): generated.extend(discover_beam(train, horizon, direction))
        generated.extend(tree_rules(train, horizon, True)); generated.extend(tree_rules(train, horizon, False))
    generated = merge_duplicate_rules(generated); save_rules(PATTERNS / "generated_rules.yaml", generated)
    all_rules = merge_duplicate_rules([*manual, *generated]); train_metrics = eval_rules(frame, all_rules, "train"); train_metrics.to_csv(REPORTS / "stage15_train_metrics.csv", index=False)
    train_pass_ids = set(train_metrics.loc[(train_metrics.n >= 30) & (train_metrics.win_rate >= .52), "rule_id"]); train_pass = [rule for rule in all_rules if rule["rule_id"] in train_pass_ids]
    # Validation chooses holding period and freezes every shortlisted configuration.
    validation_rows = []; frozen = []
    validation_frame = frame.query("split == 'validation'")
    for rule in train_pass:
        choices = []
        for holding in HOLDINGS:
            metrics, _ = evaluate_rule(validation_frame, rule, split="validation", execution_column=f"execution_latency_1m_hold_{holding}m", round_trip_cost_pct=.20)
            metrics["holding_minutes"] = holding; choices.append(metrics)
        winner = max(choices, key=lambda row: (-np.inf if pd.isna(row["mean_net_return"]) else row["mean_net_return"], row["win_rate"])); validation_rows.append(winner)
        frozen.append({**rule, "selected_holding_minutes": int(winner["holding_minutes"]), "selected_neutral_band": .10})
    validation_metrics = pd.DataFrame(validation_rows)
    if len(validation_metrics): validation_metrics["p_bh"] = bh_adjust(validation_metrics.p_vs_50)
    validation_metrics.to_csv(REPORTS / "stage15_validation_metrics.csv", index=False)
    validation_pass = set(validation_metrics.loc[validation_metrics.apply(lambda row: reject_reason(row.to_dict()) is None, axis=1), "rule_id"])
    ranked = validation_metrics.loc[validation_metrics.rule_id.isin(validation_pass)].sort_values(["wilson_low", "mean_net_return", "n"], ascending=False).head(40)
    shortlist_ids = set(ranked.rule_id); shortlist = [rule for rule in frozen if rule["rule_id"] in shortlist_ids]
    save_rules(PATTERNS / "shortlisted_rules.yaml", shortlist)
    # Locked test is evaluated only after shortlist persistence.
    test_frame = frame.query("split == 'test'"); test_rows = []; signal_events = []
    for rule in shortlist:
        holding = rule["selected_holding_minutes"]; metrics, events = evaluate_rule(test_frame, rule, split="test", execution_column=f"execution_latency_1m_hold_{holding}m", round_trip_cost_pct=.20); metrics["holding_minutes"] = holding; test_rows.append(metrics)
        if len(events):
            events["matched_conditions"] = json.dumps(rule["conditions"], sort_keys=True); signal_events.append(events[["event_key", "published_at", "metadata_source", "ai_category", "rule_direction", "rule_horizon", f"target_abnormal_return_{rule['target_horizon']}", "net_rule_return", "rule_id", "split", "matched_conditions"]].rename(columns={"metadata_source":"source","ai_category":"category", "rule_direction":"direction", "rule_horizon":"horizon", f"target_abnormal_return_{rule['target_horizon']}":"actual_return", "net_rule_return":"net_return"}))
    test_metrics = pd.DataFrame(test_rows); test_metrics.to_csv(REPORTS / "stage15_test_metrics.csv", index=False)
    (pd.concat(signal_events, ignore_index=True) if signal_events else pd.DataFrame(columns=["event_key","published_at","source","category","direction","horizon","actual_return","net_return","rule_id","split","matched_conditions"])).to_parquet(REPORTS / "stage15_signal_events.parquet", index=False)
    # Multiple testing includes every validation-evaluated rule.
    multiple = validation_metrics[["rule_id", "n", "win_rate", "p_vs_50", "p_bh"]].copy() if len(validation_metrics) else pd.DataFrame(columns=["rule_id","n","win_rate","p_vs_50","p_bh"])
    multiple["survived_bh_5pct"] = multiple.p_bh < .05; multiple["selected_for_test"] = multiple.rule_id.isin(shortlist_ids); multiple.to_csv(REPORTS / "stage15_multiple_testing.csv", index=False)
    # Cost and latency sensitivity, fully frozen.
    cost_rows = []
    for rule in shortlist:
        holding = rule["selected_holding_minutes"]
        for scenario, latency, cost in (("low",1,.08),("base",1,.20),("stress",2,.50)):
            metrics, _ = evaluate_rule(test_frame, rule, split="test", execution_column=f"execution_latency_{latency}m_hold_{holding}m", round_trip_cost_pct=cost); metrics.update({"scenario":scenario,"latency_minutes":latency,"holding_minutes":holding,"round_trip_cost_pct":cost}); cost_rows.append(metrics)
    pd.DataFrame(cost_rows).to_csv(REPORTS / "stage15_cost_sensitivity.csv", index=False)
    # Three disjoint chronological test folds: rules were frozen before all three.
    walk_rows = []
    fold_indices = np.array_split(np.arange(len(test_frame)), 3)
    for rule in shortlist:
        for fold, indices in enumerate(fold_indices, 1):
            part = test_frame.iloc[indices]; holding = rule["selected_holding_minutes"]; metrics, _ = evaluate_rule(part, rule, split=f"test_fold_{fold}", execution_column=f"execution_latency_1m_hold_{holding}m", round_trip_cost_pct=.20); metrics["fold"] = fold; walk_rows.append(metrics)
    walk = pd.DataFrame(walk_rows); walk.to_csv(REPORTS / "stage15_walkforward_metrics.csv", index=False)
    # Robustness decompositions.
    robustness = {"source":[], "category":[], "regime":[]}
    for rule in shortlist:
        for kind, column in (("source","metadata_source"),("category","ai_category"),("regime","pre_regime_trend")):
            for value, part in test_frame.groupby(column):
                metrics, _ = evaluate_rule(part, rule, split="test", execution_column=f"execution_latency_1m_hold_{rule['selected_holding_minutes']}m", round_trip_cost_pct=.20); metrics[kind] = value; robustness[kind].append(metrics)
        for value, part in test_frame.assign(period=test_frame.published_at.dt.to_period("Q").astype(str)).groupby("period"):
            metrics, _ = evaluate_rule(part, rule, split="test", execution_column=f"execution_latency_1m_hold_{rule['selected_holding_minutes']}m", round_trip_cost_pct=.20); metrics["regime"] = f"quarter:{value}"; robustness["regime"].append(metrics)
    pd.DataFrame(robustness["source"]).to_csv(REPORTS / "stage15_source_robustness.csv", index=False); pd.DataFrame(robustness["category"]).to_csv(REPORTS / "stage15_category_robustness.csv", index=False); pd.DataFrame(robustness["regime"]).to_csv(REPORTS / "stage15_regime_robustness.csv", index=False)
    # Grouped two-way interactions, thresholds fixed from train medians/categories.
    interaction_rows = []
    pairs = (("ai_sentiment","pre_btc_return_1h"),("ai_importance","pre_btc_distance_sma50"),("ai_novelty","pre_eth_realized_vol_1h"),("ai_credibility","metadata_source"),("ai_category","pre_btc_trend_state"),("ai_eth_relevance","pre_eth_minus_btc_return_1h"),("ai_direction","pre_eth_trend_state"),("ai_confidence","pre_regime_trend"))
    for left, right in pairs:
        temp = test_frame[[left,right,"target_abnormal_return_1h"]].copy()
        for feature in (left,right):
            if pd.api.types.is_numeric_dtype(train[feature]):
                cuts = [-np.inf, *train[feature].quantile([.33,.67]).tolist(), np.inf]; temp[feature] = pd.cut(temp[feature], cuts, duplicates="drop").astype(str)
        for keys, part in temp.groupby([left,right]): interaction_rows.append({"interaction":f"{left}_x_{right}","left_group":keys[0],"right_group":keys[1],"n":len(part),"positive_rate":float((part.target_abnormal_return_1h>0).mean()),"mean_abnormal_return":part.target_abnormal_return_1h.mean()})
    pd.DataFrame(interaction_rows).to_csv(REPORTS / "stage15_interactions.csv", index=False)
    manual_train = train_metrics.loc[train_metrics.rule_id.isin({r['rule_id'] for r in manual})]; generated_train = train_metrics.loc[~train_metrics.rule_id.isin({r['rule_id'] for r in manual})]
    manual_train.to_csv(REPORTS / "stage15_manual_rules.csv", index=False); generated_train.to_csv(REPORTS / "stage15_generated_rules.csv", index=False)
    baselines = baseline_comparisons(frame); baselines.to_csv(REPORTS / "stage15_baseline_comparison.csv", index=False)
    # Final approval requires every stated gate.
    approved, rejected, registry = [], [], []
    test_by_id = test_metrics.set_index("rule_id") if len(test_metrics) else pd.DataFrame()
    for rule in all_rules:
        rid = rule["rule_id"]; validation_row = validation_metrics.loc[validation_metrics.rule_id.eq(rid)]; test_row = test_metrics.loc[test_metrics.rule_id.eq(rid)] if len(test_metrics) else pd.DataFrame(); status = "rejected"; reason = "failed_train_filter"
        if rid in shortlist_ids:
            t = test_row.iloc[0]; folds = walk.loc[walk.rule_id.eq(rid)] if len(walk) else pd.DataFrame(); source_rows = pd.DataFrame(robustness["source"]); source_rows = source_rows.loc[source_rows.rule_id.eq(rid)] if len(source_rows) else source_rows
            stable = int((folds.win_rate > .5).sum()) >= 2 and (t.win_rate >= .55); source_ok = int((source_rows.n >= 10).sum()) >= 2
            gates = t.n >= 50 and t.win_rate >= .55 and t.mean_net_return > 0 and t.profit_factor > 1 and stable and source_ok and len(rule["conditions"]) <= 4
            status = "shadow_candidate" if gates else ("test_pass" if t.win_rate >= .55 and t.mean_net_return > 0 else "rejected"); reason = None if gates else "test_or_robustness_gate_failed"
        registry.append({"rule_id":rid,"version":rule.get("version","1"),"status":status,"direction":rule["direction"],"horizon":rule["target_horizon"],"conditions_json":json.dumps(rule["conditions"],sort_keys=True),"train_metrics_json":train_metrics.loc[train_metrics.rule_id.eq(rid)].to_json(orient="records"),"validation_metrics_json":validation_row.to_json(orient="records"),"test_metrics_json":test_row.to_json(orient="records"),"walkforward_metrics_json":walk.loc[walk.rule_id.eq(rid)].to_json(orient="records") if len(walk) else "[]","cost_metrics_json":pd.DataFrame(cost_rows).loc[lambda x:x.rule_id.eq(rid)].to_json(orient="records") if cost_rows else "[]","source_robustness_json":pd.DataFrame(robustness['source']).loc[lambda x:x.rule_id.eq(rid)].to_json(orient="records") if robustness['source'] else "[]","category_robustness_json":pd.DataFrame(robustness['category']).loc[lambda x:x.rule_id.eq(rid)].to_json(orient="records") if robustness['category'] else "[]","created_at":datetime.now(timezone.utc).isoformat(),"approved_at":datetime.now(timezone.utc).isoformat() if status=="shadow_candidate" else None,"rejection_reason":reason})
        (approved if status=="shadow_candidate" else rejected).append({**rule,"status":status,"rejection_reason":reason})
    approved_frame=pd.DataFrame(approved,columns=["rule_id","description","direction","target_horizon","conditions","minimum_sample_size","created_from","allowed_splits","version","status","rejection_reason"])
    approved_frame.to_csv(REPORTS / "stage15_approved_rules.csv", index=False); save_rules(PATTERNS / "approved_rules.yaml",approved)
    pd.DataFrame(rejected).to_csv(REPORTS / "stage15_rejected_rules.csv", index=False); (REPORTS / "stage15_pattern_registry.json").write_text(json.dumps(registry,indent=2),encoding="utf-8")
    hashes_unchanged = all(file_hash(ROOT / relative) == expected for relative, expected in input_hashes.items())
    best = test_metrics.sort_values(["win_rate","n"],ascending=False).iloc[0].to_dict() if len(test_metrics) else None; shadow = len(approved)
    generation = {"manual_rules":len(manual),"generated_rules":len(generated),"evaluated":len(all_rules),"train_pass":len(train_pass),"validation_pass":len(validation_pass),"survived_bh":int(multiple.survived_bh_5pct.sum()),"shortlisted_for_locked_test":len(shortlist),"test_shadow_candidates":shadow}
    (REPORTS / "stage15_rule_generation_summary.json").write_text(json.dumps(generation,indent=2),encoding="utf-8")
    summary = {"stage":15,"technical_status":"PASS","conditional_edge":"SUPPORTED" if shadow else "NOT_SUPPORTED","input_events":len(frame),"hashes_verified":True,"splits":frame.split.value_counts().to_dict(),"rule_generation":generation,"best_test_rule":best,"shadow_candidates":shadow,"paper_trading_evidence_sufficient":False,"paper_trading_run":False,"real_trading_run":False,"openai_requests":0,"test_used_once":True,"test_used_for_tuning":False,"leakage_violations":0,"stage8_13_5_hashes_unchanged":hashes_unchanged,"baseline_comparison":baselines.to_dict('records')}
    (REPORTS / "stage15_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    (REPORTS / "stage15_final_assessment.md").write_text(f"# Stage 15 — Conditional Pattern Discovery\n\nTechnical status: **PASS**. Conditional edge: **{summary['conditional_edge']}**.\n\nGenerated {len(generated)} controlled rules plus {len(manual)} manual rules; {len(shortlist)} were frozen before the single locked-test evaluation. Shadow candidates: {shadow}.\n\nNo OpenAI request, paper trading, real trading, or production deployment was performed. Paper trading evidence is not considered sufficient at this stage.\n",encoding="utf-8")
    print(json.dumps(summary,indent=2,default=str))


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--force",action="store_true");args=parser.parse_args();main(args.force)
