import json
from market_intelligence.macro.macro_importer import FredProvider
if __name__=="__main__":print(json.dumps(FredProvider().availability(),indent=2))
