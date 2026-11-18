"""季度财报登记、证据包与季度财报研究（docs/study-earnings.md）。全部离线，使用合成原文。"""

import copy
import hashlib
import json
import re

import pytest
import yaml

from investment_os import earnings as er
from investment_os.data import DataStore, ingest
from investment_os.registry import Registry
from investment_os.runs import run_study
from tests.conftest import PROJECT_ROOT

SHIPPED = yaml.safe_load((PROJECT_ROOT / "config/earnings/googl_2026q3.yaml").read_text(encoding="utf-8"))

# 满足全部会计恒等式的基数；各期按整数倍缩放（恒等式对缩放不变）
BASE = {"Search": 100, "YouTube_ads": 20, "Network": 10, "subscriptions_platforms_devices": 30, "Services_revenue": 160,
        "Cloud_revenue": 50, "OtherBets_revenue": 5, "hedging": 1, "revenue": 216, "cost_of_revenues": 80, "R_and_D": 40,
        "sales_marketing": 15, "G_and_A": 10, "op_income": 71, "Services_op": 60, "Cloud_op": 20, "OtherBets_op": -4,
        "Alphabet_level_op": -5, "other_income": 9, "EBT": 80, "income_tax": 12, "consolidated_NI": 68,
        "preferred_dividends": 3, "common_NI": 65, "equity_security_gain_loss": 7}
SCALE = {"q3_2025": 13, "q1_2026": 17, "q2_2026": 19, "q3_2026": 23, "nine_months_2025": 31, "fy_2025": 43}
END = {"q3_2025": "2025-09-30", "q1_2026": "2026-03-31", "q2_2026": "2026-06-30", "q3_2026": "2026-09-30",
       "nine_months_2025": "2025-09-30", "fy_2025": "2025-12-31"}
CASH = {"q3_2025": (4100, 2300), "q4_2025": (4300, 2500), "q1_2026": (4500, 3500), "q2_2026": (3900, 4400),
        "q3_2026": (4200, 5100), "nine_months_2026": (12600, 13000), "ttm_2026q3": (16900, 15500)}
CASH_END = {"q3_2025": "2025-09-30", "q4_2025": "2025-12-31", "q1_2026": "2026-03-31", "q2_2026": "2026-06-30",
            "q3_2026": "2026-09-30", "nine_months_2026": "2026-09-30", "ttm_2026q3": "2026-09-30"}
BAL = {"2026-09-30": (5000, 6000, 7000, 90000, 40000, 12000), "2026-06-30": (4900, 5800, 6900, 80000, 39000, 11000),
       "2025-12-31": (3000, 4000, 5000, 60000, 38000, 9000), "2025-09-30": (2900, 3900, 4900, 59000, 37000, 8000)}
EXCERPTS = {"guide_a": "we expect capital expenditures of approximately $70 billion in 2025",
            "guide_b": "we now expect 2025 capital expenditures to be in a range of $90 billion to $95 billion",
            "guide_c": "In 2026 we expect to significantly increase our investment",
            "note_a": "the fine was paid in July 2026", "rpo": "we expect to recognize just over 55 % of the revenue backlog"}


def fmt(n):
    return f"{abs(n):,}"


def numbers():
    nums = set()
    for k in SCALE:
        nums.update(abs(v * SCALE[k]) for v in BASE.values())
    for a, b in CASH.values():
        nums.update((a, b))
    for row in BAL.values():
        nums.update(row)
    nums.update({567, 561, 4968, 5000, 5100, 900, 1400, 9200})
    return nums


def filing():
    body = " ".join(f"<td>{fmt(n)}</td>" for n in sorted(numbers() - {0})) + " <td>519.5</td><td>513.9</td><td>$ 2.12</td><td>2.87</td>"
    text = " ".join(f"<p>{v}</p>" for v in EXCERPTS.values())
    return f"<html><body><table><tr>{body}</tr></table>{text}</body></html>".encode()


