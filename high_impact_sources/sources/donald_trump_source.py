from .base_source import BaseSource
class DonaldTrumpSource(BaseSource):
    name="donald_trump";source_type="public_figure";platform="truth_social"
    def fetch(self,*args,**kwargs):return []
    def availability(self):return {"source":self.name,"status":"blocked","free_or_paid":"unverified_official_access","estimated_cost_usd":None,"official_handle":"realDonaldTrump","history_depth":"not queried","timestamp_precision":"API-dependent","rate_limit":"no verified free official history interface","restrictions":"no official supported historical API verified; scraping and third-party mirrors disabled"}
