import pandas as pd

from analysis.stage17_subgroups import (
    DIRECTIONAL_HYPOTHESES, EXPLORATORY_HORIZONS, PRIMARY_HORIZONS,
    add_event_contamination, cluster_resample, fit_context_bins, membership,
)


def _membership_frame():
    rows=[]
    for event_id,asset in ((1,"BTC"),(1,"ETH"),(2,"SOL")):
        rows.append({
            "metadata_event_id":event_id,"metadata_asset":asset,"metadata_split":"train",
            "ai_asset_relevance":90,"ai_directness":"direct","ai_importance":70,"ai_specificity":70,
            "ai_novelty":50,"ai_evidence_quality":"official_document","source_information_status":"confirmed_action",
            "ai_actionability":80,"ai_execution_certainty":90,"ai_temporary_vs_structural":"structural",
            "ai_fundamental_relevance":70,"source_event_type":"official_decision","ai_regulatory_strength":80,
            "ai_technical_significance":0,"ai_institutional_relevance":70,"ai_security_significance":0,
        })
    return pd.DataFrame(rows)


def test_event_asset_is_the_identity_and_event_can_repeat_across_assets():
    frame=_membership_frame()
    assert frame.duplicated(["metadata_event_id","metadata_asset"]).sum()==0
    assert frame.duplicated(["metadata_event_id"]).sum()==1
    result=membership(frame)
    assert result.duplicated(["event_id","asset","subgroup_id"]).sum()==0
    assert len(result)==len(frame)*12


def test_all_assets_of_an_event_share_one_split():
    frame=_membership_frame()
    assert frame.groupby("metadata_event_id").metadata_split.nunique().max()==1
    frame.loc[frame.metadata_asset.eq("ETH"),"metadata_split"]="test"
    assert frame.groupby("metadata_event_id").metadata_split.nunique().max()==2


def test_cluster_resample_moves_all_asset_rows_together():
    frame=_membership_frame()[["metadata_event_id","metadata_asset"]]
    sampled=cluster_resample(frame,seed=4)
    for _,draw in sampled.groupby("cluster_draw"):
        event_id=draw.metadata_event_id.iloc[0]
        expected=set(frame.loc[frame.metadata_event_id.eq(event_id),"metadata_asset"])
        assert set(draw.metadata_asset)==expected


def test_event_contamination_and_isolated_filter():
    frame=pd.DataFrame({
        "metadata_event_id":[1,2,3],"metadata_asset":["ETH","ETH","BTC"],
        "reaction_baseline_time":pd.to_datetime(["2024-01-01T00:00Z","2024-01-01T00:30Z","2024-01-01T00:10Z"],utc=True),
    })
    report=add_event_contamination(frame)
    first_1h=report[(report.event_id.eq(1))&report.asset.eq("ETH")&report.horizon.eq("1h")].iloc[0]
    first_20m=report[(report.event_id.eq(1))&report.asset.eq("ETH")&report.horizon.eq("20m")].iloc[0]
    assert first_1h.overlapping_event_count==1 and not first_1h.isolated_event
    assert first_20m.overlapping_event_count==0 and first_20m.isolated_event
    assert report[(report.event_id.eq(3))&report.asset.eq("BTC")].isolated_event.all()


def test_latency_and_horizon_protocol_is_not_mixed():
    assert set(PRIMARY_HORIZONS)=={"1h","3h","12h"}
    assert set(PRIMARY_HORIZONS).isdisjoint(EXPLORATORY_HORIZONS)
    # Only explicitly pre-registered valence rules may receive directional PnL.
    assert set(DIRECTIONAL_HYPOTHESES)=={"H2","H3"}


def test_context_thresholds_are_fit_from_train_only():
    frame=pd.DataFrame({
        "metadata_split":["train","train","train","validation","test"],
        "pre_btc_return_60m":[-1,0,1,999,-999],"pre_return_20m":[-2,0,2,999,-999],
        "pre_realized_vol_60m":[1,2,3,999,-999],"pre_relative_strength_1h":[-3,0,3,999,-999],
    })
    first=fit_context_bins(frame)
    frame.loc[frame.metadata_split.ne("train"),["pre_btc_return_60m","pre_return_20m","pre_realized_vol_60m","pre_relative_strength_1h"]]=1e9
    assert fit_context_bins(frame)==first


def test_low_relevance_security_does_not_enter_subgroup_j():
    frame=_membership_frame()
    frame.loc[0,"source_event_type"]="security_event"
    frame.loc[0,"ai_asset_relevance"]=20
    result=membership(frame)
    row=result[(result.event_id.eq(1))&result.asset.eq("BTC")&result.subgroup_id.eq("J")].iloc[0]
    assert not row.matched