def registration():
    raw = filing()
    income = {pid: {"label": pid, "start": "2025-01-01", "end": END[pid], "document": "doc",
                    "values": {k: v * SCALE[pid] for k, v in BASE.items()}} for pid in SCALE}
    cash = {pid: {"end": CASH_END[pid], "document": "doc", "cfo": a, "cash_ppe": b} for pid, (a, b) in CASH.items()}
    return {
        "schema_version": "earnings.v1", "earnings_id": "ex_2026q3", "entity": "co_example",
        "company": {"zh": "示例", "en": "Example"}, "cik": 1, "tickers": ["EXM"],
        "latest_period": {"label": "2026 Q3", "start": "2026-07-01", "end": "2026-09-30"}, "as_of": "2026-11-16",
        "unit": "USD million", "release": {"ir_date": "2026-10-28", "ir_url": "https://example.test/ir", "form_10q_filed": "2026-10-29"},
        "related_studies": [{"study": "company_example", "label": {"zh": "年度", "en": "Annual"}}],
        "documents": [{"id": "doc", "form": "10-Q", "period_end": "2026-09-30", "accession": "0000000000-26-000001",
                       "accepted_at": "2026-10-29T00:29:06Z", "url": "https://example.test/10q.htm", "file": "10q.htm",
                       "sha256": hashlib.sha256(raw).hexdigest()}],
        "profile": copy.deepcopy(SHIPPED["profile"]), "income": income, "cash_flow": cash,
        "issuer_fcf": {"q3_2026": 4200 - 5100, "ttm_2026q3": 16900 - 15500, "document": "doc"},
        "balance": {d: {"document": "doc", "values": dict(zip(er.BALANCE_METRICS, row))} for d, row in BAL.items()},
        "rpo": {"unit": "USD billion", "points": [
            {"date": "2026-09-30", "total": 567.0, "cloud": 561.0, "document": "doc"},
            {"date": "2026-06-30", "total": 519.5, "cloud": 513.9, "document": "doc"}],
            "recognition": {"share_text": "just over 55", "months": 24, "document": "doc", "excerpt": EXCERPTS["rpo"],
                            "statement": {"zh": "约 55%", "en": "about 55%"}},
            "scope_change": {"zh": "口径扩大", "en": "Definition widened"}},
        "fx": {"document": "doc", "reported_revenue": 4968, "yoy_constant_currency_revenue": 5000, "yoy_constant_currency_growth_pct_rounded": 25,
               "qoq_constant_currency_revenue": 5100, "qoq_constant_currency_growth_pct_rounded": 7},
        "per_share": {"document": "doc", "diluted_eps_q3_2026": 2.12, "diluted_eps_q3_2025": 2.87},
        "annual_cash_ppe": {"year": 2025, "value": 9200, "document": "doc"},
        "guidance": [
            {"id": "g_a", "announced": "2025-02-04", "target_year": 2025, "kind": "point", "point_usd_bn": 7, "document": "doc",
             "excerpt": EXCERPTS["guide_a"], "statement": {"zh": "约 70", "en": "about 70"}},
            {"id": "g_b", "announced": "2025-10-29", "target_year": 2025, "kind": "range", "low_usd_bn": 9, "high_usd_bn": 9.5, "document": "doc",
             "excerpt": EXCERPTS["guide_b"], "statement": {"zh": "90 至 95", "en": "90 to 95"}},
            {"id": "g_2026_feb", "announced": "2026-02-04", "target_year": 2026, "kind": "range", "low_usd_bn": 17.5, "high_usd_bn": 18.5, "document": "doc",
             "excerpt": EXCERPTS["guide_c"], "statement": {"zh": "2026 区间", "en": "2026 range"}}],
        "notes": [{"id": "ec_fine", "document": "doc", "title": {"zh": "罚款", "en": "Fine"}, "excerpts": [EXCERPTS["note_a"]],
                   "fact": {"zh": "事实", "en": "Fact"}, "limit": {"zh": "限制", "en": "Limit"},
                   "approx": {"prior_year_charge_usd_m": 3500, "cash_payment_usd_m": 5200}}],
        "coverage": [{"id": "c1", "status": "done", "item": {"zh": "已做", "en": "Done"}},
                     {"id": "c2", "status": "data_gap", "item": {"zh": "缺数据", "en": "Gap"}},
                     {"id": "c3", "status": "judgment", "item": {"zh": "需判断", "en": "Judge"}}],
    }


@pytest.fixture
def earnings_root(project):
    er.earnings_dir(project).mkdir(parents=True, exist_ok=True)
    for p in er.earnings_dir(project).glob("*.yaml"):
        p.unlink()
    er.filings_dir(project).mkdir(parents=True)
    (er.filings_dir(project) / "10q.htm").write_bytes(filing())
    return project


