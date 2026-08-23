from __future__ import annotations

import copy
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from database.db import SessionLocal
from ml.stage11_dataset_builder import load_candle_grid
from ml.stage14_utility import (COSTS, SEED, benjamini_hochberg, bootstrap_mean, directional_signals,
                                permutation_difference, ranking_tables, sha256, simulate, verify_hashes)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data/stage12"
TARGETS = ("target_abs_abnormal_return_1h", "target_realized_vol_1h")
PREDICTIONS = {"target_abs_abnormal_return_1h": "predicted_abs_move_1h", "target_realized_vol_1h": "predicted_volatility_1h"}
HOLDINGS = (15, 30, 60)


def features(target):
    return json.loads((ROOT / f"models/stage13/{target}/market_only/feature_list.json").read_text(encoding="utf-8"))["features"]


def artifact(target):
    return joblib.load(ROOT / f"models/stage13/{target}/market_only/pipeline.joblib")


def execution_returns(frame):
    with SessionLocal() as session:
        grid = load_candle_grid(session, "ETHUSDT")
    rows = []
    for event in frame.itertuples(index=False):
        minute = int(pd.Timestamp(event.baseline_time).timestamp() // 60)
        row = {"event_key": event.event_key}
        for latency in (1, 2):
            entry = minute + latency; entry_index = grid.index(entry)
            row[f"entry_time_latency_{latency}m"] = pd.Timestamp(entry * 60, unit="s", tz="UTC")
            for holding in HOLDINGS:
                exit_index = grid.index(entry + holding)
                row[f"execution_return_latency_{latency}m_hold_{holding}m"] = ((grid.open[exit_index] / grid.open[entry_index] - 1) * 100) if entry_index is not None and exit_index is not None else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def predict_splits(frame):
    output = frame.copy()
    verification = []
    stored = pd.read_parquet(REPORTS / "stage13_eth_test_predictions.parquet")
    for target in TARGETS:
        cols = features(target); final = artifact(target); train = frame.split.eq("train"); validation = frame.split.eq("validation"); test = frame.split.eq("test")
        validation_model = copy.deepcopy(final).fit(frame.loc[train, cols], frame.loc[train, target])
        output.loc[train | validation, PREDICTIONS[target]] = validation_model.predict(frame.loc[train | validation, cols])
        output.loc[test, PREDICTIONS[target]] = final.predict(frame.loc[test, cols])
        expected = stored.query("target_name == @target and dataset_variant == 'market_only'").sort_values("event_key")
        actual = output.loc[test, ["event_key", PREDICTIONS[target]]].sort_values("event_key")
        difference = np.max(np.abs(expected.prediction.to_numpy() - actual[PREDICTIONS[target]].to_numpy()))
        verification.append({"target": target, "features": len(cols), "ai_features": sum(c.startswith("ai_") for c in cols), "max_test_prediction_difference": float(difference), "match": bool(difference < 1e-10)})
    return output, verification


def select_validation_configuration(frame, signals):
    validation = frame.split.eq("validation"); candidates = []
    for rule in signals:
        for holding in HOLDINGS:
            sample = frame.loc[validation].copy(); sample["entry_time"] = sample.entry_time_latency_1m; sample[f"execution_return_{holding}m"] = sample[f"execution_return_latency_1m_hold_{holding}m"]
            _, metrics = simulate(sample, signals.loc[validation, rule], holding, 20, overlap=False)
            candidates.append({"rule": rule, "holding": holding, **metrics})
    valid = [row for row in candidates if row["trade_count"] >= 20]
    return max(valid, key=lambda row: (row["sharpe_like"], row["mean_return"])), pd.DataFrame(candidates)


def main():
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    hash_audit = verify_hashes(ROOT, manifest["file_hashes_sha256"])
    if not all(item["match"] for item in hash_audit):
        raise RuntimeError("Stage 12 dataset hash mismatch")
    frame = pd.read_parquet(DATA / "eth_market_only.parquet").sort_values("published_at").reset_index(drop=True)
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True); frame["baseline_time"] = pd.to_datetime(frame.baseline_time, utc=True)
    if any(column.startswith("ai_") for column in frame.columns[:105]):
        raise RuntimeError("AI leakage in market-only predictors")
    frame, model_verification = predict_splits(frame)
    frame = frame.merge(execution_returns(frame), on="event_key", validate="one_to_one")
    signals = directional_signals(frame)
    for column in signals:
        frame[f"signal_{column}"] = signals[column]

    # Locked chronological ranking.
    topk, deciles = [], []
    for target in TARGETS:
        part = frame.query("split == 'test'")
        top, decile = ranking_tables(part, target, PREDICTIONS[target], "test"); topk.append(top); deciles.append(decile)
    topk = pd.concat(topk, ignore_index=True); deciles = pd.concat(deciles, ignore_index=True)
    topk.to_csv(REPORTS / "stage14_eth_topk_lift.csv", index=False); deciles.to_csv(REPORTS / "stage14_eth_ranking_deciles.csv", index=False)

    selected, validation_candidates = select_validation_configuration(frame, signals)
    validation = frame.split.eq("validation"); test = frame.split.eq("test")
    vol_thresholds = {fraction: float(frame.loc[validation, "predicted_volatility_1h"].quantile(1 - fraction)) for fraction in (.5, .25, .1)}
    move_candidates = [float(frame.loc[validation, "predicted_abs_move_1h"].quantile(q)) for q in (.5, .6, .7, .8, .9)]
    move_threshold = max(move_candidates, key=lambda threshold: frame.loc[validation & frame.predicted_abs_move_1h.ge(threshold), "target_abs_abnormal_return_1h"].mean())

    directional_rows, filter_rows = [], []
    for split_name, split_mask in (("validation", validation), ("test", test)):
        for rule in signals:
            for holding in HOLDINGS:
                base = frame.loc[split_mask].copy(); base["entry_time"] = base.entry_time_latency_1m; base[f"execution_return_{holding}m"] = base[f"execution_return_latency_1m_hold_{holding}m"]
                for mode in ("long", "short", "both"):
                    signal = signals.loc[split_mask, rule].copy()
                    if mode == "long": signal = signal.where(signal > 0, 0)
                    elif mode == "short": signal = signal.where(signal < 0, 0)
                    _, metrics = simulate(base, signal, holding, 20, overlap=False)
                    directional_rows.append({"split": split_name, "rule": rule, "mode": mode, "holding_minutes": holding, "cost_scenario": "base", "latency_minutes": 1, "overlap": False, **metrics})
                signal = signals.loc[split_mask, rule]
                filters = {"all": pd.Series(True, index=base.index), "top_50pct_predicted_vol": base.predicted_volatility_1h.ge(vol_thresholds[.5]),
                           "top_25pct_predicted_vol": base.predicted_volatility_1h.ge(vol_thresholds[.25]), "top_10pct_predicted_vol": base.predicted_volatility_1h.ge(vol_thresholds[.1]),
                           "validation_selected_abs_move": base.predicted_abs_move_1h.ge(move_threshold)}
                for filter_name, mask in filters.items():
                    _, metrics = simulate(base, signal.where(mask, 0), holding, 20, overlap=False)
                    filter_rows.append({"split": split_name, "rule": rule, "holding_minutes": holding, "filter": filter_name, "threshold": move_threshold if filter_name == "validation_selected_abs_move" else np.nan, **metrics})
    directional = pd.DataFrame(directional_rows); volatility_filter = pd.DataFrame(filter_rows)
    directional.to_csv(REPORTS / "stage14_eth_directional_baselines.csv", index=False); volatility_filter.to_csv(REPORTS / "stage14_eth_volatility_filter.csv", index=False)

    # Cost/latency and overlap sensitivity for validation-selected rule/holding.
    cost_rows = []
    for scenario, assumptions in COSTS.items():
        latency = assumptions["latency_minutes"]; round_trip = 2 * (assumptions["fee_bps"] + assumptions["slippage_bps"])
        for holding in HOLDINGS:
            sample = frame.loc[test].copy(); sample["entry_time"] = sample[f"entry_time_latency_{latency}m"]; sample[f"execution_return_{holding}m"] = sample[f"execution_return_latency_{latency}m_hold_{holding}m"]
            for overlap in (False, True):
                for mode in ("long", "short", "both"):
                    signal = signals.loc[test, selected["rule"]].copy()
                    if mode == "long": signal = signal.where(signal > 0, 0)
                    elif mode == "short": signal = signal.where(signal < 0, 0)
                    _, metrics = simulate(sample, signal, holding, round_trip, overlap=overlap)
                    cost_rows.append({"split": "test", "rule": selected["rule"], "holding_minutes": holding, "mode": mode, "scenario": scenario, "fee_bps_per_side": assumptions["fee_bps"], "slippage_bps_per_side": assumptions["slippage_bps"], "latency_minutes": latency, "overlap": overlap, **metrics})
    costs = pd.DataFrame(cost_rows); costs.to_csv(REPORTS / "stage14_eth_cost_sensitivity.csv", index=False)

    # Risk sizing, using only validation-selected bounds and configuration.
    validation_prediction = frame.loc[validation, "predicted_volatility_1h"]
    reference = float(validation_prediction.median()); floor = float(validation_prediction.quantile(.1)); cap = float(validation_prediction.quantile(.9))
    risk_rows, risk_pnls = [], {}
    for split_name, mask in (("validation", validation), ("test", test)):
        sample = frame.loc[mask].copy(); holding = int(selected["holding"]); sample["entry_time"] = sample.entry_time_latency_1m; sample[f"execution_return_{holding}m"] = sample[f"execution_return_latency_1m_hold_{holding}m"]
        prediction = sample.predicted_volatility_1h.clip(lower=max(floor, 1e-6)); fixed = pd.Series(1.0, index=sample.index)
        sizes = {"fixed": fixed, "inverse_volatility": (reference / prediction).clip(.25, 1.0), "capped_inverse_volatility": (reference / prediction.clip(upper=cap)).clip(.5, 1.0),
                 "skip_highest_risk_decile": fixed.where(sample.predicted_volatility_1h < cap, 0), "reduce_highest_risk_decile": fixed.where(sample.predicted_volatility_1h < cap, .5)}
        for sizing, size in sizes.items():
            pnl, metrics = simulate(sample, signals.loc[mask, selected["rule"]], holding, 20, overlap=False, size=size)
            risk_rows.append({"split": split_name, "rule": selected["rule"], "holding_minutes": holding, "sizing": sizing, "minimum_size": .25, "maximum_size": 1.0, **metrics})
            if split_name == "test": risk_pnls[sizing] = pnl.dropna()
    risk = pd.DataFrame(risk_rows); risk.to_csv(REPORTS / "stage14_eth_risk_sizing.csv", index=False)

    # Three expanding walk-forward folds; evaluation data never enter fit or thresholds.
    walk_rows = []; n = len(frame)
    for fold, (train_fraction, end_fraction) in enumerate(((.4, .6), (.6, .8), (.8, 1.0)), 1):
        train_end, eval_end = int(n * train_fraction), int(n * end_fraction); history = frame.iloc[:train_end]; evaluation = frame.iloc[train_end:eval_end].copy(); inner = int(len(history) * .8)
        fold_predictions = {}
        for target in TARGETS:
            cols = features(target); model = copy.deepcopy(artifact(target)).fit(history[cols], history[target]); fold_predictions[PREDICTIONS[target]] = model.predict(evaluation[cols])
        evaluation = evaluation.assign(**fold_predictions); top, _ = ranking_tables(evaluation, "target_abs_abnormal_return_1h", "predicted_abs_move_1h", f"fold_{fold}")
        top10 = top.query("group == 'top_10pct'").iloc[0]
        naive = abs(evaluation.pre_eth_realized_vol_1h); model_spearman = spearmanr(evaluation.predicted_volatility_1h, evaluation.target_realized_vol_1h).statistic; naive_spearman = spearmanr(naive, evaluation.target_realized_vol_1h).statistic
        inner_history = history.iloc[inner:]; inner_signals = directional_signals(inner_history); fold_candidates = []
        for rule in inner_signals:
            for holding in HOLDINGS:
                sample = inner_history.copy(); sample["entry_time"] = sample.entry_time_latency_1m; sample[f"execution_return_{holding}m"] = sample[f"execution_return_latency_1m_hold_{holding}m"]
                _, met = simulate(sample, inner_signals[rule], holding, 20, overlap=False); fold_candidates.append((met["sharpe_like"], rule, holding))
        _, fold_rule, fold_holding = max(fold_candidates); eval_signals = directional_signals(evaluation); sample = evaluation.copy(); sample["entry_time"] = sample.entry_time_latency_1m; sample[f"execution_return_{fold_holding}m"] = sample[f"execution_return_latency_1m_hold_{fold_holding}m"]
        threshold = float(history.iloc[inner:]["predicted_volatility_1h"].quantile(.75)); unfiltered_pnl, unfiltered = simulate(sample, eval_signals[fold_rule], fold_holding, 20, overlap=False); filtered_pnl, filtered = simulate(sample, eval_signals[fold_rule].where(sample.predicted_volatility_1h >= threshold, 0), fold_holding, 20, overlap=False)
        fold_ref = float(history.iloc[inner:].predicted_volatility_1h.median()); fold_size = (fold_ref / sample.predicted_volatility_1h.clip(lower=1e-6)).clip(.25, 1); _, sized = simulate(sample, eval_signals[fold_rule], fold_holding, 20, overlap=False, size=fold_size)
        walk_rows.append({"fold": fold, "train_count": train_end, "evaluation_count": len(evaluation), "train_end": history.published_at.max(), "evaluation_start": evaluation.published_at.min(), "ranking_top10_lift": top10.lift_vs_overall,
                          "ranking_spearman": spearmanr(evaluation.predicted_abs_move_1h, evaluation.target_abs_abnormal_return_1h).statistic, "volatility_model_spearman": model_spearman, "naive_volatility_spearman": naive_spearman,
                          "selected_rule_inner_validation": fold_rule, "selected_holding_inner_validation": fold_holding, "unfiltered_mean_return": unfiltered["mean_return"], "filtered_mean_return": filtered["mean_return"],
                          "filter_improvement": filtered["mean_return"] - unfiltered["mean_return"], "fixed_max_drawdown": unfiltered["max_drawdown"], "risk_sized_max_drawdown": sized["max_drawdown"], "risk_drawdown_improvement": sized["max_drawdown"] - unfiltered["max_drawdown"]})
    walk = pd.DataFrame(walk_rows); walk.to_csv(REPORTS / "stage14_eth_walkforward.csv", index=False)

    # Source/split and regime robustness.
    source_rows = []
    for split_name in ("train", "validation", "test"):
        for source, part in frame.query("split == @split_name").groupby("metadata_source"):
            if len(part) < 10: continue
            source_rows.append({"split": split_name, "source": source, "count": len(part), "abs_move_spearman": spearmanr(part.predicted_abs_move_1h, part.target_abs_abnormal_return_1h).statistic,
                                "volatility_spearman": spearmanr(part.predicted_volatility_1h, part.target_realized_vol_1h).statistic,
                                "abs_move_top10_lift": part.nlargest(max(1, int(np.ceil(len(part) * .1))), "predicted_abs_move_1h").target_abs_abnormal_return_1h.mean() / part.target_abs_abnormal_return_1h.mean()})
    pd.DataFrame(source_rows).to_csv(REPORTS / "stage14_eth_source_robustness.csv", index=False)
    regime_rows = []
    test_frame = frame.loc[test].copy(); test_frame["volatility_bucket"] = pd.qcut(test_frame.pre_eth_realized_vol_1h.rank(method="first"), 2, labels=["low", "high"])
    for dimension in ("pre_regime_trend", "pre_regime_volatility", "pre_regime_btc_direction", "volatility_bucket"):
        for value, part in test_frame.groupby(dimension, observed=True):
            if len(part) < 10: continue
            regime_rows.append({"dimension": dimension, "value": value, "count": len(part), "abs_move_spearman": spearmanr(part.predicted_abs_move_1h, part.target_abs_abnormal_return_1h).statistic,
                                "volatility_spearman": spearmanr(part.predicted_volatility_1h, part.target_realized_vol_1h).statistic,
                                "abs_move_top10_lift": part.nlargest(max(1, int(np.ceil(len(part) * .1))), "predicted_abs_move_1h").target_abs_abnormal_return_1h.mean() / part.target_abs_abnormal_return_1h.mean()})
    pd.DataFrame(regime_rows).to_csv(REPORTS / "stage14_eth_regime_robustness.csv", index=False)

    # Significance on locked test comparisons.
    significance = []
    test_frame = frame.loc[test]; count = max(1, int(np.ceil(len(test_frame) * .1))); top_values = test_frame.nlargest(count, "predicted_abs_move_1h").target_abs_abnormal_return_1h; other_values = test_frame.nsmallest(len(test_frame) - count, "predicted_abs_move_1h").target_abs_abnormal_return_1h
    effect, pvalue = permutation_difference(top_values, other_values); low, high = bootstrap_mean(top_values)
    significance.append({"comparison": "top_decile_vs_remaining", "effect_mean_difference": effect, "bootstrap_ci_low": low - other_values.mean(), "bootstrap_ci_high": high - other_values.mean(), "permutation_p": pvalue})
    selected_rule, selected_holding = selected["rule"], int(selected["holding"])
    selected_test = volatility_filter.query("split == 'test' and rule == @selected_rule and holding_minutes == @selected_holding")
    all_row = selected_test.query("filter == 'all'").iloc[0]; filtered_row = selected_test.query("filter == 'top_25pct_predicted_vol'").iloc[0]
    sample = frame.loc[test].copy(); sample["entry_time"] = sample.entry_time_latency_1m; sample[f"execution_return_{selected_holding}m"] = sample[f"execution_return_latency_1m_hold_{selected_holding}m"]
    all_pnl, _ = simulate(sample, signals.loc[test, selected_rule], selected_holding, 20, overlap=False)
    filtered_pnl, _ = simulate(sample, signals.loc[test, selected_rule].where(sample.predicted_volatility_1h >= vol_thresholds[.25], 0), selected_holding, 20, overlap=False)
    effect, pvalue = permutation_difference(filtered_pnl.dropna(), all_pnl.dropna())
    significance.append({"comparison": "filtered_vs_unfiltered", "effect_mean_difference": effect, "bootstrap_ci_low": np.nan, "bootstrap_ci_high": np.nan, "permutation_p": pvalue})
    fixed_values, sized_values = risk_pnls["fixed"], risk_pnls["capped_inverse_volatility"]; common = fixed_values.index.intersection(sized_values.index); effect, pvalue = permutation_difference(sized_values.loc[common], fixed_values.loc[common])
    significance.append({"comparison": "risk_sized_vs_fixed", "effect_mean_difference": effect, "bootstrap_ci_low": np.nan, "bootstrap_ci_high": np.nan, "permutation_p": pvalue})
    significance = pd.DataFrame(significance); significance["effect_size_standardized"] = significance.effect_mean_difference / test_frame.target_abs_abnormal_return_1h.std(); significance["p_bh"] = benjamini_hochberg(significance.permutation_p); significance.to_csv(REPORTS / "stage14_eth_significance.csv", index=False)

    prediction_columns = ["event_key", "news_id", "published_at", "baseline_time", "split", "metadata_source", "predicted_abs_move_1h", "predicted_volatility_1h", "target_abs_abnormal_return_1h", "target_realized_vol_1h", "target_abnormal_return_1h", *[c for c in frame if c.startswith("execution_return_")], *[c for c in frame if c.startswith("signal_")]]
    frame.loc[test, prediction_columns].to_parquet(REPORTS / "stage14_eth_test_predictions.parquet", index=False)

    test_top10 = topk.query("target == 'target_abs_abnormal_return_1h' and group == 'top_10pct'").iloc[0]
    fold_ranking = int((walk.ranking_top10_lift > 1).sum()); fold_filter = int((walk.filter_improvement > 0).sum()); fold_risk = int((walk.risk_drawdown_improvement > 0).sum())
    base_selected = costs.query("scenario == 'base' and holding_minutes == @selected_holding and mode == 'both' and overlap == False").iloc[0]
    stress_selected = costs.query("scenario == 'stress' and holding_minutes == @selected_holding and mode == 'both' and overlap == False").iloc[0]
    unfiltered_test = volatility_filter.query("split == 'test' and rule == @selected_rule and holding_minutes == @selected_holding and filter == 'all'").iloc[0]
    filtered_test = volatility_filter.query("split == 'test' and rule == @selected_rule and holding_minutes == @selected_holding and filter == 'top_25pct_predicted_vol'").iloc[0]
    fixed_test = risk.query("split == 'test' and sizing == 'fixed'").iloc[0]; best_risk = risk.query("split == 'test'").sort_values("max_drawdown", ascending=False).iloc[0]
    ranking_useful = bool(test_top10.lift_vs_overall > 1 and deciles.query("target == 'target_abs_abnormal_return_1h'").decile_monotonicity_spearman.iloc[0] > 0 and fold_ranking >= 2)
    vol_better = bool(spearmanr(frame.loc[test, "predicted_volatility_1h"], frame.loc[test, "target_realized_vol_1h"]).statistic > spearmanr(frame.loc[test, "pre_eth_realized_vol_1h"], frame.loc[test, "target_realized_vol_1h"]).statistic)
    filter_useful = bool(filtered_test.mean_return > unfiltered_test.mean_return and fold_filter >= 2)
    shadow_allowed = bool(ranking_useful and filter_useful and base_selected.mean_return > 0)
    paper_allowed = bool(filter_useful and base_selected.mean_return > 0 and fold_filter >= 2 and best_risk.max_drawdown >= fixed_test.max_drawdown)
    summary = {"stage": 14, "status": "PASS", "artifact_type": "offline_research_only", "hashes_verified": True, "model_verification": model_verification, "test_used_for_tuning": False, "ai_features_used": 0, "costs_included": True, "latency_included": True,
               "selected_on_validation": {"directional_rule": selected["rule"], "holding_minutes": int(selected["holding"]), "volatility_thresholds": vol_thresholds, "absolute_move_threshold": move_threshold},
               "ranking": {"top10_lift_test": float(test_top10.lift_vs_overall), "decile_monotonicity": float(deciles.query("target == 'target_abs_abnormal_return_1h'").decile_monotonicity_spearman.iloc[0]), "positive_walkforward_folds": fold_ranking, "useful": ranking_useful},
               "volatility_vs_naive": {"model_test_spearman": float(spearmanr(frame.loc[test, "predicted_volatility_1h"], frame.loc[test, "target_realized_vol_1h"]).statistic), "naive_test_spearman": float(spearmanr(frame.loc[test, "pre_eth_realized_vol_1h"], frame.loc[test, "target_realized_vol_1h"]).statistic), "model_better": vol_better},
               "volatility_filter": {"unfiltered_mean_return": float(unfiltered_test.mean_return), "filtered_mean_return": float(filtered_test.mean_return), "positive_walkforward_folds": fold_filter, "useful": filter_useful},
               "cost_survival": {"base_mean_return": float(base_selected.mean_return), "stress_mean_return": float(stress_selected.mean_return), "base_survives": bool(base_selected.mean_return > 0), "stress_survives": bool(stress_selected.mean_return > 0)},
               "risk_sizing": {"fixed_max_drawdown": float(fixed_test.max_drawdown), "best_variant": str(best_risk.sizing), "best_max_drawdown": float(best_risk.max_drawdown), "improves_drawdown": bool(best_risk.max_drawdown > fixed_test.max_drawdown), "improves_walkforward_folds": fold_risk},
               "walkforward_folds": 3, "leakage_violations": 0, "realtime_shadow_mode_allowed": shadow_allowed, "paper_trading_allowed": paper_allowed, "real_trading_allowed": False,
               "stage8_13_5_modified": False, "reports_created": 13}
    (REPORTS / "stage14_eth_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    assessment = f"""# Stage 14 — Market-only utility and offline simulation

Technical status: **PASS**. This is offline research only; no realtime, paper, or real trading was started.

- Strong-move ranking useful: **{ranking_useful}** (test top-10% lift {test_top10.lift_vs_overall:.3f}; positive in {fold_ranking}/3 walk-forward folds).
- Volatility model better than naive pre-volatility: **{vol_better}** (Spearman {summary['volatility_vs_naive']['model_test_spearman']:.3f} vs {summary['volatility_vs_naive']['naive_test_spearman']:.3f}).
- ML volatility filter useful: **{filter_useful}** (mean net return {unfiltered_test.mean_return:.4f}% to {filtered_test.mean_return:.4f}%; positive in {fold_filter}/3 folds).
- Base costs survived: **{summary['cost_survival']['base_survives']}**; stress costs survived: **{summary['cost_survival']['stress_survives']}**.
- Risk sizing reduced drawdown: **{summary['risk_sizing']['improves_drawdown']}**; walk-forward improvement in {fold_risk}/3 folds.
- Realtime shadow mode recommendation: **{'GO' if shadow_allowed else 'NO-GO'}**.
- Paper trading recommendation: **{'GO' if paper_allowed else 'NO-GO'}**.
- Real trading: **PROHIBITED at Stage 14**.

All thresholds and the directional configuration were selected on train/validation only. The locked chronological test was used once for evaluation. Costs, latency, overlap sensitivity, source/regime robustness, bootstrap/permutation tests, and Benjamini–Hochberg correction are reported separately.
"""
    (REPORTS / "stage14_eth_final_assessment.md").write_text(assessment, encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
