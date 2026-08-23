"""Build and audit the versioned Stage 12 final ETH ML datasets."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from database.db import session_scope
from ml.stage12_dataset_builder import (
    DATASET_VERSION, IDENTITY_COLUMNS, MODEL, PROMPT_VERSION, assemble_stage12,
    cost_scenarios, feature_group, feature_quality, git_commit, missing_report,
    sha256_file, source_counts, split_distribution, target_quality,
)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def verify_resume(output_dir: Path, version: str) -> dict[str, Any]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists(): raise SystemExit("--resume requested but manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_version") != version: raise SystemExit("Resume version differs from manifest")
    mismatches=[]
    for relative, expected in manifest["file_hashes_sha256"].items():
        path = ROOT / relative
        if not path.exists() or sha256_file(path) != expected: mismatches.append(relative)
    if mismatches: raise SystemExit(f"Resume hash verification failed: {mismatches}")
    print(json.dumps({"status":"RESUME_PASS","dataset_version":version,"event_count":manifest["event_count"],"schema_hash":manifest["schema_hash"],"hash_mismatches":[]},indent=2))
    return manifest


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--version",default=DATASET_VERSION)
    parser.add_argument("--output-dir",type=Path,default=ROOT/"data"/"stage12")
    parser.add_argument("--overwrite",action="store_true")
    parser.add_argument("--overwrite-reason")
    parser.add_argument("--preview-only",action="store_true")
    parser.add_argument("--audit-only",action="store_true")
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args()
    if args.version != DATASET_VERSION: parser.error(f"This builder implements exactly {DATASET_VERSION}")
    output_dir=args.output_dir.resolve(); output_dir.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(exist_ok=True)
    if args.resume and (output_dir/"manifest.json").exists(): verify_resume(output_dir,args.version); return
    existing=[output_dir/name for name in ("eth_market_only.parquet","eth_ai_only.parquet","eth_market_plus_ai.parquet","manifest.json") if (output_dir/name).exists()]
    if existing and not args.overwrite: raise SystemExit("Stage 12 outputs exist; use --resume or explicit --overwrite")
    if args.overwrite and not args.overwrite_reason: parser.error("--overwrite requires --overwrite-reason")

    with session_scope() as session:
        before=source_counts(session)
        event_index,features,targets,diagnostics=assemble_stage12(session,REPORTS/"stage11_eth_dataset_a.parquet")
        alembic_revision=str(session.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
        after=source_counts(session)
    if before != after: raise RuntimeError("Stage 8-11 source table counts changed during read-only build")
    numeric=[column for column in features if pd.api.types.is_numeric_dtype(features[column])]
    features[numeric]=features[numeric].replace([np.inf,-np.inf],np.nan)
    quality,approved,correlations,removed=feature_quality(features)
    target_audit,target_stability,recommended=target_quality(targets)
    missing=missing_report(features,approved,removed)
    cutoff=diagnostics.pop("cutoff_audit")
    leakage=[column for column in approved if column in {"title","body","raw_article_text"} or column.startswith("target_") or any(fragment in column.casefold() for fragment in ("reaction","future_","abnormal_return","raw_response"))]
    if leakage: raise RuntimeError(f"Leakage features approved: {leakage}")

    basic_metadata=[column for column in approved if feature_group(column)=="metadata"]
    ai=[column for column in approved if feature_group(column)=="stage9_ai"]
    market=[column for column in approved if column not in ai]
    variants={
        "eth_market_only.parquet":market,
        "eth_ai_only.parquet":basic_metadata+ai,
        "eth_market_plus_ai.parquet":approved,
    }
    target_columns=[column for column in targets if column.startswith("target_")]
    ordered_keys=features.event_key.tolist()
    output_files=[]
    if not args.audit_only:
        targets.to_parquet(output_dir/"eth_targets.parquet",index=False); output_files.append(output_dir/"eth_targets.parquet")
        for filename,columns in variants.items():
            data=features[IDENTITY_COLUMNS+columns].merge(targets,on=IDENTITY_COLUMNS,how="inner",validate="one_to_one")
            if data.event_key.tolist()!=ordered_keys: raise RuntimeError("Variant event order changed")
            if not args.preview_only:
                data.to_parquet(output_dir/filename,index=False); output_files.append(output_dir/filename)
            preview_name=f"stage12_{filename.removesuffix('.parquet')}_preview.csv"
            data.head(100).to_csv(REPORTS/preview_name,index=False,encoding="utf-8-sig")
            output_files.append(REPORTS/preview_name)

    event_index.to_parquet(REPORTS/"stage12_eth_event_index.parquet",index=False)
    event_index.to_csv(REPORTS/"stage12_eth_event_index.csv",index=False,encoding="utf-8-sig")
    cutoff.to_csv(REPORTS/"stage12_eth_feature_cutoff_audit.csv",index=False,encoding="utf-8-sig")
    quality.to_csv(REPORTS/"stage12_eth_feature_quality.csv",index=False,encoding="utf-8-sig")
    correlations.to_parquet(REPORTS/"stage12_eth_feature_correlations.parquet")
    removed.to_csv(REPORTS/"stage12_eth_removed_features.csv",index=False,encoding="utf-8-sig")
    missing.to_csv(REPORTS/"stage12_eth_missing_values.csv",index=False,encoding="utf-8-sig")
    target_audit.to_csv(REPORTS/"stage12_eth_target_quality.csv",index=False,encoding="utf-8-sig")
    target_stability.to_csv(REPORTS/"stage12_eth_target_split_stability.csv",index=False,encoding="utf-8-sig")
    split_dist=split_distribution(targets); split_dist.to_csv(REPORTS/"stage12_eth_split_distribution.csv",index=False,encoding="utf-8-sig")
    split_json=diagnostics["split_details"]
    for fold in split_json["walk_forward_folds"]:
        start=pd.Timestamp(fold["evaluation_start"]); end=pd.Timestamp(fold["evaluation_end"])
        fold["target_distribution"]={target:float(targets.loc[(targets.published_at>=start)&(targets.published_at<=end),target].mean()) for target in recommended if pd.api.types.is_numeric_dtype(targets[target])}
    write_json(REPORTS/"stage12_eth_splits.json",{"dataset_version":DATASET_VERSION,**split_json})
    write_json(REPORTS/"stage12_eth_cost_scenarios.json",cost_scenarios())
    audit_files=[
        REPORTS/"stage12_eth_event_index.parquet",REPORTS/"stage12_eth_event_index.csv",
        REPORTS/"stage12_eth_feature_cutoff_audit.csv",REPORTS/"stage12_eth_feature_quality.csv",
        REPORTS/"stage12_eth_feature_correlations.parquet",REPORTS/"stage12_eth_removed_features.csv",
        REPORTS/"stage12_eth_missing_values.csv",REPORTS/"stage12_eth_target_quality.csv",
        REPORTS/"stage12_eth_target_split_stability.csv",REPORTS/"stage12_eth_split_distribution.csv",
        REPORTS/"stage12_eth_splits.json",REPORTS/"stage12_eth_cost_scenarios.json",
    ]; output_files.extend(audit_files)
    schema_payload={"dataset_version":DATASET_VERSION,"identity_columns":IDENTITY_COLUMNS,"approved_features":approved,"removed_features":removed.feature.tolist(),"targets":target_columns,"variants":variants}
    schema_hash=hashlib_sha(json.dumps(schema_payload,sort_keys=True,default=str).encode())
    duplicate_events=int(features.event_key.duplicated().sum())
    cutoff_violations=int(cutoff.violation.sum())
    inf_values=int(np.isinf(features[[c for c in features if pd.api.types.is_numeric_dtype(features[c])]].to_numpy(float)).sum())
    summary={
        "stage":12,"dataset_version":DATASET_VERSION,"status":"PENDING_TESTS",
        "source_analyses":diagnostics["source_analysis_rows"],"source_reactions":before["news_market_reactions"],
        "event_rows":len(features),"exclusions":diagnostics["excluded_events"],
        "features_before_audit":len(quality),"features_approved":len(approved),"features_removed":len(removed),
        "target_count":len(target_columns),"recommended_targets":recommended,
        "split_counts":targets.split.value_counts().to_dict(),"missing_feature_cells":int(features[approved].isna().sum().sum()),
        "feature_cutoff_violations":cutoff_violations,"leakage_violations":len(leakage),"duplicate_events":duplicate_events,
        "infinite_values":inf_values,"manifest_path":str((output_dir/"manifest.json").relative_to(ROOT)),
        "pytest_result":"PENDING","stage8_11_counts_unchanged":before==after,
    }
    write_json(REPORTS/"stage12_eth_summary.json",summary)
    assessment=(f"# Stage 12 Final ETH ML Dataset\n\nStatus: PENDING TESTS\n\n- Events: {len(features)}; exclusions: {diagnostics['excluded_events']}.\n- Approved features: {len(approved)}; removed: {len(removed)}.\n- Targets: {len(target_columns)}; recommended: {recommended}.\n- Cutoff violations: {cutoff_violations}; leakage: {len(leakage)}; duplicate events: {duplicate_events}.\n- No API, model training, paper trading, or real trading was run.\n")
    (REPORTS/"stage12_eth_final_assessment.md").write_text(assessment,encoding="utf-8")
    output_files.extend([REPORTS/"stage12_eth_summary.json",REPORTS/"stage12_eth_final_assessment.md"])
    manifest={
        "stage":12,"dataset_version":DATASET_VERSION,"created_at":datetime.now(timezone.utc).isoformat(),
        "git_commit_hash":git_commit(ROOT),"database_alembic_revision":alembic_revision,"source_table_counts":before,
        "event_count":len(features),"excluded_event_count":diagnostics["excluded_events"],"feature_list":approved,
        "target_list":target_columns,"recommended_targets":recommended,"split_definition":split_json,
        "time_coverage":{"start":features.published_at.min(),"end":features.published_at.max()},
        "ai_model":MODEL,"prompt_version":PROMPT_VERSION,"feature_cutoff_rule":diagnostics["feature_cutoff_rule"],
        "rolling_beta_formula":diagnostics["beta_formula"],"schema_hash":schema_hash,
        "file_hashes_sha256":{},"tests_status":"PENDING","leakage_status":"PASS" if not leakage and not cutoff_violations else "FAIL",
        "stage8_11_source_counts_unchanged":before==after,"overwrite_reason":args.overwrite_reason,
    }
    write_json(output_dir/"manifest.json",manifest)

    test = subprocess.run([str(ROOT/".venv"/"Scripts"/"python.exe"),"-m","pytest","tests","-q"],cwd=ROOT,text=True,capture_output=True)
    test_summary=(test.stdout+"\n"+test.stderr).strip()
    passed=test.returncode==0
    pass_conditions=not cutoff_violations and not leakage and not duplicate_events and inf_values==0 and before==after and passed and len(features)==6851
    summary.update({"status":"PASS" if pass_conditions else "FAIL","pytest_result":test_summary,"pytest_exit_code":test.returncode})
    write_json(REPORTS/"stage12_eth_summary.json",summary)
    assessment=assessment.replace("Status: PENDING TESTS",f"Status: {'PASS' if pass_conditions else 'FAIL'}")+f"\n- Pytest: {'PASS' if passed else 'FAIL'}.\n"
    (REPORTS/"stage12_eth_final_assessment.md").write_text(assessment,encoding="utf-8")
    all_hash_files=list(dict.fromkeys(output_files))
    manifest["tests_status"]="PASS" if passed else "FAIL"
    manifest["file_hashes_sha256"]={str(path.relative_to(ROOT)).replace("\\","/"):sha256_file(path) for path in all_hash_files if path.exists()}
    write_json(output_dir/"manifest.json",manifest)
    print(json.dumps({"status":summary["status"],"events":len(features),"approved_features":len(approved),"removed_features":len(removed),"targets":len(target_columns),"recommended_targets":recommended,"splits":summary["split_counts"],"cutoff_violations":cutoff_violations,"leakage_violations":len(leakage),"duplicate_events":duplicate_events,"pytest_exit_code":test.returncode,"manifest":str(output_dir/"manifest.json")},indent=2))
    if not pass_conditions: raise SystemExit(1)


def hashlib_sha(value: bytes) -> str:
    import hashlib
    return hashlib.sha256(value).hexdigest()


if __name__=="__main__": main()