def write(root, doc):
    (er.earnings_dir(root) / f"{doc['earnings_id']}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_check_passes_and_counts_values_identities_and_excerpts(earnings_root):
    write(earnings_root, registration())
    rep = er.check(earnings_root)
    assert rep.errors == [], rep.errors
    c = rep.checked
    # 6 个利润表期间 × 7 条恒等式 + 第四季度推导 7 条 + 2 条自由现金流
    assert c["documents"] == 1 and c["identities"] == 6 * 7 + 7 + 2 and c["excerpts"] == 5


@pytest.mark.parametrize("change,message", [
    (lambda d: d["income"]["q3_2026"]["values"].update(op_income=1), "不成立"),
    (lambda d: d["income"]["q3_2026"]["values"].update(revenue=216 * 23 + 7_000_001, Services_revenue=160 * 23 + 7_000_001), "没有出现在原文"),
    (lambda d: d["documents"][0].update(sha256="0" * 64), "SHA256 与登记不一致"),
    (lambda d: d["guidance"][0].update(excerpt="we expect nothing at all"), "摘录没有逐字出现"),
    (lambda d: d["guidance"][1].update(low_usd_bn=None), "缺少区间上下限"),
    (lambda d: d["guidance"][0].update(kind="forecast"), "kind 应为"),
    (lambda d: d["guidance"][0].update(statement={"zh": "只有中文"}), "缺少中英文陈述"),
    (lambda d: d["coverage"][0].update(status="maybe"), "status 应为"),
    (lambda d: d["issuer_fcf"].update(q3_2026=1), "不等于发行人披露的自由现金流"),
    (lambda d: d["income"]["q3_2026"]["values"].pop("hedging"), "缺少 hedging"),
    (lambda d: d["notes"][0].update(limit={"zh": "限制"}), "缺少中英文"),
    (lambda d: d["guidance"][0].update(document="missing"), "原文 missing 未登记"),
])
def test_check_rejects_unsupported_registrations(earnings_root, change, message):
    doc = registration()
    change(doc)
    write(earnings_root, doc)
    errors = er.check(earnings_root).errors
    assert any(message in x for x in errors), errors
    with pytest.raises(ValueError):
        er.build_bundle(earnings_root)


def test_missing_original_asks_for_fetch(earnings_root):
    write(earnings_root, registration())
    (er.filings_dir(earnings_root) / "10q.htm").unlink()
    assert any("iros earnings fetch" in x for x in er.check(earnings_root).errors)


def test_fetch_downloads_only_missing_files_with_the_user_agent(earnings_root):
    write(earnings_root, registration())
    (er.filings_dir(earnings_root) / "10q.htm").unlink()
    seen = []
    assert er.fetch(earnings_root, "test agent", lambda url, headers: seen.append((url, headers)) or filing()) == ["10q.htm"]
    assert seen == [("https://example.test/10q.htm", {"User-Agent": "test agent"})]
    assert er.fetch(earnings_root, "test agent", lambda *a: pytest.fail("already present")) == []
    with pytest.raises(ValueError):
        er.fetch(earnings_root, "")


def test_bundle_records_carry_period_end_and_eastern_filing_day(earnings_root):
    write(earnings_root, registration())
    doc = er.build_bundle(earnings_root)
    recs = {r["id"]: r for r in doc["records"]}
    r = recs["ex_2026q3|income|q3_2026|revenue"]
    assert r["value"] == 216 * 23 and r["date"] == "2026-09-30"
    assert r["published_at"] == "2026-10-28"  # 2026-10-29T00:29Z 是美东 10 月 28 日
    assert len(doc["records"]) == 6 * 25 + 7 * 2 + 4 * 6
    assert doc["metadata"]["earnings"]["ex_2026q3"]["related_studies"][0]["study"] == "company_example"
    assert er._et_day("2026-10-28") == "2026-10-28"  # 只有日期时按原日期


STUDY = {"study_id": "earnings_test", "title": "测试财报", "question": "?", "result_type": "descriptive", "branch": "earnings_quarter",
         "scope": {"market": "US", "start": "2025-07-01", "end": "2026-09-30", "frequency": "quarterly", "vintage_policy": "latest"},
         "data": {"evidence": "earnings_evidence"}, "method": {"earnings": "ex_2026q3"}, "limitations": ["测试限制"]}


def run(root):
    path = root / "bundle.json"
    path.write_text(json.dumps(er.build_bundle(root)), encoding="utf-8")
    assert ingest(Registry.load(root), DataStore(root), "earnings_evidence", {"path": str(path)}).status == "created"
    spath = root / "config" / "studies" / "earnings_test.yaml"
    spath.write_text(yaml.safe_dump(STUDY, allow_unicode=True), encoding="utf-8")
    m = run_study(root, spath)
    assert m["status"] != "failed", m.get("error")
    return json.loads((root / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))


def test_study_derives_q4_compares_periods_and_checks_outlooks(earnings_root):
    write(earnings_root, registration())
    r = run(earnings_root)
    res = r["results"]
    q = {x["period"]: x for x in res["quarters"]}
    assert [x["period"] for x in res["quarters"]] == ["q3_2025", "q4_2025", "q1_2026", "q2_2026", "q3_2026"]
    assert q["q4_2025"]["derived"] and q["q4_2025"]["revenue"] == 216 * (43 - 31)
    assert q["q4_2025"]["free_cash_flow"] == 4300 - 2500 and not q["q3_2026"]["derived"]
    assert q["q3_2026"]["op_margin"] == pytest.approx(71 / 216 * 100)
    yoy = res["comparison"]["yoy"]
    assert yoy["base"] == "2025 Q3" and yoy["pct"]["revenue"] == pytest.approx((23 / 13 - 1) * 100)
    assert res["comparison"]["qoq"]["pct"]["revenue"] == pytest.approx((23 / 19 - 1) * 100)
    assert res["comparison"]["segment_op_delta_yoy"]["reconciles"]
    # 示意算术：去年同期营业利润加回登记的约数
    assert res["bridges"]["prior_op_income_plus_charge"] == 71 * 13 + 3500
    assert res["bridges"]["ebt_ex_equity_securities"]["q3_2026"] == (80 - 7) * 23
    g = {x["id"]: x for x in res["guidance"]["observations"]}
    assert g["g_a"]["result"] == "difference_only" and g["g_a"]["difference_usd_bn"] == pytest.approx(9.2 - 7)
    assert g["g_b"]["result"] == "within_range" and g["g_2026_feb"]["result"] == "pending"
    assert res["guidance"]["remaining_arithmetic"]["low_usd_bn"] == pytest.approx(17.5 - 13)
    assert res["rpo"]["points"][1]["total_qoq_pct"] == pytest.approx((567.0 / 519.5 - 1) * 100)
    assert r["data_cutoff"] == "2026-10-28"  # 展望与日程不是数据
    assert {u["kind"] for u in r["unsupported"]} == {"data", "scope"} and len(r["unsupported"]) == 2
    assert r["validation"]["evidence_check"]["status"] == "pass"
    ids = [f["id"] for f in r["interpretation"]["items"]]
    assert ids == ["earnings_revenue", "earnings_operating", "earnings_segment", "earnings_net_income", "earnings_cash", "earnings_backlog"]
    assert "不能称为有机增长" in r["interpretation"]["items"][0]["text"]


def test_page_report_findings_and_english(earnings_root):
    from investment_os.reporting.earnings import sections
    from investment_os.site.findings_en import english_findings
    from investment_os.site.i18n import use
    from investment_os.site.renderers import get_renderer
    from investment_os.site.targets import available

    write(earnings_root, registration())
    r = run(earnings_root)
    page = get_renderer("earnings_quarter").coverage_section(r)
    for anchor in ("earnings-quarterly", "earnings-segments", "earnings-cash", "earnings-comparability", "earnings-outlook",
                   "earnings-backlog", "earnings-coverage", "earnings-sources"):
        assert page.count(f'id="{anchor}"') == 1, anchor
    assert page.count("<svg") == 4 and "罚款" in page and "2025 Q4*" in page and "../company_example/" in page
    with use("en", {}, set()):
        en = get_renderer("earnings_quarter").coverage_section(r)
    assert "Fine" in en and "罚款" not in en and "Needs judgement" in en and "Annual" in en
    texts = english_findings(r, r["interpretation"]["items"])
    assert all(t["translated"] for t in texts) and "cannot be called organic" in texts[0]["text"]
    assert available(r, "earnings-quarterly") and available(r, "earnings-comparability")
    body, title, part = sections(r)
    assert body[1][0] == "table" and len(body[1][2]) == 11 and part[1][0] == "table"


def test_state_changes_with_cash_flow_sign_and_coverage(earnings_root):
    from investment_os.research.findings import earnings_quarter_state

    write(earnings_root, registration())
    state = earnings_quarter_state(run(earnings_root))
    assert state["最新季度"] == "2026 Q3" and state["自由现金流符号"] == "为负" and state["非经营项目损益方向"] == "净收益"
    assert state["覆盖项"] == "已完成 1、数据不足 1、需判断 1"


def test_shipped_registration_is_public_and_complete():
    """随仓库提交的登记：结构完整、中英文齐全、不含本机路径、邮箱或密钥（原文只在本机，核对由 iros earnings check 完成）。"""
    path = PROJECT_ROOT / "config/earnings/googl_2026q3.yaml"
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"/Users/|@[\w.-]+\.\w+|api[_-]?key|SEC_USER_AGENT=", text, re.I)
    reg = yaml.safe_load(text)
    assert reg["schema_version"] == er.SCHEMA and reg["earnings_id"] == path.stem and reg["entity"] == "cik_1652044"
    assert all(re.fullmatch(r"[0-9a-f]{64}", d["sha256"]) for d in reg["documents"])
    assert er.profile_errors(reg) == []
    assert all(set(p["values"]) == set(reg["profile"]["income_metrics"]) for p in reg["income"].values())
    for section in ("notes", "guidance", "coverage"):
        for item in reg[section]:
            for key in ("title", "fact", "limit", "statement", "item"):
                if key in item:
                    assert item[key]["zh"] and item[key]["en"]
    assert {c["status"] for c in reg["coverage"]} == set(er.STATUSES)
    # 每个被引用的原文都已登记
    ids = {d["id"] for d in reg["documents"]}
    refs = {p["document"] for p in reg["income"].values()} | {p["document"] for p in reg["cash_flow"].values()} | {g["document"] for g in reg["guidance"]}
    assert refs <= ids
    # 登记里的全年数 = 第四季度推导 + 前三季度，且各期恒等式成立
    for pid, p in reg["income"].items():
        rep = er.Report()
        er._identities(pid, p["values"], rep, reg["profile"]["identities"])
        assert rep.errors == [], rep.errors
    assert copy.deepcopy(reg["income"]["fy_2025"]["values"])["revenue"] - reg["income"]["nine_months_2025"]["values"]["revenue"] > 0


