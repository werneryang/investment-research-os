"""事件登记、证据包与事件时间线研究（docs/study-events.md）。全部离线。"""

import hashlib
import json

import pytest
import yaml

from investment_os import events as ev
from investment_os.data import DataStore, ingest
from investment_os.registry import Registry
from investment_os.runs import run_study

FILING = b"""<html><body><p>Item 5.02. On March 3, 2026, the Board accepted the resignation of Pat Doe,
as Chief Executive Officer, effective immediately.</p><p>The Board appointed Sam Roe as interim Chief Executive&#160;Officer.</p>
<p>The company will report results on March 20, as previously scheduled.</p></body></html>"""


def registration(**over):
    doc = {"schema_version": "event.v1", "event_id": "ex_ceo_2026", "entity": "co_nvidia",
           "title": {"zh": "示例", "en": "Example"}, "event_date": "2026-03-03", "as_of": "2026-03-06",
           "documents": [{"id": "doc_8k", "accession": "0000000000-26-000001", "form": "8-K", "items": ["5.02"],
                          "url": "https://example.test/8k.htm", "file": "8k.htm",
                          "sha256": hashlib.sha256(FILING).hexdigest(), "accepted_at": "2026-03-04T17:05:00-05:00"}],
           "facts": [
               {"id": "f_resign", "date": "2026-03-03", "kind": "event", "document": "doc_8k", "locator": "Item 5.02",
                "excerpt": "the Board accepted the resignation of Pat Doe, as Chief Executive Officer, effective immediately.",
                "statement": {"zh": "首席执行官辞职", "en": "CEO resigned"}},
               {"id": "f_interim", "date": "2026-03-03", "kind": "event", "document": "doc_8k", "locator": "Item 5.02",
                "excerpt": "The Board appointed Sam Roe as interim Chief Executive Officer.",
                "statement": {"zh": "任命临时首席执行官", "en": "Interim CEO appointed"}},
               {"id": "f_results", "date": "2026-03-20", "kind": "scheduled", "document": "doc_8k", "locator": "Item 5.02",
                "excerpt": "The company will report results on March 20, as previously scheduled.",
                "statement": {"zh": "按原定日程公布业绩", "en": "Results as scheduled"}}],
           "not_mentioned": [{"id": "n_reason", "item": {"zh": "原因", "en": "Reason"}, "documents": ["doc_8k"],
                              "terms": ["reason", "because"]}]}
    doc.update(over)
    return doc


@pytest.fixture
def events_root(project):
    for p in ev.events_dir(project).glob("*.yaml"):
        p.unlink()
    ev.filings_dir(project).mkdir(parents=True)
    (ev.filings_dir(project) / "8k.htm").write_bytes(FILING)
    return project


