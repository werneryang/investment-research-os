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
        "income": income, "cash_flow": cash,
        "issuer_fcf": {"q3_2026": 4200 - 5100, "ttm_2026q3": 16900 - 15500, "document": "doc"},
        "balance": {d: {"document": "doc", "values": dict(zip(er.BALANCE_METRICS, row))} for d, row in BAL.items()},
        "rpo": {"unit": "USD billion", "points": [
            {"date": "2026-09-30", "total": 567.0, "cloud": 561.0, "document": "doc"},
            {"date": "2026-06-30", "total": 519.5, "cloud": 513.9, "document": "doc"}],
            "recognition": {"share_text": "just over 55", "months": 24, "document": "doc", "excerpt": EXCERPTS["rpo"]},
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
    assert res["guidance"]["remaining_2026_arithmetic"]["low_usd_bn"] == pytest.approx(17.5 - 13)
    assert res["rpo"]["points"][1]["total_qoq_pct"] == pytest.approx((567.0 / 519.5 - 1) * 100)
    assert r["data_cutoff"] == "2026-10-28"  # 展望与日程不是数据
    assert {u["kind"] for u in r["unsupported"]} == {"data", "scope"} and len(r["unsupported"]) == 2
    assert r["validation"]["evidence_check"]["status"] == "pass"
    ids = [f["id"] for f in r["interpretation"]["items"]]
    assert ids == ["earnings_revenue", "earnings_operating", "earnings_cloud", "earnings_net_income", "earnings_cash", "earnings_backlog"]
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
    assert state["最新季度"] == "2026 Q3" and state["自由现金流符号"] == "为负" and state["权益证券损益方向"] == "净收益"
    assert state["覆盖项"] == "已完成 1、数据不足 1、需判断 1"


def test_shipped_registration_is_public_and_complete():
    """随仓库提交的登记：结构完整、中英文齐全、不含本机路径、邮箱或密钥（原文只在本机，核对由 iros earnings check 完成）。"""
    path = PROJECT_ROOT / "config/earnings/googl_2026q3.yaml"
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"/Users/|@[\w.-]+\.\w+|api[_-]?key|SEC_USER_AGENT=", text, re.I)
    reg = yaml.safe_load(text)
    assert reg["schema_version"] == er.SCHEMA and reg["earnings_id"] == path.stem and reg["entity"] == "cik_1652044"
    assert all(re.fullmatch(r"[0-9a-f]{64}", d["sha256"]) for d in reg["documents"])
    assert set(reg["income"]) == set(SCALE) and all(set(p["values"]) == set(er.INCOME_METRICS) for p in reg["income"].values())
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
        er._identities(pid, p["values"], rep)
        assert rep.errors == [], rep.errors
    assert copy.deepcopy(reg["income"]["fy_2025"]["values"])["revenue"] - reg["income"]["nine_months_2025"]["values"]["revenue"] > 0
