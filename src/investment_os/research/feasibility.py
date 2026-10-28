"""研究单元的输入能力评估（docs/supply-chain-research-design.md §4）：A / B / C / 未评估。

评估绑定一个研究单元（一个问题、一组输入与参数），不给整个行业笼统打分：

- unassessed：必需输入的来源尚未达到接入已验证，或研究单元没有声明所需输入；不计算
- C：有硬错误（单位、方向、地域不可协调等）、核验未通过、假设参数未获准或超出允许范围、
  或所依赖的单元不可计算；受影响的数值不生成。硬错误不能靠改用假设降为 B
- B：结构与量纲成立，关键参数来自允许假设清单（范围、单位与依据齐全）；结果是明示假设的情景
- A：关键基准输入全部核验通过，没有假设参数；在声明范围内计算。假设冲击仍按情景结果发布

等级沿依赖传播：依赖 B 的单元至少为 B，依赖 C 或未评估的单元不计算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import VerificationStatus
from .base import StudyInput

GATE_POLICY_VERSION = "feasibility.v1"
GRADES = ("A", "B", "C", "unassessed")
COMPUTABLE = ("A", "B")

# 至少达到接入已验证的来源才评估；只有资料入口或说明的来源不进入计算
_ASSESSABLE = (VerificationStatus.ACCESS_VERIFIED.value, VerificationStatus.USE_VERIFIED.value)


@dataclass
class Assessment:
    unit: str
    grade: str
    reasons: list[str] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    @property
    def computable(self) -> bool:
        return self.grade in COMPUTABLE

    def to_dict(self) -> dict[str, Any]:
        return {"unit": self.unit, "grade": self.grade, "reasons": list(self.reasons),
                "assumptions": list(self.assumptions), "depends_on": list(self.depends_on),
                "gate_policy_version": GATE_POLICY_VERSION}


def check_assumption(name: str, value: Any, allowed: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """核对一个假设参数是否在允许假设清单内；返回 (记录, 错误)。

    清单每项须有 range [lo, hi]、unit 与 rationale；缺任一项都视为未获准。
    """
    spec = allowed.get(name)
    record: dict[str, Any] = {"name": name, "value": value, "origin_type": "assumed"}
    if not isinstance(spec, dict):
        return record, f"参数 {name} 不在允许假设清单中，既未观察也未获准假设"
    missing = [k for k in ("range", "unit", "rationale") if not spec.get(k)]
    if missing:
        return record, f"参数 {name} 的允许假设缺少 {', '.join(missing)}"
    lo, hi = (float(x) for x in spec["range"])
    record.update(unit=spec["unit"], allowed_range=[lo, hi], rationale=spec["rationale"])
    try:
        x = float(value)
    except (TypeError, ValueError):
        return record, f"参数 {name} 的取值不是数值：{value!r}"
    if not lo <= x <= hi:
        return record, f"参数 {name} = {x:g} 超出允许范围 [{lo:g}, {hi:g}]（{spec['unit']}）"
    return record, None


def assess(unit: str, *, inputs: list[StudyInput], hard_errors: list[str] = (),
           failed_checks: list[str] = (), assumptions: list[dict[str, Any]] = (),
           assumption_errors: list[str] = (), depends_on: list[Assessment] = ()) -> Assessment:
    """按 §4.1 的条件给一个研究单元定级；顺序固定，较严重的条件优先。"""
    deps = [d.unit for d in depends_on]
    if not inputs:
        return Assessment(unit, "unassessed", ["研究单元没有声明所需输入"], depends_on=deps)
    pending = [f"{i.role}（{i.dataset_id}）的来源状态为 {i.source_status}，未达到接入已验证"
               for i in inputs if i.source_status not in _ASSESSABLE]
    if pending:
        return Assessment(unit, "unassessed", pending, depends_on=deps)
    blocked = [f"依赖的单元 {d.unit} 为 {d.grade}" for d in depends_on if not d.computable]
    reasons = [*hard_errors, *failed_checks, *assumption_errors, *blocked]
    if reasons:
        return Assessment(unit, "C", reasons, list(assumptions), deps)
    if assumptions or any(d.grade == "B" for d in depends_on):
        why = [f"使用假设参数 {a['name']} = {a['value']}" for a in assumptions]
        why += [f"依赖的单元 {d.unit} 为 B" for d in depends_on if d.grade == "B"]
        return Assessment(unit, "B", why, list(assumptions), deps)
    return Assessment(unit, "A", ["关键基准输入全部核验通过，未使用假设参数"], [], deps)
