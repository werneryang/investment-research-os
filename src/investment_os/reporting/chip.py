"""芯片经营分析的报告段落与图表：研究单元等级、分部数字与派生比率、受限请求。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

GRADE_LABEL = {"A": "A：已核验输入", "B": "B：明示假设", "C": "C：受阻，不生成数值", "unassessed": "未评估：不计算"}
ATTRIBUTION_LABEL = {"confirmed": "已人工签认", "reviewed": "技术复核通过（未人工签认）", "candidate": "候选（未复核）",
                     "unmapped": "未登记映射"}
METRIC_LABEL = {"Revenues": "营收", "RevenueFromContractWithCustomerExcludingAssessedTax": "营收",
                "OperatingIncomeLoss": "营业利润", "CostOfGoodsAndServicesSold": "销售成本"}


def _m(v: Any) -> str:
    """美元 → 百万美元。"""
    return "—" if v is None else f"{v / 1e6:,.0f}"


def _p(v: Any) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def sections(result: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    units = result["results"]["units"]
    body: list[Any] = [
        "每个研究单元单独定级，数字全部取自同一份年度申报；比率与同比只在该申报内计算。"
        "输入能力只评价分部财务输入；分部到芯片活动的归属另列：技术复核通过为 reviewed（不等于人工签认），未复核为候选。",
        ("table", ["研究单元", "输入能力", "活动归属", "所用申报", "依据"],
         [[u["id"], GRADE_LABEL.get(u["grade"], u["grade"]),
           ATTRIBUTION_LABEL.get(u["attribution_status"], u["attribution_status"]) if u["grade"] in ("A", "B") else "—",
           f"`{u['filing']}`" if u["filing"] else "—", "；".join(u["reasons"])] for u in units]),
    ]
    names = {}
    for u in units:
        rows = result["tables"].get(u["id"]) or []
        if not rows:
            continue
        revenue = next(t for t in u["metrics"] if METRIC_LABEL.get(t) == "营收")
        has_cost = "CostOfGoodsAndServicesSold" in u["metrics"]
        body.append(f"**{u['id']}**：{u['question']}（{u['observation']}；单位百万美元，财年按 FSDS 月末口径）")
        head = ["分部", "财年", "营收", "营收同比", "营业利润", "营业利润率"] + (["销售成本", "毛利率"] if has_cost else [])
        body.append(("table", head, [
            [r["entity"], str(r["fiscal_year"]), _m(r[revenue]), _p(r.get("revenue_growth")),
             _m(r.get("OperatingIncomeLoss")), _p(r.get("operating_margin"))]
            + ([_m(r.get("CostOfGoodsAndServicesSold")), _p(r.get("gross_margin"))] if has_cost else [])
            for r in rows]))
        names[u["id"]] = u
    detail: list[Any] = []
    for u in units:
        if u.get("link_review"):
            detail.append(("table", ["映射", "匹配", "有效期", "状态", "技术复核与结论边界"], [
                [f"`{x['link']}`", x["match"], f"{x['valid_from'] or '未登记'} — {x['valid_to'] or '未登记'}",
                 ATTRIBUTION_LABEL.get(x["status"], x["status"]),
                 (f"{x['technical_review']['review']}（{x['technical_review']['reviewed_at']}，"
                  f"{x['technical_review']['result']}）：{x['technical_review']['limits']}")
                 if x["technical_review"] else "—"] for x in u["link_review"]]))
        if u["known_gaps"]:
            detail.append(f"**{u['id']}** 已知缺口：" + "；".join(u["known_gaps"]))
        if u["filings_skipped"]:
            detail.append(f"{u['id']} 跳过的较新申报：" + "；".join(u["filings_skipped"]))
    bundle = result["methods"].get("bundle") or {}
    detail.append(f"证据包生成于 {bundle.get('built_at', '—')}，产业链登记 {bundle.get('catalog_version', '—')}；"
                  f"分部事实分区 {len(bundle.get('segment_fact_partitions') or {})} 个。")
    return body, "单元口径与缺口", detail


def check_line(name: str, v: dict[str, Any]) -> str:
    kind = name.split(":")[0]
    if v.get("status") == "skipped":
        return f"；{v.get('reason', '未核对')}"
    if kind == "segment_total":
        return f"；{v['checked']} 个财年，各分部（含 AllOtherSegments）营收之和与同一申报的合并营收比较（容差 1 美元）"
    if kind == "gross_profit":
        return f"；{v['checked']} 项，分部毛利与营收减销售成本比较（容差 1 美元）"
    return ""


def figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    import matplotlib.pyplot as plt

    from .report import _save, _style

    figs: list[tuple[str, Path]] = []
    units = [u for u in result["results"]["units"] if result["tables"].get(u["id"])]
    if not units:
        return figs
    _style()
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, len(units), figsize=(5 * len(units), 3.8), squeeze=False)
    for ax, u in zip(axes[0], units):
        rows = result["tables"][u["id"]]
        revenue = next(t for t in u["metrics"] if METRIC_LABEL.get(t) == "营收")
        years = sorted({r["fiscal_year"] for r in rows})
        bottom = [0.0] * len(years)
        for e in dict.fromkeys(r["entity"] for r in rows):
            vals = [next(r[revenue] for r in rows if r["entity"] == e and r["fiscal_year"] == y) / 1e9 for y in years]
            ax.bar([str(y) for y in years], vals, bottom=bottom, label=e.split("_", 2)[-1])
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_title(f"{u['id']}: segment revenue (USD bn)")
        ax.legend(frameon=False, fontsize=8)
    figs.append(("分部营收（同一申报，十亿美元）", _save(fig, out_dir / "chip_segment_revenue.png")))
    return figs
