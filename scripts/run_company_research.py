#!/usr/bin/env python3
"""Run and verify every registered company study from the local pinned bundle."""
import json
from pathlib import Path
from investment_os.runs import run_study, verify_run

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    runs=[]
    for path in sorted((ROOT/'config/studies').glob('company_*.yaml')):
        manifest=run_study(ROOT,path)
        if manifest['status'] not in ('success','partial'):
            raise SystemExit(f"{path.name}: {manifest.get('error')}")
        check=verify_run(ROOT,manifest['run_id'])
        if not check['reproduced']:
            raise SystemExit(f"Reproduction failed: {manifest['run_id']}")
        runs.append(manifest['run_id'])
        print(manifest['run_id'],manifest['status'],'reproduced',flush=True)
    (ROOT/'data/company-research/verified-runs.json').write_text(json.dumps(runs,indent=2))
