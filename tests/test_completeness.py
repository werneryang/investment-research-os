"""完整性判断的反例：覆盖达标不等于期间完整；按指标所依赖的数据判断；尚未发布与缺失分开。"""

from datetime import datetime, timezone

import pandas as pd
import pytest

from investment_os.data import ingest
from investment_os.registry import Registry
from investment_os.research.findings import completeness, coverage_summary, findings
from investment_os.runs import run_study, verify_run

from .conftest import TREASURY_2024, treasury_connector
from .test_study_e2e import STUDY, load_result, write_study

HEADER = TREASURY_2024.splitlines()[0]
ROW_VALUES = "5.54,5.51,5.48,5.43,5.24,4.84,4.40,4.18,4.01,4.03,4.05,4.37,4.21"


def _csv(dates, blank_2y=()):
    rows = []
    for d in dates:
        values = ROW_VALUES.split(",")
        if d in blank_2y:
            values[6] = ""  # 2 Yr 列
        rows.append(f"{pd.Timestamp(d):%m/%d/%Y},{','.join(values)}")
    return "\n".join([HEADER, *rows]) + "\n"


def _load(project, csv):
    reg = Registry.load(project)
    from investment_os.data import DataStore
    ingest(reg, DataStore(project), "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: csv}))


def _expected(project, start, end):
    cal = Registry.load(project).calendars["us_treasury_daily"]
    return [d.date().isoformat() for d in cal.expected_dates(pd.Timestamp(start), pd.Timestamp(end))]


def _run(project, start, end, min_cov=0.95, clock=None, tenors=("2Y", "10Y")):
    scope = {**STUDY["scope"], "start": start, "end": end}
    method = {**STUDY["method"], "key_tenors": list(tenors), "min_coverage": min_cov, "curvature": []}
    kwargs = {"clock": clock} if clock else {}
    m = run_study(project, write_study(project, scope=scope, method=method), **kwargs)
    assert m["status"] != "failed", m.get("error")
    return m, load_result(project, m)


def test_coverage_above_threshold_with_a_gap_is_not_complete(project):
    """审查反例 1：预期 20 天、实际 19 天、门槛 95% —— 覆盖达标，但期间不完整。"""
    days = _expected(project, "2024-01-02", "2024-01-30")
    assert len(days) == 20
    _load(project, _csv([d for d in days if d != "2024-01-17"]))
    m, r = _run(project, "2024-01-02", "2024-01-30")
    cov = r["coverage"]
    assert cov["coverage_acceptable"] is True
    assert cov["period_complete"] is False and cov["completeness"] == "gaps"
    assert cov["missing_dates"] == ["2024-01-17"]
    assert m["status"] == "partial"
    assert r["results"]["levels"]["10Y"]["sample"] == "observed"
    texts = " ".join(f["text"] for f in findings(r))
    # 测试数据中 2Y 高于 10Y，每天都倒挂；措辞只描述已观测日期
    assert "已观测的 19 个交易日中倒挂 19 天（缺 1 天，不能推及整个期间）" in texts
    assert "期间倒挂" not in texts


def test_full_coverage_on_unverified_calendar_is_not_complete(project):
    """审查反例 2：20/20 天，但这些日期不在日历核验范围内 —— 无法证明完整。"""
    path = project / "config" / "calendars.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace('verified_from: "2024-01-01"',
                                                             'verified_from: "2024-06-01"'), encoding="utf-8")
    days = _expected(project, "2024-01-02", "2024-01-30")
    _load(project, _csv(days))
    m, r = _run(project, "2024-01-02", "2024-01-30")
    cov = r["coverage"]
    assert cov["missing_days"] == 0 and cov["coverage_acceptable"] is True
    assert cov["period_complete"] is False and cov["completeness"] == "unverified_calendar"
    assert m["status"] == "partial"
    assert r["results"]["spreads"]["2Y-10Y"]["sample"] == "observed"


