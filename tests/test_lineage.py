"""研究依赖图：用真实仓库做阳性/阴性反测，用构造的小仓库测断链与信号解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from investment_os import lineage
from investment_os.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph():
    return lineage.build(ROOT)


def test_known_study_chain_reaches_compute_dataset_connector_and_source(graph):
    """阳性：国债曲线研究经分支、import、数据集、接入器一直追到来源。"""
    reach = set(graph["reach"]["ust_curve_2024"])
    for nid in ("mod:investment_os.research.rates_curve", "mod:investment_os.analytics.rates",
                "mod:investment_os.validation.crosscheck", "mod:investment_os.tenor",
                "ds:ust_par_yield_curve", "mod:investment_os.connectors.treasury", "src:ust_treasury",
                "ds:fred_dgs10", "mod:investment_os.connectors.fred", "src:fred_api",
                # 运行框架所有研究共用
                "mod:investment_os.research.findings", "mod:investment_os.validation.reference"):
        assert nid in reach, nid
    # 不相干的分支与来源不在链上
    assert "mod:investment_os.research.industry" not in reach
    assert "src:ken_french" not in reach
    ch = lineage.chain(graph, "ust_curve_2024")
    assert [t["label"] for t in ch["compute"]] == ["research/rates_curve.py"]
    signals = {t["label"]: t["signal"] for t in ch["data"]}
    assert signals == {"ust_par_yield_curve": "data.curve", "fred_dgs10": "data.cross_check?"}


def test_evidence_bundle_chain_reaches_producer_and_declared_scripts(graph):
    """证据包数据集：自动识别 DATASET_ID 的生成模块；经中间文件的环节由 config/lineage.yaml 声明。"""
    assert "mod:investment_os.earnings" in graph["reach"]["earnings_googl_2026q3"]
    assert "cfg:config/earnings/googl_2026q3.yaml" in graph["reach"]["earnings_googl_2026q3"]
    dossier = set(graph["reach"]["us_industry_dossier"])
    assert {"script:scripts/prepare_industry.py", "script:scripts/build_industry_fundamentals.py",
            "script:scripts/prepare_industry_cases.py"} <= dossier
    assert "script:scripts/build_industry_fundamentals.py" not in graph["reach"]["us_industry_12"]


def test_module_confirmed_unused_by_hand_is_listed(graph):
    """阴性：analytics/returns.py 只被测试导入（grep 已手工确认），任何研究都到达不了。"""
    unused = {u["id"]: u for u in graph["unused"]}
    assert "mod:investment_os.analytics.returns" in unused
    assert unused["mod:investment_os.analytics.returns"]["others"] == ["tests/test_analytics.py"]
    assert not graph["used_by"].get("mod:investment_os.analytics.returns")
    # 模块被用到、但其中的接入器没有数据集被研究用到
    assert "connector:fred_api_vintages" in unused  # 4 个 ALFRED 数据集都没有研究用
    assert "connector:fred_api_current" not in unused
    # 被研究用到的不列入
    assert "mod:investment_os.analytics.rates" not in unused
    assert "ds:ust_par_yield_curve" not in unused


def test_fan_in_and_impact(graph):
    fan = dict(lineage.fan_in(graph, ("compute", "fetch", "script")))
    assert fan["mod:investment_os.research.findings"] == len(graph["studies"])
    assert fan["mod:investment_os.research.rates_curve"] == 2
    impact = {r["source"]: r for r in lineage.impact(graph)}
    assert "ust_curve_2024" in impact["src:ust_treasury"]["studies"]
    assert set(impact["src:ust_treasury"]["datasets"]) == {"ust_par_yield_curve"}


def test_repository_has_no_broken_links(graph):
    assert graph["broken"] == []
    assert graph["counts"]["studies"] == len(list((ROOT / "config" / "studies").glob("*.yaml")))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_broken_links_in_a_small_repo(tmp_path):
    pkg = tmp_path / "src" / "investment_os"
    _write(pkg / "__init__.py", "")
    _write(pkg / "research" / "__init__.py", "from . import good\n")
    _write(pkg / "research" / "base.py", "def register_branch(name):\n    return lambda f: f\n")
    _write(pkg / "research" / "good.py",
           "from .base import register_branch\nfrom ..analytics import used\nfrom ..analytics.gone import x\n"
           "@register_branch('good')\ndef run():\n    from ..analytics import lazy\n")
    _write(pkg / "analytics" / "__init__.py", "")
    _write(pkg / "analytics" / "used.py", "def f():\n    pass\n")
    _write(pkg / "analytics" / "lazy.py", "def f():\n    pass\n")
    _write(pkg / "analytics" / "orphan.py", "def f():\n    pass\n")
    _write(pkg / "connectors" / "__init__.py", "")
    _write(pkg / "connectors" / "web.py", "class Web:\n    name = 'web'\n")
    _write(tmp_path / "config" / "sources.yaml", "sources:\n  - {id: pub, name: Pub}\n")
    _write(tmp_path / "config" / "datasets.yaml",
           "datasets:\n  a: {source_id: pub, connector: web}\n  b: {source_id: nowhere, connector: ghost}\n")
    _write(tmp_path / "config" / "studies" / "s1.yaml",
           "study_id: s1\ntitle: S1\nbranch: good\ndata: {x: a, y: missing_ds}\nmethod: {earnings: nofile}\n")
    _write(tmp_path / "config" / "studies" / "s2.yaml", "study_id: s2\ntitle: S2\nbranch: nobranch\ndata: {x: b}\n")
    g = lineage.build(tmp_path)
    kinds = sorted((b["kind"], b["to"]) for b in g["broken"])
    assert kinds == [("branch", "nobranch"), ("connector", "ghost"), ("data.y", "missing_ds"),
                     ("import", "investment_os.analytics.gone"), ("method.earnings", "config/earnings/nofile.yaml"),
                     ("source_id", "nowhere")]
    reach = set(g["reach"]["s1"])
    assert {"mod:investment_os.analytics.used", "mod:investment_os.analytics.lazy", "ds:a",
            "mod:investment_os.connectors.web", "src:pub"} <= reach
    unused = {u["id"] for u in g["unused"]}
    assert "mod:investment_os.analytics.orphan" in unused
    assert "mod:investment_os.analytics.used" not in unused


def test_cli_writes_markdown(tmp_path, capsys):
    out = tmp_path / "lineage.md"
    assert main(["--root", str(ROOT), "lineage", "--md", str(out), "--check"]) == 0
    text = out.read_text(encoding="utf-8")
    assert "# 研究依赖清单" in text and "`analytics/returns.py`" in text
    assert "断链 0" in capsys.readouterr().out
