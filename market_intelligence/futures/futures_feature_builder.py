from __future__ import annotations

import numpy as np
import pandas as pd


def _asof(base, data, time, columns, *, tolerance=None):
    if data.empty:
        for column in columns:
            base[column] = np.nan
        return base
    part = data.sort_values(time)[[time, *columns]].rename(columns={time: "metric_time"})
    return pd.merge_asof(base.sort_values("baseline_time"), part, left_on="baseline_time", right_on="metric_time", direction="backward", tolerance=tolerance).drop(columns="metric_time")


def _rolling_zscore(series, window):
    mean = series.rolling(window, min_periods=max(2, min(window, 3))).mean()
    std = series.rolling(window, min_periods=max(2, min(window, 3))).std()
    return (series - mean) / std.replace(0, np.nan)


def build_futures_features(events: pd.DataFrame, funding: pd.DataFrame, oi: pd.DataFrame, ratios: pd.DataFrame, taker: pd.DataFrame, symbol="ETHUSDT"):
    result = events[["event_key", "baseline_time"]].copy().sort_values("baseline_time")
    fund = funding.loc[funding.symbol.eq(symbol)].sort_values("funding_time").copy() if not funding.empty else funding
    if not fund.empty:
        fund["pre_funding_previous"] = fund.funding_rate.shift(1)
        fund["pre_funding_change"] = fund.funding_rate - fund.pre_funding_previous
        fund["pre_funding_zscore_7d"] = _rolling_zscore(fund.funding_rate.astype(float), 21)
        fund = fund.rename(columns={"funding_rate": "pre_funding_current", "mark_price": "pre_funding_mark_price"})
    result = _asof(result, fund, "funding_time", ["pre_funding_current", "pre_funding_mark_price", "pre_funding_previous", "pre_funding_change", "pre_funding_zscore_7d"])

    oi_part = oi.loc[oi.symbol.eq(symbol)].sort_values("timestamp").copy() if not oi.empty else oi
    if not oi_part.empty:
        values = oi_part.open_interest.astype(float)
        oi_part["pre_oi_change_5m"] = values.pct_change(1) * 100
        oi_part["pre_oi_change_15m"] = values.pct_change(3) * 100
        oi_part["pre_oi_change_1h"] = values.pct_change(12) * 100
        oi_part["pre_oi_change_4h"] = values.pct_change(48) * 100
        oi_part["pre_oi_zscore_7d"] = _rolling_zscore(values, 2016)
        oi_part = oi_part.rename(columns={"open_interest": "pre_oi_current", "open_interest_value": "pre_oi_value"})
    oi_columns = ["pre_oi_current", "pre_oi_value", "pre_oi_change_5m", "pre_oi_change_15m", "pre_oi_change_1h", "pre_oi_change_4h", "pre_oi_zscore_7d"]
    result = _asof(result, oi_part, "timestamp", oi_columns, tolerance=pd.Timedelta("10min"))

    global_ratio = ratios.query("symbol == @symbol and ratio_type == 'global'").sort_values("timestamp").copy() if not ratios.empty else ratios
    if not global_ratio.empty:
        global_ratio["pre_long_short_change_1h"] = global_ratio.long_short_ratio.astype(float).pct_change(12) * 100
        global_ratio = global_ratio.rename(columns={"long_short_ratio": "pre_long_short_ratio"})
    result = _asof(result, global_ratio, "timestamp", ["pre_long_short_ratio", "pre_long_short_change_1h"], tolerance=pd.Timedelta("10min"))
    top_ratio = ratios.query("symbol == @symbol and ratio_type == 'top_position'").sort_values("timestamp").rename(columns={"long_short_ratio": "pre_top_trader_ratio"}) if not ratios.empty else ratios
    result = _asof(result, top_ratio, "timestamp", ["pre_top_trader_ratio"], tolerance=pd.Timedelta("10min"))

    taker_part = taker.loc[taker.symbol.eq(symbol)].sort_values("timestamp").copy() if not taker.empty else taker
    if not taker_part.empty:
        ratio = taker_part.buy_sell_ratio.astype(float)
        taker_part["pre_taker_net_flow_5m"] = (ratio - 1) / (ratio + 1)
        taker_part["pre_taker_net_flow_15m"] = taker_part.pre_taker_net_flow_5m.rolling(3, min_periods=1).mean()
        taker_part["pre_taker_net_flow_1h"] = taker_part.pre_taker_net_flow_5m.rolling(12, min_periods=1).mean()
        taker_part = taker_part.rename(columns={"buy_sell_ratio": "pre_taker_buy_sell_ratio"})
    result = _asof(result, taker_part, "timestamp", ["pre_taker_buy_sell_ratio", "pre_taker_net_flow_5m", "pre_taker_net_flow_15m", "pre_taker_net_flow_1h"], tolerance=pd.Timedelta("10min"))
    result["pre_funding_extreme_positive"] = (result.pre_funding_current > .0005).astype("Int64")
    result["pre_funding_extreme_negative"] = (result.pre_funding_current < -.0005).astype("Int64")
    result["crowded_long"] = ((result.pre_funding_current > .0005) & (result.pre_long_short_ratio > 1.2)).astype("Int64")
    result["crowded_short"] = ((result.pre_funding_current < -.0005) & (result.pre_long_short_ratio < .8)).astype("Int64")
    return result
