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
    ACCESS_FIELDS,
    FREQUENCIES,
    SOURCE_ACCESS,
    SOURCE_REDISTRIBUTION,
    SOURCE_SIGNUP,
    AvailabilityRule,
    CompanySpec,
    DatasetSpec,
    FundamentalsSpec,
    MetricSpec,
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


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _choice(item: dict[str, Any], key: str, choices: tuple[str, ...], default: str) -> str:
    value = item.get(key, default)
    if value not in choices:
        raise RegistryError(f"来源 {item['id']} 的 {key} 无效：{value}；可用：{', '.join(choices)}")
    return value


def load_sources(path: Path) -> dict[str, SourceSpec]:
    """来源登记。候选来源只需发布者与入口；§5.1 的其余字段在登记数据集前补齐（见 load_datasets）。"""
    data = _load_yaml(path)
    raw = data.get("sources") or []
    categories = data.get("categories") or {}
    sources: dict[str, SourceSpec] = {}
    for item in raw:
        _require(item, ["id", "publisher", "url"], f"来源 {item.get('id', '?')}")
        if item["id"] in sources:
            raise RegistryError(f"来源 ID 重复：{item['id']}")
        if categories and item.get("category") not in categories:
            raise RegistryError(f"来源 {item['id']} 的类别无效：{item.get('category')}；"
                                f"可用：{', '.join(categories)}")
        records = []
        for v in item.get("verification") or []:
            _require(v, ["status", "date", "evidence"], f"来源 {item['id']} 的核验记录")
            try:
                status = VerificationStatus(v["status"])
            except ValueError as e:
                raise RegistryError(f"来源 {item['id']} 的核验状态无效：{v['status']}") from e
            dataset = v.get("dataset")
            # 一个样本取得成功不代表整个来源可用：接入与用途核验必须指明数据集
            if dataset is None and status is not VerificationStatus.DOCS_VERIFIED:
                raise RegistryError(f"来源 {item['id']} 的 {status.value} 记录必须指明数据集；"
                                    f"不指明数据集的记录只能是 docs_verified")
            use = None
            if v.get("use") is not None:
                try:
                    use = Use(v["use"])
                except ValueError as e:
                    raise RegistryError(f"来源 {item['id']} 的核验用途无效：{v['use']}；"
                                        f"可用：{', '.join(u.value for u in Use)}") from e
            if status is VerificationStatus.USE_VERIFIED and use is None:
                raise RegistryError(f"来源 {item['id']} 的 use_verified 记录必须声明 use")
            try:
                valid_from = _date_or_none(v.get("valid_from"))
                valid_through = _date_or_none(v.get("valid_through"))
            except ValueError as e:
                raise RegistryError(f"来源 {item['id']} 的核验日期范围无效：{e}") from e
            if valid_from and valid_through and valid_from > valid_through:
                raise RegistryError(f"来源 {item['id']} 的核验日期范围起点晚于终点")
            records.append(VerificationRecord(
                dataset=dataset, status=status, date=str(v["date"]),
                evidence=v["evidence"], use=use, scope=v.get("scope", ""),
                valid_from=valid_from, valid_through=valid_through,
            ))
        sources[item["id"]] = SourceSpec(
            id=item["id"], publisher=item["publisher"], url=item["url"],
            **{k: item.get(k) or "" for k in ACCESS_FIELDS},
            alternatives=tuple(item.get("alternatives") or ()),
            verification=tuple(records),
            name=item.get("name", ""),
            category=item.get("category", ""),
            directions=tuple(item.get("directions") or ()),
            access=_choice(item, "access", SOURCE_ACCESS + ("",), ""),
            signup=_choice(item, "signup", SOURCE_SIGNUP, "unknown"),
            redistribution=_choice(item, "redistribution", SOURCE_REDISTRIBUTION, "unknown"),
            coverage=item.get("coverage", ""),
            offers=tuple(item.get("offers") or ()),
            notes=item.get("notes", ""),
            next_step=item.get("next_step", ""),
        )
    return sources


def load_source_index(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """资源目录的类别（id → 名称）与能力缺口。"""
    data = _load_yaml(path)
    gaps = data.get("gaps") or []
    for g in gaps:
        _require(g, ["name", "detail"], "能力缺口")
    return dict(data.get("categories") or {}), list(gaps)


def _scheduled(ds_id: str, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"start", "end"}:
        raise RegistryError(f"数据集 {ds_id} 的 scheduled_fetch 只能包含 start、end")
    return {k: str(v) for k, v in value.items()}


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
        missing = sources[item["source_id"]].missing_access_fields()
        if missing:
            raise RegistryError(f"数据集 {ds_id} 的来源 {item['source_id']} 是候选登记，接入前须补齐："
                                f"{', '.join(missing)}（architecture §5.1）")
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
            archive_data=bool(item.get("archive_data", False)),
            description=item.get("description", ""),
            params=dict(item.get("params") or {}),
            value_range=(float(vr[0]), float(vr[1])) if vr else None,
            scheduled_fetch=_scheduled(ds_id, item.get("scheduled_fetch")),
        )
    return datasets


