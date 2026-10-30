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
    # FSDS 只有月末口径；精确期末不推定
    assert row.filing_period_month_end == pd.Timestamp("2026-01-31") and pd.isna(row.document_period_end)
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


def test_empty_segment_partitions_are_typed_and_readable(tmp_path):
    """没有分部事实的季度也写出带类型的空分区，与有数据的分区一起读取。"""
    store = EdgarStore(tmp_path)
    for q, ciks in (("2026q1", SUB), ("2009q1", SUB.splitlines()[0] + "\n")):
        raw = store.save_raw("fsds", q, fsds_zip(sub=ciks), "zip", f"https://example.invalid/{q}.zip", NOW)
        store.write_partition("facts", "fsds", q, pd.DataFrame(columns=store_columns("facts")),
                              {"raw": raw, "companies": "x"}, NOW)
    res = {r["quarter"]: r["rows"] for r in extract_segments(tmp_path, {1045810}, clock=lambda: NOW)}
    assert res == {"2009q1": 0, "2026q1": 2}
    assert len(store.query("segment_facts")) == 2


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


DOC_TEXT = ("<p>For the fiscal year ended January 25, 2026</p>"
            "<p>We utilize foundries, such as <b>Foundry Co</b>, to produce our wafers.</p>"
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
        "entities": {"entities": [{"id": "co_a", "type": "company", "name": "A", "cik": 1045810},
                                  {"id": "co_b", "type": "company", "name": "B", "cik": 2},
                                  {"id": "co_f", "type": "company", "name": "Foundry Co"},
                                  {"id": "co_r", "type": "company", "name": "Rival"},
                                  {"id": "seg_a", "type": "segment", "name": "Seg", "parent": "co_a",
                                   "xbrl_members": [{"member": "GraphicsSegment", "seen_in": "0001-26-1"}]}]},
        "claims": {"documents": [{"id": "doc_a", "accession": "0001-26-1", "url": "https://example.invalid/a.htm",
                                  "file": "a.htm", "sha256": sha, "accepted_at": "2026-02-25T16:42:00-05:00",
                                  "entity": "co_a", "document_period_end": "2026-01-25"}],
                   "claims": [{"id": "clm_foundry", "type": "filing_text", "document": "doc_a", "locator": "Item 1",
                               "excerpt": "We utilize foundries, such as Foundry Co, to produce our wafers.",
                               "origin_type": "observed", "review_status": "candidate"},
                              {"id": "clm_rival", "type": "filing_text", "document": "doc_a", "locator": "Item 1",
                               "excerpt": 'We face competition from "Rival".', "origin_type": "observed",
                               "review_status": "candidate"},
                              {"id": "clm_rev", "type": "xbrl_segment", "accession": "0001-26-1", "tag": "Revenues",
                               "segments": "BusinessSegments=GraphicsSegment;ConsolidationItems=OperatingSegments;",
                               "period_end": "2026-01-31", "duration_quarters": 4, "value": 22459000000, "unit": "USD",
                               "origin_type": "observed", "review_status": "candidate"}]},
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
    assert rep.verified == {"naics_code": 1, "xbrl_member": 1, "document": 1, "document_period_end": 1,
                            "excerpt": 2, "xbrl_fact": 1}
    assert set(rep.claim_checks.values()) == {"verified"}
    assert set(rep.statuses.values()) == {"candidate"}  # 机器核对通过不等于人工确认
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
    (("relations", "relations", 0, "claims"), ["clm_missing"], "未登记的证据"),
    (("claims", "claims", 0, "excerpt"), "We utilize foundries, such as Another Co.", "没有逐字出现"),
    (("claims", "claims", 2, "value"), 1, "数值"),
    (("claims", "claims", 2, "segments"), "BusinessSegments=Gaming;", "找不到对应的行"),
    (("claims", "documents", 0, "sha256"), "0" * 64, "SHA256"),
    (("activities", "activities", 0, "naics"), [{"code": "999999", "match_type": "exact", "review_status": "candidate"}],
     "不在 NAICS 2022 表中"),
    (("entities", "entities", 4, "xbrl_members"), [{"member": "Gaming", "seen_in": "0001-26-1"}], "XBRL 成员"),
    # 分部改挂到另一家公司：别名所在申报属于原公司
    (("entities", "entities", 4, "parent"), "co_b", "不是上级公司"),
    # 产品维度的成员不能当作业务分部别名
    (("entities", "entities", 4, "xbrl_members"), [{"member": "TW", "seen_in": "0001-26-1"}], "业务分部维度"),
    (("claims", "claims", 2, "unit"), "shares", "单位 shares"),
    (("claims", "documents", 0, "document_period_end"), "2026-01-24", "精确期末未得到原文支持"),
    (("claims", "documents", 0, "entity"), "co_b", "不是登记的 co_b"),
    # 竞争关系换成与原文无关的两家公司：证据不属于相关公司
    (("relations", "relations", 1, "parties"), ["co_b", "co_r"], "不属于相关公司"),
])
def test_check_reports_each_rule_violation(mini, path, value, message):
    root, data = mini
    rep = run_check(root, _broken(data, path, value))
    assert any(message in e for e in rep.errors), rep.errors


def test_missing_value_is_unverified_not_passed(mini):
    root, data = mini
    rep = run_check(root, _broken(data, ("claims", "claims", 2, "value"), None))
    assert rep.errors == [] and rep.claim_checks["clm_rev"] == "unverified"
    assert "xbrl_fact" not in rep.verified and any("缺少数值或单位" in w for w in rep.warnings)


def test_link_alias_must_match_segment(mini):
    root, data = mini
    d = _broken(data, ("claims", "claims", 2, "segments"), "Geographical=TW;")
    assert any("不是 seg_a 的登记别名" in e for e in run_check(root, d).errors)


