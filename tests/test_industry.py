import copy
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from investment_os.analytics.industry import complete_returns, stats, hac_ols, bh_adjust, quarterly_returns, lag_correlations
from investment_os.connectors.evidence import EvidenceBundleConnector
from investment_os.data.ingest import ingest
from investment_os.research.industry import aggregate_fundamentals, bundle_records, guidance_cases


def test_drawdown_includes_initial_capital_and_correct_recovery():
    s = pd.Series([-.5, 1., .2], index=pd.period_range("2020-01", periods=3, freq="M"))
    r = stats(s)
    assert r["max_drawdown"] == -.5
    assert r["peak"] == "2019-12" and r["trough"] == "2020-01" and r["recovery"] == "2020-02"
    assert r["cagr"] == pytest.approx(1.2**4-1)


def test_calendar_gaps_cannot_be_compounded_or_compressed_to_quarters():
    s=pd.Series([.1,.2],index=pd.PeriodIndex(["2020-01","2020-03"],freq="M"))
    assert complete_returns(s,"2020-01","2020-03") is None
    assert quarterly_returns(s).isna().all()
    with pytest.raises(ValueError,match="contiguous"):
        stats(s)


def test_factor_regression_known_exposure_gap_and_multiple_tests():
    idx=pd.period_range("2000-01",periods=120,freq="M")
    x=pd.DataFrame({"Mkt-RF": np.sin(np.arange(120))*.04},index=idx)
    y=.001+1.5*x["Mkt-RF"]
    fit=hac_ols(y,x)
    assert fit["coefficients"]["Mkt-RF"]["estimate"] == pytest.approx(1.5)
    assert fit["coefficients"]["alpha"]["estimate"] == pytest.approx(.001)
    assert fit["r_squared"] == pytest.approx(1.)
    assert hac_ols(y.drop(idx[20]),x)["status"] == "calendar_gap"
    assert bh_adjust([.01,.04,.03]) == pytest.approx([.03,.04,.04])


def test_lag_direction_and_missing_quarter_calendar():
    idx=pd.period_range("2000Q1",periods=60,freq="Q")
    rng=np.random.default_rng(12)
    returns=pd.Series(rng.normal(0,.02,60),index=idx)
    growth=returns.shift(1).fillna(0)
    level=(1+growth).cumprod()*100
    values=lag_correlations(returns,level,"2000Q1","2014Q4")
    assert next(x for x in values if x["lag_quarters"]==1)["correlation"] == pytest.approx(1.)
    missing=level.drop(idx[30])
    v=lag_correlations(returns,missing,"2000Q1","2014Q4")
    assert next(x for x in v if x["lag_quarters"]==0)["pairs"] == 57


def fact(cik,year,metric,value):
    return {"cik":cik,"fiscal_end":f"{year}1231","topic":"trade","metric":metric,
            "value":value,"first_value":value}


def test_margins_and_growth_match_issuers_and_keep_missing_eligible_filers():
    f=[fact(1,2024,"revenue",100),fact(1,2025,"revenue",110),fact(1,2025,"net_income",11),
       fact(2,2025,"revenue",1000)]
    members=[{"cik":str(c),"period":f"{y}1231","topic":"trade"} for c,y in [(1,2024),(1,2025),(2,2025),(3,2025)]]
    rows,_=aggregate_fundamentals(f,2025,2025,membership=members)
    r=rows[0]
    assert r["companies"]==3 and r["entrants"]==2 and r["continuing"]==1
    assert r["metrics"]["revenue"]["matched_growth"] == pytest.approx(.1)
    assert r["metrics"]["revenue"]["missing"]==1
    assert r["ratios"]["net_margin"]["value"] == pytest.approx(.1) # not 11/1110
    assert r["ratios"]["net_margin"]["count"]==1


def test_new_evidence_bundle_does_not_resurrect_deleted_observations(registry,store,tmp_path):
    path=tmp_path/"evidence.json"
    doc={"schema":"industry-evidence.v1","unit":"USD","records":[{"id":"a","date":"2024-01-01","value":1},{"id":"b","date":"2024-01-01","value":2}]}
    path.write_text(json.dumps(doc))
    assert ingest(registry,store,"industry_sec_facts",{"path":str(path)},EvidenceBundleConnector()).status=="created"
    _, original_version = store.load("industry_sec_facts")
    doc["records"]=doc["records"][:1];path.write_text(json.dumps(doc))
    assert ingest(registry,store,"industry_sec_facts",{"path":str(path)},EvidenceBundleConnector()).status=="created"
    frame,version=store.load("industry_sec_facts")
    assert len(frame)==1  # full snapshot; old versions remain separately addressable
    original, _ = store.load("industry_sec_facts", original_version.version_id)
    assert len(original)==2
    assert [r["id"] for r in bundle_records(SimpleNamespace(frame=frame,version=version))]==["a"]
    doc["records"]*=2;path.write_text(json.dumps(doc))
    assert ingest(registry,store,"industry_sec_facts",{"path":str(path)},EvidenceBundleConnector()).status=="failed"


def test_guidance_rejects_lookahead_target_or_basis_mismatch():
    r={"forecast_date":"2024-01-01","actual_date":"2024-04-01","forecast_target":"2024Q1","actual_target":"2024Q1",
       "forecast_basis":"GAAP","actual_basis":"GAAP","low":90.,"high":110.,"value":115.}
    assert guidance_cases([r])[0]["vs_midpoint"]==pytest.approx(.15)
    for key,value in (("forecast_date","2024-04-02"),("actual_target","2024Q2"),("actual_basis","non-GAAP")):
        bad=copy.deepcopy(r);bad[key]=value
        with pytest.raises(ValueError): guidance_cases([bad])


def test_filing_selection_uses_alias_order_cutoff_and_preserves_first_value():
    choose = runpy.run_path(str(Path(__file__).resolve().parents[1]/"scripts/build_industry_fundamentals.py"))["choose_facts"]
    rows=[]
    for accession,filed,value,tag in (("a","20250120","100","Revenues"),("a","20250120","90","SalesRevenueNet"),("b","20250220","110","Revenues")):
        rows.append(dict(adsh=accession,cik="1",period="20241231",filed=filed,accepted=filed+"120000",value=value,tag=tag,qtrs="4",topic="trade",sic="5300",name="Test",form="10-K",source_archive="test.zip",source_sha256="a"*64))
    f=pd.DataFrame(rows);metrics={"revenue":{"period":"duration","tags":["Revenues","SalesRevenueNet"]}}
    initial,_=choose(f,metrics,"2025-01-31")
    revised,_=choose(f,metrics,"2025-03-01")
    assert initial[0]["value"]==100
    assert revised[0]["value"]==110 and revised[0]["first_value"]==100
    # A conflicting duplicate is excluded, not silently resolved by row order.
    bad=f.copy(); extra=f.iloc[2].copy();extra["value"]="999"
    selected,conflicts=choose(pd.concat([bad,pd.DataFrame([extra])]),metrics,"2025-03-01")
    assert conflicts==2 and selected[0]["value"]==100
