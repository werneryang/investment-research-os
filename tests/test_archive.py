"""运行档案：只追加、按实质内容去重、可恢复，网站历史页使用档案。"""

import json
import shutil
from datetime import datetime, timezone

import pytest

from investment_os import archive
from investment_os.cli import main
from investment_os.runs import run_study, verify_run
from investment_os.site import build_site

from .conftest import PROJECT_ROOT
from .test_study_e2e import write_study


def test_save_archives_only_substantive_changes(loaded, tmp_path):
    arch = tmp_path / "archive"
    first = run_study(loaded, write_study(loaded))
    same = run_study(loaded, write_study(loaded))  # 结论相同的重跑
    added = archive.save(loaded, arch)
    assert [e["run_id"] for e in added] == [first["run_id"]]
    assert added[0]["reason"] == "首次归档"
    assert (arch / "runs" / first["run_id"] / "manifest.json").exists()
    assert (arch / "reports" / "ust_curve_test" / first["run_id"] / "report.html").exists()
    assert not (arch / "runs" / same["run_id"]).exists()

    changed = run_study(loaded, write_study(loaded, scope={**write_scope(), "end": "2024-01-04"}))
    added = archive.save(loaded, arch)
    assert [e["run_id"] for e in added] == [changed["run_id"]]
    assert added[0]["reason"] == "实质内容变化"
    assert archive.save(loaded, arch) == []  # 重复保存不产生新记录
    # 被跳过的重跑记为 skipped，之后不会因为结论又变了而被补归档
    log = [json.loads(x) for x in (arch / "archive.jsonl").read_text().splitlines()]
    assert [(e["run_id"], e.get("skipped", False)) for e in log] == [
        (first["run_id"], False), (same["run_id"], True), (changed["run_id"], False)]
    assert same["run_id"] not in archive.archived_runs(arch)


def write_scope():
    from .test_study_e2e import STUDY
    return dict(STUDY["scope"])


def test_archive_never_overwrites(loaded, tmp_path):
    arch = tmp_path / "archive"
    m = run_study(loaded, write_study(loaded))
    archive.save(loaded, arch)
    with pytest.raises(FileExistsError):
        archive._copy_run(loaded, arch, m)


def test_failed_runs_are_not_archived(project, tmp_path):
    m = run_study(project, write_study(project))  # 没有数据，运行失败
    assert m["status"] == "failed"
    assert archive.save(project, tmp_path / "archive") == []