# ---- 结构不同的虚构公司：两个分部、没有 Other Bets / 优先股 / 套期、非日历财年（52/53 周，财年止于一月下旬）、
# ---- 没有展望、积压订单、恒定汇率、每股收益、非经营项目示意算术与发行人自由现金流
FBASE = {"Compute_revenue": 700, "Graphics_revenue": 300, "revenue": 1000, "cost_of_revenues": 400, "operating_expenses": 250,
         "op_income": 350, "Compute_op": 300, "Graphics_op": 100, "Unallocated_op": -50, "other_income": 20, "EBT": 370,
         "income_tax": 60, "consolidated_NI": 310}
FSCALE = {"q3_fy25": 7, "q1_fy26": 9, "q2_fy26": 10, "q3_fy26": 12, "nine_fy25": 21, "fy_fy25": 29}
FEND = {"q3_fy25": "2024-10-27", "q1_fy26": "2025-04-27", "q2_fy26": "2025-07-27", "q3_fy26": "2025-10-26",
        "nine_fy25": "2024-10-27", "fy_fy25": "2025-01-26"}
FCASH = {"q3_fy25": (2000, 500), "q4_fy25": (2500, 600), "q1_fy26": (2300, 700), "q2_fy26": (2600, 800), "q3_fy26": (3100, 900),
         "nine_fy26": (8000, 2400), "ttm_fy26q3": (10500, 3000)}
FCASH_END = {"q3_fy25": "2024-10-27", "q4_fy25": "2025-01-26", "q1_fy26": "2025-04-27", "q2_fy26": "2025-07-27", "q3_fy26": "2025-10-26",
             "nine_fy26": "2025-10-26", "ttm_fy26q3": "2025-10-26"}
FBAL = {"2025-10-26": (1000, 2000, 30000, 20000, 3000, 9000), "2025-07-27": (900, 1900, 28000, 19000, 3100, 8500)}
FNOTE = "the fiscal year ends on the last Sunday of January"


def fictional_filing():
    nums = set()
    for k, scale in FSCALE.items():
        nums.update(abs(v * scale) for v in FBASE.values())
    for a, b in FCASH.values():
        nums.update((a, b))
    for row in FBAL.values():
        nums.update(row)
    body = " ".join(f"<td>{fmt(n)}</td>" for n in sorted(nums - {0}))
    return f"<html><body><table><tr>{body}</tr></table><p>{FNOTE}</p></body></html>".encode()


def _name(zh, en):
    return {"zh": zh, "en": en}


