from .base_provider import OnchainProvider
class EtherscanProvider(OnchainProvider):
    name="etherscan";paid=False
    def availability(self):return {"requires_key":True,"free_tier":"3 calls/s; 100000/day","estimated_cost_usd":0}
    def fetch(self,start,end):raise RuntimeError("ETHERSCAN_API_KEY is required; dry-run only")
