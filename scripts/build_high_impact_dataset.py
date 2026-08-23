import json
from database.db import session_scope
from high_impact_sources.config import REPORTS
from high_impact_sources.datasets.dataset_builder import build
def main():
    with session_scope() as session:_,_,manifest=build(session,REPORTS)
    print(json.dumps({"rows":manifest["rows"],"leakage_violations":manifest["leakage_violations"]}))
if __name__=="__main__":main()