def fictional_profile():
    return {
        "short_name": "Fabrica",
        "quarters": [
            {"id": "q3_fy25", "label": "FY25 Q3", "end": "2024-10-27", "name": _name("2025 财年第三季度", "Q3 FY25")},
            {"id": "q4_fy25", "label": "FY25 Q4", "end": "2025-01-26", "name": _name("2025 财年第四季度", "Q4 FY25"),
             "derive": {"total": "fy_fy25", "less": "nine_fy25", "method": _name("全年减前三季度", "full year less nine months"),
                        "note": _name("第四季度由全年减前三季度推出。", "Q4 is derived as the full year less nine months.")}},
            {"id": "q1_fy26", "label": "FY26 Q1", "end": "2025-04-27", "name": _name("2026 财年第一季度", "Q1 FY26")},
            {"id": "q2_fy26", "label": "FY26 Q2", "end": "2025-07-27", "name": _name("2026 财年第二季度", "Q2 FY26")},
            {"id": "q3_fy26", "label": "FY26 Q3", "end": "2025-10-26", "name": _name("2026 财年第三季度", "Q3 FY26")}],
        "current": "q3_fy26", "yoy_base": "q3_fy25", "qoq_base": "q2_fy26",
        "year_to_date": {"id": "nine_fy26", "quarters": ["q1_fy26", "q2_fy26", "q3_fy26"],
                         "label": _name("2026 财年前三季度", "First nine months of FY26"), "short": _name("前三季度", "nine-month")},
        "trailing": "ttm_fy26q3",
        "income_metrics": list(FBASE),
        "identities": [
            {"name": "分部收入合计 = 收入", "terms": {"Compute_revenue": 1, "Graphics_revenue": 1}, "equals": "revenue"},
            {"name": "收入 − 营业成本 − 营业费用 = 营业利润", "terms": {"revenue": 1, "cost_of_revenues": -1, "operating_expenses": -1}, "equals": "op_income"},
            {"name": "分部营业利润合计 = 营业利润", "terms": {"Compute_op": 1, "Graphics_op": 1, "Unallocated_op": 1}, "equals": "op_income"},
            {"name": "营业利润 + 其他收支 = 税前利润", "terms": {"op_income": 1, "other_income": 1}, "equals": "EBT"},
            {"name": "税前利润 − 所得税 = 净利润", "terms": {"EBT": 1, "income_tax": -1}, "equals": "consolidated_NI"}],
        "segment_ops": ["Compute_op", "Graphics_op", "Unallocated_op"],
        "ratios": [{"key": "Compute_margin", "num": "Compute_op", "den": "Compute_revenue"},
                   {"key": "Graphics_margin", "num": "Graphics_op", "den": "Graphics_revenue"}],
        "growth": ["revenue", "Compute_revenue", "Graphics_revenue", "op_income", "consolidated_NI", "cfo", "cash_ppe"],
        "margins": ["gross_margin", "op_margin", "Compute_margin"],
        "findings": {"revenue_caveat": _name("发行人只披露报告口径。", "The issuer reports only the reported basis."),
                     "segment": {"name": "Compute", "revenue": "Compute_revenue", "margin": "Compute_margin",
                                 "caveat": _name("分部口径见可比性说明。", "See the comparability notes for the segment basis.")}},
        "metrics": {"revenue": _name("收入", "Revenue"), "Compute_revenue": _name("计算", "Compute"), "Graphics_revenue": _name("图形", "Graphics"),
                    "op_income": _name("营业利润", "Operating income"), "consolidated_NI": _name("净利润", "Net income"),
                    "gross_margin": _name("毛利率", "Gross margin"), "op_margin": _name("营业利润率", "Operating margin")},
        "table": ["revenue", "Compute_revenue", "Graphics_revenue", "op_income", {"key": "consolidated_NI", "growth": False},
                  "gross_margin", "op_margin"],
        "charts": [{"title": _name("收入与利润", "Revenue and profit"), "unit": "usd_bn",
                    "series": [{"key": "revenue", "label": _name("收入", "Revenue")}, {"key": "op_income", "label": _name("营业利润", "Operating income")}]},
                   {"title": _name("利润率", "Margins"), "unit": "pct",
                    "series": [{"key": "op_margin", "label": _name("营业利润率", "Operating margin")}]}],
        "segments": [{"name": "Compute", "revenue": "Compute_revenue", "op": "Compute_op", "margin": "Compute_margin"},
                     {"name": "Graphics", "revenue": "Graphics_revenue", "op": "Graphics_op", "margin": "Graphics_margin"}],
        "unallocated": {"key": "Unallocated_op", "label": _name("未分摊", "Unallocated")},
    }


def fictional_registration():
    raw = fictional_filing()
    income = {pid: {"label": pid, "start": "2024-01-29", "end": FEND[pid], "document": "doc",
                    "values": {k: v * FSCALE[pid] for k, v in FBASE.items()}} for pid in FSCALE}
    cash = {pid: {"end": FCASH_END[pid], "document": "doc", "cfo": a, "cash_ppe": b} for pid, (a, b) in FCASH.items()}
    return {
        "schema_version": "earnings.v1", "earnings_id": "fbr_fy26q3", "entity": "co_fabrica",
        "company": _name("法布里卡", "Fabrica Corp"), "cik": 2, "tickers": ["FBR"],
        "latest_period": {"label": "FY26 Q3", "start": "2025-07-28", "end": "2025-10-26"}, "as_of": "2025-11-20",
        "unit": "USD million", "release": {"ir_date": "2025-11-19", "ir_url": "https://example.test/fbr", "form_10q_filed": "2025-11-20"},
        "documents": [{"id": "doc", "form": "10-Q", "period_end": "2025-10-26", "accession": "0000000000-25-000002",
                       "accepted_at": "2025-11-20T21:30:00Z", "url": "https://example.test/fbr10q.htm", "file": "fbr10q.htm",
                       "sha256": hashlib.sha256(raw).hexdigest()}],
        "profile": fictional_profile(), "income": income, "cash_flow": cash,
        "balance": {d: {"document": "doc", "values": dict(zip(er.BALANCE_METRICS, row))} for d, row in FBAL.items()},
        "notes": [{"id": "fiscal_calendar", "document": "doc", "title": _name("财年", "Fiscal year"), "excerpts": [FNOTE],
                   "fact": _name("财年止于一月最后一个星期日。", "The fiscal year ends on the last Sunday of January."),
                   "limit": _name("52/53 周财年，季度长度可能为 13 或 14 周。", "A 52/53-week year: quarters may span 13 or 14 weeks.")}],
        "coverage": [{"id": "c1", "status": "done", "item": _name("五个季度", "Five quarters")},
                     {"id": "c2", "status": "data_gap", "item": _name("分部内部口径", "Segment internals")}],
    }


@pytest.fixture
def fictional_root(earnings_root):
    (er.filings_dir(earnings_root) / "fbr10q.htm").write_bytes(fictional_filing())
    return earnings_root


