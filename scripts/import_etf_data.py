import json
from market_intelligence.etf.eth_etf_importer import EthEtfProvider
if __name__=="__main__":print(json.dumps(EthEtfProvider().availability(),indent=2))
