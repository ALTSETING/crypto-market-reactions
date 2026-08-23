class EthEtfProvider:
    def availability(self):return {"status":"blocked","reason":"no verified stable official free daily-flow API","estimated_cost_usd":None}
    def fetch(self,start,end):raise RuntimeError("Provider not configured; dry-run only")