def run_fictional(root):
    path = root / "bundle.json"
    path.write_text(json.dumps(er.build_bundle(root)), encoding="utf-8")
    assert ingest(Registry.load(root), DataStore(root), "earnings_evidence", {"path": str(path)}).status == "created"
    spath = root / "config" / "studies" / "earnings_fbr.yaml"
    spath.write_text(yaml.safe_dump({**STUDY, "study_id": "earnings_fbr", "title": "虚构公司", "method": {"earnings": "fbr_fy26q3"}},
                                    allow_unicode=True), encoding="utf-8")
    m = run_study(root, spath)
    assert m["status"] != "failed", m.get("error")
    return json.loads((root / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))


def test_other_company_checks_bundles_and_computes_from_its_own_profile(fictional_root):
    write(fictional_root, fictional_registration())
    rep = er.check(fictional_root)
    assert rep.errors == [], rep.errors
    # 6 个利润表期间 × 5 条恒等式 + 第四季度推导 5 条；没有发行人自由现金流
    assert rep.checked["identities"] == 6 * 5 + 5 and rep.checked["excerpts"] == 1
    doc = er.build_bundle(fictional_root)
    snap = doc["metadata"]["earnings"]["fbr_fy26q3"]
    assert snap["profile"]["short_name"] == "Fabrica" and snap["rpo"] is None and snap["guidance"] == []
    assert len(doc["records"]) == 6 * len(FBASE) + 7 * 2 + 2 * 6
    r = run_fictional(fictional_root)
    res = r["results"]
    q = {x["period"]: x for x in res["quarters"]}
    assert [x["label"] for x in res["quarters"]] == ["FY25 Q3", "FY25 Q4", "FY26 Q1", "FY26 Q2", "FY26 Q3"]
    assert q["q4_fy25"]["derived"] and q["q4_fy25"]["revenue"] == 1000 * (29 - 21) and q["q4_fy25"]["end"] == "2025-01-26"
    assert q["q3_fy26"]["Compute_margin"] == pytest.approx(300 / 700 * 100) and q["q3_fy26"]["free_cash_flow"] == 3100 - 900
    assert "ebt_ex_equity_securities" not in q["q3_fy26"] and "Other" not in " ".join(q["q3_fy26"])
    yoy = res["comparison"]["yoy"]
    assert yoy["base"] == "FY25 Q3" and yoy["pct"]["revenue"] == pytest.approx((12 / 7 - 1) * 100)
    assert res["comparison"]["qoq"]["base"] == "FY26 Q2"
    assert res["comparison"]["segment_op_delta_yoy"]["reconciles"] and set(res["comparison"]["segment_op_delta_yoy"]["delta"]) == {"Compute_op", "Graphics_op", "Unallocated_op"}
    assert res["bridges"] is None and res["rpo"] is None and res["guidance"] is None and res["fx"] is None and res["per_share"] is None
    assert res["cash"]["year_to_date"]["cfo"] == 8000 and res["cash"]["trailing"]["free_cash_flow"] == 7500
    assert res["cash"]["year_to_date"]["consolidated_ni"] == 310 * (9 + 10 + 12)
    assert r["data_cutoff"] == "2025-11-20" and r["validation"]["evidence_check"]["status"] == "pass"
    ids = [f["id"] for f in r["interpretation"]["items"]]
    assert ids == ["earnings_revenue", "earnings_operating", "earnings_segment", "earnings_net_income", "earnings_cash"]
    text = " ".join(f["text"] for f in r["interpretation"]["items"])
    assert "发行人只披露报告口径" in text and "Compute 收入" in text and "Alphabet" not in text and "Cloud" not in text
    assert "近四个季度合计 7.50" in text and "权益证券" not in text
    from investment_os.research.findings import earnings_quarter_state

    assert earnings_quarter_state(r) == {"最新季度": "FY26 Q3", "自由现金流符号": "为正", "覆盖项": "已完成 1、数据不足 1、需判断 0"}


def test_other_company_page_report_and_english_follow_the_profile(fictional_root):
    from investment_os.reporting.earnings import sections
    from investment_os.site.findings_en import english_findings
    from investment_os.site.i18n import use
    from investment_os.site.renderers import get_renderer
    from investment_os.site.targets import available

    write(fictional_root, fictional_registration())
    r = run_fictional(fictional_root)
    renderer = get_renderer("earnings_quarter")
    page = renderer.coverage_section(r)
    for anchor in ("earnings-quarterly", "earnings-segments", "earnings-cash", "earnings-comparability", "earnings-outlook",
                   "earnings-backlog", "earnings-coverage", "earnings-sources"):
        assert page.count(f'id="{anchor}"') == 1, anchor
    assert page.count("<svg") == 2 and "FY25 Q4*" in page and "第四季度由全年减前三季度推出" in page
    assert "Compute" in page and "Graphics" in page and "未分摊" in page and "2026 财年前三季度" in page
    assert "Google" not in page and "Alphabet" not in page and "YouTube" not in page and "Other Bets" not in page
    assert "没有登记资本开支展望" in page and "没有登记收入积压订单" in page and "示意性的税前算术" not in page and "恒定汇率" not in page
    assert "Fabrica 于 2025-11-19 发布2026 财年第三季度业绩" in page
    with use("en", {}, set()):
        en = renderer.coverage_section(r)
        stats = renderer.key_stats(r)
        method = renderer.method_items(r)[0]
    assert "No capital expenditure outlook is registered." in en and "No revenue backlog is registered." in en
    assert "Fabrica released Q3 FY26 results" in en and "Q4 is derived as the full year less nine months." in en
    assert "Q3 FY26 revenue (USD bn)" in stats and "Q4 FY25 is derived as full year less nine months" in method
    assert "Five quarters of consolidated results" in method and "Alphabet" not in en and "Google" not in en
    texts = english_findings(r, r["interpretation"]["items"])
    assert all(t["translated"] for t in texts) and "The issuer reports only the reported basis." in texts[0]["text"]
    assert "Compute revenue was USD" in texts[2]["text"] and "equity" not in " ".join(t["text"] for t in texts)
    assert available(r, "earnings-quarterly") and available(r, "earnings-comparability")
    body, title, part = sections(r)
    assert body[1][0] == "table" and [row[0] for row in body[1][2]] == ["收入", "计算", "图形", "营业利润", "净利润", "毛利率", "营业利润率"]
    assert body[2][1][:3] == ["比较", "收入", "计算 收入"]


