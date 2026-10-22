"""研究分支的公共契约（模块 M，architecture §6.3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from ..contracts import DatasetVersion, ResultType
from ..registry import StudySpec


@dataclass
class StudyInput:
    """研究分支收到的一个数据输入：已加载的数据及其版本信息。"""

    role: str
    dataset_id: str
    frame: pd.DataFrame
    version: DatasetVersion
    source_status: str


@dataclass
class ResearchResult:
    """所有成果共有的字段；``results`` 与 ``tables`` 由各分支按成果类型填写。"""

    study_id: str
    title: str
    question: str
    result_type: ResultType
    branch: str
    scope: dict[str, Any]
    data_cutoff: str | None
    methods: dict[str, Any]
    inputs: list[dict[str, Any]]
    results: dict[str, Any]
    coverage: dict[str, Any]
    unsupported: list[dict[str, str]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    # 证据表格（以记录列表形式保存，便于报告与复查）
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def is_partial(self) -> bool:
        return bool(self.unsupported) or not self.coverage.get("period_complete", True)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["result_type"] = self.result_type.value
        return d


Branch = Callable[[StudySpec, dict[str, StudyInput]], ResearchResult]
_BRANCHES: dict[str, Branch] = {}


def register_branch(name: str) -> Callable[[Branch], Branch]:
    def deco(fn: Branch) -> Branch:
        _BRANCHES[name] = fn
        return fn
    return deco


def get_branch(name: str) -> Branch:
    try:
        return _BRANCHES[name]
    except KeyError:
        raise ValueError(f"未实现的研究分支：{name}；已实现：{', '.join(sorted(_BRANCHES))}") from None


def input_record(inp: StudyInput) -> dict[str, Any]:
    return {
        "role": inp.role,
        "dataset_id": inp.dataset_id,
        "version_id": inp.version.version_id,
        "content_hash": inp.version.content_hash,
        "source_id": inp.frame["source_id"].iloc[0] if len(inp.frame) else None,
        "source_status": inp.source_status,
    }
