#!/usr/bin/env python3
"""Select historical sector samples from the existing SEC FSDS archives.

Never changes the E1 company partitions. Only 10-K/10-K/A US business-address
filers, annual fiscal-end facts, consolidated US GAAP USD tags. All membership,
alias selection and missingness are recorded. No current ticker list is used.
Run: uv run python scripts/build_industry_fundamentals.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]

EXTRA = {
    "operating_income": ["OperatingIncomeLoss"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "repurchases": ["PaymentsForRepurchaseOfCommonStock"],
    "stock_compensation": ["ShareBasedCompensation"],
    "long_term_debt": ["LongTermDebtCurrent", "LongTermDebtNoncurrent"],
}


def topic_for_sic(sic, mapping):
    try:
        sic = int(sic)
    except (ValueError, TypeError):
        return None
    return next((name for name, topic in mapping["topics"].items()
                 if any(lo <= sic <= hi for lo, hi in topic.get("sic_ranges", []))), None)


def extract(path, cache, mapping, tags, config_hash):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    target = cache / f"{path.stem}_{digest[:16]}_{config_hash}.parquet"
    if target.exists():
        return pd.read_parquet(target), digest
    with zipfile.ZipFile(path) as z:
        subs = pd.read_csv(z.open("sub.txt"), sep="\t", dtype=str, keep_default_na=False)
        subs["topic"] = subs.sic.map(lambda x: topic_for_sic(x, mapping))
        subs = subs[subs.form.isin(["10-K", "10-K/A"]) & subs.topic.notna() & (subs.countryba == "US")]
        keep = set(subs.adsh)
        chunks = []
        for chunk in pd.read_csv(z.open("num.txt"), sep="\t", dtype=str, keep_default_na=False,
                                 usecols=lambda c: c in {"adsh", "tag", "version", "ddate", "qtrs", "uom", "value", "coreg", "segments"},
                                 chunksize=500_000):
            mask = (chunk.adsh.isin(keep) & chunk.tag.isin(tags) & chunk.version.str.startswith("us-gaap/")
                    & chunk.uom.eq("USD") & chunk.qtrs.isin(["0", "4"]))
            for c in ("coreg", "segments"):
                if c in chunk:
                    mask &= chunk[c].eq("")
            chosen = chunk[mask].copy()
            if len(chosen):
                chunks.append(chosen)
        if not chunks:
            result = pd.DataFrame()
        else:
            facts = pd.concat(chunks, ignore_index=True)
            result = facts.merge(subs[["adsh", "cik", "name", "sic", "topic", "form", "period", "filed", "accepted"]], on="adsh", validate="many_to_one")
            # Only the reported fiscal year; comparative columns cannot retroactively
            # transfer a new SIC classification to the prior sample.
            result = result[result.ddate.eq(result.period)].copy()
            result["source_archive"] = path.name
            result["source_sha256"] = digest
        result.to_parquet(target, index=False)
        return result, digest


def choose_facts(frame, metrics, cutoff):
    """Per fiscal end: keep original SIC, first value and the latest amendment.

    Only contemporaneous-year filings and amendments are considered; future-year
    comparative columns are excluded. Conflicting same-tag facts fail closed.
    """
    f = frame[frame.filed.le(cutoff.replace("-", ""))].copy()
    f["value"] = pd.to_numeric(f.value, errors="coerce")
    f = f.dropna(subset=["value"]).drop_duplicates(["adsh", "tag", "qtrs", "value"])
    conflict = f.groupby(["adsh", "tag", "qtrs"]).value.transform("nunique").gt(1)
    conflicts = int(conflict.sum())
    f = f[~conflict].copy()
    f = f.sort_values(["filed", "accepted", "adsh", "source_archive"])
    memberships = f.drop_duplicates(["cik", "period"], keep="first").set_index(["cik", "period"])
    records = []
    for metric, spec in metrics.items():
        alias = {tag: i for i, tag in enumerate(spec["tags"])}
        a = f[f.tag.isin(alias) & f.qtrs.eq("0" if spec["period"] == "instant" else "4")].copy()
        a["priority"] = a.tag.map(alias)
        a = a.sort_values("priority", kind="stable").drop_duplicates(["adsh", "cik", "period"], keep="first")
        a = a.sort_values(["filed", "accepted", "adsh"])
        first = a.drop_duplicates(["cik", "period"]).set_index(["cik", "period"])
        for row in a.drop_duplicates(["cik", "period"], keep="last").to_dict("records"):
            key = (row["cik"], row["period"])
            original = first.loc[key]
            member = memberships.loc[key]
            year = int(row["period"][:4])
            if not 2009 <= year <= 2025:
                continue
            records.append({"id": f"{row['cik']}_{row['period']}_{metric}",
                            "date": f"{year}-01-01", "value": float(row["value"]),
                            "published_at": pd.Timestamp(row["filed"]).isoformat(),
                            "cik": int(row["cik"]), "company": row["name"], "topic": member.topic,
                            "sic": member.sic, "metric": metric, "fiscal_end": row["period"],
                            "accession": row["adsh"], "form": row["form"], "tag": row["tag"],
                            "first_value": float(original.value), "first_filed": original.filed,
                            "membership_accession": member.adsh,
                            "source_archive": row["source_archive"], "source_sha256": row["source_sha256"],
                            "locator": f"num.txt:adsh={row['adsh']};tag={row['tag']};ddate={row['period']};qtrs={row['qtrs']};USD;consolidated",
                            "source_url": f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/{row['adsh'].replace('-', '')}/{row['adsh']}-index.html"})
    return records, conflicts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", default="2026-10-25")
    args = parser.parse_args()
    mapping = yaml.safe_load((ROOT/"config/industry.yaml").read_text())
    base = yaml.safe_load((ROOT/"config/fundamentals.yaml").read_text())
    metrics = {k: {"period": v["period"], "tags": [s.split(":", 1)[1] for s in v["tags"]]}
               for k, v in base["metrics"].items() if v["unit"] == "USD"}
    for name, tags in EXTRA.items():
        if name != "long_term_debt":  # Components are separate; never select one as total debt.
            metrics[name] = {"period": "instant" if name == "cash" else "duration", "tags": tags}
    for name, tag in zip(("debt_current", "debt_noncurrent"), EXTRA["long_term_debt"]):
        metrics[name] = {"period": "instant", "tags": [tag]}
    config_hash = hashlib.sha256(json.dumps([mapping, metrics, "extract.v2"], sort_keys=True).encode()).hexdigest()[:12]
    cache = ROOT/"data/industry/cache"; cache.mkdir(parents=True, exist_ok=True)
    paths = sorted((ROOT/"data/edgar/raw/fsds").glob("*.zip"))
    if not paths:
        raise SystemExit("No local FSDS archives; run the existing EDGAR sync first")
    tags = {t for m in metrics.values() for t in m["tags"]}
    frames, sources = [], []
    for i, path in enumerate(paths):
        frame, digest = extract(path, cache, mapping, tags, config_hash)
        if len(frame):
            frames.append(frame)
        sources.append({"file": path.name, "sha256": digest, "selected_rows": len(frame)})
        print(f"{i+1}/{len(paths)} {path.name}: {len(frame)} facts", flush=True)
    records, conflicts = choose_facts(pd.concat(frames, ignore_index=True), metrics, args.cutoff)
    members = []
    for path in paths:
        with zipfile.ZipFile(path) as z:
            s = pd.read_csv(z.open("sub.txt"), sep="\t", dtype=str, keep_default_na=False)
        s["topic"] = s.sic.map(lambda x: topic_for_sic(x, mapping))
        s = s[s.form.isin(["10-K", "10-K/A"]) & s.topic.notna() & s.countryba.eq("US")
              & s.filed.le(args.cutoff.replace("-", "")) & s.period.str[:4].between("2009", "2025")]
        members.append(s[["cik", "name", "period", "sic", "topic", "adsh", "filed"]])
    membership = pd.concat(members).sort_values(["filed", "adsh"]).drop_duplicates(["cik", "period"]).to_dict("records")
    membership_index = {(int(x["cik"]), x["period"]): x for x in membership}
    for record in records:
        first = membership_index[(record["cik"], record["fiscal_end"])]
        record.update(topic=first["topic"], sic=first["sic"], membership_accession=first["adsh"])
    doc = {"schema": "industry-evidence.v1", "unit": "USD", "records": records,
           "metadata": {"cutoff": args.cutoff, "mapping": mapping, "metrics": metrics,
                        "archives": sources, "membership": membership, "conflicting_rows_excluded": conflicts,
                        "sampling": "Historical 10-K/10-K/A, US business address, fiscal-end US-GAAP consolidated USD facts; not the CRSP listed-equity universe"}}
    path = ROOT/"data/industry/fundamentals.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, allow_nan=False))
    print(json.dumps({"output": str(path), "records": len(records), "companies": len({r['cik'] for r in records}), "conflicts_excluded": conflicts}))


if __name__ == "__main__":
    main()
