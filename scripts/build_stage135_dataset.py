import json
from pathlib import Path
import pandas as pd
from market_intelligence.datasets import build_stage135_datasets
ROOT=Path(__file__).resolve().parents[1]
if __name__=="__main__":
 variants,targets,manifest=build_stage135_datasets(ROOT);(ROOT/"reports/stage135_dataset_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
 futures=[c for c in variants["market_futures"] if c.startswith(("pre_funding","pre_oi","pre_long","pre_top","pre_taker","crowded","price_","possible_"))]
 pd.DataFrame([{"feature":c,"non_null":int(variants["market_futures"][c].notna().sum()),"coverage":float(variants["market_futures"][c].notna().mean())} for c in futures]).to_csv(ROOT/"reports/stage135_futures_features.csv",index=False)
 print(json.dumps(manifest,indent=2))
