from high_impact_sources.sources import SECSource,EthereumFoundationSource,EthereumGitHubSource,ElonMuskSource,DonaldTrumpSource
REGISTRY={"sec":SECSource,"ethereum_foundation":EthereumFoundationSource,"ethereum_github":EthereumGitHubSource,"elon_musk":ElonMuskSource,"donald_trump":DonaldTrumpSource}
def get_source(name:str):
    try:return REGISTRY[name]()
    except KeyError:raise ValueError(f"Unknown source {name!r}; choose {', '.join(REGISTRY)}") from None