def test_human_review_is_separate_from_machine_checks(mini):
    root, data = mini
    with pytest.raises(CatalogError, match="人工复核记录"):
        write_catalog(root, _broken(data, ("claims", "claims", 0, "review_status"), "confirmed"))
    reviewed = _broken(data, ("claims", "claims", 0, "review_status"), "confirmed")
    reviewed["claims"]["claims"][0].update(reviewer="analyst", reviewed_at="2026-10-30")
    rep = run_check(root, reviewed)
    assert rep.statuses["rel"] == "candidate"  # 证据确认不等于关系确认：关系有自己的复核记录
    both = _review(reviewed, "relations", 0)
    rep = run_check(root, both)
    assert rep.errors == [] and rep.statuses["rel"] == "confirmed" and rep.statuses["cmp"] == "candidate"
    rejected = copy.deepcopy(reviewed)
    rejected["claims"]["claims"][0]["review_status"] = "rejected"
    errors = run_check(root, rejected).errors
    assert any("被否定" in e for e in errors) and any("没有可用的证据" in e for e in errors)


def _confirmed(data, idx):
    return _review(data, "claims", idx)


def _review(data, kind, idx, status="confirmed"):
    d = copy.deepcopy(data)
    d[kind][kind][idx].update(review_status=status, reviewer="analyst", reviewed_at="2026-10-30")
    return d


@pytest.mark.parametrize("change, messages", [
    # 另一家公司的已确认 XBRL 证据挂到本公司分部：归属与别名都不符
    (lambda d: d["claims"]["claims"][2].update(accession="0002-26-1", segments="Geographical=US;",
                                               period_end="2025-12-31", value=4),
     ["不属于相关公司", "不是 seg_a 的登记别名"]),
    # 同一公司另一分部的已确认证据：别名不符
    (lambda d: d["claims"]["claims"][2].update(segments="Geographical=TW;", value=1), ["不是 seg_a 的登记别名"]),
])
def test_failed_ownership_or_alias_never_yields_confirmed(mini, change, messages):
    """检查报错时，相关映射不能显示为 confirmed：不适用的证据不计入，对象自身有错误即为 invalid。"""
    root, data = mini
    d = _confirmed(data, 2)
    change(d)
    rep = check(write_catalog(root, d), NAICS, parse_fsds_segments(fsds_zip(), {1045810, 999}, NOW),
                documents_dir=root / "filings")
    for m in messages:
        assert any(m in e and "lnk" in e for e in rep.errors), (m, rep.errors)
    assert rep.claim_checks["clm_rev"] == "verified"  # 证据本身数值正确，问题在于挂错了对象
    assert rep.statuses["lnk"] == "invalid"


def test_confirmed_requires_an_applicable_verified_claim(mini):
    root, data = mini
    rep = run_check(root, _review(_confirmed(data, 2), "links", 0))
    assert rep.errors == [] and rep.statuses["lnk"] == "confirmed"
    # 证据人工确认但机器核对失败：报错，映射为 invalid
    bad = _review(_confirmed(data, 2), "links", 0)
    bad["claims"]["claims"][2]["value"] = 1
    rep = run_check(root, bad)
    assert rep.claim_checks["clm_rev"] == "failed" and rep.statuses["lnk"] == "invalid"


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


def test_confirming_a_figure_does_not_confirm_the_mapping(mini):
    """只确认营收数值、业务定义证据仍为候选时，映射不能变为 confirmed；映射须有自己的人工复核，且证据全部确认。"""
    root, data = mini
    d = copy.deepcopy(data)
    d["links"]["links"][0]["claims"] = ["clm_foundry", "clm_rev"]  # 业务性质（摘录）+ 分部营收（数值）
    numbers_only = _confirmed(d, 2)
    rep = run_check(root, numbers_only)
    assert rep.errors == [] and rep.statuses["lnk"] == "candidate"
    with pytest.raises(CatalogError, match="人工复核记录"):
        write_catalog(root, _broken(numbers_only, ("links", "links", 0, "review_status"), "confirmed"))
    # 映射已人工确认但业务定义证据未确认：报错，不让确认越过证据
    rep = run_check(root, _review(numbers_only, "links", 0))
    assert rep.statuses["lnk"] == "invalid" and any("clm_foundry 未经人工确认" in e for e in rep.errors)
    rep = run_check(root, _review(_confirmed(numbers_only, 0), "links", 0))
    assert rep.errors == [] and rep.statuses["lnk"] == "confirmed"
    rep = run_check(root, _review(d, "links", 0, "rejected"))
    assert rep.errors == [] and rep.statuses["lnk"] == "rejected"


def test_a_failed_claim_among_several_makes_the_item_invalid(mini):
    """多条证据中有一条机器核对失败时，其余证据全部确认也不能让映射显示为 confirmed。"""
    root, data = mini
    d = copy.deepcopy(data)
    d["links"]["links"][0]["claims"] = ["clm_foundry", "clm_rev"]
    d = _review(_confirmed(_confirmed(d, 0), 2), "links", 0)
    assert run_check(root, d).statuses["lnk"] == "confirmed"
    d["claims"]["claims"][0]["excerpt"] = "This sentence is not in the filing."
    rep = run_check(root, d)
    assert rep.claim_checks["clm_foundry"] == "failed" and rep.claim_checks["clm_rev"] == "verified"
    assert rep.statuses["lnk"] == "invalid" and any("lnk 引用的证据 clm_foundry 机器核对失败" in e for e in rep.errors)
    assert rep.statuses["rel"] == "invalid"  # 同一证据支撑的关系同样无效
