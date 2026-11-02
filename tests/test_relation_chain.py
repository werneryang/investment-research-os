"""关系链：展开规则、登记的新字段与外部来源、年报营收解析、研究分支（docs/relation-chain-design.md）。全部离线。"""

import copy
import hashlib
import json

import pytest
import yaml

from investment_os.data import ingest
from investment_os.runs import run_study
from investment_os.supply_chain.chain import expand
from investment_os.supply_chain.relation_bundle import inline_revenue

from .test_supply_chain import mini, run_check  # noqa: F401  复用迷你登记


def rel(rid, provider, recipient, activity=None, recipient_activity=None, status="reviewed", kind="supply",
        evidence_class="primary", available_at="2026-02-26", **extra):
    return rid, {"type": kind, "provider": provider, "recipient": recipient, "activity": activity,
                 "recipient_activity": recipient_activity, "status": status, "evidence_class": evidence_class,
                 "available_at": available_at, "claims": [], "disclosed_by": [], **extra}


def snap(*relations, searches=None):
    names = ["root", "a", "b", "c", "d", "e", "f", "g", "rival", "x"]
    entities = {n: {"name": n.upper(), "type": "company"} for n in names}
    entities["anon"] = {"name": "Anon", "type": "anonymous", "parent": "root"}
    return {"entities": entities, "activities": {}, "relations": dict(relations), "claims": {}, "documents": {},
            "searches": searches or {}}


def edges(chain, layer):
    return sorted(e["to"] for e in chain["layers"][layer - 1])


def reasons(chain):
    return {(b["node"], b["reason"]) for b in chain["breakpoints"]}


def test_upstream_and_downstream_do_not_mix_and_competition_is_a_side_note():
    s = snap(rel("r1", "a", "root", "act_foundry"), rel("r2", "root", "x", "act_design", "act_cloud"),
             ("c1", {"type": "competition", "parties": ["a", "rival"], "market": "m", "status": "candidate",
                     "available_at": "2026-01-01", "claims": []}))
    up, down = expand(s, "root", "upstream"), expand(s, "root", "downstream")
    assert edges(up, 1) == ["a"] and edges(down, 1) == ["x"]
    assert [x["relation"] for x in up["side_relations"]] == ["c1"] and down["side_relations"] == []


def test_next_layer_follows_only_inputs_that_serve_the_arriving_business():
    s = snap(rel("r1", "a", "root", "act_foundry"),
             rel("r2", "b", "a", "act_materials", "act_foundry"),     # 服务于 a 的代工业务：展开
             rel("r3", "c", "a", "act_materials", "act_phones"),      # 服务于 a 的其他业务：不进入链条
             rel("r4", "d", "a", "act_materials"))                    # 未说明服务于哪项业务：不进入链条
    up = expand(s, "root", "upstream")
    assert edges(up, 2) == ["b"]
    assert ("b", "depth_limit") in reasons(up)


def test_stops_are_recorded_with_their_reasons():
    s = snap(rel("r1", "a", "root", "act_foundry"), rel("r2", "b", "root", None, activity_gap="未说明"),
             rel("r3", "c", "root", "act_x", status="candidate"), rel("r4", "anon", "root", "act_x"),
             rel("r5", "d", "root", "act_x", evidence_class="external"),
             rel("r6", "e", "root", "act_x"),
             searches={"q1": {"id": "q1", "subject": "e", "direction": "upstream", "available_at": "2026-04-17",
                              "document": "doc", "result": "not_found"}})
    up = expand(s, "root", "upstream")
    assert {("a", "not_searched"), ("b", "activity_unknown"), ("c", "unreviewed"), ("anon", "anonymous"),
            ("d", "external_only"), ("e", "searched_not_disclosed")} <= reasons(up)
    # 未复核的关系仍显示在链上，只是不展开
    assert "c" in edges(up, 1)


def test_corroborated_external_relations_expand_only_when_enabled_and_mark_the_path():
    s = snap(rel("r1", "a", "root", "act_packaging", evidence_class="external_corroborated"),
             rel("r2", "b", "a", "act_substrate", "act_packaging"))
    assert ("a", "external_only") in reasons(expand(s, "root", "upstream"))
    up = expand(s, "root", "upstream", expand_corroborated=True)
    assert edges(up, 2) == ["b"] and up["layers"][1][0]["external_path"]


def test_as_of_filters_relations_and_searches_and_cycles_are_not_expanded():
    s = snap(rel("r1", "a", "root", "act_x"), rel("r2", "b", "root", "act_x", available_at="2026-12-01"),
             rel("r3", "root", "a", "act_y", "act_x"))
    up = expand(s, "root", "upstream", as_of="2026-10-31")
    assert edges(up, 1) == ["a"]
    assert [e["cycle"] for e in up["layers"][1]] == [True]  # 回到起点：只记录这条边


