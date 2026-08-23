class FredProvider:
    def availability(self):return {"status":"key_required","requires_key":True,"free":True,"estimated_cost_usd":0}
    def fetch(self,start,end):raise RuntimeError("FRED_API_KEY is required; dry-run only")