def load_fundamentals(path: Path) -> FundamentalsSpec:
    """财报指标与公司登记（config/fundamentals.yaml）。"""
    raw = _load_yaml(path)
    metrics: dict[str, MetricSpec] = {}
    for mid, m in (raw.get("metrics") or {}).items():
        _require(m, ["period", "unit", "tags"], f"指标 {mid}")
        if m["period"] not in ("duration", "instant"):
            raise RegistryError(f"指标 {mid} 的 period 只能是 duration 或 instant")
        tags = []
        for t in m["tags"]:
            taxonomy, _, tag = str(t).partition(":")
            if not tag:
                raise RegistryError(f"指标 {mid} 的科目 {t} 应写成 taxonomy:tag")
            tags.append((taxonomy, tag))
        metrics[mid] = MetricSpec(id=mid, period=m["period"], unit=m["unit"], tags=tuple(tags),
                                  description=m.get("description", ""))
    companies = []
    for c in raw.get("companies") or []:
        _require(c, ["cik", "label"], "财报公司")
        companies.append(CompanySpec(cik=int(c["cik"]), label=str(c["label"])))
    if len({c.cik for c in companies}) != len(companies):
        raise RegistryError("财报公司的 CIK 重复")
    return FundamentalsSpec(companies=tuple(companies), metrics=metrics)


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
        """研究用途：情景模拟为 scenario；否则由版本策略决定（as_of 为时点研究，其余为描述）。"""
        if self.result_type is ResultType.SIMULATION:
            return Use.SCENARIO
        return Use.POINT_IN_TIME if self.scope.get("vintage_policy") == "as_of" else Use.DESCRIPTIVE

    @property
    def config_hash(self) -> str:
        canon = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()


_RELATIVE = re.compile(r"^today(?:-(\d+)([dmy]))?$")


def _resolve_relative(value: Any, today: date) -> str | None:
    """today、today-30d、today-6m、today-1y → 具体日期；其他值返回 None。"""
    m = _RELATIVE.match(value) if isinstance(value, str) else None
    if not m:
        return None
    n, unit = m.groups()
    delta = pd.DateOffset(**{{"d": "days", "m": "months", "y": "years"}[unit]: int(n)}) if n else None
    day = (pd.Timestamp(today) - delta) if delta is not None else pd.Timestamp(today)
    return day.date().isoformat()


def resolve_relative_dates(raw: dict[str, Any], today: date) -> dict[str, Any]:
    """把 scope.start/end 中的 today、today-30d、today-6m、today-1y 换算为具体日期。

    运行时换算一次并写入运行清单，复现时使用换算后的固定日期，而不是重新取「今天」。
    """
    out = copy.deepcopy(raw)
    scope = out.get("scope") or {}
    resolved = {}
    for key in ("start", "end"):
        day = _resolve_relative(scope.get(key), today)
        if day is None:
            continue
        resolved[key] = scope[key]
        scope[key] = day
    if resolved:
        scope["relative_dates"] = resolved
    return out


def scheduled_request(spec: DatasetSpec, today: date) -> dict[str, Any]:
    """定时取得的请求：scheduled_fetch 中的相对日期按当天换算。"""
    request = dict(spec.scheduled_fetch or {})
    for key in ("start", "end"):
        day = _resolve_relative(request.get(key), today)
        if day is not None:
            request[key] = day
    return request


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
    source_categories: dict[str, str] = field(default_factory=dict)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    fundamentals: FundamentalsSpec | None = None

    @classmethod
    def load(cls, root: Path) -> "Registry":
        root = Path(root)
        sources = load_sources(root / "config" / "sources.yaml")
        categories, gaps = load_source_index(root / "config" / "sources.yaml")
        cal_path = root / "config" / "calendars.yaml"
        calendars = load_calendars(_load_yaml(cal_path)) if cal_path.exists() else {}
        datasets = load_datasets(root / "config" / "datasets.yaml", sources, calendars)
        fund_path = root / "config" / "fundamentals.yaml"
        fundamentals = load_fundamentals(fund_path) if fund_path.exists() else None
        return cls(root=root, sources=sources, datasets=datasets, calendars=calendars,
                   source_categories=categories, gaps=gaps, fundamentals=fundamentals)

    def dataset(self, dataset_id: str) -> DatasetSpec:
        try:
            return self.datasets[dataset_id]
        except KeyError:
            raise RegistryError(f"未登记的数据集：{dataset_id}") from None

    def source_of(self, dataset_id: str) -> SourceSpec:
        return self.sources[self.dataset(dataset_id).source_id]