def test_same_company_reached_through_two_businesses_expands_each_business():
    s = snap(rel("r1", "a", "root", "act_foundry", kind="foundry"), rel("r2", "a", "root", "act_memory"),
             rel("r3", "b", "a", "act_wafer", "act_foundry"), rel("r4", "c", "a", "act_chem", "act_memory"))
    assert edges(expand(s, "root", "upstream"), 2) == ["b", "c"]


def test_catalog_requires_share_owner_and_consistent_searches(mini, tmp_path):
    root, data = mini
    data = copy.deepcopy(data)
    data["relations"]["relations"][0]["share"] = {"value": 0.2, "numerator": "n", "denominator": "d", "period": "FY"}
    data["relations"]["relations"][0]["recipient_activity"] = "act_unknown"
    data["searches"] = {"searches": [{"id": "q", "document": "doc", "subject": "co_a", "direction": "upstream",
                                      "looked_for": "?", "method": "m", "searched_at": "2026-10-31",
                                      "result": "found", "relations": []}]}
    rep = run_check(root, data)
    assert any("of 写明" in x for x in rep.errors)
    assert any("recipient_activity act_unknown 未登记" in x for x in rep.errors)
    assert any("记为 found" in x for x in rep.errors)


def test_external_reports_are_checked_by_file_hash_and_kept_apart_from_primary_evidence(mini):
    root, data = mini
    data = copy.deepcopy(data)
    report = b"private report"
    (root / "data" / "supply_chain" / "external").mkdir(parents=True)
    (root / "data" / "supply_chain" / "external" / "r.pdf").write_bytes(report)
    data["claims"]["claims"].append({"id": "clm_ext", "type": "external_report", "publisher": "Broker", "title": "T",
                                     "published_at": "2026-09-01", "channel": "Fidelity", "file": "r.pdf",
                                     "sha256": hashlib.sha256(report).hexdigest(), "locator": "p. 3",
                                     "summary": "Names a supplier", "display": "summary", "origin_type": "observed",
                                     "review_status": "candidate"})
    data["relations"]["relations"][0]["claims"] = ["clm_ext"]
    data["relations"]["relations"][0]["corroborated_by"] = ["clm_foundry"]
    rep = run_check(root, data)
    assert rep.claim_checks["clm_ext"] == "verified" and rep.evidence_class["rel"] == "external_corroborated"
    assert rep.evidence_class["cmp"] == "primary"
    data["claims"]["claims"][-1]["sha256"] = "0" * 64
    assert any("SHA256 与登记不一致" in x for x in run_check(root, data).errors)
    data["claims"]["claims"][-1]["excerpt"] = "quoted text"
    with pytest.raises(ValueError, match="不保存原文摘录"):
        run_check(root, data)


IXBRL = """<xbrli:context id="c1"><xbrli:entity></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
<xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c2"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">x:AMember</xbrldi:explicitMember>
<xbrldi:explicitMember dimension="srt:ConsolidationItemsAxis">us-gaap:OperatingSegmentsMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c3"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">x:USMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c4"><xbrli:entity></xbrli:entity><xbrli:period><xbrli:startDate>2025-10-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<ix:nonFraction unitRef="usd" contextRef="c1" name="us-gaap:Revenues" scale="6">1,234.5</ix:nonFraction>
<ix:nonFraction unitRef="usd" contextRef="c1" name="us-gaap:Revenues" scale="6">1,234.5</ix:nonFraction>
<ix:nonFraction unitRef="usd" contextRef="c2" name="us-gaap:Revenues" scale="6">1,000</ix:nonFraction>
<ix:nonFraction unitRef="usd" contextRef="c3" name="us-gaap:Revenues" scale="6">900</ix:nonFraction>
<ix:nonFraction unitRef="usd" contextRef="c4" name="us-gaap:Revenues" scale="6">300</ix:nonFraction>
<ix:nonFraction unitRef="twd" contextRef="c1" name="ifrs-full:RevenueFromContractsWithCustomers" scale="6">3,809,054.3</ix:nonFraction>"""


def test_inline_revenue_keeps_annual_consolidated_and_business_segments_only():
    rows = inline_revenue(IXBRL)
    got = sorted((r["tag"], r["segment"] or "", r["unit"], r["value"]) for r in rows)
    assert got == [("ifrs-full:RevenueFromContractsWithCustomers", "", "TWD", pytest.approx(3_809_054.3e6)),
                   ("us-gaap:Revenues", "", "USD", 1_234.5e6), ("us-gaap:Revenues", "x:AMember", "USD", 1_000e6)]


