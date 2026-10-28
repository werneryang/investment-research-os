"""固定投入系数的无环约束网络（docs/supply-chain-research-design.md §2.5、§9）。

一个最终产出单位需要若干投入，投入本身又可能需要下一级投入；系数固定、单期、不含库存与替代。
沿网络把每种资源对每单位最终产出的总需求系数累乘、累加，再用各资源能力除以系数求可支持的最大产出：

    最大产出 = min(需求, min_i 能力_i ÷ 总系数_i)，缺口 = 需求 − 最大产出

只做纯数学计算，不判断输入是否适用于某个行业；适用性由研究分支与可行性评估决定。
缺值、单位不一致、回路、非正系数都直接报错，不按零或默认值补齐。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


class ConstraintError(ValueError):
    """网络或输入不能计算：缺值、单位不一致、回路、非正系数等。"""


@dataclass(frozen=True)
class Requirement:
    """生产一单位 ``parent`` 需要 ``coefficient`` 单位的 ``child``（单位 ``unit``）。"""

    parent: str
    child: str
    coefficient: float
    unit: str


@dataclass(frozen=True)
class Capacity:
    resource: str
    value: float
    unit: str


def _number(value: Any, what: str) -> float:
    if value is None or isinstance(value, bool):
        raise ConstraintError(f"{what} 缺失")
    x = float(value)
    if math.isnan(x):
        raise ConstraintError(f"{what} 缺失")
    if math.isinf(x):
        raise ConstraintError(f"{what} 不是有限数")
    return x


def total_coefficients(final: str, requirements: list[Requirement]) -> dict[str, tuple[float, str]]:
    """每种下级资源对每单位 ``final`` 的总需求系数及其单位（多条路径相加）。"""
    children: dict[str, list[Requirement]] = {}
    units: dict[str, str] = {}
    for r in requirements:
        c = _number(r.coefficient, f"{r.parent} → {r.child} 的系数")
        if c <= 0:
            raise ConstraintError(f"{r.parent} → {r.child} 的系数必须为正：{c}")
        if r.child == final:
            raise ConstraintError(f"{r.parent} → {r.child} 指回最终产出，形成回路")
        if units.setdefault(r.child, r.unit) != r.unit:
            raise ConstraintError(f"资源 {r.child} 的单位不一致：{units[r.child]} 与 {r.unit}")
        children.setdefault(r.parent, []).append(r)

    totals: dict[str, float] = {}
    visiting: list[str] = []

    def walk(node: str, multiplier: float) -> None:
        if node in visiting:
            raise ConstraintError("约束网络有回路：" + " → ".join([*visiting[visiting.index(node):], node]))
        visiting.append(node)
        for r in children.get(node, []):
            amount = multiplier * float(r.coefficient)
            totals[r.child] = totals.get(r.child, 0.0) + amount
            walk(r.child, amount)
        visiting.pop()

    walk(final, 1.0)
    if not totals:
        raise ConstraintError(f"最终产出 {final} 没有任何投入要求")
    return {k: (v, units[k]) for k, v in totals.items()}


def max_output(final: str, demand: float, requirements: list[Requirement],
               capacities: list[Capacity]) -> dict[str, Any]:
    """在各资源能力约束下可支持的最大最终产出、瓶颈与缺口。

    每种被要求的资源都必须给出能力且单位与要求一致；多给的资源报错，避免拼错名称被静默忽略。
    """
    d = _number(demand, f"{final} 的需求")
    if d < 0:
        raise ConstraintError(f"{final} 的需求不能为负：{d}")
    totals = total_coefficients(final, requirements)
    caps: dict[str, Capacity] = {}
    for cap in capacities:
        if cap.resource in caps:
            raise ConstraintError(f"资源 {cap.resource} 的能力重复给出")
        caps[cap.resource] = cap
    unknown = sorted(set(caps) - set(totals))
    if unknown:
        raise ConstraintError(f"能力中有网络未使用的资源：{', '.join(unknown)}")
    supported: dict[str, float] = {}
    for resource, (coef, unit) in totals.items():
        cap = caps.get(resource)
        if cap is None:
            raise ConstraintError(f"资源 {resource} 缺少能力，不能按无限或零处理")
        if cap.unit != unit:
            raise ConstraintError(f"资源 {resource} 的能力单位 {cap.unit} 与需求单位 {unit} 不一致")
        value = _number(cap.value, f"资源 {resource} 的能力")
        if value < 0:
            raise ConstraintError(f"资源 {resource} 的能力不能为负：{value}")
        supported[resource] = value / coef
    limit = min(supported.values())
    output = min(d, limit)
    binding = sorted(r for r, v in supported.items() if v == limit)
    return {
        "final": final,
        "demand": d,
        "output": output,
        "shortfall": d - output,
        "binding": binding if limit < d else [],
        "supported_by_resource": supported,
        "requirements": {r: {"coefficient": c, "unit": u, "required": d * c, "capacity": caps[r].value}
                         for r, (c, u) in totals.items()},
    }
