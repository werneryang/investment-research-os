"""研究运行与运行记录（模块 O/V）。

每次运行从开始即写入运行清单：研究定义、数据版本、代码版本、输出及其校验值。
失败的运行同样留下记录。``verify_run`` 用清单中固定的数据版本重算并比较结果。
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .connectors.base import now_utc
from .contracts import DatasetSpec, RunStatus, VintageSupport
from .data.store import (
    DataStore,
    as_of,
    compact,
    eligibility_as_of,
    sha256_bytes,
    version_as_of,
)
from .registry import (
    Registry,
    StudySpec,
    load_study,
    parse_study,
    resolve_relative_dates,
)
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


# 影响研究结果的代码与配置目录；文档、测试等改动不算代码变化
SOURCE_DIRS = ("src", "config")
_IGNORED_PARTS = {"__pycache__", ".DS_Store"}


def source_hash(root: Path) -> str:
    """src/ 与 config/ 的内容校验值（相对路径 + 文件字节），不依赖 Git，含未提交改动。"""
    digest = hashlib.sha256()
    for top in SOURCE_DIRS:
        base = Path(root) / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or _IGNORED_PARTS & set(path.parts) or path.suffix == ".pyc":
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def code_version(root: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"package_version": __version__, "source_hash": source_hash(root)}
    info["git_commit"] = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--", *SOURCE_DIRS)
    info["dirty"] = None if status is None else bool(status)
    return info


def code_changed(root: Path, original: dict[str, Any], current: dict[str, Any]) -> bool:
    """比较影响结果的代码与配置是否变化，而不是比较提交号。

    新清单直接比较 source_hash。旧清单没有 source_hash：若原运行基于干净提交，
    比较该提交与当前 HEAD 的 src/config 树，且当前无未提交改动；无法判断时视为已变化。
    """
    if original.get("source_hash"):
        return original["source_hash"] != current["source_hash"]
    commit = original.get("git_commit")
    if not commit or original.get("dirty") is not False or current.get("dirty") is not False:
        return True
    for top in SOURCE_DIRS:
        then, now = _git(root, "rev-parse", f"{commit}:{top}"), _git(root, "rev-parse", f"HEAD:{top}")
        if then is None or then != now:
            return True
    return False


def environment() -> dict[str, str]:
    env = {"python": platform.python_version()}
    for pkg in ("pandas", "numpy", "pyarrow", "matplotlib", "pyyaml"):
        try:
            env[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            pass
    return env


@dataclass
class LoadedInputs:
    inputs: dict[str, StudyInput]
    warnings: list[str] = field(default_factory=list)
    unused: dict[str, dict[str, str]] = field(default_factory=dict)  # role → {dataset_id, reason}


def _select_version(store: DataStore, spec: DatasetSpec, study: StudySpec, pin: str | None):
    """选择数据版本。时点研究中，只有当前修订的数据集只能用当时已有的版本。"""
    if pin is not None or study.scope.get("vintage_policy", "latest") != "as_of":
        return store.load(spec.id, pin)
    if spec.vintages is VintageSupport.SUPPLIER:
        return store.load(spec.id)
    at = study.scope["as_of"]
    v = version_as_of(store.versions(spec.id), at)
    if v is None:
        raise LookupError(
            f"{spec.id} 只有当前修订版本，且本系统在 {at} 之前没有取得过该数据集；"
            "可用时间规则不能证明修订值当时已知，不能用于此时点研究")
    return store.load(spec.id, v.version_id)


def load_inputs(registry: Registry, store: DataStore, study: StudySpec,
                pins: dict[str, str] | None = None,
                frozen: dict[str, dict[str, Any]] | None = None) -> LoadedInputs:
    """加载研究输入。

    ``frozen`` 来自原运行清单：角色集合、版本与核验状态全部按原样固定；
    原运行未使用的可选输入保持不使用，即使现在已经有数据。
    """
    pins = pins or {}
    policy = study.scope.get("vintage_policy", "latest")
    if policy not in ("latest", "as_of"):
        raise ValueError(f"未知的版本策略：{policy}")
    out = LoadedInputs(inputs={})
    for role, (dataset_id, required) in _data_roles(study).items():
        spec = registry.dataset(dataset_id)
        fixed = frozen.get(role) if frozen is not None else None
        if frozen is not None and (fixed is None or not fixed.get("used", True)):
            reason = (fixed or {}).get("reason", "原运行未使用该输入")
            out.unused[role] = {"dataset_id": dataset_id, "reason": f"按原运行固定为不使用：{reason}"}
            continue
        pin = fixed["version_id"] if fixed else pins.get(dataset_id)
        try:
            frame, version = _select_version(store, spec, study, pin)
        except LookupError as e:
            if required:
                raise
            out.warnings.append(f"可选输入 {role}（{dataset_id}）不可用：{e}")
            out.unused[role] = {"dataset_id": dataset_id, "reason": str(e)}
            continue
        if policy == "as_of":
            at = study.scope["as_of"]
            reasons = eligibility_as_of(frame, at, spec.vintages)["reason"]
            for reason, n in reasons[reasons != ""].value_counts().items():
                out.warnings.append(f"{dataset_id} 有 {n} 行在时点视图中排除：{_EXCLUSION_TEXT[reason]}")
            frame = as_of(frame, at, spec.vintages)
        status = (fixed["source_status"] if fixed
                  else registry.source_of(dataset_id).status_for(dataset_id, study.use).value)
        out.inputs[role] = StudyInput(role=role, dataset_id=dataset_id, frame=frame,
                                      version=version, source_status=status)
    return out


_EXCLUSION_TEXT = {
    "available_at_unknown": "可用时间未知",
    "not_yet_available": "当时尚未可用",
    "no_evidence_known_then": "无证据表明当时已知（当前修订值且当时尚未取得）",
}


def execute(root: Path, study: StudySpec, pins: dict[str, str] | None = None,
            frozen: dict[str, dict[str, Any]] | None = None
            ) -> tuple[ResearchResult, LoadedInputs]:
    """无副作用地执行研究：加载固定版本数据 → 研究分支 → 原始快照抽查。"""
    registry = Registry.load(root)
    store = DataStore(root)
    loaded = load_inputs(registry, store, study, pins, frozen)
    result = get_branch(study.branch)(study, loaded.inputs, registry)
    primary_role = next(r for r, (_, req) in _data_roles(study).items() if req)
    primary = loaded.inputs[primary_role]
    result.validation["raw_spot_check"] = spot_check(store, primary.version, primary.frame)
    return result, loaded


def _status(result: ResearchResult) -> RunStatus:
    failed_checks = [k for k, v in result.validation.items()
                     if isinstance(v, dict) and v.get("status") == "fail"]
    return RunStatus.PARTIAL if result.is_partial or failed_checks else RunStatus.SUCCESS


def run_study(root: Path, study_path: Path, pins: dict[str, str] | None = None,
              clock: Callable[[], datetime] = now_utc) -> dict[str, Any]:
    from .reporting import write_report  # 延迟导入：matplotlib 只在生成报告时需要

    root = Path(root)
    started = clock()
    study = parse_study(resolve_relative_dates(load_study(study_path).raw, started.date()),
                        Path(study_path).name)
    # 随机后缀保证同一秒内的运行也不碰撞；目录排他创建，已有记录绝不覆盖
    run_id = f"{study.study_id}-{compact(started)}-{uuid.uuid4().hex[:8]}"
    run_dir = root / "runs" / run_id
    (root / "runs").mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)
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
        result, loaded = execute(root, study, pins)
        rhash = result_hash(result)
        result_doc = {**result.to_dict(), "run_id": run_id, "generated_at": clock().isoformat(),
                      "result_hash": rhash}
        _write_json(run_dir / "result.json", result_doc)
        report_paths = write_report(root, result_doc)
        status = _status(result)
        manifest.update({
            "status": status.value,
            # 记录完整角色集合：未使用的输入同样固定，复现时不会被后来的数据补上
            "inputs": [{"role": i.role, "used": True, "dataset_id": i.dataset_id,
                        "version_id": i.version.version_id, "content_hash": i.version.content_hash,
                        "source_status": i.source_status, "use": study.use.value}
                       for i in loaded.inputs.values()]
            + [{"role": role, "used": False, **info} for role, info in loaded.unused.items()],
            "result_hash": rhash,
            "warnings": loaded.warnings,
            "unsupported": result.unsupported,
            "outputs": [_output_ref(root, p) for p in [run_dir / "result.json", *report_paths]],
        })
    except Exception as e:  # noqa: BLE001 - 任何失败都要留下运行记录
        manifest.update({"status": RunStatus.FAILED.value, "error": f"{type(e).__name__}: {e}"})
    manifest["finished_at"] = clock().isoformat()
    _write_json(run_dir / "manifest.json", manifest)
    return manifest


_VOLATILE_RESULT_KEYS = ("run_id", "generated_at", "result_hash")


def _partial_hash(result: dict[str, Any], excluded_roles: set[str]) -> str:
    """去掉缺失输入相关部分后的结果校验值：该输入的记录，以及以该角色命名的核验项。"""
    doc = {k: v for k, v in result.items() if k not in _VOLATILE_RESULT_KEYS}
    doc["inputs"] = [i for i in doc.get("inputs", []) if i.get("role") not in excluded_roles]
    doc["validation"] = {k: v for k, v in (doc.get("validation") or {}).items() if k not in excluded_roles}
    canon = json.dumps(doc, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def verify_run(root: Path, run_id: str) -> dict[str, Any]:
    """用运行清单中固定的研究定义与数据版本重算，比较结果校验值。

    可选输入的固定版本已不存在时（例如该数据集未获准归档），不使用它重算，
    比较去掉该输入及其核验项之后的结果，并标为部分复现；必需输入缺失则报错。
    """
    root = Path(root)
    run_dir = root / "runs" / run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") == RunStatus.FAILED.value:
        raise ValueError(f"运行 {run_id} 本身失败，没有可复现的结果")
    study = parse_study(manifest["study_config"], run_id)
    # 旧清单只列出使用过的输入：未列出的角色视为未使用
    frozen = {i["role"]: dict(i) for i in manifest["inputs"]}
    store = DataStore(root)
    required = {role: req for role, (_, req) in _data_roles(study).items()}
    missing: set[str] = set()
    for role, fixed in frozen.items():
        if not fixed.get("used", True):
            continue
        try:
            store.get_version(fixed["dataset_id"], fixed["version_id"])
        except LookupError:
            if required.get(role, True):
                raise LookupError(f"必需输入 {role}（{fixed['dataset_id']} {fixed['version_id']}）不在本地，"
                                  "无法复现；可用 iros archive restore --with-data 恢复归档数据") from None
            missing.add(role)
            frozen[role] = {**fixed, "used": False, "reason": "固定版本不在本地（未归档）"}
    result, _ = execute(root, study, frozen=frozen)
    new_hash = result_hash(result)
    current_code = code_version(root)
    record = {
        "verified_at": now_utc().isoformat(),
        "run_id": run_id,
        "original_hash": manifest["result_hash"],
        "new_hash": new_hash,
        "original_code": manifest["code"],
        "current_code": current_code,
        "code_changed": code_changed(root, manifest["code"], current_code),
    }
    if missing:
        original = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        record.update(scope="partial", excluded_roles=sorted(missing),
                      reproduced=_partial_hash(original, missing) == _partial_hash(result.to_dict(), missing))
    else:
        record.update(scope="full", reproduced=new_hash == manifest["result_hash"])
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
