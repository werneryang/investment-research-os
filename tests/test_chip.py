"""芯片 P3b：证据包的生成与拒绝条件，经营分析分支的单元评估、单一申报选取与核对。全部离线、虚构数据。"""

import copy
import json

import pandas as pd
import pytest
import yaml

from investment_os.connectors.sec import parse_fsds_segments
from investment_os.data import ingest
from investment_os.runs import run_study, verify_run
from investment_os.supply_chain.bundle import build_bundle, fact_fiscal_year
from investment_os.supply_chain.catalog import load_catalog
from investment_os.supply_chain.classification import import_naics

from .test_supply_chain import NAICS_ROWS, NOW, fsds_zip, mini, naics_xlsx, write_catalog  # noqa: F401

FY = {"2024": "20240131", "2025": "20250131", "2026": "20260131"}


def test_fact_fiscal_year_counts_back_from_the_filing():
    assert fact_fiscal_year(2026, pd.Timestamp("2026-01-31"), pd.Timestamp("2024-01-31")) == 2024
    assert fact_fiscal_year(2025, pd.Timestamp("2025-08-31"), pd.Timestamp("2025-08-31")) == 2025
    # 月末取整造成的错位（如 52/53 周财年）不改变财年
    assert fact_fiscal_year(2026, pd.Timestamp("2026-01-31"), pd.Timestamp("2025-02-28")) == 2025


# ---- 证据包生成 ----------------------------------------------------------------

def _ready(root, data):
    """把迷你登记的原文放到默认位置，并导入 NAICS，使核对没有未核对项。"""
    docs = root / "data" / "supply_chain" / "filings"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "a.htm").write_bytes((root / "filings" / "a.htm").read_bytes())
    src = root / "naics.xlsx"
    src.write_bytes(naics_xlsx(NAICS_ROWS))
    import_naics(root, src, clock=lambda: NOW)
    return write_catalog(root, data)


def test_bundle_pins_segment_facts_and_catalog_state(mini):
    root, data = mini
    cat = _ready(root, data)
    facts = parse_fsds_segments(fsds_zip(), {1045810}, NOW)
    cons = pd.DataFrame([{"accession": "0001-26-1", "cik": 1045810, "tag": "Revenues",
                          "period_end": pd.Timestamp("2026-01-31"), "unit": "USD", "value": 22459000000.0,
                          "available_at": pd.Timestamp("2026-02-26", tz="America/New_York")}])
    doc = build_bundle(root, cat, facts, cons, clock=lambda: NOW)
    kinds = sorted(r["kind"] for r in doc["records"])
    assert kinds == ["consolidated", "segment"]  # 地区维度不进入证据包
    seg = next(r for r in doc["records"] if r["kind"] == "segment")
    assert seg["entity"] == "seg_a" and seg["fiscal_year"] == 2026 and seg["value"] == 22459000000
    meta = doc["metadata"]
    assert meta["catalog_check"]["errors"] == [] and meta["links"]["lnk"]["status"] == "candidate"
    assert meta["claims"]["clm_rev"] == {"review_status": "candidate", "machine_check": "verified"}
    assert set(meta["catalog_files"]) == {"activities", "entities", "links", "relations", "claims", "units"}


def test_bundle_refuses_when_catalog_has_errors_or_unverified_items(mini):
    root, data = mini
    facts = parse_fsds_segments(fsds_zip(), {1045810}, NOW)
    with pytest.raises(ValueError, match="未全部通过"):  # NAICS 未导入、原文不在默认位置：有未核对项
        build_bundle(root, write_catalog(root, data), facts, pd.DataFrame())
    bad = copy.deepcopy(data)
    bad["claims"]["claims"][2]["value"] = 1
    with pytest.raises(ValueError, match="未全部通过"):
        build_bundle(root, _ready(root, bad), facts, pd.DataFrame())


# ---- 经营分析分支 ----------------------------------------------------------------

UNITS = {
    "fin": {"id": "fin", "question": "分部营收与利润？", "activity": "act_design", "entities": ["seg_x", "seg_y"],
            "metrics": ["Revenues", "OperatingIncomeLoss"], "period": {"fiscal_years": [2025, 2026]},
            "status": "unassessed"},
    "units": {"id": "units", "question": "型号出货量？", "activity": "act_design", "entities": ["co_x"],
              "metrics": ["unit_shipments"], "period": {"fiscal_years": [2026, 2026]}, "status": "unassessed"},
    "old": {"id": "old", "question": "旧分部？", "activity": "act_design", "entities": ["seg_old"],
            "metrics": ["Revenues"], "period": {"fiscal_years": [2025, 2025]}, "status": "unassessed"},
    "gross": {"id": "gross", "question": "毛利？", "activity": "act_design", "entities": ["seg_x"],
              "metrics": ["Revenues", "CostOfGoodsAndServicesSold"], "period": {"fiscal_years": [2026, 2026]},
              "status": "unassessed"},
}


