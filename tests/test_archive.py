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
