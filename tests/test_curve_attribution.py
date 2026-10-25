"""国债曲线变化的会计分解（docs/study-curve-attribution.md）：恒等式、共同日期、阈值、敏感性、背景与端到端运行。"""

import json
import shutil

import pandas as pd
import pytest
import yaml

from investment_os.connectors.fred import FredGraphCsvConnector
from investment_os.contracts import DatasetVersion, ResultType
from investment_os.data import ingest
from investment_os.registry import parse_study
from investment_os.research.base import StudyInput
from investment_os.research.curve_attribution import run
from investment_os.research.findings import curve_attribution_findings, curve_attribution_state, interpret
from investment_os.runs import run_study, verify_run
from investment_os.site import build_site

from .conftest import NO_RETRY, PROJECT_ROOT, FakeHttp

STUDY = {
    "study_id": "attr_test", "title": "分解测试", "question": "q", "result_type": "explanatory",
    "branch": "curve_attribution",
    "scope": {"market": "US", "currency": "USD", "start": "2024-01-01", "end": "2024-12-31", "frequency": "daily",
              "vintage_policy": "latest"},
    "data": {"curve": "ust_par_yield_curve", "real": "fred_dfii10", "breakeven": "fred_t10yie", "policy": "fred_dff"},
    "method": {"long_tenor": "10Y", "short_tenor": "2Y", "share_min_bp": 10, "sensitivity_days": 1,
               "sensitivity_max_range_pp": 15, "identity_tolerance_bp": 0.5},
    "limitations": ["会计恒等式分解，不是因果推断"],
}


def _version(dataset_id: str, series: dict) -> DatasetVersion:
    return DatasetVersion(dataset_id=dataset_id, version_id=f"v-{dataset_id}", schema_version="series.v1",
                          content_hash="0" * 64, created_at="2026-10-24T00:00:00+00:00", rows=0, path="",
                          raw_snapshots=[], transform="normalize.v1", quality={}, series=series)


def _input(role: str, dataset_id: str, values: dict, series_id: str = "S", series_meta: dict | None = None):
    rows = [{"series_id": sid, "observation_at": pd.Timestamp(d), "value": v, "quality_status": "ok",
             "source_id": "test"}
            for sid, points in (values.items() if isinstance(next(iter(values.values())), dict) else
                                [(series_id, values)])
            for d, v in points.items()]
    return StudyInput(role=role, dataset_id=dataset_id, frame=pd.DataFrame(rows),
                      version=_version(dataset_id, series_meta or {series_id: {}}), source_status="access_verified")


DATES = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]


def _inputs(n10, real, be, n2, ff, extra=None):
    curve = _input("curve", "ust_par_yield_curve",
                   {"UST_PAR_10Y": dict(zip(DATES, n10)), "UST_PAR_2Y": dict(zip(DATES, n2))},
                   series_meta={"UST_PAR_10Y": {"tenor": "10 Yr"}, "UST_PAR_2Y": {"tenor": "2 Yr"}})
    out = {"curve": curve, "real": _input("real", "fred_dfii10", dict(zip(DATES, real))),
           "breakeven": _input("breakeven", "fred_t10yie", dict(zip(DATES, be))),
           "policy": _input("policy", "fred_dff", ff)}
    out.update(extra or {})
    return out


# 10Y 4.00 → 4.60 = 实际 1.80 → 2.30 + 盈亏平衡 2.20 → 2.30；2Y 4.30 → 4.20，联邦基金 5.33 → 4.33
N10 = [4.00, 4.10, 4.20, 4.30, 4.50, 4.60]
REAL = [1.80, 1.88, 1.96, 2.05, 2.21, 2.30]
BE = [2.20, 2.22, 2.24, 2.25, 2.29, 2.30]
N2 = [4.30, 4.28, 4.26, 4.24, 4.22, 4.20]
# 联邦基金利率含周末（01-06、01-07），只用与其他输入的共同日期
FF = {d: v for d, v in zip(DATES + ["2024-01-06", "2024-01-07"], [5.33, 5.33, 5.08, 4.83, 4.58, 4.33, 4.83, 4.83])}


