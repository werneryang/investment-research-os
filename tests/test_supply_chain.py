"""产业链 P0：NAICS 分类导入、FSDS 分部事实、产业链登记的结构与证据核对。全部离线。"""

import copy
import hashlib
import io
import shutil
import zipfile
from datetime import datetime, timezone

import openpyxl
import pandas as pd
import pytest
import yaml

from investment_os.connectors.base import FetchError
from investment_os.connectors.sec import parse_fsds_segments, segment_axes
from investment_os.data.fundamentals import EdgarStore, extract_segments
from investment_os.supply_chain.catalog import CatalogError, check, load_catalog, normalize_text
from investment_os.supply_chain.classification import ClassificationStore, import_naics, parse_naics_structure

from .conftest import PROJECT_ROOT

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


# ---- L1：NAICS 结构表 -------------------------------------------------------

def naics_xlsx(rows, header=("Change Indicator", "2022 NAICS Code", "2022 NAICS Title")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["2022 NAICS Structure", None, None])
    ws.append(["T = trilateral agreement", None, None])
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


NAICS_ROWS = [(None, "31-33", "ManufacturingT"), (None, "334", "Computer and Electronic Product ManufacturingT"),
              (None, "3344", "Semiconductor and Other Electronic Component ManufacturingT"),
              (None, "33441", "Semiconductor and Other Electronic Component ManufacturingT "),
              (None, "334413", "Semiconductor and Related Device Manufacturing "),
              ("**", "54", "Professional, Scientific, and Technical ServicesT")]


def test_naics_parse_keeps_codes_levels_and_trilateral_flag():
    df = parse_naics_structure(naics_xlsx(NAICS_ROWS))
    by = df.set_index("code")
    assert by.loc["31-33", "level"] == 2 and by.loc["334", "parent"] == "31-33"  # 区间部门
    assert by.loc["334413", "parent"] == "33441" and by.loc["334413", "level"] == 6
    assert by.loc["3344", "trilateral"] and by.loc["3344", "title"].endswith("Manufacturing")
    assert not by.loc["334413", "trilateral"] and by.loc["334413", "title"] == "Semiconductor and Related Device Manufacturing"
    assert by.loc["54", "change_indicator"] == "**"


@pytest.mark.parametrize("content, message", [
    (b"<html>error</html>", "不是 .xlsx"),
    (naics_xlsx(NAICS_ROWS, header=("Indicator", "Code", "Title")), "表头"),
    (naics_xlsx([(None, "31-33", "Manufacturing"), (None, "334413", "Semis")]), "上级"),
    (naics_xlsx([(None, "31-33", "Manufacturing"), (None, "31-33", "Again")]), "重复"),
    (naics_xlsx([(None, "3X4", "Bad")]), "无法识别"),
])
def test_naics_parse_rejects_bad_files(content, message):
    with pytest.raises(FetchError, match=message):
        parse_naics_structure(content)


def test_naics_import_saves_raw_table_and_catalog(tmp_path):
    src = tmp_path / "naics.xlsx"
    src.write_bytes(naics_xlsx(NAICS_ROWS))
    entry = import_naics(tmp_path, src, clock=lambda: NOW)
    store = ClassificationStore(tmp_path)
    assert entry["rows"] == 6 and entry["origin"] == "local_file" and store.entries()[-1]["sha256"] == entry["sha256"]
    assert (store.base / entry["raw"]).read_bytes() == src.read_bytes()
    assert set(store.load()["code"]) == {r[1] for r in NAICS_ROWS}


# ---- L3：FSDS 分部事实 -------------------------------------------------------

SUB = ("adsh\tcik\tname\tsic\tfye\tform\tperiod\tfy\tfp\tfiled\taccepted\tprevrpt\n"
       "0001-26-1\t1045810\tNVIDIA CORP\t3674\t0131\t10-K\t20260131\t2026\tFY\t20260225\t2026-02-25 16:42:00.0\t0\n"
       "0001-26-2\t1045810\tNVIDIA CORP\t3674\t0131\t8-K\t20260131\t2026\tFY\t20260225\t2026-02-25 16:42:00.0\t0\n"
       "0002-26-1\t999\tOTHER\t3674\t1231\t10-K\t20251231\t2025\tFY\t20260220\t2026-02-20 10:00:00.0\t0\n")
NUM_HEAD = "adsh\ttag\tversion\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue\tfootnote\n"
NUM = NUM_HEAD + "".join("\t".join(r) + "\n" for r in [
    ("0001-26-1", "Revenues", "us-gaap/2025", "20260131", "4", "USD", "", "", "215938000000", ""),  # 合并口径
    ("0001-26-1", "Revenues", "us-gaap/2025", "20260131", "4", "USD",
     "BusinessSegments=GraphicsSegment;ConsolidationItems=OperatingSegments;", "", "22459000000", ""),
    ("0001-26-1", "Revenues", "us-gaap/2025", "20260131", "4", "USD", "Geographical=TW;", "", "1", ""),
    ("0001-26-1", "StockholdersEquity", "us-gaap/2025", "20260131", "0", "USD",
     "EquityComponents=RetainedEarnings;", "", "5", ""),  # 维度不在范围内
    ("0001-26-1", "Revenues", "us-gaap/2025", "20260131", "4", "USD", "Geographical=US;", "Sub", "2", ""),  # 共同申报人
    ("0001-26-2", "Revenues", "us-gaap/2025", "20260131", "4", "USD", "Geographical=US;", "", "3", ""),  # 非定期报告
    ("0002-26-1", "Revenues", "us-gaap/2025", "20251231", "4", "USD", "Geographical=US;", "", "4", ""),  # 未登记公司
])


