"""读取并校验 config/ 下的来源、数据集与研究定义登记（模块 Q）。"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .calendars import CalendarSpec, load_calendars
from .contracts import (
    FREQUENCIES,
    AvailabilityRule,
    DatasetSpec,
    ResultType,
    SourceSpec,
    Use,
    VerificationRecord,
    VerificationStatus,
    VintageSupport,
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
            use = None
            if v.get("use") is not None:
                try:
                    use = Use(v["use"])
                except ValueError as e:
                    raise RegistryError(f"来源 {item['id']} 的核验用途无效：{v['use']}；"
                                        f"可用：{', '.join(u.value for u in Use)}") from e
            if status is VerificationStatus.USE_VERIFIED and use is None:
                raise RegistryError(f"来源 {item['id']} 的 use_verified 记录必须声明 use")
            records.append(VerificationRecord(
                dataset=v["dataset"], status=status, date=str(v["date"]),
                evidence=v["evidence"], use=use, scope=v.get("scope", ""),
            ))
        sources[item["id"]] = SourceSpec(
            **{k: item[k] for k in required},
            alternatives=tuple(item.get("alternatives") or ()),
            verification=tuple(records),
        )
    return sources


def load_datasets(path: Path, sources: dict[str, SourceSpec],
                  calendars: dict[str, CalendarSpec] | None = None) -> dict[str, DatasetSpec]:
    raw = _load_yaml(path).get("datasets") or {}
    datasets: dict[str, DatasetSpec] = {}
    for ds_id, item in raw.items():
        _require(item, ["source_id", "upstream_id", "connector", "frequency", "unit",
                        "timezone", "availability"], f"数据集 {ds_id}")
        if item["source_id"] not in sources:
            raise RegistryError(f"数据集 {ds_id} 引用了未登记来源 {item['source_id']}")
        if item["frequency"] not in FREQUENCIES:
            raise RegistryError(f"数据集 {ds_id} 的频率 {item['frequency']} 不受支持；"
                                f"可用：{', '.join(FREQUENCIES)}")
        calendar = item.get("calendar")
        if calendar is not None and calendar not in (calendars or {}):
            raise RegistryError(f"数据集 {ds_id} 引用了未登记日历 {calendar}")
        try:
            vintages = VintageSupport(item.get("vintages", VintageSupport.NONE.value))
        except ValueError as e:
            raise RegistryError(f"数据集 {ds_id} 的 vintages 无效：{item.get('vintages')}") from e
        av = item["availability"]
        try:
            availability = AvailabilityRule(type=av["type"], days=int(av.get("days", 0)))
        except ValueError as e:
            raise RegistryError(f"数据集 {ds_id}：{e}") from e
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
            availability=availability,
            vintages=vintages,
            calendar=calendar,
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
    def use(self) -> Use:
        """研究用途由版本策略决定：as_of 为时点研究，其余为使用最新修订的描述。"""
        return Use.POINT_IN_TIME if self.scope.get("vintage_policy") == "as_of" else Use.DESCRIPTIVE

    @property
    def config_hash(self) -> str:
        canon = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()


_RELATIVE = re.compile(r"^today(?:-(\d+)([dmy]))?$")


def resolve_relative_dates(raw: dict[str, Any], today: date) -> dict[str, Any]:
    """把 scope.start/end 中的 today、today-30d、today-6m、today-1y 换算为具体日期。

    运行时换算一次并写入运行清单，复现时使用换算后的固定日期，而不是重新取「今天」。
    """
    out = copy.deepcopy(raw)
    scope = out.get("scope") or {}
    resolved = {}
    for key in ("start", "end"):
        value = scope.get(key)
        m = _RELATIVE.match(str(value)) if isinstance(value, str) else None
        if not m:
            continue
        n, unit = m.groups()
        delta = pd.DateOffset(**{{"d": "days", "m": "months", "y": "years"}[unit]: int(n)}) if n else None
        day = (pd.Timestamp(today) - delta) if delta is not None else pd.Timestamp(today)
        scope[key] = day.date().isoformat()
        resolved[key] = value
    if resolved:
        scope["relative_dates"] = resolved
    return out


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
    calendars: dict[str, CalendarSpec] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Registry":
        root = Path(root)
        sources = load_sources(root / "config" / "sources.yaml")
        cal_path = root / "config" / "calendars.yaml"
        calendars = load_calendars(_load_yaml(cal_path)) if cal_path.exists() else {}
        datasets = load_datasets(root / "config" / "datasets.yaml", sources, calendars)
        return cls(root=root, sources=sources, datasets=datasets, calendars=calendars)

    def dataset(self, dataset_id: str) -> DatasetSpec:
        try:
            return self.datasets[dataset_id]
        except KeyError:
            raise RegistryError(f"未登记的数据集：{dataset_id}") from None

    def source_of(self, dataset_id: str) -> SourceSpec:
        return self.sources[self.dataset(dataset_id).source_id]
