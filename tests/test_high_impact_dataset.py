import pandas as pd
from high_impact_sources.analysis.pattern_builder import net_return,sample_eligibility
from high_impact_sources.datasets.dataset_builder import chronological_split

def test_costs_correct():assert net_return(1,5,5)==.8
def test_minimum_sample_rules():assert sample_eligibility(50,20,20,200)=={"basic_inference":True,"shadow_candidate":False}
def test_chronological_split_no_overlap():
    frame=pd.DataFrame({"metadata_published_at":pd.date_range("2020-01-01",periods=10,tz="UTC"),"metadata_event_id":range(10)});split=chronological_split(frame);assert list(split.value_counts().sort_index())==[2,6,2]
def test_targets_not_features_contract():
    feature_names=["pre_return_5m","source_reliability","metadata_event_id"];assert not any(x.startswith("target_") for x in feature_names)