def test_identities_and_shares():
    res = run(parse_study(STUDY), _inputs(N10, REAL, BE, N2, FF), None)
    r = res.results
    assert (r["start_date"], r["end_date"]) == ("2024-01-02", "2024-01-09")
    assert res.coverage["common_days"] == 6 and res.coverage["observations_by_part"]["policy"] == 8
    lg, sh, sl = r["long_end"], r["short_end"], r["slope"]
    assert lg["nominal"]["change_bp"] == pytest.approx(60) and lg["real"]["change_bp"] == pytest.approx(50)
    assert lg["breakeven"]["change_bp"] == pytest.approx(10) and abs(lg["residual_bp"]) < 1e-9
    assert lg["shares_pct"]["real"] == pytest.approx(500 / 6)
    assert sh["policy"]["change_bp"] == pytest.approx(-100) and sh["spread"]["change_bp"] == pytest.approx(90)
    assert sl["change_bp"] == pytest.approx(70)
    assert sum(sl["contributions_bp"].values()) == pytest.approx(sl["change_bp"])  # 斜率变化恰好由各项组成
    assert res.validation["identity_check"]["status"] == "pass" and not res.unsupported
    assert len(res.tables["path_bp"]) == 6 and res.tables["path_bp"][0]["long"] == 0


def test_findings_state_and_rule_metadata():
    res = run(parse_study(STUDY), _inputs(N10, REAL, BE, N2, FF), None).to_dict()
    texts = {f["id"]: f["text"] for f in curve_attribution_findings(res)}
    assert "10Y 名义收益率上升 60 bp：实际收益率 +50 bp，盈亏平衡通胀（通胀补偿）+10 bp" in texts["long_end"]
    assert "实际收益率约占 83%" in texts["long_end"]
    assert "政策利率变化 −100 bp，2Y 只变化 −10 bp" in texts["short_end"]
    assert texts["slope"].startswith("10Y − 2Y 变陡 70 bp；对斜率贡献最大的是联邦基金有效利率（+100 bp")
    assert curve_attribution_state(res) == {"10Y 主要来源": "实际收益率", "2Y 相对政策利率": "同向或基本持平",
                                            "10Y − 2Y 期间": "变陡"}
    it = interpret(res)
    assert it["rule_version"] == "curve_attribution-findings.v1" and it["rule_fingerprint"]


def test_small_moves_get_no_shares_and_unstable_shares_only_direction():
    flat10 = [4.00, 4.01, 4.02, 4.03, 4.04, 4.05]  # 10Y 只变化 5 bp
    real = [1.80, 1.81, 1.82, 1.83, 1.84, 1.85]
    res = run(parse_study(STUDY), _inputs(flat10, real, [x - y for x, y in zip(flat10, real)], N2, FF), None).to_dict()
    assert res["results"]["long_end"]["shares_pct"]["real"] is None
    assert "名义变化小于 10 bp，不给占比" in curve_attribution_findings(res)[0]["text"]

    # 期初附近实际收益率剧烈来回：移动端点时占比变化很大
    real2 = [1.80, 2.40, 1.95, 2.05, 2.21, 2.30]
    be2 = [a - b for a, b in zip(N10, real2)]
    res = run(parse_study(STUDY), _inputs(N10, real2, be2, N2, FF), None).to_dict()
    assert not res["results"]["sensitivity"]["real"]["stable"]
    assert "只描述方向" in curve_attribution_findings(res)[0]["text"]


def test_identity_failure_withdraws_the_long_end_attribution():
    real_bad = [r + (0.02 if i == 3 else 0) for i, r in enumerate(REAL)]  # 一天的口径不一致 2 bp
    res = run(parse_study(STUDY), _inputs(N10, real_bad, BE, N2, FF), None).to_dict()
    ident = res["validation"]["identity_check"]
    assert ident["status"] == "fail" and ident["failures"][0]["date"] == "2024-01-05"
    assert res["unsupported"] and res["unsupported"][0]["item"].startswith("长端分解")
    ids = [f["id"] for f in curve_attribution_findings(res)]
    assert "identity_failed" in ids and "long_end" not in ids


