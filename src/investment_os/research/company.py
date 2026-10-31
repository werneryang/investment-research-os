"""Annual company research from a pinned, auditable SEC evidence bundle."""
from __future__ import annotations

import hashlib
import json
from datetime import date

from ..contracts import ResultType
from .base import ResearchResult, input_record, register_branch

METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow", "capex")


def select_fact(history):
    """Latest filing; conflicting values within a filing are withheld upstream."""
    return sorted(history, key=lambda x: (x["available_at"], x["accession"]))[-1] if history else None


def ratio(a, b):
    if not a or not b or a["value"] is None or b["value"] is None or b["value"] <= 0:
        return None
    return a["value"] / b["value"] if a["accession"] == b["accession"] else None


def paired_growth(current, previous):
    """A like-tag pair within one filing, never growth over a missing year."""
    pairs = []
    for a in current:
        for b in previous:
            if (a["accession"] == b["accession"] and a["tag"] == b["tag"]
                    and a["value"] is not None and b["value"] is not None and b["value"] > 0):
                pairs.append((a["available_at"], a["accession"], a, b))
    if not pairs:
        return None
    _, _, a, b = max(pairs, key=lambda x: x[:2])
    return {"value": a["value"] / b["value"] - 1, "accession": a["accession"],
            "tag": a["tag"], "current": a["value"], "previous": b["value"]}


def analyze(records, profiles):
    index = {}
    for r in records:
        key = (r["cik"], r["date"], r["metric"])
        if key in index:
            raise ValueError(f"Duplicate company metric: {key}")
        index[key] = r
    rows, summaries = [], []
    for p in profiles:
        cik = p["cik"]
        dates = sorted({d for c, d, _ in index if c == cik})
        if not dates:
            raise ValueError(f"No annual observations for {cik}")
        company_rows = []
        for i, d in enumerate(dates):
            evidence = {m: index.get((cik, d, m), {"history": []}) for m in METRICS}
            facts = {m: select_fact(evidence[m]["history"]) for m in METRICS}
            row = {"cik": cik, "label": p["label"], "date": d,
                   **{m: f["value"] if f else None for m, f in facts.items()},
                   "evidence": evidence, "growth": {}}
            for name, numerator in (("operating_margin", "operating_income"), ("net_margin", "net_income"),
                                    ("cash_margin", "operating_cash_flow"), ("capex_intensity", "capex")):
                row[name] = ratio(facts[numerator], facts["revenue"])
            ocf, capex = facts["operating_cash_flow"], facts["capex"]
            row["free_cash_flow"] = (ocf["value"] - capex["value"] if ocf and capex
                and ocf["value"] is not None and capex["value"] is not None
                and capex["value"] >= 0 and ocf["accession"] == capex["accession"] else None)
            if p.get("financial"):
                # Bank/insurance cash flows and revenue are not industrial metrics.
                for name in ("operating_margin", "cash_margin", "capex_intensity", "free_cash_flow"):
                    row[name] = None
            if i and 350 <= (date.fromisoformat(d) - date.fromisoformat(dates[i-1])).days <= 380:
                for m in ("revenue", "operating_cash_flow", "capex"):
                    row["growth"][m] = paired_growth(evidence[m]["history"],
                        index.get((cik, dates[i-1], m), {"history": []})["history"])
            company_rows.append(row)
        latest = company_rows[-1]
        missing = sum(r[m] is None for r in company_rows for m in METRICS)
        revisions = sum(e.get("same_tag_changed", False) for r in company_rows for e in r["evidence"].values())
        switches = sum(e.get("tags_used", 0) > 1 for r in company_rows for e in r["evidence"].values())
        summaries.append({**p, "first": dates[0], "last": dates[-1], "periods": len(dates),
                          "missing": missing, "revision_candidates": revisions, "tag_switches": switches,
                          "missing_end_years": sorted(set(range(int(dates[0][:4]),int(dates[-1][:4])+1))
                                                    - {int(d[:4]) for d in dates}),
                          "latest": {k: v for k,v in latest.items() if k != "evidence"}})
        rows.extend(company_rows)
    return rows, summaries


@register_branch("company", result_types=(ResultType.DESCRIPTIVE,))
def run(study, inputs, registry):
    inp = inputs["facts"]
    # Use the rows that survived the public input loader; never bypass its window.
    window = inp.frame.observation_at.between(study.scope["start"], study.scope["end"])
    ids = set(inp.frame.loc[window, "series_id"])
    records = [v for k,v in inp.version.series.items() if k in ids]
    meta = inp.version.series["_bundle"]
    profiles = meta["profiles"]
    if study.method.get("cik"):
        profiles = [p for p in profiles if p["cik"] == study.method["cik"]]
    if not profiles:
        raise ValueError("Requested company not in evidence bundle")
    rows, summaries = analyze(records, profiles)
    all_profiles = {p['cik']: p for p in meta['profiles']}
    for s in summaries:
        s['peer_links'] = [{k: all_profiles[c][k] for k in ('label', 'slug')} for c in s.get('peers', [])]
    missing = sum(s["missing"] for s in summaries)
    results = {"companies": summaries, "company_count": len(summaries),
               "missing": missing, "revision_candidates": sum(s["revision_candidates"] for s in summaries),
               "tag_switches": sum(s["tag_switches"] for s in summaries),
               "snapshot": meta["snapshot"], "source_partitions": meta["source_partitions"],
               "detail_fingerprint": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
    return ResearchResult(study.study_id, study.title, study.question, ResultType.DESCRIPTIVE, "company",
        study.scope, max(s["last"] for s in summaries), study.method, [input_record(inp)], results,
        {"completeness": "partial", "period_complete": False, "companies": len(summaries),
         "annual_periods": len(rows), "missing_metrics": missing},
        [{"item": "全市场排名、因果归因及历史回测", "kind": "scope", "reason": "目的性选择的 15 家样本；使用快照内最新年度申报，不是历史时点投资信号"}],
        list(study.limitations),
        {"selection": {"status": "pass", "reason": "年度合并 USD；逐项保留科目、申报、版本与缺失；派生比率要求同一申报"},
         "filing_review": {"status": "skipped", "reason": "本次未逐条人工核对全部年报；同科目改值仅为修订候选，不自动认定会计重述"}},
        {"annual": rows})
