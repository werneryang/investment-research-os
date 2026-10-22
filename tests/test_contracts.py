from pathlib import Path

import pandas as pd
import pytest

from investment_os.contracts import (
    AvailabilityRule,
    SourceSpec,
    Use,
    VerificationRecord,
    VerificationStatus,
)
from investment_os.data.timing import available_at, period_end, published_to_utc
from investment_os.registry import Registry, RegistryError, load_datasets, load_sources
from investment_os.tenor import parse_tenor

from .conftest import PROJECT_ROOT


@pytest.mark.parametrize("text,code,months", [
    ("10 Yr", "10Y", 120), ("1 Mo", "1M", 1), ("1.5 Month", "1.5M", 1.5),
    ("6 Wk", "6W", 6 * 12 / 52), ("3M", "3M", 3), ("30Y", "30Y", 360),
])
def test_parse_tenor(text, code, months):
    t = parse_tenor(text)
    assert t.code == code
    assert t.months == pytest.approx(months)


def test_parse_tenor_rejects_non_tenor():
    with pytest.raises(ValueError):
        parse_tenor("Date")


def test_project_registry_loads():
    reg = Registry.load(PROJECT_ROOT)
    assert reg.source_of("ust_par_yield_curve").id == "ust_treasury"
    # 多条核验记录取最高状态
    assert reg.sources["ust_treasury"].status_for("ust_par_yield_curve") is VerificationStatus.ACCESS_VERIFIED
    # 没有记录的数据集仍是候选
    assert reg.sources["manual"].status_for("manual_example") is VerificationStatus.CANDIDATE


def test_use_verification_only_counts_for_that_use():
    rec = lambda status, use=None: VerificationRecord("d", status, "2026-10-22", "e", use)  # noqa: E731
    src = SourceSpec("s", "p", "c", "u", "l", "r", "r", "r", "m", verification=(
        rec(VerificationStatus.ACCESS_VERIFIED),
        rec(VerificationStatus.USE_VERIFIED, Use.DESCRIPTIVE),
    ))
    assert src.status_for("d", Use.DESCRIPTIVE) is VerificationStatus.USE_VERIFIED
    assert src.status_for("d", Use.POINT_IN_TIME) is VerificationStatus.ACCESS_VERIFIED
    assert src.status_for("d") is VerificationStatus.ACCESS_VERIFIED
    assert src.verified_uses("d") == [Use.DESCRIPTIVE]


def test_use_verified_requires_use(tmp_path: Path):
    (tmp_path / "s.yaml").write_text("""
sources:
  - {id: x, publisher: p, channel: c, url: u, license: l, registration: r,
     rate_limit: r, revisions: r, maintenance: m,
     verification: [{dataset: d, status: use_verified, date: "2026-01-01", evidence: e}]}
""", encoding="utf-8")
    with pytest.raises(RegistryError, match="必须声明 use"):
        load_sources(tmp_path / "s.yaml")


def test_dataset_rejects_unsupported_frequency(tmp_path: Path):
    (tmp_path / "d.yaml").write_text("""
datasets:
  a: {source_id: s, upstream_id: u, connector: c, frequency: hourly, unit: percent,
      timezone: UTC, availability: {type: period_end_lag_days, days: 1}}
""", encoding="utf-8")
    with pytest.raises(RegistryError, match="频率"):
        load_datasets(tmp_path / "d.yaml", {"s": object()})


def test_treasury_calendar_matches_verified_2024_dates():
    cal = Registry.load(PROJECT_ROOT).calendars["us_treasury_daily"]
    days = cal.expected_dates(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))
    assert len(days) == 250
    assert pd.Timestamp("2024-03-29") not in days  # 耶稣受难日
    assert pd.Timestamp("2024-01-15") not in days  # MLK


def test_registry_rejects_unknown_status(tmp_path: Path):
    (tmp_path / "s.yaml").write_text("""
sources:
  - {id: x, publisher: p, channel: c, url: u, license: l, registration: r,
     rate_limit: r, revisions: r, maintenance: m,
     verification: [{dataset: d, status: works_great, date: "2026-01-01", evidence: e}]}
""", encoding="utf-8")
    with pytest.raises(RegistryError, match="核验状态无效"):
        load_sources(tmp_path / "s.yaml")


def test_dataset_must_reference_registered_source(tmp_path: Path):
    (tmp_path / "d.yaml").write_text("""
datasets:
  a: {source_id: nowhere, upstream_id: u, connector: c, frequency: daily, unit: percent,
      timezone: UTC, availability: {type: unknown}}
""", encoding="utf-8")
    with pytest.raises(RegistryError, match="未登记来源"):
        load_datasets(tmp_path / "d.yaml", {})


def test_availability_rule_validates_type():
    with pytest.raises(ValueError):
        AvailabilityRule(type="whenever")


def _dates(*xs):
    return pd.Series(pd.to_datetime(list(xs)))


def test_next_day_rule_uses_source_timezone():
    obs = _dates("2024-01-02", "2024-07-01")
    out = available_at(obs, pd.Series([None, None]), "daily", AvailabilityRule("next_day"),
                       "America/New_York")
    # 纽约次日 0 点：冬令时 UTC 05:00，夏令时 UTC 04:00
    assert out.iloc[0] == pd.Timestamp("2024-01-03 05:00", tz="UTC")
    assert out.iloc[1] == pd.Timestamp("2024-07-02 04:00", tz="UTC")


def test_period_end_lag_rule_for_monthly():
    obs = _dates("2024-01-01", "2024-02-01")
    assert list(period_end(obs, "monthly").dt.day) == [31, 29]
    out = available_at(obs, pd.Series([None, None]), "monthly",
                       AvailabilityRule("period_end_lag_days", 45), "UTC")
    # 1 月 31 日之后第 45 天（3 月 16 日）结束时
    assert out.iloc[0] == pd.Timestamp("2024-03-17", tz="UTC")


def test_published_rule_leaves_unknown_empty():
    obs = _dates("2024-01-01", "2024-02-01")
    pub = published_to_utc(pd.Series([pd.Timestamp("2024-02-13"), None]), "America/New_York")
    out = available_at(obs, pub, "monthly", AvailabilityRule("published_next_day"), "America/New_York")
    assert out.iloc[0] == pd.Timestamp("2024-02-14 05:00", tz="UTC")
    assert pd.isna(out.iloc[1])


def test_unknown_rule_never_guesses():
    out = available_at(_dates("2024-01-01"), pd.Series([None]), "monthly",
                       AvailabilityRule("unknown"), "UTC")
    assert out.isna().all()
