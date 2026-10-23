"""日历与用途核验的维护：核对、建议、预览与确认写入。"""

import json
from datetime import date

import pytest

from investment_os import maintenance
from investment_os.cli import main
from investment_os.contracts import Use
from investment_os.registry import Registry

from .test_completeness import _csv, _expected, _load


def _set_through(project, through):
    """把日历与 Treasury 描述性用途核验的终点都改到 through（模拟「已核验到某日」）。"""
    for name in ("calendars.yaml", "sources.yaml"):
        path = project / "config" / name
        text = path.read_text(encoding="utf-8")
        key = "verified_through" if name == "calendars.yaml" else "valid_through"
        assert f'{key}: "2026-10-22"' in text
        path.write_text(text.replace(f'{key}: "2026-10-22"', f'{key}: "{through}"'), encoding="utf-8")


def test_extendable_check_proposes_calendar_and_use_extension(loaded):
    _set_through(loaded, "2024-01-03")  # 数据有 1 月 2–5 日
    check = maintenance.check_calendar(loaded)
    assert check["status"] == "extendable" and check["proposed_verified_through"] == "2024-01-05"
    assert (check["candidate_range"], check["expected_days"], check["observed_days"]) == (
        ["2024-01-04", "2024-01-05"], 2, 2)
    assert check["regressions"] == {"missing": [], "unexpected": []}
    proposal = maintenance.build_proposal(loaded, check)
    assert proposal["applicable"] and proposal["calendar_entry"]["through"] == "2024-01-05"
    [rec] = proposal["use_records"]
    assert rec["source_id"] == "ust_treasury"
    assert (rec["record"]["use"], rec["record"]["valid_from"], rec["record"]["valid_through"]) == (
        "descriptive", "2024-01-04", "2024-01-05")
    assert check["dataset_version"] in rec["record"]["evidence"]


def test_apply_previews_then_writes_only_after_confirmation(loaded):
    _set_through(loaded, "2024-01-03")
    proposal = maintenance.build_proposal(loaded, maintenance.check_calendar(loaded))
    cal_path, src_path = loaded / "config" / "calendars.yaml", loaded / "config" / "sources.yaml"
    before = (cal_path.read_text(encoding="utf-8"), src_path.read_text(encoding="utf-8"))

    preview = maintenance.apply_proposal(loaded, proposal)
    assert preview["confirmed"] is False and '+    verified_through: "2024-01-05"' in preview["preview"]["calendars.yaml"]
    assert (cal_path.read_text(encoding="utf-8"), src_path.read_text(encoding="utf-8")) == before  # 未写入

    maintenance.apply_proposal(loaded, proposal, confirm=True)
    reg = Registry.load(loaded)
    cal = reg.calendars["us_treasury_daily"]
    assert cal.verified_through.date() == date(2024, 1, 5) and cal.checks[-1]["through"] == "2024-01-05"
    src = reg.sources["ust_treasury"]
    ranges = sorted((v.valid_from, v.valid_through) for v in src.verification if v.use is Use.DESCRIPTIVE)
    assert ranges == [(date(2024, 1, 1), date(2024, 1, 3)), (date(2024, 1, 4), date(2024, 1, 5))]  # 原记录保留
    assert src.use_coverage("ust_par_yield_curve", Use.DESCRIPTIVE,
                            date(2024, 1, 2), date(2024, 1, 5)).status == "in_scope"
    # 原有注释与内容保留
    assert "耶稣受难日并非每年休市" in cal_path.read_text(encoding="utf-8")
    assert src_path.read_text(encoding="utf-8").startswith(before[1][:200])

    with pytest.raises(ValueError, match="建议已过时"):
        maintenance.apply_proposal(loaded, proposal, confirm=True)


def test_missing_publication_stops_extension_before_it(project):
    _set_through(project, "2024-01-02")
    _load(project, _csv(["2024-01-02", "2024-01-03", "2024-01-05"]))  # 1 月 4 日无数据
    check = maintenance.check_calendar(project)
    assert check["status"] == "partial" and check["proposed_verified_through"] == "2024-01-03"
    assert check["anomalies"]["missing"] == ["2024-01-04"]
    assert "异常（规则预期发布但没有数据）：2024-01-04" in maintenance.render_markdown(check)


def test_first_new_date_anomalous_blocks_extension(project):
    _set_through(project, "2024-01-02")
    _load(project, _csv(["2024-01-02", "2024-01-04"]))  # 1 月 3 日即缺失
    check = maintenance.check_calendar(project)
    assert check["status"] == "blocked" and check["proposed_verified_through"] is None
    proposal = maintenance.build_proposal(project, check)
    assert proposal["applicable"] is False
    with pytest.raises(ValueError, match="没有可写入的延长"):
        maintenance.apply_proposal(project, proposal, confirm=True)


def test_publication_on_a_rule_holiday_is_an_anomaly(project):
    _set_through(project, "2024-01-11")
    days = _expected(project, "2024-01-02", "2024-01-12") + ["2024-01-15", "2024-01-16"]  # 1 月 15 日为联邦假日
    _load(project, _csv(days))
    check = maintenance.check_calendar(project)
    assert check["anomalies"]["unexpected"] == ["2024-01-15"]
    assert check["status"] == "partial" and check["proposed_verified_through"] == "2024-01-14"


def test_regression_inside_verified_range_blocks_and_fails_cli(project, capsys):
    _set_through(project, "2024-01-04")
    _load(project, _csv(["2024-01-02", "2024-01-04", "2024-01-05"]))  # 已核验范围内缺 1 月 3 日
    check = maintenance.check_calendar(project)
    assert check["status"] == "regression" and check["regressions"]["missing"] == ["2024-01-03"]
    assert check["proposed_verified_through"] is None
    assert main(["--root", str(project), "calendar", "check", "--markdown"]) == 1
    assert "已核验范围内回归" in capsys.readouterr().out


def test_cli_check_writes_proposal_and_apply_needs_confirm(loaded, tmp_path, capsys):
    _set_through(loaded, "2024-01-03")
    out = tmp_path / "proposal.json"
    assert main(["--root", str(loaded), "calendar", "check", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["applicable"] is True
    assert main(["--root", str(loaded), "calendar", "apply", str(out)]) == 0
    assert "预览（未写入）" in capsys.readouterr().out
    assert Registry.load(loaded).calendars["us_treasury_daily"].verified_through.date() == date(2024, 1, 3)
    assert main(["--root", str(loaded), "calendar", "apply", str(out), "--confirm"]) == 0
    assert "已写入" in capsys.readouterr().out
    assert Registry.load(loaded).calendars["us_treasury_daily"].verified_through.date() == date(2024, 1, 5)


def test_up_to_date_when_no_new_data(loaded):
    _set_through(loaded, "2024-01-05")
    check = maintenance.check_calendar(loaded)
    assert check["status"] == "up_to_date" and maintenance.build_proposal(loaded, check)["applicable"] is False


@pytest.mark.parametrize("through", ["2024-01-05", "2024-01-08"])
def test_regression_is_reported_even_without_new_dates(project, capsys, through):
    _set_through(project, through)
    _load(project, _csv(["2024-01-02", "2024-01-04", "2024-01-05"]))
    check = maintenance.check_calendar(project)
    assert check["regressions"]["missing"] == ["2024-01-03"]
    assert check["status"] == "regression"
    assert maintenance.build_proposal(project, check)["applicable"] is False
    assert main(["--root", str(project), "calendar", "check"]) == 1
    assert "已核验范围内" in capsys.readouterr().out