def test_inline_revenue_prefers_the_most_precise_fact_and_rejects_conflicts():
    # ASML 年报表格里的 32,667.3 百万欧元，与叙述中按十亿取整的 32.7 同属一个事实：取小数位多的
    head = ('<xbrli:context id="c1"><xbrli:entity></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>'
            '<xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>')
    rounded = '<ix:nonFraction unitRef="eur" contextRef="c1" decimals="-8" name="us-gaap:Revenues" scale="9">32.7</ix:nonFraction>'
    precise = '<ix:nonFraction unitRef="eur" contextRef="c1" decimals="-5" name="us-gaap:Revenues" scale="6">32,667.3</ix:nonFraction>'
    for text in (head + rounded + precise, head + precise + rounded):
        assert [r["value"] for r in inline_revenue(text)] == [pytest.approx(32_667.3e6)]
    other = precise.replace("32,667.3", "32,000.0")
    with pytest.raises(ValueError, match="不一致"):
        inline_revenue(head + precise + other)


def test_site_names_the_root_and_lists_partnerships_with_competition():
    from investment_os.site.relation_chain import _short, _side, _summary

    assert [_short(n) for n in ("NVIDIA Corporation", "Intel Corporation", "Micron Technology, Inc.", "Fabrinet")] == \
        ["NVIDIA", "Intel", "Micron Technology", "Fabrinet"]
    side = {"relation": "ptn", "type": "partnership", "party_names": ["Intel", "NVIDIA"], "market": None}
    rival = {"relation": "cmp", "type": "competition", "party_names": ["AMD", "Intel"], "market": "DCAI"}
    html = _side({"upstream": {"side_relations": [rival, side]}, "downstream": {"side_relations": [side]}})
    assert html.count("<li>") == 2 and "合作" in html and "竞争 · DCAI" in html  # 两条链都列出的旁注只显示一次
    named = {"counterparty_type": "company"}
    res = {"root_name": "Intel Corporation",
           "summary": {"upstream_named": 2, "downstream_named": 0, "reverse_searched": 15, "reverse_found": 0,
                       "breakpoints": {"upstream": {"activity_unknown": 1}}},
           "upstream": {"layers": [[], [named, {"counterparty_type": "anonymous"}, {"counterparty_type": "anonymous"}]]}}
    text = _summary({"results": res})
    assert "点名 1 家公司；2 项为未点名的投入类别" in text and "15 家样本公司年报有 0 家点名 Intel" in text


def _bundle(searched=True):
    relations = dict([rel("r_sup", "co_s", "co_root", "act_foundry", disclosed_by=["co_root"],
                          share=None, limits="列举"),
                      rel("r_cust", "co_root", "anon_c", "act_design", share={"value": 0.2, "numerator": "n",
                                                                             "denominator": "d", "period": "FY", "of": "co_root"})])
    for r in relations.values():
        r["claims"] = ["clm"]
    searches = {"q": {"id": "q", "document": "doc_x", "subject_name": "Buyer", "subject_cik": 9, "direction": "downstream",
                      "counterpart": "co_root", "looked_for": "?", "method": "全文检索", "searched_at": "2026-10-31",
                      "result": "not_found", "available_at": "2026-03-01"}} if searched else {}
    snapshot = {"catalog_version": "v2",
                "entities": {"co_root": {"name": "Root", "type": "company"}, "co_s": {"name": "Supplier", "type": "company"},
                             "anon_c": {"name": "匿名客户", "type": "anonymous", "parent": "co_root"}},
                "activities": {"act_foundry": {"name": "晶圆代工"}, "act_design": {"name": "芯片设计"}},
                "relations": relations,
                "claims": {"clm": {"type": "filing_text", "locator": "Item 1", "excerpt": "We use S.", "url": "u", "form": "10-K"}},
                "documents": {"doc_x": {"form": "10-K", "url": "u2", "document_period_end": "2025-12-31"}},
                "searches": searches}

    def revenue(entity, end, value, segment=None):
        return {"id": f"{entity}|{segment}|{end}", "date": end, "value": value, "published_at": "2026-02-26",
                "kind": "segment_revenue" if segment else "revenue", "entity": entity, "document": f"doc_{entity}",
                "accession": "A", "form": "10-K", "document_period_end": "2026-01-31", "tag": "us-gaap:Revenues",
                "start": "x", "end": end, "segment": segment, "unit": "USD"}
    records = [revenue("co_root", "2025-01-31", 100.0), revenue("co_root", "2026-01-31", 150.0),
               revenue("co_root", "2026-01-31", 120.0, "s:A"), revenue("co_root", "2026-01-31", 30.0, "s:B"),
               revenue("co_root", "2025-01-31", 70.0, "s:A"), revenue("co_root", "2025-01-31", 30.0, "s:B")]
    return {"schema": "industry-evidence.v1", "unit": "mixed", "records": records,
            "metadata": {"built_at": "2026-10-31", "catalog_check": {"errors": [], "warnings": [], "verified": {"excerpt": 1}},
                         "catalog_files": {}, "revenue_documents": {}, "snapshot": snapshot}}