def fsds_zip(sub=SUB, num=NUM):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sub.txt", sub)
        z.writestr("num.txt", num)
    return buf.getvalue()


def test_segment_axes_parses_fsds_text():
    assert segment_axes("BusinessSegments=GraphicsSegment;ConsolidationItems=OperatingSegments;") == {
        "BusinessSegments": "GraphicsSegment", "ConsolidationItems": "OperatingSegments"}
    assert segment_axes("") == {}
    with pytest.raises(FetchError):
        segment_axes("BusinessSegments;")


def test_parse_segments_keeps_only_business_dimensions_of_registered_periodic_filings():
    df = parse_fsds_segments(fsds_zip(), {1045810}, NOW)
    assert sorted(df["segments"]) == ["BusinessSegments=GraphicsSegment;ConsolidationItems=OperatingSegments;",
                                      "Geographical=TW;"]
    row = df[df["segments"].str.startswith("Business")].iloc[0]
    assert row.value == 22459000000 and row.form == "10-K" and row.fiscal_year == 2026 and row["name"] == "NVIDIA CORP"
    assert row.accepted_at == pd.Timestamp("2026-02-25 16:42", tz="America/New_York")
    assert row.available_at == pd.Timestamp("2026-02-26", tz="America/New_York")


def test_extract_segments_reuses_saved_raw_file_and_is_idempotent(tmp_path):
    store = EdgarStore(tmp_path)
    raw = store.save_raw("fsds", "2026q1", fsds_zip(), "zip", "https://example.invalid/2026q1.zip", NOW)
    store.write_partition("facts", "fsds", "2026q1", pd.DataFrame(columns=store_columns("facts")),
                          {"raw": raw, "companies": "x"}, NOW)
    first = extract_segments(tmp_path, {1045810}, clock=lambda: NOW)
    assert first == [{"quarter": "2026q1", "action": "created", "rows": 2}]
    assert extract_segments(tmp_path, {1045810}, clock=lambda: NOW)[0]["action"] == "unchanged"
    assert len(store.query("segment_facts")) == 2
    assert extract_segments(tmp_path, {1045810}, ["2025q4"])[0]["action"] == "missing_raw"


def store_columns(table):
    from investment_os.data.fundamentals import TABLES
    return TABLES[table]


# ---- L2–L4：产业链登记 -------------------------------------------------------

def test_project_catalog_loads_and_has_no_errors_offline():
    """仓库中的登记结构完整；没有本地原文与分部事实时只记为未核对，不报错也不冒充通过。"""
    cat = load_catalog(PROJECT_ROOT)
    rep = check(cat, naics=None, segment_facts=None, documents_dir=PROJECT_ROOT / "no-such-dir")
    assert rep.errors == []
    assert rep.warnings and not rep.verified
    assert {1045810, 723125} == cat.ciks()
    assert rep.inventory["counts"]["activities"] == 8


DOC_TEXT = ("<p>We utilize foundries, such as <b>Foundry Co</b>, to produce our wafers.</p>"
            "<p>We face competition from “Rival”.</p>")


