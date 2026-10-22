"""跨模块共享的公共契约：枚举、时间字段与数据对象结构。

模块之间只通过这里定义的结构交换信息（architecture §3、§6），
不依赖彼此的临时文件布局。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    """来源核验状态，按来源 × 数据集 × 用途分别记录（architecture §5.1）。"""

    CANDIDATE = "candidate"  # 候选来源：仅有资料入口
    DOCS_VERIFIED = "docs_verified"  # 说明已核验
    ACCESS_VERIFIED = "access_verified"  # 接入已验证
    USE_VERIFIED = "use_verified"  # 用途已验证


class QualityStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"  # 来源未提供数值；不以零或前值填补
    QUARANTINED = "quarantined"  # 冲突或异常，隔离且不参与计算


class ResultType(str, Enum):
    """研究成果类型（architecture §6.3）。"""

    DESCRIPTIVE = "descriptive"
    EXPLANATORY = "explanatory"
    FORECAST = "forecast"
    SIMULATION = "simulation"


class RunStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"  # 部分结论因数据不足被限制
    FAILED = "failed"


# 标准化序列对象的结构版本。字段变化时递增，并提供迁移。
SERIES_SCHEMA_VERSION = "series.v1"

# 标准化序列的列（architecture §6.2）。数值语义列放在后半部分。
SERIES_COLUMNS: list[str] = [
    "series_id",
    "observation_at",  # 观测对应时点或期间起点（date）
    "value",
    "unit",
    "frequency",
    "currency",
    "published_at",  # 该版本实际发布时间，未知为空
    "available_at",  # 按明示规则最早可用于研究决策的时点，未知为空
    "retrieved_at",  # 系统实际取得资料的时点
    "vintage_id",  # 供应方历史版本，或明确标记的本地快照版本
    "source_id",
    "upstream_id",
    "quality_status",
    "reason",
]


@dataclass(frozen=True)
class AvailabilityRule:
    """把观测期间映射为最早可用时点的保守规则。

    - ``next_day``：观测日次日 0 点（来源时区）
    - ``period_end_lag_days``：观测期间结束后第 ``days`` 天结束时（days=0 即期末次日 0 点）
    - ``published_next_day``：发布日次日 0 点；需要来源提供发布日期
    - ``unknown``：无法确定，``available_at`` 留空，时点敏感研究将拒绝使用
    """

    type: str
    days: int = 0

    VALID_TYPES = ("next_day", "period_end_lag_days", "published_next_day", "unknown")

    def __post_init__(self) -> None:
        if self.type not in self.VALID_TYPES:
            raise ValueError(f"未知的可用时间规则：{self.type}")
        if self.type == "period_end_lag_days" and self.days < 0:
            raise ValueError("period_end_lag_days 的天数不能为负")

    def describe(self) -> str:
        return {
            "next_day": "观测日次日 0 点（来源时区）",
            "period_end_lag_days": f"观测期间结束后第 {self.days} 天结束时（来源时区）",
            "published_next_day": "供应方发布日次日 0 点（来源时区）",
            "unknown": "未知，留空",
        }[self.type]


@dataclass(frozen=True)
class VerificationRecord:
    dataset: str
    status: VerificationStatus
    date: str
    evidence: str
    use: str = ""


@dataclass(frozen=True)
class SourceSpec:
    """来源登记（architecture §5.1 的最低内容）。"""

    id: str
    publisher: str
    channel: str
    url: str
    license: str
    registration: str
    rate_limit: str
    revisions: str
    maintenance: str
    alternatives: tuple[str, ...] = ()
    verification: tuple[VerificationRecord, ...] = ()

    def status_for(self, dataset: str) -> VerificationStatus:
        records = [v for v in self.verification if v.dataset == dataset]
        if not records:
            return VerificationStatus.CANDIDATE
        order = list(VerificationStatus)
        return max((r.status for r in records), key=order.index)


@dataclass(frozen=True)
class DatasetSpec:
    """数据集登记：一个来源下的具体数据对象及其语义。"""

    id: str
    source_id: str
    upstream_id: str
    connector: str
    frequency: str
    unit: str
    currency: str | None
    timezone: str
    availability: AvailabilityRule
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    value_range: tuple[float, float] | None = None


@dataclass
class DatasetVersion:
    """标准化数据集的一个版本及其血缘。"""

    dataset_id: str
    version_id: str
    schema_version: str
    content_hash: str
    created_at: str
    rows: int
    path: str
    raw_snapshots: list[dict[str, Any]]
    transform: str
    quality: dict[str, Any]
    series: dict[str, dict[str, Any]] = field(default_factory=dict)
    parent_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetVersion":
        return cls(**d)
