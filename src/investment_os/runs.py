"""研究运行与运行记录（模块 O/V）。

每次运行从开始即写入运行清单：研究定义、数据版本、代码版本、输出及其校验值。
失败的运行同样留下记录。``verify_run`` 用清单中固定的数据版本重算并比较结果。
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

import pandas as pd

from . import __version__
from .connectors.base import now_utc
from .contracts import RunStatus
from .data.store import DataStore, as_of, compact, sha256_bytes
from .registry import Registry, StudySpec, load_study, parse_study
from .research import ResearchResult, StudyInput, get_branch
from .validation.reference import spot_check


def _data_roles(study: StudySpec) -> dict[str, tuple[str, bool]]:
    """data 段支持 ``role: dataset_id`` 或 ``role: {dataset, required}``。"""
    roles = {}
    for role, value in study.data.items():
        if isinstance(value, dict):
            roles[role] = (value["dataset"], bool(value.get("required", True)))
        else:
            roles[role] = (str(value), True)
    return roles


def result_hash(result: ResearchResult) -> str:
    canon = json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def code_version(root: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"package_version": __version__}
    try:
        info["git_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "src", "config"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        info["dirty"] = bool(dirty)
    except (OSError, subprocess.CalledProcessError):
        info["git_commit"] = None
        info["dirty"] = None
    return info


def environment() -> dict[str, str]:
    env = {"python": platform.python_version()}
    for pkg in ("pandas", "numpy", "pyarrow", "matplotlib", "pyyaml"):
        try:
            env[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            pass
    return env


def load_inputs(registry: Registry, store: DataStore, study: StudySpec,
                pins: dict[str, str] | None = None) -> tuple[dict[str, StudyInput], list[str]]:
    pins = pins or {}
    inputs: dict[str, StudyInput] = {}
    warnings: list[str] = []
    policy = study.scope.get("vintage_policy", "latest")
    for role, (dataset_id, required) in _data_roles(study).items():
        try:
            frame, version = store.load(dataset_id, pins.get(dataset_id))
        except LookupError as e:
            if required:
                raise
            warnings.append(f"可选输入 {role}（{dataset_id}）不可用：{e}")
            continue
        if policy == "as_of":
            at = pd.Timestamp(study.scope["as_of"])
            unknown = int(frame["available_at"].isna().sum())
            frame = as_of(frame, at)
            if unknown:
                warnings.append(f"{dataset_id} 有 {unknown} 行可用时间未知，已从时点视图中排除")
        elif policy != "latest":
            raise ValueError(f"未知的版本策略：{policy}")
        status = registry.source_of(dataset_id).status_for(dataset_id).value
        inputs[role] = StudyInput(role=role, dataset_id=dataset_id, frame=frame,
                                  version=version, source_status=status)
    return inputs, warnings


def execute(root: Path, study: StudySpec, pins: dict[str, str] | None = None
            ) -> tuple[ResearchResult, dict[str, StudyInput], list[str]]:
    """无副作用地执行研究：加载固定版本数据 → 研究分支 → 原始快照抽查。"""
    registry = Registry.load(root)
    store = DataStore(root)
    inputs, warnings = load_inputs(registry, store, study, pins)
    result = get_branch(study.branch)(study, inputs)
    primary_role = next(r for r, (_, req) in _data_roles(study).items() if req)
    primary = inputs[primary_role]
    result.validation["raw_spot_check"] = spot_check(store, primary.version, primary.frame)
    return result, inputs, warnings


def _status(result: ResearchResult) -> RunStatus:
    failed_checks = [k for k, v in result.validation.items()
                     if isinstance(v, dict) and v.get("status") == "fail"]
    return RunStatus.PARTIAL if result.is_partial or failed_checks else RunStatus.SUCCESS


def run_study(root: Path, study_path: Path, pins: dict[str, str] | None = None) -> dict[str, Any]:
    from .reporting import write_report  # 延迟导入：matplotlib 只在生成报告时需要

    root = Path(root)
    study = load_study(study_path)
    started = now_utc()
    run_id = f"{study.study_id}-{compact(started)}"
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "study_id": study.study_id,
        "study_path": str(Path(study_path).resolve().relative_to(root.resolve()))
        if Path(study_path).resolve().is_relative_to(root.resolve()) else str(study_path),
        "study_config": study.raw,
        "study_config_hash": study.config_hash,
        "started_at": started.isoformat(),
        "code": code_version(root),
        "environment": environment(),
        "pins": pins or {},
        "status": "running",
    }
    _write_json(run_dir / "manifest.json", manifest)
    try:
        result, inputs, warnings = execute(root, study, pins)
        rhash = result_hash(result)
        result_doc = {**result.to_dict(), "run_id": run_id, "generated_at": now_utc().isoformat(),
                      "result_hash": rhash}
        _write_json(run_dir / "result.json", result_doc)
        report_paths = write_report(root, result_doc)
        status = _status(result)
        manifest.update({
            "status": status.value,
            "inputs": [{"role": i.role, "dataset_id": i.dataset_id, "version_id": i.version.version_id,
                        "content_hash": i.version.content_hash, "source_status": i.source_status}
                       for i in inputs.values()],
            "result_hash": rhash,
            "warnings": warnings,
            "unsupported": result.unsupported,
            "outputs": [_output_ref(root, p) for p in [run_dir / "result.json", *report_paths]],
        })
    except Exception as e:  # noqa: BLE001 - 任何失败都要留下运行记录
        manifest.update({"status": RunStatus.FAILED.value, "error": f"{type(e).__name__}: {e}"})
    manifest["finished_at"] = now_utc().isoformat()
    _write_json(run_dir / "manifest.json", manifest)
    return manifest


def verify_run(root: Path, run_id: str) -> dict[str, Any]:
    """用运行清单中固定的研究定义与数据版本重算，比较结果校验值。"""
    root = Path(root)
    run_dir = root / "runs" / run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") == RunStatus.FAILED.value:
        raise ValueError(f"运行 {run_id} 本身失败，没有可复现的结果")
    study = parse_study(manifest["study_config"], run_id)
    pins = {i["dataset_id"]: i["version_id"] for i in manifest["inputs"]}
    result, _, _ = execute(root, study, pins)
    new_hash = result_hash(result)
    current_code = code_version(root)
    record = {
        "verified_at": now_utc().isoformat(),
        "run_id": run_id,
        "reproduced": new_hash == manifest["result_hash"],
        "original_hash": manifest["result_hash"],
        "new_hash": new_hash,
        "original_code": manifest["code"],
        "current_code": current_code,
        "code_changed": current_code.get("git_commit") != manifest["code"].get("git_commit")
        or bool(current_code.get("dirty")) or bool(manifest["code"].get("dirty")),
    }
    with (run_dir / "verifications.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_runs(root: Path) -> list[dict[str, Any]]:
    runs_dir = Path(root) / "runs"
    if not runs_dir.exists():
        return []
    out = []
    for path in sorted(runs_dir.glob("*/manifest.json")):
        m = json.loads(path.read_text(encoding="utf-8"))
        out.append({k: m.get(k) for k in ("run_id", "study_id", "status", "started_at", "result_hash")})
    return out


def _output_ref(root: Path, path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(root)), "sha256": sha256_bytes(path.read_bytes())}


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