@pytest.fixture
def mini(tmp_path):
    """最小登记：一份原文、一个 XBRL 事实、一条映射、有向与无向关系各一。"""
    docs = tmp_path / "filings"
    docs.mkdir()
    (docs / "a.htm").write_text(DOC_TEXT, encoding="utf-8")
    sha = hashlib.sha256(DOC_TEXT.encode()).hexdigest()
    data = {
        "activities": {"activities": [{"id": "act_design", "name": "设计", "definition": "设计芯片",
                                       "naics": [{"code": "334413", "match_type": "ambiguous", "review_status": "candidate"}]},
                                      {"id": "act_foundry", "name": "代工", "definition": "代工"}]},
        "entities": {"entities": [{"id": "co_a", "type": "company", "name": "A", "cik": 1},
                                  {"id": "co_f", "type": "company", "name": "Foundry Co"},
                                  {"id": "co_r", "type": "company", "name": "Rival"},
                                  {"id": "seg_a", "type": "segment", "name": "Seg", "parent": "co_a",
                                   "xbrl_members": [{"member": "GraphicsSegment", "seen_in": "0001-26-1"}]}]},
        "claims": {"documents": [{"id": "doc_a", "accession": "0001-26-1", "url": "https://example.invalid/a.htm",
                                  "file": "a.htm", "sha256": sha, "accepted_at": "2026-02-25T16:42:00-05:00"}],
                   "claims": [{"id": "clm_foundry", "type": "filing_text", "document": "doc_a", "locator": "Item 1",
                               "excerpt": "We utilize foundries, such as Foundry Co, to produce our wafers.",
                               "origin_type": "observed", "review_status": "confirmed"},
                              {"id": "clm_rival", "type": "filing_text", "document": "doc_a", "locator": "Item 1",
                               "excerpt": 'We face competition from "Rival".', "origin_type": "observed",
                               "review_status": "confirmed"},
                              {"id": "clm_rev", "type": "xbrl_segment", "accession": "0001-26-1", "tag": "Revenues",
                               "segments": "BusinessSegments=GraphicsSegment;ConsolidationItems=OperatingSegments;",
                               "period_end": "2026-01-31", "duration_quarters": 4, "value": 22459000000,
                               "origin_type": "observed", "review_status": "confirmed"}]},
        "links": {"links": [{"id": "lnk", "entity": "seg_a", "activity": "act_design", "match": "partial",
                             "claims": ["clm_rev"]}]},
        "relations": {"relations": [{"id": "rel", "type": "foundry", "provider": "co_f", "recipient": "co_a",
                                     "activity": "act_foundry", "claims": ["clm_foundry"]},
                                    {"id": "cmp", "type": "competition", "parties": ["co_a", "co_r"],
                                     "market": "芯片", "activity": "act_design", "claims": ["clm_rival"]}]},
        "units": {"units": [{"id": "u", "question": "?", "activity": "act_design", "entities": ["seg_a"],
                             "status": "unassessed"}]},
    }
    return tmp_path, data


def write_catalog(root, data):
    base = root / "config" / "supply_chain"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    for name, doc in data.items():
        (base / f"{name}.yaml").write_text(yaml.safe_dump({"schema_version": "supply_chain.v1", **doc},
                                                          allow_unicode=True), encoding="utf-8")
    return load_catalog(root)


NAICS = pd.DataFrame({"code": ["31-33", "334413"]})


def run_check(root, data):
    facts = parse_fsds_segments(fsds_zip(), {1045810}, NOW)
    return check(write_catalog(root, data), NAICS, facts, documents_dir=root / "filings")


def test_mini_catalog_verifies_excerpts_facts_members_and_codes(mini):
    root, data = mini
    rep = run_check(root, data)
    assert rep.errors == [] and rep.warnings == []
    assert rep.verified == {"naics_code": 1, "xbrl_member": 1, "document": 1, "excerpt": 2, "xbrl_fact": 1}
    assert rep.claim_available_at["clm_foundry"].startswith("2026-02-26T00:00:00")


def _broken(data, path, value):
    d = copy.deepcopy(data)
    target = d
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return d


@pytest.mark.parametrize("path, value, message", [
    (("relations", "relations", 0, "recipient"), "co_f", "不同的 provider 与 recipient"),
    (("relations", "relations", 1, "parties"), ["co_r", "co_a"], "按 ID 排序"),
    (("relations", "relations", 1, "market"), None, "必须写明 market"),
    (("relations", "relations", 0, "activity"), None, "activity_gap"),
    (("claims", "claims", 0, "review_status"), "rejected", "被否定"),
    (("claims", "claims", 0, "review_status"), "candidate", "没有任何 confirmed"),
    (("claims", "claims", 0, "excerpt"), "We utilize foundries, such as Another Co.", "没有逐字出现"),
    (("claims", "claims", 2, "value"), 1, "数值"),
    (("claims", "claims", 2, "segments"), "BusinessSegments=Gaming;", "找不到对应的行"),
    (("claims", "documents", 0, "sha256"), "0" * 64, "SHA256"),
    (("activities", "activities", 0, "naics"), [{"code": "999999", "match_type": "exact", "review_status": "candidate"}],
     "不在 NAICS 2022 表中"),
    (("entities", "entities", 3, "xbrl_members"), [{"member": "Gaming", "seen_in": "0001-26-1"}], "XBRL 成员"),
])
def test_check_reports_each_rule_violation(mini, path, value, message):
    root, data = mini
    rep = run_check(root, _broken(data, path, value))
    assert any(message in e for e in rep.errors), rep.errors


def test_duplicate_relations_and_unknown_keys_are_rejected(mini):
    root, data = mini
    dup = copy.deepcopy(data)
    dup["relations"]["relations"].append({**data["relations"]["relations"][0], "id": "rel2"})
    assert any("重复记录" in e for e in run_check(root, dup).errors)
    # YAML 流式写法里未加引号的逗号会把值拆成新键：读取时直接报错
    bad = _broken(data, ("entities", "entities", 0, "Inc."), None)
    with pytest.raises(CatalogError, match="未知字段"):
        write_catalog(root, bad)
    with pytest.raises(CatalogError, match="ID 重复"):
        write_catalog(root, _broken(data, ("entities", "entities", 1, "id"), "co_a"))


def test_normalize_text_matches_curly_quotes_and_tags():
    assert normalize_text("<p>A “B”\n  C</p>") == 'A "B" C'
    assert normalize_text("such as <b>Foundry Co</b>, to<br>next") == "such as Foundry Co, to next"
