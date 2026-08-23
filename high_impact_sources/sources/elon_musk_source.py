from .base_source import BaseSource
class ElonMuskSource(BaseSource):
    name="elon_musk";source_type="public_figure";platform="x"
    def fetch(self,*args,**kwargs):return []
    def availability(self):return {"source":self.name,"status":"blocked","free_or_paid":"paid_or_authenticated","estimated_cost_usd":None,"official_handle":"elonmusk","history_depth":"not queried","timestamp_precision":"API-dependent","rate_limit":"plan-dependent","restrictions":"official X API credentials/paid access required; HTML scraping disabled"}
