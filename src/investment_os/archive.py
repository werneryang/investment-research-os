"""运行档案：把运行记录与报告保存到独立目录（CI 中为 archive 分支的工作树），并在下次构建时恢复。

档案布局（与项目根目录相同的相对路径，便于直接复制回来）：

    runs/<run_id>/manifest.json、result.json、verifications.jsonl
    reports/<study_id>/<run_id>/report.html、report.md、figures/*.png
    archive.jsonl     每次检查的记录：运行 ID、研究、实质内容校验值、原因；
                      结论未变的运行记为 skipped（不复制文件，以后也不再考虑）

只追加、不修改已归档的运行。固定期间的研究每天重跑时结果相同，只有实质内容
（结果、覆盖、限制、核验结论）变化时才归档，避免档案无意义地增长。
原始数据只归档登记为 archive_data: true 的数据集（公开再分发须先确认许可），
且只归档已归档运行实际使用的数据版本：

    data/normalized/<dataset>/<version>.parquet
    data/raw/<dataset>/<快照文件>（及 .meta.json）
    data/catalog/<dataset>.jsonl   这些版本的目录记录
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .connectors.base import now_utc
from .data.store import DataStore
from .registry import Registry

# 实质内容：不含运行 ID、生成时间与输入版本号（数据版本每天变化，但结论可能不变）
_SUBSTANTIVE_KEYS = ("study_id", "scope", "data_cutoff", "results", "coverage", "unsupported", "limitations")
ARCHIVE_README = """# Investment Research OS 运行档案

本分支由 GitHub Actions 自动维护，只追加、不修改。由 `iros archive save` 写入，结构与项目根目录相同：

- `runs/<run_id>/`：运行清单、结果与复现记录
- `reports/<study_id>/<run_id>/`：完整报告与图表
- `data/`：允许公开再分发的数据集（`archive_data: true`）中，被已归档运行使用的数据版本
- `archive.jsonl`：每次检查的记录；结论未变的运行记为 skipped，不复制文件

在新环境中复现某次运行：

    uv run iros archive restore <本分支的工作树> --with-data
    uv run iros verify <run_id>