@pytest.mark.parametrize("change,message", [
    (lambda d: d.pop("profile"), "缺少 profile"),
    (lambda d: d["profile"]["identities"][2]["terms"].update(Unallocated_op=2), "不成立"),
    (lambda d: d["profile"].update(identities=[]), "identities 不能为空"),
    (lambda d: d["profile"]["quarters"][1].pop("derive"), "不在 income 中"),
    (lambda d: d["profile"]["quarters"][1]["derive"].update(total="nope"), "derive.total 不在 income 中"),
    (lambda d: d["profile"].update(quarters=d["profile"]["quarters"][3:]), "至少 3 个"),
    (lambda d: d["profile"].update(current="q9"), "profile.current 应是 quarters 中的 id"),
    (lambda d: d["profile"]["quarters"][0].update(name={"zh": "只有中文"}), "中英文 name"),
    (lambda d: d["profile"]["metrics"].update(revenue={"zh": "收入", "en": "Revenue", "platforms and devices": None}), "缺少 revenue 的中英文标签"),
    (lambda d: d["profile"]["table"].append("nonsense"), "nonsense 不是可显示的行键"),
    (lambda d: d["profile"]["charts"][0].update(unit="eur"), "usd_bn 或 pct"),
    (lambda d: d["profile"]["income_metrics"].remove("cost_of_revenues"), "缺少必备科目 cost_of_revenues"),
    (lambda d: d["profile"].update(segments=[]), "segments 不能为空"),
    (lambda d: d["profile"].update(segment_ops=["Compute_op", "Graphics_op"]), "分部营业利润合计 = op_income"),
    (lambda d: d["profile"]["findings"].pop("revenue_caveat"), "revenue_caveat"),
    (lambda d: d["profile"].update(non_operating={"key": "other_income", "label": {"zh": "其他", "en": "other"}}), "calibers.ex_items"),
    (lambda d: d["profile"].update(growth=["revenue", "ghost"]), "引用了不存在的科目 ghost"),
    (lambda d: d["cash_flow"].pop("q1_fy26"), "不在 cash_flow 中"),
    (lambda d: d["notes"][0].update(excerpts=["the fiscal year ends in june"]), "摘录没有逐字出现"),
    (lambda d: d["income"]["q3_fy26"]["values"].update(consolidated_NI=1), "不成立"),
])
def test_other_company_profile_errors_are_reported_by_check(fictional_root, change, message):
    doc = fictional_registration()
    change(doc)
    write(fictional_root, doc)
    errors = er.check(fictional_root).errors
    assert any(message in x for x in errors), errors
    with pytest.raises(ValueError):
        er.build_bundle(fictional_root)


def test_result_recorded_before_profiles_degrades_instead_of_failing():
    """早于 profile 的运行（结果里没有 profile）：没有规则化发现，页面给出提示，不报错。"""
    from investment_os.research.findings import earnings_quarter_findings, earnings_quarter_state
    from investment_os.site.renderers import get_renderer

    old = {"results": {"quarters": []}, "methods": {"description": "旧说明"}, "limitations": []}
    assert earnings_quarter_findings(old) == [] and earnings_quarter_state(old) == {}
    renderer = get_renderer("earnings_quarter")
    assert "没有 profile" in renderer.coverage_section(old) and renderer.key_stats(old) == "" and renderer.home_summary(old) is None
    assert "旧说明" in renderer.method_items(old)[0]


