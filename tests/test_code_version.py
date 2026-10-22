"""verify 的代码变化判断：比较 src/ 与 config/ 的内容，而不是提交号。"""

import subprocess
from pathlib import Path

import pytest

from investment_os.data import ingest
from investment_os.runs import (
    code_changed,
    code_version,
    run_study,
    source_hash,
    verify_run,
)

from .conftest import TREASURY_2024, treasury_connector
from .test_study_e2e import write_study


def _tree(root: Path) -> None:
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "a.py").write_text("x = 1\n")
    (root / "config").mkdir()
    (root / "config" / "s.yaml").write_text("a: 1\n")


def test_source_hash_ignores_caches_and_other_dirs(tmp_path: Path):
    _tree(tmp_path)
    before = source_hash(tmp_path)
    (tmp_path / "src" / "pkg" / "__pycache__").mkdir()
    (tmp_path / "src" / "pkg" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\0")
    (tmp_path / "src" / ".DS_Store").write_bytes(b"\0")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text("改了文档\n")
    assert source_hash(tmp_path) == before


def test_source_hash_detects_code_config_and_renames(tmp_path: Path):
    _tree(tmp_path)
    before = source_hash(tmp_path)
    (tmp_path / "config" / "s.yaml").write_text("a: 2\n")
    assert source_hash(tmp_path) != before
    (tmp_path / "config" / "s.yaml").write_text("a: 1\n")
    assert source_hash(tmp_path) == before
    (tmp_path / "src" / "pkg" / "a.py").rename(tmp_path / "src" / "pkg" / "b.py")
    assert source_hash(tmp_path) != before


def test_verify_ignores_doc_changes_but_flags_config_changes(project, registry, store):
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: TREASURY_2024}))
    manifest = run_study(project, write_study(project))
    (project / "docs").mkdir()
    (project / "docs" / "implementation.md").write_text("记录基线运行\n")
    record = verify_run(project, manifest["run_id"])
    assert record["reproduced"] is True and record["code_changed"] is False

    sources = project / "config" / "sources.yaml"
    sources.write_text(sources.read_text() + "\n# 新增注释\n")
    record = verify_run(project, manifest["run_id"])
    assert record["reproduced"] is True  # 结果不变，但如实报告配置已变化
    assert record["code_changed"] is True


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _tree(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "base")
    return tmp_path


def _commit(root: Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", msg)


def test_legacy_manifest_falls_back_to_git_trees(repo: Path):
    """旧清单只有提交号：只改文档的新提交不算代码变化，改代码则算。"""
    legacy = {"git_commit": _git(repo, "rev-parse", "HEAD"), "dirty": False}
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("doc\n")
    _commit(repo, "docs only")
    assert code_changed(repo, legacy, code_version(repo)) is False

    (repo / "src" / "pkg" / "a.py").write_text("x = 2\n")
    assert code_changed(repo, legacy, code_version(repo)) is True  # 未提交改动
    _commit(repo, "code")
    assert code_changed(repo, legacy, code_version(repo)) is True


def test_legacy_dirty_or_unknown_manifest_counts_as_changed(repo: Path):
    current = code_version(repo)
    assert code_changed(repo, {"git_commit": _git(repo, "rev-parse", "HEAD"), "dirty": True}, current)
    assert code_changed(repo, {"git_commit": None, "dirty": None}, current)
