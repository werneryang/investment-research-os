"""跨模块共享的公共契约：枚举、时间字段与数据对象结构。

模块之间只通过这里定义的结构交换信息（architecture §3、§6），
不依赖彼此的临时文件布局。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
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


class Use(str, Enum):
    """研究用途。用途核验（use_verified）只对声明的用途有效（architecture §5.1）。"""

    DESCRIPTIVE = "descriptive"  # 使用最新修订历史的描述与比较
    POINT_IN_TIME = "point_in_time"  # 只用当时可获知数据的时点研究
    SCENARIO = "scenario"  # 在假设输入上计算的情景（如假设债券的利率冲击）


class VintageSupport(str, Enum):
    """数据集提供历史版本的能力，决定能否用于时点研究。

    只有 SUPPLIER 的行能凭 available_at 证明「当时已知」；NONE 的行还需要
    retrieved_at 证据，即本系统当时确实已经取得该值。
    """

    SUPPLIER = "supplier"  # 供应方提供历史版本及发布日期（如 ALFRED）
    NONE = "none"  # 只有当前修订版本；时点研究只能用当时已取得的本地快照


FREQUENCIES = ("daily", "weekly", "monthly", "quarterly", "annual")

# 资源目录的索引字段（config/sources.yaml）；候选来源的取值是资料入口上的初步判断，未经核验
SOURCE_ACCESS = ("api", "file", "tool", "web", "manual")  # 接口、文件下载、第三方工具、网页资料、人工导入
SOURCE_SIGNUP = ("none", "free_key", "unknown")  # 无需注册、免费注册或 key、未核验
SOURCE_REDISTRIBUTION = ("allowed", "per_series", "restricted", "unknown")  # 公开再分发是否允许


@dataclass(frozen=True)
class VerificationRecord:
    dataset: str | None  # None：来源整体的说明核验，不对任何数据集生效
    status: VerificationStatus
    date: str
    evidence: str
    use: Use | None = None  # 仅 use_verified 需要，且只对该用途有效
    scope: str = ""  # 核验所覆盖的范围说明（期间、样本、方式）
    # 核验覆盖的观测日期范围（含两端）；留空表示该端不设限
    valid_from: date | None = None
    valid_through: date | None = None


# 研究期间相对用途核验日期范围的位置
SCOPE_IN = "in_scope"  # 研究期间完全在核验范围内
SCOPE_PARTIAL = "partial"  # 部分在范围内：uncovered 列出范围外的日期
SCOPE_OUT = "out_of_scope"  # 完全在范围外
SCOPE_NONE = "not_verified"  # 该用途没有用途核验记录


@dataclass(frozen=True)
class UseCoverage:
    status: str
    uncovered: tuple[tuple[date, date], ...] = ()
    records: tuple[VerificationRecord, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "uncovered": [[a.isoformat(), b.isoformat()] for a, b in self.uncovered],
            "verified_ranges": [[(r.valid_from.isoformat() if r.valid_from else None),
                                 (r.valid_through.isoformat() if r.valid_through else None)]
                                for r in self.records],
            "record_dates": [r.date for r in self.records],
        }


def uncovered_spans(start: date, end: date,
                    ranges: list[tuple[date | None, date | None]]) -> list[tuple[date, date]]:
    """[start, end] 中不被任何 ranges（含两端，None 为不设限）覆盖的连续日期区间。"""
    spans: list[tuple[date, date]] = [(start, end)]
    for lo, hi in ranges:
        lo = lo or date.min
        hi = hi or date.max
        nxt = []
        for a, b in spans:
            if b < lo or a > hi:
                nxt.append((a, b))
                continue
            if a < lo:
                nxt.append((a, lo - timedelta(days=1)))
            if b > hi:
                nxt.append((hi + timedelta(days=1), b))
        spans = nxt
    return spans


# 登记数据集之前必须填写的来源字段（architecture §5.1）
ACCESS_FIELDS = ("channel", "license", "registration", "rate_limit", "revisions", "maintenance")


@dataclass(frozen=True)
class SourceSpec:
    """来源登记（architecture §5.1 的最低内容）与资源目录的索引字段。

    候选来源可以只有发布者、入口与索引字段；§5.1 的其余字段在登记数据集（开始接入）前补齐。
    """

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
    name: str = ""  # 目录中显示的短名称
    category: str = ""
    directions: tuple[str, ...] = ()  # 可服务的研究方向（site/content.yaml）
    access: str = ""
    signup: str = "unknown"
    redistribution: str = "unknown"
    coverage: str = ""  # 历史与频率覆盖
    offers: tuple[str, ...] = ()  # 可提供、尚未登记为数据集的数据
    notes: str = ""
    next_step: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.publisher

    def missing_access_fields(self) -> list[str]:
        """接入前必须填写的 §5.1 字段中还空着的。"""
        return [k for k in ACCESS_FIELDS if not getattr(self, k)]

    def best_status(self) -> VerificationStatus:
        """来源整体达到的最高状态（任一数据集或来源说明），只用于资源目录，不代表每个数据集都达到。"""
        order = list(VerificationStatus)
        return max((v.status for v in self.verification), key=order.index, default=VerificationStatus.CANDIDATE)

    def status_for(self, dataset: str, use: Use | None = None) -> VerificationStatus:
        """按「来源 × 数据集 × 用途」取状态。

        说明与接入核验对数据集整体有效；用途核验只在查询同一用途时计入。
        不给用途时，结果最高为 access_verified。
        """
        records = [
            v for v in self.verification
            if v.dataset == dataset
            and (v.status is not VerificationStatus.USE_VERIFIED or (use is not None and v.use is use))
        ]
        if not records:
            return VerificationStatus.CANDIDATE
        order = list(VerificationStatus)
        return max((r.status for r in records), key=order.index)

    def use_record(self, dataset: str, use: Use) -> VerificationRecord | None:
        """该数据集针对该用途的最新一条用途核验记录（含日期、证据与范围）。"""
        records = [v for v in self.verification if v.dataset == dataset
                   and v.status is VerificationStatus.USE_VERIFIED and v.use is use]
        return max(records, key=lambda v: v.date) if records else None

    def use_coverage(self, dataset: str, use: Use, start: date, end: date) -> UseCoverage:
        """研究期间 [start, end] 相对该用途核验日期范围的位置。多条记录的范围取并集。"""
        records = tuple(v for v in self.verification if v.dataset == dataset
                        and v.status is VerificationStatus.USE_VERIFIED and v.use is use)
        if not records:
            return UseCoverage(SCOPE_NONE)
        gaps = uncovered_spans(start, end, [(r.valid_from, r.valid_through) for r in records])
        if not gaps:
            return UseCoverage(SCOPE_IN, (), records)
        status = SCOPE_OUT if gaps == [(start, end)] else SCOPE_PARTIAL
        return UseCoverage(status, tuple(gaps), records)

    def verified_uses(self, dataset: str) -> list[Use]:
        return sorted({v.use for v in self.verification
                       if v.dataset == dataset and v.status is VerificationStatus.USE_VERIFIED
                       and v.use is not None}, key=lambda u: u.value)


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
    vintages: VintageSupport = VintageSupport.NONE
    calendar: str | None = None  # 预期观测日历；用于判断日期覆盖
    archive_data: bool = False  # 是否允许把原始与标准化数据存入公开档案（再分发许可须先确认）
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    value_range: tuple[float, float] | None = None
    # 定时取得（iros fetch --all）的请求；None 表示不参加定时取得
    scheduled_fetch: dict[str, str] | None = None


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


# ---- 财报事实（docs/edgar-design.md §3）--------------------------------------
# 财报不放进 series.v1：同一期间会在多份申报中以不同数值出现，期间长度不一，财年也不对齐日历年。

FUNDAMENTALS_SCHEMA_VERSION = "fundamentals.v1"

# 申报：每份申报一行。accepted_at 为 EDGAR 接受时间（美东，精确到秒），作为发布时间；
# Company Facts API 不给接受时间，只有申报日期，此时 accepted_at 留空
FILING_COLUMNS: list[str] = [
    "accession", "cik", "name", "form", "fiscal_year", "fiscal_period", "period_end", "fye",
    "filed", "accepted_at", "prevrpt", "sic", "source", "retrieved_at",
]

# 财报事实：每个「申报 × 科目 × 期间 × 单位」一行，只含合并口径（无分部、无共同申报人）。
# duration_quarters：0 为时点余额，1 为单季，2–3 为年初至今，4 为全年；
# period_start 只有 Company Facts API 提供（FSDS 只给期末与季度数）。
# available_at：接受时间（缺失时为申报日期）的次日 0 点（美东），保守规则
FACT_COLUMNS: list[str] = [
    "accession", "cik", "taxonomy", "tag", "period_start", "period_end", "duration_quarters",
    "unit", "value", "available_at", "source", "retrieved_at",
]


# 分部与维度事实：FSDS num.txt 中 segments 非空的行（docs/supply-chain-research-design.md §3、§7）。
# 与合并口径事实分表保存：同一数字按不同维度（业务分部、产品、地区、主要客户）各出现一次，不能相加。
# segments 保留 FSDS 原文（如 BusinessSegments=GraphicsSegment;ConsolidationItems=OperatingSegments;），
# 成员名称会随申报改变（NVIDIA 的 ComputeAndNetworking → ComputeAndNetworkingSegment），映射在产业链登记中维护。
# 日期口径：FSDS 把期末取整到最近的月末。period_end（事实的 ddate）与 filing_period_month_end（申报的 period）
# 都是月末口径，不是精确期末（NVIDIA 2026 财年实际止于 2026-01-25，FSDS 记为 2026-01-31）。
# document_period_end 为精确期末，FSDS 不提供，未从申报原文或其他来源取得时留空；跨来源按期间匹配前须先取得精确期末
SEGMENT_FACT_COLUMNS: list[str] = [
    "accession", "cik", "name", "form", "fiscal_year", "fiscal_period", "filing_period_month_end",
    "document_period_end", "accepted_at",
    "taxonomy", "tag", "segments", "period_end", "duration_quarters", "unit", "value",
    "available_at", "source", "retrieved_at",
]

# 官方行业分类（classification.v1）：每个代码一行，保留来源的代码、名称与层级，不改写为其他体系
CLASSIFICATION_SCHEMA_VERSION = "classification.v1"
CLASSIFICATION_COLUMNS: list[str] = [
    "system", "version", "code", "title", "level", "parent", "trilateral", "change_indicator",
]


@dataclass(frozen=True)
class MetricSpec:
    """研究用指标：按顺序取第一个出现的 XBRL 科目（别名），并记录实际使用了哪个。"""

    id: str
    period: str  # duration（期间发生额）或 instant（时点余额）
    unit: str
    tags: tuple[tuple[str, str], ...]  # (taxonomy, tag)
    description: str = ""


@dataclass(frozen=True)
class CompanySpec:
    cik: int
    label: str


@dataclass(frozen=True)
class FundamentalsSpec:
    companies: tuple[CompanySpec, ...]
    metrics: dict[str, MetricSpec]
    forms_annual: tuple[str, ...] = ("10-K", "10-K/A")