未归档数据的可选输入（如 FRED 交叉核验）无法重算，verify 会标为部分复现。
"""
_RECORD_FILES = ("manifest.json", "result.json", "verifications.jsonl")


def substantive_hash(result: dict[str, Any]) -> str:
    doc = {k: result.get(k) for k in _SUBSTANTIVE_KEYS}
    doc["validation"] = {k: (v or {}).get("status") for k, v in (result.get("validation") or {}).items()}
    canon = json.dumps(doc, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _log(archive: Path) -> list[dict[str, Any]]:
    path = archive / "archive.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _copy_run(src_root: Path, dst_root: Path, manifest: dict[str, Any]) -> None:
    run_id, study_id = manifest["run_id"], manifest["study_id"]
    src_run, dst_run = src_root / "runs" / run_id, dst_root / "runs" / run_id
    dst_run.mkdir(parents=True, exist_ok=False)  # 已归档的运行绝不覆盖
    for name in _RECORD_FILES:
        if (src_run / name).exists():
            shutil.copy2(src_run / name, dst_run / name)
    src_rep = src_root / "reports" / study_id / run_id
    if src_rep.exists():
        shutil.copytree(src_rep, dst_root / "reports" / study_id / run_id)


def _archive_inputs(root: Path, archive: Path, manifest: dict[str, Any], allowed: set[str]) -> list[str]:
    """把运行实际使用、且允许归档的数据版本复制到档案（已存在的跳过）。返回归档的数据集。"""
    store, done = DataStore(root), []
    for inp in manifest.get("inputs", []):
        if not inp.get("used", True) or inp["dataset_id"] not in allowed:
            continue
        version = store.get_version(inp["dataset_id"], inp["version_id"])
        catalog = archive / "data" / "catalog" / f"{version.dataset_id}.jsonl"
        known = {json.loads(x)["version_id"] for x in catalog.read_text(encoding="utf-8").splitlines() if x} \
            if catalog.exists() else set()
        for rel in [version.path] + [r["path"] for r in version.raw_snapshots]:
            for f in (Path(rel), Path(rel).with_suffix(".meta.json")):
                src, dst = store.base / f, archive / "data" / f
                if src.exists() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        if version.version_id not in known:
            catalog.parent.mkdir(parents=True, exist_ok=True)
            with catalog.open("a", encoding="utf-8") as f:
                f.write(json.dumps(version.to_dict(), ensure_ascii=False, default=str) + "\n")
        done.append(version.dataset_id)
    return done


def save(root: Path, archive: Path) -> list[dict[str, Any]]:
    """把 root 中尚未归档、未失败且实质内容有变化的运行复制到档案。返回新增记录。"""
    root, archive = Path(root), Path(archive)
    allowed = {d.id for d in Registry.load(root).datasets.values() if d.archive_data}
    archive.mkdir(parents=True, exist_ok=True)
    readme = archive / "README.md"
    if not readme.exists():
        readme.write_text(ARCHIVE_README, encoding="utf-8")
    log = _log(archive)
    archived = {e["run_id"] for e in log}
    last_hash = {}
    for e in log:
        if not e.get("skipped"):
            last_hash[e["study_id"]] = e["substantive_hash"]

    added = []
    manifests = sorted((root / "runs").glob("*/manifest.json")) if (root / "runs").exists() else []
    candidates = []
    for path in manifests:
        m = json.loads(path.read_text(encoding="utf-8"))
        if m.get("status") in (None, "failed", "running") or m["run_id"] in archived:
            continue
        # started_at 只精确到秒；同一秒的运行按清单写入时间区分先后，保证按实际运行顺序归档
        candidates.append(((m.get("started_at", ""), path.stat().st_mtime_ns), m, path.parent))
    for _, m, run_dir in sorted(candidates, key=lambda c: c[0]):
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        digest = substantive_hash(result)
        entry = {"run_id": m["run_id"], "study_id": m["study_id"], "started_at": m.get("started_at"),
                 "substantive_hash": digest, "archived_at": now_utc().isoformat()}
        if last_hash.get(m["study_id"]) == digest:
            # 结论相同：只记一笔「已检查、未归档」，以后不再重新考虑这次运行
            entry.update(skipped=True, reason="结论与上一归档相同")
        else:
            entry["reason"] = "首次归档" if m["study_id"] not in last_hash else "实质内容变化"
            _copy_run(root, archive, m)
            entry["data_archived"] = _archive_inputs(root, archive, m, allowed)
            last_hash[m["study_id"]] = digest
            added.append(entry)
        with (archive / "archive.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return added


def restore(root: Path, archive: Path, with_data: bool = False) -> list[str]:
    """把档案中的运行复制回 root（已存在的运行跳过），供网站列出历史。返回恢复的运行 ID。

    ``with_data`` 同时恢复归档的数据版本（用于日后复现）；目录按创建时间重排，
    保证「最新版本」仍是时间上最新的那个。
    """
    root, archive = Path(root), Path(archive)
    restored = []
    for e in _log(archive):
        if e.get("skipped") or (root / "runs" / e["run_id"]).exists():
            continue
        manifest = json.loads((archive / "runs" / e["run_id"] / "manifest.json").read_text(encoding="utf-8"))
        _copy_run(archive, root, manifest)
        restored.append(e["run_id"])
    if with_data and (archive / "data").exists():
        _restore_data(root, archive)
    return restored


def _restore_data(root: Path, archive: Path) -> None:
    for src in (archive / "data").rglob("*"):
        rel = src.relative_to(archive / "data")
        if src.is_file() and rel.parts[0] != "catalog":
            dst = root / "data" / rel
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    for cat in (archive / "data" / "catalog").glob("*.jsonl"):
        dst = root / "data" / "catalog" / cat.name
        records = {}
        for path in (dst, cat):
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rec = json.loads(line)
                        records.setdefault(rec["version_id"], rec)
        ordered = sorted(records.values(), key=lambda r: r["created_at"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in ordered),
                       encoding="utf-8")


def archived_runs(archive_or_root: Path) -> dict[str, dict[str, Any]]:
    """run_id → 归档记录（含归档原因）；不含检查后未归档的运行。"""
    return {e["run_id"]: e for e in _log(Path(archive_or_root)) if not e.get("skipped")}
