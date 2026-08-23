IDENTITY=["dataset_version","event_key","news_id","published_at","baseline_time","split"]
POST_NEWS_PREFIXES=("return_","abnormal_return_","max_favorable","max_adverse","max_absolute","realized_vol_","volume_shock_")
def assert_no_post_news_features(columns):
    bad=[column for column in columns if column.startswith(POST_NEWS_PREFIXES) or column.startswith("target_")]
    if bad:raise RuntimeError(f"Post-news leakage in predictive features: {bad}")
