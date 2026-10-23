"""研究分支的公共契约（模块 M，architecture §6.3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from ..contracts import DatasetVersion, ResultType
from ..registry import Registry, StudySpec


@dataclass
class StudyInput:
    """研究分支收到的一个数据输入：已加载的数据及其版本信息。"""

    role: str
    dataset_id: str
    frame: pd.DataFrame
    version: DatasetVersion
    source_status: str
    # 用途已验证时，研究期间相对核验日期范围的位置（UseCoverage.to_dict()）；其他情况为 None
    use_scope: dict[str, Any] | None = None


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
    # 运行时固定的解释（findings.interpret）；旧结果没有该字段
    interpretation: dict[str, Any] | None = None

    @property
    def is_partial(self) -> bool:
        if self.unsupported:
            return True
        state = self.coverage.get("completeness")
        if state is None:  # 旧结果没有 completeness 字段
            return not self.coverage.get("period_complete", True)
        return state not in ("complete", "complete_to_date")

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["result_type"] = self.result_type.value
        if d["interpretation"] is None:  # 只在有解释时写入，旧结果的结构与校验值不变
            del d["interpretation"]
        return d


# 分支接收研究定义、输入与登记（用于日历等公共参照），返回结构化成果
Branch = Callable[[StudySpec, dict[str, StudyInput], Registry], ResearchResult]
_BRANCHES: dict[str, Branch] = {}
_RESULT_TYPES: dict[str, tuple[ResultType, ...]] = {}


def register_branch(name: str, result_types: tuple[ResultType, ...] = (ResultType.DESCRIPTIVE,)
                    ) -> Callable[[Branch], Branch]:
    """注册研究分支，并声明它支持的成果类型（研究能力地图据此显示）。"""
    def deco(fn: Branch) -> Branch:
        _BRANCHES[name] = fn
        _RESULT_TYPES[name] = tuple(result_types)
        return fn
    return deco


def branch_result_types() -> dict[str, tuple[ResultType, ...]]:
    return dict(_RESULT_TYPES)


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
        # 只在有值时写入，旧运行的结果结构与校验值保持不变
        **({"use_scope": inp.use_scope} if inp.use_scope is not None else {}),
    }