def rec(acc, entity, member, tag, fy, value, available, kind="segment", period=None):
    period = period or f"{fy}-01-31"
    return {"id": f"{acc}|{tag}|{member}|{period}", "date": period, "value": value, "published_at": available[:10],
            "kind": kind, "entity": entity, "member": member, "company": "co_x" if entity else None, "cik": 1,
            "accession": acc, "tag": tag, "fiscal_year": fy, "period_end_month": period, "available_at": available}


def bundle_doc(extra=(), drop=(), link_status="candidate", units=UNITS):
    new, old = "2026-02-26T00:00:00-05:00", "2025-02-27T00:00:00-05:00"
    records = []
    for fy, (x_rev, x_oi, y_rev, y_oi) in {2025: (100e6, 40e6, 50e6, 10e6), 2026: (160e6, 70e6, 60e6, 15e6)}.items():
        records += [rec("A-26", "seg_x", "X", "Revenues", fy, x_rev, new), rec("A-26", "seg_x", "X", "OperatingIncomeLoss", fy, x_oi, new),
                    rec("A-26", "seg_y", "Y", "Revenues", fy, y_rev, new), rec("A-26", "seg_y", "Y", "OperatingIncomeLoss", fy, y_oi, new),
                    rec("A-26", None, "AllOtherSegments", "Revenues", fy, 1e6, new, kind="other_segment"),
                    rec("A-26", None, None, "Revenues", fy, x_rev + y_rev + 1e6, new, kind="consolidated")]
    records += [rec("A-26", "seg_x", "X", "CostOfGoodsAndServicesSold", 2026, 90e6, new),
                rec("A-26", "seg_x", "X", "GrossProfit", 2026, 70e6, new),
                rec("A-25", "seg_old", "OLD", "Revenues", 2025, 5e6, old)]
    records = [r for r in records if r["id"] not in drop] + list(extra)
    links = {"lnk_x": {"entity": "seg_x", "activity": "act_design", "match": "partial", "scope": "", "status": link_status},
             "lnk_y": {"entity": "seg_y", "activity": "act_design", "match": "partial", "scope": "", "status": "candidate"},
             "lnk_old": {"entity": "seg_old", "activity": "act_design", "match": "partial", "scope": "", "status": "candidate"}}
    entities = {"co_x": {"name": "X", "parent": None, "type": "company", "superseded_in": None},
                "seg_x": {"name": "X", "parent": "co_x", "type": "segment", "superseded_in": None},
                "seg_y": {"name": "Y", "parent": "co_x", "type": "segment", "superseded_in": None},
                "seg_old": {"name": "Old", "parent": "co_x", "type": "segment", "superseded_in": "A-26"}}
    return {"schema": "industry-evidence.v1", "unit": "USD", "records": records,
            "metadata": {"built_at": "2026-10-29", "catalog_version": "v1", "catalog_check": {"errors": []},
                         "links": links, "entities": entities, "units": units, "catalog_files": {},
                         "segment_fact_partitions": {}}}


STUDY = {"study_id": "chip_test", "title": "测试", "question": "?", "result_type": "descriptive",
         "branch": "chip_operations",
         "scope": {"market": "US", "currency": "USD", "start": "2024-01-01", "end": "2026-01-31",
                   "frequency": "annual", "vintage_policy": "latest"},
         "data": {"evidence": "chip_segment_evidence"}, "method": {"units": ["fin", "units", "old", "gross"]},
         "limitations": ["测试"]}


def run_doc(project, registry, store, doc, study=STUDY):
    path = project / "bundle.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ingest(registry, store, "chip_segment_evidence", {"path": str(path)}).status == "created"
    spath = project / "config" / "studies" / "chip.yaml"
    spath.write_text(yaml.safe_dump(study, allow_unicode=True), encoding="utf-8")
    m = run_study(project, spath)
    assert m["status"] != "failed", m.get("error")
    return m, json.loads((project / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))


def test_units_are_graded_and_computed_from_a_single_filing(project, registry, store):
    m, r = run_doc(project, registry, store, bundle_doc())
    units = {u["id"]: u for u in r["results"]["units"]}
    assert {k: u["grade"] for k, u in units.items()} == {"fin": "A", "units": "C", "old": "C", "gross": "A"}
    assert "没有观测" in units["units"]["reasons"][0]  # 不按收入推算出货量
    assert "已在重组后停用" in units["old"]["reasons"][0]
    assert units["fin"]["filing"] == "A-26" and units["fin"]["attribution_status"] == "candidate"
    rows = {(x["entity"], x["fiscal_year"]): x for x in r["tables"]["fin"]}
    assert rows[("seg_x", 2026)]["operating_margin"] == pytest.approx(70 / 160)
    assert rows[("seg_x", 2026)]["revenue_growth"] == pytest.approx(0.6)
    assert "revenue_growth" not in rows[("seg_x", 2025)]  # 申报中没有上一年，不跨申报补
    assert r["tables"]["gross"][0]["gross_margin"] == pytest.approx(1 - 90 / 160)
    assert r["validation"]["segment_total:fin"]["status"] == "pass"
    assert r["validation"]["gross_profit:gross"]["status"] == "pass"
    assert {u["item"] for u in r["unsupported"]} == {"研究单元 units", "研究单元 old"}
    assert any("归属为 candidate" in x for x in r["limitations"])
    assert verify_run(project, m["run_id"])["reproduced"]


