"""数据覆盖条：按日期显示曲线观测日与各关键期限是否有合格值（服务端生成的 SVG）。

预期日期 = 结果中的有效观测日 ∪ 结果记录的缺失日期。缺失日期只在结果中有完整列表时
才能完整显示；旧结果只有示例时如实注明。

宽屏显示逐日覆盖条；窄屏逐日格子不足 1 像素，改显示按月汇总（取当月最差状态，未取得日不计）。
非合格日期另以文字列表给出，触屏与键盘也能查看，不依赖悬停提示。
"""

from __future__ import annotations

from typing import Any

from .common import e

CELL_W, ROW_H, GAP, LABEL_W = 3, 14, 4, 46
MONTH_W, MONTH_ROW_H, MONTH_LABEL_W = 24, 16, 40

# 状态：(类名, 说明)；按严重程度从高到低排列，月汇总取最严重的一个
STATUS = {
    "miss": ("cov-miss", "下载时已过保守可用时点，仍没有数据"),
    "gap": ("cov-gap", "当日有曲线，但该期限无合格值"),
    "pending": ("cov-pending", "未取得：数据下载时尚未到保守可用时点（不代表已确认尚未发布）"),
    "ok": ("cov-ok", "有合格观测"),
}
SEVERITY = list(STATUS)
# 月汇总：未取得不是缺陷，只在整月都未取得时显示，避免一个未取得日把整月画成空白
MONTH_SEVERITY = ["miss", "gap", "ok", "pending"]


def _status(row: dict[str, Any] | None, day: str, tenor: str | None, pending: set[str]) -> str:
    if row is None:
        return "pending" if day in pending else "miss"
    return "ok" if tenor is None or row.get(tenor) is not None else "gap"


def _daily_svg(days: list[str], rows: list[tuple[str, str | None]], grid: dict, aria: str) -> str:
    width = LABEL_W + len(days) * CELL_W
    height = len(rows) * (ROW_H + GAP) + 16
    parts = []
    for i, (label, _) in enumerate(rows):
        y = i * (ROW_H + GAP)
        parts.append(f'<text class="cov-label" x="0" y="{y + ROW_H - 3}">{e(label)}</text>')
        for j, day in enumerate(days):
            cls, tip = STATUS[grid[label][j]]
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
    return (f'<svg class="cov-daily" viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMinYMin meet" '
            f'role="img" aria-label="{aria}">{"".join(parts)}</svg>')


def _monthly_svg(days: list[str], rows: list[tuple[str, str | None]], grid: dict, aria: str) -> str:
    months = sorted({d[:7] for d in days})
    index = {m: i for i, m in enumerate(months)}
    width = MONTH_LABEL_W + len(months) * MONTH_W
    height = len(rows) * (MONTH_ROW_H + GAP) + 28
    parts = []
    for i, (label, _) in enumerate(rows):
        y = i * (MONTH_ROW_H + GAP)
        parts.append(f'<text class="cov-label-m" x="0" y="{y + MONTH_ROW_H - 4}">{e(label)}</text>')
        worst: dict[str, int] = {}
        counts: dict[str, int] = {}
        for day, s in zip(days, grid[label]):
            m = day[:7]
            worst[m] = min(worst.get(m, len(MONTH_SEVERITY)), MONTH_SEVERITY.index(s))
            counts[m] = counts.get(m, 0) + (s == "ok")
        for m in months:
            cls, tip = STATUS[MONTH_SEVERITY[worst[m]]]
            total = sum(d[:7] == m for d in days)
            parts.append(f'<rect class="m {cls}" x="{MONTH_LABEL_W + index[m] * MONTH_W}" y="{y}" '
                         f'width="{MONTH_W - 2}" height="{MONTH_ROW_H}" rx="2">'
                         f'<title>{e(m)} {e(label)}：{counts[m]}/{total} 天合格；最差状态：{tip}</title></rect>')
    base = len(rows) * (MONTH_ROW_H + GAP)
    for m in months:
        x = MONTH_LABEL_W + index[m] * MONTH_W + (MONTH_W - 2) / 2
        parts.append(f'<text class="cov-tick-m" x="{x}" y="{base + 9}" text-anchor="middle">{int(m[5:])}月</text>')
        if m == months[0] or m.endswith("-01"):
            parts.append(f'<text class="cov-tick-m" x="{x}" y="{base + 22}" text-anchor="middle">{m[:4]}</text>')
    return (f'<svg class="cov-monthly" viewBox="0 0 {width} {height}" width="100%" '
            f'preserveAspectRatio="xMinYMin meet" role="img" aria-label="{aria}（按月汇总）">{"".join(parts)}</svg>')


def _exceptions(days: list[str], rows: list[tuple[str, str | None]], grid: dict) -> str:
    """非合格日期的文字列表：同一天的多个期限合并为一行。"""
    lines = []
    for j, day in enumerate(days):
        by_status: dict[str, list[str]] = {}
        for label, _ in rows:
            s = grid[label][j]
            if s != "ok":
                by_status.setdefault(s, []).append(label)
        for s in SEVERITY:
            if s in by_status:
                labels = by_status[s]
                where = "整日" if labels[0] == rows[0][0] else "、".join(labels)
                lines.append(f'<li><span class="key {STATUS[s][0]}"></span>{e(day)} · {e(where)}：{STATUS[s][1]}</li>')
    if not lines:
        return '<p class="small muted">所有预期观测日、所有关键期限均有合格观测。</p>'
    return (f'<details class="cov-exceptions"><summary>非合格日期（{len(lines)} 条）</summary>'
            f'<ul>{"".join(lines)}</ul></details>')


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
    grid = {label: [_status(observed.get(d), d, tenor, pending) for d in days] for label, tenor in rows}
    aria = f"数据覆盖：{len(observed)} 个观测日，{len(missing)} 个缺失日"
    note = ("<p class=\"small warn\">结果只记录了部分缺失日期，覆盖条只显示其中一部分。</p>"
            if partial_list else "")
    return f"""
<figure class="coverage">
  {_daily_svg(days, rows, grid, aria)}
  {_monthly_svg(days, rows, grid, aria)}
  <figcaption class="small muted"><span class="key cov-ok"></span>有合格观测
  <span class="key cov-gap"></span>当日有曲线但该期限缺失 <span class="key cov-miss"></span>已过可用时点仍无数据
  <span class="key cov-pending"></span>未取得（下载时未到保守可用时点）
  · 横轴为预期观测日（{len(days)} 天）<span class="cov-note-daily">，悬停单元格可看日期</span><span class="cov-note-monthly">；窄屏按月汇总，颜色取当月最差状态（未取得日不计）</span>。</figcaption>
  {_exceptions(days, rows, grid)}
  {note}
</figure>"""