def test_background_is_described_not_decomposed():
    cpi = {f"{y}-{m:02d}-01": 300 + (y - 2023) * 12 + m for y in (2022, 2023) for m in range(1, 13)}
    cpi.update({"2024-01-01": 310.0})
    walcl = {"2023-12-27": 7_700_000.0, "2024-01-03": 7_690_000.0}
    extra = {"cpi": _input("cpi", "fred_cpiaucsl", cpi), "fed_assets": _input("fed_assets", "fred_walcl", walcl)}
    res = run(parse_study(STUDY), _inputs(N10, REAL, BE, N2, FF, extra), None).to_dict()
    bg = res["results"]["background"]
    assert bg["fed_assets"]["start"]["date"] == "2023-12-27" and bg["fed_assets"]["end"]["date"] == "2024-01-03"
    assert bg["cpi_yoy"]["end"]["month"] == "2024-01"
    assert set(res["results"]["slope"]["contributions_bp"]) == {"real", "breakeven", "residual", "policy", "spread"}
    assert any(f["id"] == "background" and "不参与分解" in f["text"] for f in curve_attribution_findings(res))


def test_branch_only_produces_explanatory_results():
    with pytest.raises(ValueError, match="解释与归因"):
        run(parse_study({**STUDY, "result_type": "descriptive"}), _inputs(N10, REAL, BE, N2, FF), None)
    assert parse_study(STUDY).result_type is ResultType.EXPLANATORY


def _fred(series: str, rows: dict) -> FredGraphCsvConnector:
    body = f"observation_date,{series}\n" + "".join(f"{d},{v}\n" for d, v in rows.items())
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    return FredGraphCsvConnector(http_get=FakeHttp({url: body.encode()}), **NO_RETRY)


def test_end_to_end_run_reproduces_and_publishes(loaded, registry, store):
    """夹具中的 Treasury 曲线（2024-01-02 至 01-05）加上与之满足恒等式的 FRED 序列，走完整流程。"""
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    ten = [3.95, 3.91, 3.99, 4.05]
    be = [2.20, 2.18, 2.21, 2.23]
    ingest(registry, store, "fred_t10yie", {}, _fred("T10YIE", dict(zip(days, be))))
    ingest(registry, store, "fred_dfii10", {}, _fred("DFII10", {d: round(t - b, 2) for d, t, b in zip(days, ten, be)}))
    ingest(registry, store, "fred_dff", {}, _fred("DFF", {"2024-01-01": 5.33, **dict.fromkeys(days, 5.33),
                                                           "2024-01-06": 5.33}))
    study = {**STUDY, "scope": {**STUDY["scope"], "end": "2024-01-31"},
             "data": {**STUDY["data"], "cross_check": {"dataset": "fred_dgs10", "required": False}}}
    path = loaded / "config" / "studies" / "attr_test.yaml"
    path.write_text(yaml.safe_dump(study, allow_unicode=True), encoding="utf-8")
    manifest = run_study(loaded, path)
    assert manifest["status"] == "success"
    result = json.loads((loaded / "runs" / manifest["run_id"] / "result.json").read_text())
    assert result["results"]["long_end"]["nominal"]["change_bp"] == pytest.approx(10)
    assert result["results"]["short_end"]["policy"]["change_bp"] == pytest.approx(0)
    assert result["validation"]["cross_check"]["status"] == "pass"
    assert result["validation"]["raw_spot_check"]["status"] == "pass"
    assert result["interpretation"]["rule_version"] == "curve_attribution-findings.v1"
    assert verify_run(loaded, manifest["run_id"])["reproduced"] is True

    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    build_site(loaded, loaded / "_site")
    page = (loaded / "_site" / "studies" / "attr_test" / "index.html").read_text(encoding="utf-8")
    assert "分解明细与背景" in page and "恒等式核对 · 通过" in page and "attribution_bars.png" in page
    cap = (loaded / "_site" / "map.html").read_text(encoding="utf-8")
    assert "<code>curve_attribution</code>" in cap  # 能力地图：解释与归因有了实现的分支