# Real NVIDIA cash-flow inputs, paired with synthetic income/balance statements.
# SEC FY27 Q3/Q2 furnished releases: CFO - purchases - related principal (USDm).
def principal_registration(root):
    doc = registration()
    p = doc["profile"]
    p["fcf_deduct_principal"] = True
    p["metrics"]["cash_ppe"] = _name("购置固定资产及无形资产", "Purchases of property, equipment and intangible assets")
    p["metrics"]["cash_ppe_principal"] = _name("相关本金支付", "Related principal payments")
    for cf in doc["cash_flow"].values():
        cf["cash_ppe_principal"] = 0
    doc["cash_flow"]["q3_2026"].update(cfo=48253, cash_ppe=4422, cash_ppe_principal=54)
    doc["cash_flow"]["q2_2026"].update(cfo=24077, cash_ppe=2677, cash_ppe_principal=59)
    for pid, qs in (("nine_months_2026", ("q1_2026", "q2_2026", "q3_2026")),
                    ("ttm_2026q3", ("q4_2025", "q1_2026", "q2_2026", "q3_2026"))):
        for m in er.cash_metrics(p):
            doc["cash_flow"][pid][m] = sum(doc["cash_flow"][q][m] for q in qs)
    # Expected FCF constants are independently hand-calculated, not generated by production helpers.
    doc["issuer_fcf"] = {"q3_2026": 43777, "q2_2026": 21341, "ttm_2026q3": 67918, "document": "doc"}
    values = [cf[m] for cf in doc["cash_flow"].values() for m in er.cash_metrics(p)] + [43777, 21341, 67918]
    raw = filing().replace(b"</body>", ("<p>" + " ".join(fmt(v) for v in values) + "</p></body>").encode())
    (er.filings_dir(root) / "10q.htm").write_bytes(raw)
    doc["documents"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    return doc


def test_principal_fcf_check_bundle_research_and_bilingual_page(earnings_root):
    from investment_os.site.findings_en import english_findings
    from investment_os.site.i18n import use
    from investment_os.site.renderers import get_renderer

    doc = principal_registration(earnings_root)
    write(earnings_root, doc)
    assert not er.check(earnings_root).errors
    bundle = er.build_bundle(earnings_root)
    principal = [r for r in bundle["records"] if r["metric"] == "cash_ppe_principal"]
    assert len(principal) == len(doc["cash_flow"])
    assert {r["document"] for r in principal} == {"doc"}
    assert next(r["value"] for r in principal if r["period"] == "q3_2026") == 54
    r = run(earnings_root)
    rows = {q["period"]: q for q in r["results"]["quarters"]}
    assert (rows["q3_2026"]["cfo"], rows["q3_2026"]["cash_ppe"], rows["q3_2026"]["cash_ppe_principal"]) == (48253, 4422, 54)
    assert rows["q3_2026"]["free_cash_flow"] == 43777
    assert rows["q2_2026"]["free_cash_flow"] == 21341
    cash = r["results"]["cash"]
    assert cash["current_free_cash_flow"] == 43777
    assert cash["trailing"]["free_cash_flow"] == 67918
    assert cash["trailing"]["cash_ppe_principal"] == cash["year_to_date"]["cash_ppe_principal"] == 113
    assert cash["year_to_date"]["cfo_to_cash_ppe"] == pytest.approx(76830 / 10599)
    assert "相关本金支付" in cash["caliber"]["zh"] and "less related principal payments" in cash["caliber"]["en"]
    zh = get_renderer("earnings_quarter").coverage_section(r)
    assert "购置固定资产及无形资产" in zh and "相关本金支付" in zh and "43.78" in zh
    with use("en", {}, set()):
        en = get_renderer("earnings_quarter").coverage_section(r)
    assert "Related principal payments" in en and "intangible assets" in en and "less related principal payments" in en
    finding = next(x for x in r["interpretation"]["items"] if x["id"] == "earnings_cash")
    assert finding["evidence"]["free_cash_flow_usd_m"] == 43777
    en_findings = english_findings(r, r["interpretation"]["items"])
    assert "43.78" in next(x["text"] for x in en_findings if x["id"] == "earnings_cash")


@pytest.mark.parametrize("period", ["q3_2026", "nine_months_2026", "ttm_2026q3"])
@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf"), True, "54"])
def test_principal_requires_nonnegative_finite_numeric_value_in_every_period(earnings_root, period, value):
    doc = principal_registration(earnings_root)
    if value is None:
        del doc["cash_flow"][period]["cash_ppe_principal"]
    else:
        doc["cash_flow"][period]["cash_ppe_principal"] = value
    write(earnings_root, doc)
    errors = er.check(earnings_root).errors
    assert any(f"cash_flow.{period}.cash_ppe_principal" in e for e in errors)
    with pytest.raises(ValueError, match="核对未通过"):
        er.build_bundle(earnings_root)


@pytest.mark.parametrize("flag", [None, False, "true", 1])
def test_principal_cannot_be_silently_ignored_without_explicit_boolean_opt_in(earnings_root, flag):
    doc = principal_registration(earnings_root)
    if flag is None:
        del doc["profile"]["fcf_deduct_principal"]
    else:
        doc["profile"]["fcf_deduct_principal"] = flag
    write(earnings_root, doc)
    assert any("显式启用" in e for e in er.check(earnings_root).errors)


def test_principal_is_checked_against_source_and_issuer_reconciliation(earnings_root):
    doc = principal_registration(earnings_root)
    doc["cash_flow"]["q3_2026"]["cash_ppe_principal"] = 987654321
    write(earnings_root, doc)
    errors = er.check(earnings_root).errors
    assert any("现金流 q3_2026.cash_ppe_principal" in e and "没有出现在原文" in e for e in errors)
    assert any("不等于发行人披露的自由现金流" in e for e in errors)
    doc["cash_flow"]["q3_2026"]["cash_ppe_principal"] = 54
    doc["issuer_fcf"]["q3_2026"] = 43831  # CFO - purchases alone must fail.
    write(earnings_root, doc)
    assert any("不等于发行人披露的自由现金流" in e for e in er.check(earnings_root).errors)


@pytest.mark.parametrize("metric", ["cash_ppe", "cash_ppe_principal"])
def test_principal_requires_separate_bilingual_labels(earnings_root, metric):
    doc = principal_registration(earnings_root)
    doc["profile"]["metrics"].pop(metric)
    write(earnings_root, doc)
    assert any(f"profile.metrics.{metric}" in e for e in er.check(earnings_root).errors)


def test_legacy_fcf_default_is_unchanged_and_zero_purchases_do_not_divide_by_zero(earnings_root):
    from investment_os.research.earnings_quarter import cash_conversion, quarter_rows

    doc = registration()
    table = {("income", pid): row["values"] for pid, row in doc["income"].items()}
    table.update({("cash_flow", pid): {m: row[m] for m in er.CASH_METRICS} for pid, row in doc["cash_flow"].items()})
    p = doc["profile"]
    rows = quarter_rows(table, p)
    cash = cash_conversion(rows, table, doc["issuer_fcf"], p)
    p_false = {**p, "fcf_deduct_principal": False}
    assert rows == quarter_rows(table, p_false)
    assert cash == cash_conversion(rows, table, doc["issuer_fcf"], p_false)
    assert all("cash_ppe_principal" not in row for row in rows)
    assert rows[-1]["free_cash_flow"] == -900 and cash["trailing"]["free_cash_flow"] == 1400
    table[("cash_flow", p["year_to_date"]["id"])]["cash_ppe"] = 0
    assert cash_conversion(rows, table, doc["issuer_fcf"], p)["year_to_date"]["cfo_to_cash_ppe"] is None
