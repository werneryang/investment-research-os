"""数据覆盖条：按日期显示曲线观测日与各关键期限是否有合格值（服务端生成的 SVG）。

预期日期 = 结果中的有效观测日 ∪ 结果记录的缺失日期。缺失日期只在结果中有完整列表时
才能完整显示；旧结果只有示例时如实注明。
"""

from __future__ import annotations

from typing import Any

from .common import e

CELL_W, ROW_H, GAP, LABEL_W = 3, 14, 4, 46


def coverage_strip(result: dict[str, Any]) -> str:
    cov = result.get("coverage", {})
    daily = result.get("tables", {}).get("daily", [])
    if not daily and not cov.get("missing_dates"):
        return '<p class="muted small">没有可显示的观测。</p>'
    observed = {r["date"]: r for r in daily}
    missing = list(cov.get("missing_dates") or cov.get("missing_examples") or [])
    pending = set(cov.get("pending_dates") or [])
    partial_list = not cov.get("missing_dates") and (cov.get("missing_days") or 0) > len(missing)
    days = sorted(set(observed) | set(missing) | pending)
    tenors = list(cov.get("tenors", {}))
    rows = [("观测日", None)] + [(t, t) for t in tenors]
    width = LABEL_W + len(days) * CELL_W
    height = len(rows) * (ROW_H + GAP) + 16

    parts = []
    for i, (label, tenor) in enumerate(rows):
        y = i * (ROW_H + GAP)
        parts.append(f'<text class="cov-label" x="0" y="{y + ROW_H - 3}">{e(label)}</text>')
        for j, day in enumerate(days):
            row = observed.get(day)
            if row is None and day in pending:
                cls, tip = "cov-pending", "未取得：数据下载时尚未到保守可用时点（不代表已确认尚未发布）"
            elif row is None:
                cls, tip = "cov-miss", "下载时已过保守可用时点，仍没有数据"
            elif tenor is None or row.get(tenor) is not None:
                cls, tip = "cov-ok", "有合格观测"
            else:
                cls, tip = "cov-gap", "当日有曲线，但该期限无合格值"
            parts.append(f'<rect class="{cls}" x="{LABEL_W + j * CELL_W}" y="{y}" width="{CELL_W - 0.6}" '
                         f'height="{ROW_H}"><title>{e(day)} {e(label)}：{tip}</title></rect>')
    # 月份刻度
    seen: set[str] = set()
    last_x = -100.0
    for j, day in enumerate(days):
        if day[:7] not in seen:
            seen.add(day[:7])
            x = LABEL_W + j * CELL_W
            if x - last_x < 36:  # 首月不足几天时不与下一个月份标签重叠
                continue
            last_x = x
            parts.append(f'<text class="cov-tick" x="{x}" y="{height - 2}">{e(day[2:7].replace("-", "/"))}</text>')
    note = ("<p class=\"small warn\">结果只记录了部分缺失日期，覆盖条只显示其中一部分。</p>"
            if partial_list else "")
    return f"""
<figure class="coverage">
  <svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMinYMin meet" role="img"
       aria-label="数据覆盖：{len(observed)} 个观测日，{len(missing)} 个缺失日">{''.join(parts)}</svg>
  <figcaption class="small muted"><span class="key cov-ok"></span>有合格观测
  <span class="key cov-gap"></span>当日有曲线但该期限缺失 <span class="key cov-miss"></span>已过可用时点仍无数据
  <span class="key cov-pending"></span>未取得（下载时未到保守可用时点）
  · 横轴为预期观测日（{len(days)} 天）。悬停单元格可看日期。</figcaption>
  {note}
</figure>"""
