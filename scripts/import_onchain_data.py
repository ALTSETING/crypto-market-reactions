import json
from market_intelligence.onchain.ethereum_metrics import EtherscanProvider
if __name__=="__main__":print(json.dumps(EtherscanProvider().availability(),indent=2))