STUDY = {"study_id": "chain_test", "title": "测试", "question": "?", "result_type": "descriptive", "branch": "relation_chain",
         "scope": {"market": "US", "start": "2024-01-01", "end": "2026-10-31", "frequency": "annual", "vintage_policy": "latest"},
         "data": {"evidence": "relation_chain_evidence"}, "method": {"root": "co_root", "depth": 2, "as_of": "2026-10-31"},
         "limitations": ["测试"]}


def run_doc(project, registry, store, doc):
    path = project / "bundle.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ingest(registry, store, "relation_chain_evidence", {"path": str(path)}).status == "created"
    spath = project / "config" / "studies" / "chain.yaml"
    spath.write_text(yaml.safe_dump(STUDY, allow_unicode=True), encoding="utf-8")
    m = run_study(project, spath)
    assert m["status"] != "failed", m.get("error")
    return json.loads((project / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))


def test_study_reports_chain_breakpoints_reverse_search_and_same_filing_growth(project, registry, store):
    r = run_doc(project, registry, store, _bundle())
    res = r["results"]
    assert [e["to"] for e in res["upstream"]["layers"][0]] == ["co_s"]
    assert res["upstream"]["breakpoint_counts"] == {"not_searched": 1}
    assert res["downstream"]["breakpoint_counts"] == {"anonymous": 1}
    assert res["reverse_search"][0]["subject"] == "Buyer" and res["summary"]["reverse_found"] == 0
    root = res["revenue"]["co_root"]
    assert root["consolidated"][1]["growth"] == pytest.approx(0.5)
    assert r["validation"]["segment_total"]["status"] == "pass"
    items = {u["item"]: u["kind"] for u in r["unsupported"]}
    assert items["Q2b 下游客户资本开支对照"] == "data" and items["因果判断"] == "scope"
    assert "营收对照：Supplier" in items  # 链上公司没有年报营收时如实列出


def test_study_refuses_bundles_with_unchecked_catalog(project, registry, store):
    doc = _bundle()
    doc["metadata"]["catalog_check"]["warnings"] = ["原文不在本地"]
    path = project / "bundle.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    ingest(registry, store, "relation_chain_evidence", {"path": str(path)})
    spath = project / "config" / "studies" / "chain.yaml"
    spath.write_text(yaml.safe_dump(STUDY, allow_unicode=True), encoding="utf-8")
    assert run_study(project, spath)["status"] == "failed"


def _edge(layer, src, to, relation, kind="supply", status="reviewed", evidence_class="primary", counterparty="company",
          share=None):
    return {"layer": layer, "from": src, "from_name": src.upper(), "to": to, "to_name": to.upper(), "relation": relation,
            "type": kind, "activity_name": None, "status": status, "evidence_class": evidence_class,
            "external_path": False, "counterparty_type": counterparty, "share": share}


def test_chain_graph_draws_one_box_per_subject_and_one_link_per_relationship():
    from investment_os.site.relation_chain import _wrap, chain_graph

    up = {"layers": [[_edge(1, "root", "s", "r1", kind="foundry"), _edge(1, "root", "s", "r2"),
                      _edge(1, "root", "t", "r3", status="candidate", evidence_class="external", share={"value": 0.163})],
                     [_edge(2, "s", "anon_in", "r4", counterparty="anonymous")]],
          "breakpoints": [{"node": "s", "relation": "r2", "reason": "not_searched", "layer": 2}]}
    down = {"layers": [[_edge(1, "root", "buyer<b>", "r5", counterparty="anonymous")]], "breakpoints": []}
    res = {"root": "root", "root_name": "Root Co", "depth": 2, "upstream": up, "downstream": down,
           "reverse_search": [{"subject": "Buyer"}], "summary": {"reverse_searched": 3, "reverse_found": 0}}
    svg = chain_graph({"results": res})
    assert svg.count('<path class="cg-edge') == 5  # 同一对主体的两条关系各画一条
    assert svg.count('class="cg-node') == 6        # s 只有一个框；另有 t、anon_in、root、buyer、反向检索
    assert 'class="cg-edge unreviewed external"' in svg and "占比 16.3%" in svg
    assert "停止：尚未查阅" in svg and 'href="#chain-reverse-search"' in svg
    assert "BUYER&lt;B&gt;" in svg and "<b>" not in svg  # SVG 文字转义，不含 HTML 标签
    assert _wrap("Taiwan Semiconductor Manufacturing Company Limited and more words", 13, 2)[-1].endswith("…")
    assert _wrap("台积电 2025 年设备供应商（未点名）", 13, 3) == ["台积电 2025 年设备供应商（", "未点名）"]
