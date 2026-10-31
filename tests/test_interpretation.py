"""解释版本：发现、状态、规则版本与阈值在运行时固定并纳入复现；旧运行标为事后生成；
变化记录列出两次运行之间可以客观比较的差异。"""

import hashlib
import json
import shutil

import investment_os.research.findings as rules
from investment_os.data import DataStore, ingest
from investment_os.registry import Registry
from investment_os.runs import run_study, verify_run
from investment_os.site import build_site

from .conftest import PROJECT_ROOT, TREASURY_2024, treasury_connector
from .test_study_e2e import STUDY, load_result, write_study


def _strip_interpretation(project, run_id, strip=lambda r: r.pop("interpretation")):
    """模拟旧运行：结果里没有解释（或其他后加的字段），清单的结果校验值按旧结构重算。"""
    path = project / "runs" / run_id
    result = json.loads((path / "result.json").read_text(encoding="utf-8"))
    strip(result)
    (path / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in result.items() if k not in ("run_id", "generated_at", "result_hash")}
    manifest["result_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    result["result_hash"] = manifest["result_hash"]
    (path / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    for out in manifest["outputs"]:
        if out["path"].endswith("result.json"):
            out["sha256"] = hashlib.sha256((path / "result.json").read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_run_records_interpretation(loaded):
    m = run_study(loaded, write_study(loaded))
    interp = load_result(loaded, m)["interpretation"]
    assert interp["rule_version"] == "rates_curve-findings.v2"
    assert len(interp["rule_fingerprint"]) == 16 and interp["params"] == {"flat_bp": 5.0}
    assert interp["items"][0]["text"] == "10 年期收益率由 3.95% 升至 4.05%（+10 bp，2024-01-02 至 2024-01-05）。"
    assert interp["state"]["10Y 期间"] == "上升"


def test_verify_covers_the_interpretation(loaded, monkeypatch):
    m = run_study(loaded, write_study(loaded))
    # 只改阈值、不改数据与计算：+10 bp 在 100 bp 阈值下变成「基本持平」，复现不一致
    monkeypatch.setattr(rules, "FLAT_BP", 100.0)
    assert verify_run(loaded, m["run_id"])["reproduced"] is False
    monkeypatch.setattr(rules, "FLAT_BP", 5.0)
    assert verify_run(loaded, m["run_id"])["reproduced"] is True


def test_site_shows_recorded_findings_not_rewritten_by_new_rules(loaded, monkeypatch):
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    run_study(loaded, write_study(loaded))
    monkeypatch.setattr(rules, "FLAT_BP", 100.0)  # 发布网站时规则已变化
    build_site(loaded, loaded / "_site")
    page = (loaded / "_site" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert "10 年期收益率由 3.95% 升至 4.05%" in page  # 运行当时的措辞
    assert "基本持平：3.95%" not in page
    assert "在运行时按规则 rates_curve-findings.v2" in page and "当前规则已变化" in page


def test_old_runs_are_labelled_retrospective_and_still_reproduce(loaded):
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    m = run_study(loaded, write_study(loaded))
    _strip_interpretation(loaded, m["run_id"])
    assert verify_run(loaded, m["run_id"])["reproduced"] is True  # 复现不补写解释
    assert "interpretation" not in load_result(loaded, m)
    build_site(loaded, loaded / "_site")
    page = (loaded / "_site" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert "在发布网站时事后生成" in page and "该运行当时没有记录发现" in page


def test_change_log_lists_what_differed_between_runs(loaded):
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    # 第一次：窗口到 1 月 4 日，10Y +4 bp（基本持平）
    first = run_study(loaded, write_study(loaded, scope={**STUDY["scope"], "end": "2024-01-04"}))
    # 数据修订后第二次：窗口到 1 月 5 日，10Y +10 bp（上升）
    revised = TREASURY_2024.replace("01/02/2024,5.55", "01/02/2024,5.56")
    ingest(Registry.load(loaded), DataStore(loaded), "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: revised}))
    second = run_study(loaded, write_study(loaded))
    v1, v2 = (next(i["version_id"] for i in m["inputs"] if i["role"] == "curve") for m in (first, second))
    assert v1 != v2

    build_site(loaded, loaded / "_site")
    page = (loaded / "_site" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert "10Y 期间：基本持平 → 上升" in page
    assert "研究窗口 2024-01-02—2024-01-04 → 2024-01-02—2024-01-05" in page
    assert f"数据版本 ust_par_yield_curve：{v1} → {v2}" in page
    assert "不推断变化的原因" in page
    # 两次运行的代码与规则相同，不应列出代码或规则差异
    assert "代码或配置" not in page and "解释规则 rates_curve" not in page


def test_verify_keeps_unclassified_withheld_conclusions_of_old_runs(loaded):
    """旧运行的未输出结论没有 kind：复现不补写分类，否则同样的数据与计算会被判为不一致。"""
    path = write_study(loaded, method={**STUDY["method"], "key_tenors": ["2Y", "10Y", "6W"]})
    m = run_study(loaded, path)
    assert {u["kind"] for u in load_result(loaded, m)["unsupported"]} == {"data"}
    _strip_interpretation(loaded, m["run_id"], lambda r: [u.pop("kind") for u in r["unsupported"]])
    assert verify_run(loaded, m["run_id"])["reproduced"] is True
