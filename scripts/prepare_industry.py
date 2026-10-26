#!/usr/bin/env python3
"""Fetch industry research inputs, or import prepared evidence bundles.

No credentials beyond the project's existing SEC sync are needed. Raw archives
stay local. Run build_industry_fundamentals.py and prepare_industry_cases.py first
for the optional full dossier, then use --evidence.
"""
import argparse
from pathlib import Path

from investment_os.data.ingest import ingest
from investment_os.data.store import DataStore
from investment_os.registry import Registry

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    registry, store = Registry.load(ROOT), DataStore(ROOT)
    ids = [d.id for d in registry.datasets.values() if d.id.startswith(("french_ind12_", "french_ind49_"))]
    ids += ["french_ff3", "french_ff5", "french_mom", "fred_dff"]
    ids += ["fred_"+x.lower() for x in ("RVAM", "RVAMA", "RVAR", "RVAW", "RVAI", "MANEMP", "USMINE", "USTRADE", "USINFO", "AWHAEMAN", "CES3000000003", "IPMAN", "MCUMFN", "CPIAUCNS", "USREC")]
    ids.append("fred_dcoilwtico")
    failures = []
    for dataset in ids:
        if not args.refresh and store.latest(dataset):
            print(dataset, "already available", flush=True)
            continue
        result = ingest(registry, store, dataset, {})
        print(dataset, result.status, result.message, flush=True)
        if result.status == "failed":
            failures.append(dataset)
    if args.evidence:
        for dataset, file in (("industry_sec_facts", "fundamentals"), ("industry_valuation", "valuation"), ("industry_guidance", "guidance")):
            result = ingest(registry, store, dataset, {"path": str(ROOT/f"data/industry/{file}.json")})
            print(dataset, result.status, result.message, flush=True)
            if result.status == "failed":
                failures.append(dataset)
    if failures:
        raise SystemExit("Failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