def test_spread_completeness_requires_both_ends_on_the_same_day(project):
    """某天有 10Y 但没有 2Y：10Y 完整，2Y 与 10Y − 2Y 利差不完整。"""
    days = _expected(project, "2024-01-02", "2024-01-05")
    _load(project, _csv(days, blank_2y={"2024-01-03"}))
    _, r = _run(project, "2024-01-02", "2024-01-05", min_cov=0.7)
    metrics = r["coverage"]["metrics"]
    assert metrics["levels"]["10Y"] == {"observed": 4, "due": 4, "missing": 0, "complete": True}
    assert metrics["levels"]["2Y"]["missing"] == 1
    assert metrics["spreads"]["2Y-10Y"] == {"observed": 3, "due": 4, "missing": 1, "complete": False}
    # 曲线日期本身完整，但依赖 2Y 的指标是已观测样本
    assert r["coverage"]["completeness"] == "complete"
    assert r["results"]["levels"]["10Y"]["sample"] == "complete"
    sp = r["results"]["spreads"]["2Y-10Y"]
    assert sp["sample"] == "observed" and sp["inversion"]["observations"] == 3
    text = next(f["text"] for f in findings(r) if f["id"] == "spread_2Y-10Y")
    assert "已观测的 3 个交易日中" in text and "缺 1 天" in text


def test_not_yet_published_is_not_missing(project):
    """评估时 1 月 5 日尚未到发布时间（次日 0 点规则）：不计入分母，也不算缺失。"""
    days = _expected(project, "2024-01-02", "2024-01-05")
    _load(project, _csv(days[:-1]))  # 没有 1 月 5 日
    at = datetime(2024, 1, 5, 20, 0, tzinfo=timezone.utc)
    m, r = _run(project, "2024-01-02", "2024-01-05", clock=lambda: at)
    cov = r["coverage"]
    assert (cov["due_days"], cov["missing_days"], cov["pending_days"]) == (3, 0, 1)
    assert cov["pending_dates"] == ["2024-01-05"]
    assert cov["completeness"] == "complete_to_date" and cov["period_complete"] is False
    assert m["status"] == "success"
    assert "另 1 天尚未发布" in coverage_summary(cov)
    spread = next(f["text"] for f in findings(r) if f["id"] == "spread_2Y-10Y")
    assert "截至 2024-01-04 倒挂 3 天" in spread and "期间倒挂" not in spread
    # 评估时间写入清单；日后复现仍按当时判断，不会把 1 月 5 日改判为缺失
    assert m["study_config"]["scope"]["evaluated_at"] == at.isoformat()
    assert verify_run(project, m["run_id"])["reproduced"] is True

    # 同样的数据在 1 月 8 日评估：1 月 5 日应已发布，记为缺失
    later = datetime(2024, 1, 8, 20, 0, tzinfo=timezone.utc)
    _, r2 = _run(project, "2024-01-02", "2024-01-05", min_cov=0.7, clock=lambda: later)
    assert (r2["coverage"]["completeness"], r2["coverage"]["missing_dates"]) == ("gaps", ["2024-01-05"])


def test_data_arriving_before_its_availability_time_counts(project):
    """规则偏保守：数据比规则时间更早出现时，按已观测计入，不算尚未发布。"""
    days = _expected(project, "2024-01-02", "2024-01-05")
    _load(project, _csv(days))
    at = datetime(2024, 1, 5, 20, 0, tzinfo=timezone.utc)
    _, r = _run(project, "2024-01-02", "2024-01-05", clock=lambda: at)
    assert r["coverage"]["completeness"] == "complete" and "pending_days" not in r["coverage"]


@pytest.mark.parametrize("cov,expected", [
    ({"period_complete": True}, "complete"),
    ({"period_complete": False}, "insufficient"),
    ({"completeness": "gaps", "period_complete": False}, "gaps"),
])
def test_old_results_fall_back_to_period_complete(cov, expected):
    assert completeness(cov) == expected