def test_restore_then_site_lists_archived_history(loaded, tmp_path):
    """模拟 CI：上一次构建归档的运行，在新的空白环境中恢复并出现在历史页。"""
    arch = tmp_path / "archive"
    earlier = run_study(loaded, write_study(loaded, scope={**write_scope(), "end": "2024-01-04"}))
    archive.save(loaded, arch)

    fresh = tmp_path / "fresh"
    shutil.copytree(loaded, fresh, ignore=shutil.ignore_patterns("runs", "reports"))
    shutil.copytree(PROJECT_ROOT / "site", fresh / "site")
    today = run_study(fresh, write_study(fresh))
    assert main(["--root", str(fresh), "archive", "save", str(arch)]) == 0
    assert main(["--root", str(fresh), "archive", "restore", str(arch)]) == 0
    assert (fresh / "runs" / earlier["run_id"] / "result.json").exists()

    build_site(fresh, fresh / "_site", arch)
    history = (fresh / "_site" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert earlier["run_id"] in history and today["run_id"] in history
    assert "首次归档" in history and "实质内容变化" in history
    assert (fresh / "_site" / "runs" / earlier["run_id"] / "report.html").exists()
    log = [json.loads(x) for x in (arch / "archive.jsonl").read_text().splitlines()]
    assert [e["run_id"] for e in log] == [earlier["run_id"], today["run_id"]]


def test_history_counts_archived_runs_separately(loaded, tmp_path):
    """列出的运行含未单独归档的最新运行时，不把列出的次数说成归档次数。"""
    arch = tmp_path / "archive"
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    run_study(loaded, write_study(loaded))
    archive.save(loaded, arch)
    run_study(loaded, write_study(loaded))  # 结论相同的重跑：最新运行照常显示，但不归档
    build_site(loaded, loaded / "_site", arch)
    history = (loaded / "_site" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert "在列出的 2 次运行中（其中已归档 1 次）" in history and "未单独归档" in history
    assert "在已归档的" not in history


def test_archived_treasury_data_allows_later_partial_reproduction(loaded, tmp_path):
    """只归档允许再分发的 Treasury 数据；日后在新环境中恢复后可复现主研究，交叉核验如实标为未重算。"""
    arch = tmp_path / "archive"
    m = run_study(loaded, write_study(loaded))
    archive.save(loaded, arch)
    archived = [p.relative_to(arch / "data").as_posix() for p in (arch / "data").rglob("*") if p.is_file()]
    assert archived and all("ust_par_yield_curve" in a for a in archived)  # fred_dgs10 未获准归档
    assert (arch / "data" / "catalog" / "ust_par_yield_curve.jsonl").exists()

    later = tmp_path / "later"
    shutil.copytree(PROJECT_ROOT / "config", later / "config")
    assert main(["--root", str(later), "archive", "restore", str(arch), "--with-data"]) == 0
    record = verify_run(later, m["run_id"])
    assert record["scope"] == "partial" and record["excluded_roles"] == ["cross_check"]
    assert record["reproduced"] is True

    # 必需输入不在本地时明确报错，而不是悄悄改用其他版本
    bare = tmp_path / "bare"
    shutil.copytree(PROJECT_ROOT / "config", bare / "config")
    archive.restore(bare, arch)
    with pytest.raises(LookupError, match="必需输入"):
        verify_run(bare, m["run_id"])


def test_restore_with_data_keeps_latest_version_latest(loaded, tmp_path):
    from investment_os.data import DataStore
    arch = tmp_path / "archive"
    run_study(loaded, write_study(loaded))
    archive.save(loaded, arch)
    old_version = DataStore(loaded).latest("ust_par_yield_curve").version_id

    fresh = tmp_path / "fresh"
    shutil.copytree(PROJECT_ROOT / "config", fresh / "config")
    from investment_os.data import ingest
    from investment_os.registry import Registry

    from .conftest import TREASURY_2025, treasury_connector
    later = datetime(2030, 1, 1, tzinfo=timezone.utc)
    ingest(Registry.load(fresh), DataStore(fresh), "ust_par_yield_curve", {"start": 2025, "end": 2025},
           treasury_connector({2025: TREASURY_2025}), clock=lambda: later)
    new_version = DataStore(fresh).latest("ust_par_yield_curve").version_id
    archive.restore(fresh, arch, with_data=True)
    versions = [v.version_id for v in DataStore(fresh).versions("ust_par_yield_curve")]
    assert versions == [old_version, new_version]  # 按创建时间排序，最新仍是新取得的版本


def test_interpretation_only_change_is_archived(loaded, tmp_path, monkeypatch):
    """回归：只改解释规则、数字不变时，新解释也必须进入长期档案。"""
    import investment_os.research.findings as rules

    arch = tmp_path / "archive"
    run_study(loaded, write_study(loaded))
    archive.save(loaded, arch)
    monkeypatch.setattr(rules, "FLAT_BP", 100.0)  # +10 bp 由「升至」变为「基本持平」
    second = run_study(loaded, write_study(loaded))
    added = archive.save(loaded, arch)
    assert [e["run_id"] for e in added] == [second["run_id"]]
    assert added[0]["reason"] == "解释变化（结果不变）" and added[0]["hash_version"] == archive.SUBSTANTIVE_HASH_VERSION
    stored = json.loads((arch / "runs" / second["run_id"] / "result.json").read_text(encoding="utf-8"))
    assert stored["interpretation"]["items"][0]["text"].startswith("10 年期收益率基本持平")
    third = run_study(loaded, write_study(loaded))  # 规则不再变化：跳过
    assert archive.save(loaded, arch) == []
    log = [json.loads(x) for x in (arch / "archive.jsonl").read_text().splitlines()]
    assert log[-1]["run_id"] == third["run_id"] and log[-1]["skipped"] is True


def test_old_archive_entries_are_compared_with_the_current_hash(loaded, tmp_path):
    """旧档案按旧算法记录的校验值不直接比较：重新计算上一归档结果，结论与解释都相同时照常跳过。"""
    arch = tmp_path / "archive"
    first = run_study(loaded, write_study(loaded))
    archive.save(loaded, arch)
    log_path = arch / "archive.jsonl"
    entries = [json.loads(x) for x in log_path.read_text().splitlines()]
    entries[0]["substantive_hash"] = "旧算法的校验值"
    entries[0].pop("hash_version")
    log_path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    run_study(loaded, write_study(loaded))
    assert archive.save(loaded, arch) == []  # 不因校验值算法变化而误判为结论变化
    assert first["run_id"] in archive.archived_runs(arch)


def test_download_time_alone_does_not_trigger_archiving(project, registry, store, tmp_path):
    """回归：每天重新下载、内容不变时，固定期间研究的结论相同，不能因为下载时间不同而每天归档。"""
    from datetime import datetime, timezone

    from investment_os.data import ingest

    from .conftest import TREASURY_2024, treasury_connector
    from .test_study_e2e import AtTime

    arch = tmp_path / "archive"
    for day in (8, 9):
        at = datetime(2024, 1, day, 20, 0, tzinfo=timezone.utc)
        ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
               AtTime(treasury_connector({2024: TREASURY_2024}), at), clock=lambda at=at: at)
        m = run_study(project, write_study(project))
        assert json.loads((project / "runs" / m["run_id"] / "result.json").read_text())["coverage"][
            "data_retrieved_at"] == at.isoformat()
        archive.save(project, arch)
    log = [json.loads(x) for x in (arch / "archive.jsonl").read_text().splitlines()]
    assert [e.get("skipped", False) for e in log] == [False, True]


def test_same_unobtained_dates_with_different_download_times_are_skipped(project, registry, store, tmp_path):
    """回归：两次下载都在 1 月 5 日保守可用时点之前，未取得的日期相同，只是下载时间不同——不应再次归档，
    限制文字中也不能出现每次都变的下载时间。"""
    from datetime import datetime, timezone

    from investment_os.data import ingest

    from .conftest import TREASURY_2024, treasury_connector
    from .test_study_e2e import AtTime

    without_jan5 = "\n".join(l for l in TREASURY_2024.splitlines() if not l.startswith("01/05/2024")) + "\n"
    arch = tmp_path / "archive"
    for hour in (19, 21):  # 1 月 5 日美东 14:00 与 16:00
        at = datetime(2024, 1, 5, hour, 0, tzinfo=timezone.utc)
        ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
               AtTime(treasury_connector({2024: without_jan5}), at), clock=lambda at=at: at)
        m = run_study(project, write_study(project), clock=lambda at=at: at)
        result = json.loads((project / "runs" / m["run_id"] / "result.json").read_text())
        assert result["coverage"]["pending_dates"] == ["2024-01-05"]
        assert not any("UTC" in x for x in result["limitations"])
        archive.save(project, arch)
    log = [json.loads(x) for x in (arch / "archive.jsonl").read_text().splitlines()]
    assert [e.get("skipped", False) for e in log] == [False, True]
