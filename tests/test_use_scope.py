"""运行记录用途核验相对研究期间的位置；复现按原运行固定；页面显示「部分在范围内」。"""

import hashlib
import json
import shutil

from investment_os.runs import run_study, verify_run
from investment_os.site import build_site

from .conftest import PROJECT_ROOT
from .test_study_e2e import write_study


def _set_verified_through(project, old, new):
    path = project / "config" / "sources.yaml"
    text = path.read_text(encoding="utf-8")
    assert f'valid_through: "{old}"' in text
    path.write_text(text.replace(f'valid_through: "{old}"', f'valid_through: "{new}"'), encoding="utf-8")


def _curve_input(inputs):
    return next(i for i in inputs if i["role"] == "curve")


def test_run_records_in_scope(loaded):
    m = run_study(loaded, write_study(loaded))  # 研究期间 2024-01-02 至 2024-01-05
    inp = _curve_input(m["inputs"])
    assert inp["source_status"] == "use_verified"
    assert inp["use_scope"]["status"] == "in_scope" and inp["use_scope"]["uncovered"] == []
    # 未获用途核验的输入不写 use_scope
    assert "use_scope" not in next(i for i in m["inputs"] if i["role"] == "cross_check")


def test_partial_scope_is_recorded_frozen_and_shown(loaded):
    _set_verified_through(loaded, "2026-10-22", "2024-01-03")
    m = run_study(loaded, write_study(loaded))
    scope = _curve_input(m["inputs"])["use_scope"]
    assert scope["status"] == "partial" and scope["uncovered"] == [["2024-01-04", "2024-01-05"]]
    result = json.loads((loaded / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))
    assert _curve_input(result["inputs"])["use_scope"] == scope

    # 之后扩大核验范围：复现仍按原运行记录的位置，结果校验值不变
    _set_verified_through(loaded, "2024-01-03", "2026-10-22")
    assert verify_run(loaded, m["run_id"])["reproduced"] is True

    # 页面：研究页证据面板与首页证据摘要显示部分在范围内及范围外日期
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    build_site(loaded, loaded / "_site")
    study = (loaded / "_site" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert "用途已验证 · 部分在范围内" in study and "2024-01-04 至 2024-01-05" in study
    home = (loaded / "_site" / "index.html").read_text(encoding="utf-8")
    assert "用途核验部分在范围内（ust_par_yield_curve 范围外：2024-01-04 至 2024-01-05）" in home


def test_old_manifest_without_use_scope_still_reproduces(loaded):
    """旧清单没有 use_scope：复现时不补写，结果结构与校验值保持原样。"""
    m = run_study(loaded, write_study(loaded))
    path = loaded / "runs" / m["run_id"]
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    result = json.loads((path / "result.json").read_text(encoding="utf-8"))
    for inputs in (manifest["inputs"], result["inputs"]):
        for i in inputs:
            i.pop("use_scope", None)
    body = {k: v for k, v in result.items() if k not in ("run_id", "generated_at", "result_hash")}
    manifest["result_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert verify_run(loaded, m["run_id"])["reproduced"] is True