def test_newer_filing_missing_a_year_is_skipped_not_spliced(project, registry, store):
    """较新的申报缺少所需财年时退到下一份完整申报，不把两份申报的数字拼起来。"""
    newer = [rec("A-27", "seg_x", "X", t, 2026, v, "2027-02-26T00:00:00-05:00")
             for t, v in (("Revenues", 999e6), ("OperatingIncomeLoss", 1e6))]
    _, r = run_doc(project, registry, store, bundle_doc(extra=newer))
    fin = next(u for u in r["results"]["units"] if u["id"] == "fin")
    assert fin["filing"] == "A-26" and fin["filings_skipped"][0].startswith("A-27")
    assert max(x["Revenues"] for x in r["tables"]["fin"]) == 160e6


def test_conflicts_and_failed_checks_block_units(project, registry, store):
    conflict = [rec("A-26", "seg_x", "X2", "Revenues", 2026, 161e6, "2026-02-26T00:00:00-05:00")]
    conflict[0]["id"] += "|dup"
    doc = bundle_doc(extra=conflict)
    _, r = run_doc(project, registry, store, doc)
    fin = next(u for u in r["results"]["units"] if u["id"] == "fin")
    assert fin["grade"] == "C" and "冲突" in fin["reasons"][0] and not r["tables"]["fin"]


def test_segment_total_and_gross_profit_mismatch_give_c(project, registry, store):
    doc = bundle_doc()
    for x in doc["records"]:
        if x["kind"] == "consolidated" and x["fiscal_year"] == 2026:
            x["value"] += 5e6
        if x["tag"] == "GrossProfit":
            x["value"] = 71e6
    _, r = run_doc(project, registry, store, doc)
    units = {u["id"]: u for u in r["results"]["units"]}
    assert units["fin"]["grade"] == "C" and "合并营收不一致" in units["fin"]["reasons"][0]
    assert units["gross"]["grade"] == "C" and any("毛利 ≠ 营收 − 销售成本" in x for x in units["gross"]["reasons"])


def test_attribution_follows_link_review_and_missing_consolidated_is_skipped(project, registry, store):
    doc = bundle_doc(drop={f"A-26|Revenues|None|{y}-01-31" for y in (2025, 2026)}, link_status="confirmed")
    _, r = run_doc(project, registry, store, doc)
    fin = next(u for u in r["results"]["units"] if u["id"] == "fin")
    assert fin["attribution_status"] == "candidate"  # seg_y 的映射仍是候选
    assert r["validation"]["segment_total:fin"]["status"] == "skipped"
    only_x = copy.deepcopy(STUDY)
    units = copy.deepcopy(UNITS)
    units["fin"]["entities"] = ["seg_x"]
    _, r = run_doc(project, registry, store, bundle_doc(link_status="confirmed", units=units), only_x)
    assert next(u for u in r["results"]["units"] if u["id"] == "fin")["attribution_status"] == "confirmed"


def test_unknown_units_and_catalog_errors_are_rejected(project, registry, store):
    path = project / "config" / "studies" / "chip.yaml"
    for doc, study, message in ((bundle_doc(), {**STUDY, "method": {"units": ["nope"]}}, "未在证据包中定义"),
                                (dict(bundle_doc(), metadata={**bundle_doc()["metadata"],
                                                              "catalog_check": {"errors": ["x"]}}), STUDY, "核对有错误")):
        bpath = project / "bundle.json"
        bpath.write_text(json.dumps(doc), encoding="utf-8")
        ingest(registry, store, "chip_segment_evidence", {"path": str(bpath)})
        path.write_text(yaml.safe_dump(study, allow_unicode=True), encoding="utf-8")
        m = run_study(project, path)
        assert m["status"] == "failed" and message in m["error"]


def test_project_study_lists_units_defined_in_the_catalog():
    from .conftest import PROJECT_ROOT
    study = yaml.safe_load((PROJECT_ROOT / "config" / "studies" / "chip_operations_p3b.yaml").read_text(encoding="utf-8"))
    assert set(study["method"]["units"]) <= set(load_catalog(PROJECT_ROOT).units)