def write(root, doc):
    (ev.events_dir(root) / f"{doc['event_id']}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def test_check_passes_and_counts_documents_excerpts_and_absent_terms(events_root):
    write(events_root, registration())
    rep = ev.check(events_root)
    assert rep.errors == []
    # 摘录跨越标签、实体（&#160;）与换行时仍按合并空白后的文字比较
    assert rep.checked == {"documents": 1, "excerpts": 3, "absent_terms": 2}


@pytest.mark.parametrize("change,message", [
    (lambda d: d["facts"][0].update(excerpt="the Board accepted the resignation of Pat Doe for health reasons"), "摘录没有逐字出现"),
    (lambda d: d["not_mentioned"][0].update(terms=["resignation"]), "不能登记为未提及"),
    (lambda d: d["documents"][0].update(sha256="0" * 64), "SHA256 与登记不一致"),
    (lambda d: d["facts"][2].update(date="2026-03-05"), "日程，但日期不晚于查阅日"),
    (lambda d: d["facts"][0].update(date="2026-03-09"), "日期晚于查阅日"),
    (lambda d: d["facts"][0].update(kind="rumor"), "kind 应为"),
    (lambda d: d["facts"][0].update(statement={"zh": "只有中文"}), "缺少中英文陈述"),
    (lambda d: d["facts"][0].update(document="doc_missing"), "引用的原文未登记"),
])
def test_check_rejects_unsupported_registrations(events_root, change, message):
    doc = registration()
    change(doc)
    write(events_root, doc)
    errors = ev.check(events_root).errors
    assert any(message in x for x in errors), errors
    with pytest.raises(ValueError):
        ev.build_bundle(events_root)


def test_bundle_records_carry_event_time_and_eastern_filing_day(events_root):
    write(events_root, registration())
    doc = ev.build_bundle(events_root)
    recs = {r["id"]: r for r in doc["records"]}
    assert recs["ex_ceo_2026|fact|f_resign"]["value"] == 0
    assert recs["ex_ceo_2026|fact|f_results"]["value"] == 17
    filing = recs["ex_ceo_2026|filing|doc_8k"]
    assert filing["date"] == "2026-03-04" and filing["value"] == 1  # 17:05 美东仍是 3 月 4 日
    assert doc["metadata"]["events"]["ex_ceo_2026"]["not_mentioned"][0]["terms"] == ["reason", "because"]


def test_fetch_downloads_only_missing_files_with_the_user_agent(events_root):
    write(events_root, registration())
    (ev.filings_dir(events_root) / "8k.htm").unlink()
    seen = []
    got = ev.fetch(events_root, "test agent", lambda url, headers: seen.append((url, headers)) or FILING)
    assert got == ["8k.htm"] and seen == [("https://example.test/8k.htm", {"User-Agent": "test agent"})]
    assert ev.fetch(events_root, "test agent", lambda *a: pytest.fail("already present")) == []
    with pytest.raises(ValueError):
        ev.fetch(events_root, "")


STUDY = {"study_id": "event_test", "title": "测试事件", "question": "?", "result_type": "descriptive", "branch": "event_timeline",
         "scope": {"market": "US", "start": "2026-03-01", "end": "2026-03-20", "frequency": "daily", "vintage_policy": "latest"},
         "data": {"evidence": "event_evidence"}, "method": {"event": "ex_ceo_2026"}, "limitations": ["测试"]}


def run(root):
    path = root / "bundle.json"
    path.write_text(json.dumps(ev.build_bundle(root)), encoding="utf-8")
    assert ingest(Registry.load(root), DataStore(root), "event_evidence", {"path": str(path)}).status == "created"
    spath = root / "config" / "studies" / "event_test.yaml"
    spath.write_text(yaml.safe_dump(STUDY, allow_unicode=True), encoding="utf-8")
    m = run_study(root, spath)
    assert m["status"] != "failed", m.get("error")
    return json.loads((root / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))


def test_study_orders_facts_and_filings_and_reports_disclosure_lag(events_root):
    write(events_root, registration())
    r = run(events_root)
    res = r["results"]
    assert [(x["kind"], x.get("fact")) for x in res["timeline"]] == [
        ("event", "f_resign"), ("event", "f_interim"), ("filing", None), ("scheduled", "f_results")]
    assert res["disclosure"]["lag_days"] == 1 and res["disclosure"]["date"] == "2026-03-04"
    assert res["summary"]["counts"]["event"] == 2 and [x["fact"] for x in res["scheduled"]] == ["f_results"]
    assert r["data_cutoff"] == "2026-03-04"  # 日程不是数据，不推后截止日
    assert {u["kind"] for u in r["unsupported"]} == {"scope"}
    assert r["validation"]["evidence_check"]["status"] == "pass"


def test_page_and_report_show_the_timeline_and_what_is_not_mentioned(events_root):
    from investment_os.reporting.events import sections
    from investment_os.site.i18n import use
    from investment_os.site.renderers import get_renderer
    from investment_os.site.targets import available

    write(events_root, registration())
    r = run(events_root)
    page = get_renderer("event_timeline").coverage_section(r)
    assert page.count('id="event-timeline"') == 1 and 'id="event-not-mentioned"' in page
    assert "Pat Doe" in page and "reason, because" in page
    with use("en", {}, set()):
        en = get_renderer("event_timeline").coverage_section(r)
    assert "CEO resigned" in en and "首席执行官辞职" not in en
    assert available(r, "event-timeline")
    body, title, part = sections(r)
    assert body[1][0] == "table" and len(body[1][2]) == 4 and part[0][2][0][0] == "原因"
