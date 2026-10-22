"""读取并校验 config/ 下的来源、数据集与研究定义登记（模块 Q）。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .contracts import (
    AvailabilityRule,
    DatasetSpec,
    ResultType,
    SourceSpec,
    VerificationRecord,
    VerificationStatus,
)


class RegistryError(ValueError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RegistryError(f"缺少登记文件：{path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{path} 顶层必须是映射")
    return data


def _require(d: dict[str, Any], keys: list[str], where: str) -> None:
    missing = [k for k in keys if k not in d]
    if missing:
        raise RegistryError(f"{where} 缺少字段：{', '.join(missing)}")


def load_sources(path: Path) -> dict[str, SourceSpec]:
    raw = _load_yaml(path).get("sources") or []
    sources: dict[str, SourceSpec] = {}
    required = ["id", "publisher", "channel", "url", "license", "registration",
                "rate_limit", "revisions", "maintenance"]
    for item in raw:
        _require(item, required, f"来源 {item.get('id', '?')}")
        if item["id"] in sources:
            raise RegistryError(f"来源 ID 重复：{item['id']}")
        records = []
        for v in item.get("verification") or []:
            _require(v, ["dataset", "status", "date", "evidence"], f"来源 {item['id']} 的核验记录")
            try:
                status = VerificationStatus(v["status"])
            except ValueError as e:
                raise RegistryError(f"来源 {item['id']} 的核验状态无效：{v['status']}") from e
            records.append(VerificationRecord(
                dataset=v["dataset"], status=status, date=str(v["date"]),
                evidence=v["evidence"], use=v.get("use", ""),
            ))
        sources[item["id"]] = SourceSpec(
            **{k: item[k] for k in required},
            alternatives=tuple(item.get("alternatives") or ()),
            verification=tuple(records),
        )
    return sources


def load_datasets(path: Path, sources: dict[str, SourceSpec]) -> dict[str, DatasetSpec]:
    raw = _load_yaml(path).get("datasets") or {}
    datasets: dict[str, DatasetSpec] = {}
    for ds_id, item in raw.items():
        _require(item, ["source_id", "upstream_id", "connector", "frequency", "unit",
                        "timezone", "availability"], f"数据集 {ds_id}")
        if item["source_id"] not in sources:
            raise RegistryError(f"数据集 {ds_id} 引用了未登记来源 {item['source_id']}")
        av = item["availability"]
        vr = item.get("value_range")
        datasets[ds_id] = DatasetSpec(
            id=ds_id,
            source_id=item["source_id"],
            upstream_id=item["upstream_id"],
            connector=item["connector"],
            frequency=item["frequency"],
            unit=item["unit"],
            currency=item.get("currency"),
            timezone=item["timezone"],
            availability=AvailabilityRule(type=av["type"], days=int(av.get("days", 0))),
            description=item.get("description", ""),
            params=dict(item.get("params") or {}),
            value_range=(float(vr[0]), float(vr[1])) if vr else None,
        )
    return datasets


@dataclass
class StudySpec:
    """研究定义（architecture §6.3 的公共字段来源）。"""

    study_id: str
    title: str
    question: str
    result_type: ResultType
    branch: str
    scope: dict[str, Any]
    data: dict[str, str]
    method: dict[str, Any]
    benchmark: str = ""
    evaluation: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        canon = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def load_study(path: Path) -> StudySpec:
    return parse_study(_load_yaml(Path(path)), Path(path).name)


def parse_study(raw: dict[str, Any], where: str = "研究定义") -> StudySpec:
    _require(raw, ["study_id", "title", "question", "result_type", "branch", "scope",
                   "data", "method"], f"研究定义 {where}")
    try:
        result_type = ResultType(raw["result_type"])
    except ValueError as e:
        raise RegistryError(f"未知成果类型：{raw['result_type']}") from e
    return StudySpec(
        study_id=raw["study_id"],
        title=raw["title"],
        question=raw["question"],
        result_type=result_type,
        branch=raw["branch"],
        scope=dict(raw["scope"]),
        data=dict(raw["data"]),
        method=dict(raw["method"]),
        benchmark=raw.get("benchmark", ""),
        evaluation=list(raw.get("evaluation") or []),
        limitations=list(raw.get("limitations") or []),
        raw=raw,
    )


@dataclass
class Registry:
    root: Path
    sources: dict[str, SourceSpec]
    datasets: dict[str, DatasetSpec]

    @classmethod
    def load(cls, root: Path) -> "Registry":
        root = Path(root)
        sources = load_sources(root / "config" / "sources.yaml")
        datasets = load_datasets(root / "config" / "datasets.yaml", sources)
        return cls(root=root, sources=sources, datasets=datasets)

    def dataset(self, dataset_id: str) -> DatasetSpec:
        try:
            return self.datasets[dataset_id]
        except KeyError:
            raise RegistryError(f"未登记的数据集：{dataset_id}") from None

    def source_of(self, dataset_id: str) -> SourceSpec:
        return self.sources[self.dataset(dataset_id).source_id]
