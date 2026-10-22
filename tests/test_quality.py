import pandas as pd

from investment_os.quality import (
    classify_values,
    dataset_report,
    ok_rows,
    resolve_duplicates,
)


def test_classify_values_marks_missing_unparseable_and_out_of_range():
    raw = pd.Series(["4.05", "", ".", "N/A", "abc", "99", "-0.10"])
    out = classify_values(raw, (-5, 30))
    assert list(out["quality_status"]) == [
        "ok", "missing", "missing", "missing", "quarantined", "quarantined", "ok"]
    assert out["reason"].iloc[4] == "unparseable:abc"
    assert out["reason"].iloc[5].startswith("out_of_range")
    # 缺失不填零
    assert out["value"].iloc[1:4].isna().all()
    assert out["value"].iloc[6] == -0.10


def _frame(rows):
    return pd.DataFrame(rows, columns=["series_id", "observation_at", "vintage_id", "value",
                                       "quality_status", "reason"])


def test_resolve_duplicates_drops_exact_and_quarantines_conflicts():
    d = pd.Timestamp("2024-01-02")
    df = _frame([
        ("A", d, "v", 1.0, "ok", ""),
        ("A", d, "v", 1.0, "ok", ""),  # 完全重复
        ("B", d, "v", 1.0, "ok", ""),
        ("B", d, "v", 2.0, "ok", ""),  # 同键不同值
    ])
    out, stats = resolve_duplicates(df, ["series_id", "observation_at", "vintage_id"])
    assert stats == {"exact_duplicates_dropped": 1, "conflicting_rows": 2}
    assert (out[out["series_id"] == "A"]["quality_status"] == "ok").all()
    assert (out[out["series_id"] == "B"]["quality_status"] == "quarantined").all()
    assert len(ok_rows(out)) == 1


def test_dataset_report_finds_monthly_gap():
    obs = pd.to_datetime(["2024-01-01", "2024-02-01", "2024-04-01"])
    df = _frame([("CPI", o, "v", 300.0, "ok", "") for o in obs])
    report = dataset_report(df, "monthly")
    assert report["series"]["CPI"]["gaps"] == 1
    assert report["issues"][0]["examples"] == ["2024-03-01"]
