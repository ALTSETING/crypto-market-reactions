"""Conservative pattern eligibility helpers (no rule mining by force)."""
def sample_eligibility(train_n:int,validation_n:int,test_n:int,total_n:int):
    return {"basic_inference":train_n>=50 and validation_n>=20 and test_n>=20,
            "shadow_candidate":total_n>=200 and test_n>=50}

def net_return(gross_return_pct:float,fee_bps:float,slippage_bps:float)->float:
    return gross_return_pct-2*(fee_bps+slippage_bps)/100
