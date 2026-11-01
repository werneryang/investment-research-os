"""网站图形的共用部件。

- 交互面板：chart.json 的 kind="panels"，由 site/assets/charts.js 绘制（折线、散点、柱状、瀑布，可切换视图）。
- 不依赖脚本的图形：热力图（HTML 表格）、点图与时间线（SVG），生成网站时直接写入页面。

只做呈现：数值都来自运行结果，这里只换算成显示单位（例如比例 × 100 显示为百分比）。点的 ref 是结果中的
路径（如 results.nominal.SP500），关键发现引用同一路径时，「在图中定位」会高亮对应的点或单元格。
颜色只用 style.css 的 --c1…--c8 与发散色 --div-pos / --div-neg，按固定顺序使用。
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable

from .common import e
from .i18n import has_cjk, is_en

Html = str


def zh_mark(*texts: str) -> str:
    """英文页面上没有译文的中文：给 SVG 元素标 lang="zh-CN"（HTML 里由 te() 用 span 标注）。"""
    return ' lang="zh-CN"' if is_en() and any(has_cjk(t) for t in texts) else ""


# ---- 交互面板的数据格式 ---------------------------------------------------------

def axis(label: str, unit: str = "", digits: int = 1, **extra: Any) -> dict[str, Any]:
    """轴：label 与 unit 分开给，unit 为 "%" 时直接接在数值后。extra：log_toggle、log_default、zero、signed、type。"""
    return {"label": label, "unit": unit, "digits": digits, **extra}


def series(label: str, points: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """一条序列。extra：slot（固定的颜色序号，从 0 起，让颜色跟随主体而不是顺序）、dash。"""
    return {"label": label, "points": points, **extra}


def view(label: str, *items: dict[str, Any]) -> dict[str, Any]:
    return {"label": label, "series": list(items)}


def panel(kind: str, title: str, x: dict[str, Any], y: dict[str, Any], views: list[dict[str, Any]],
          **extra: Any) -> dict[str, Any] | None:
    """一个面板；没有任何数据点时返回 None（panels() 会去掉）。extra：wide、height、labels、horizontal、note、views_label。"""
    if not any(s["points"] for v in views for s in v["series"]):
        return None
    return {"type": kind, "title": title, "x": x, "y": y, "views": views, **extra}


def panels(*items: dict[str, Any] | None) -> dict[str, Any] | None:
    kept = [p for p in items if p]
    return {"kind": "panels", "panels": kept} if kept else None


def scaled(v: Any, factor: float = 100.0) -> float | None:
    """比例换算成显示单位；缺失保持缺失（不补零）。"""
    return None if v is None else round(float(v) * factor, 4)


# ---- 热力图（HTML 表格） -----------------------------------------------------------

def _shade(value: float, top: float, diverging: bool) -> str:
    """单元格底色：量值越大越深（最多混入 75%），蓝为零以上、红为零以下；顺序色只用蓝。"""
    share = 0.0 if not top else min(1.0, abs(value) / top)
    tone = "var(--div-neg)" if diverging and value < 0 else "var(--div-pos)"
    return f"background:color-mix(in srgb,{tone} {round(share * 75)}%,var(--panel))"


def heatmap(rows: list[tuple[str, str]], cols: list[tuple[str, str]],
            cell: Callable[[str, str], tuple[float | None, str | None] | None], fmt: Callable[[float], str], *,
            diverging: bool = True, top: float | None = None, legend: str = "",
            link: Callable[[str, str], str | None] | None = None, row_head: str = "") -> Html:
    """rows / cols：[(键, 显示名)]；cell(行键, 列键) 返回 (值, ref) 或 None。缺失显示为「—」，不着色。"""
    values = {}
    for r, _ in rows:
        for c, _ in cols:
            got = cell(r, c)
            if got and got[0] is not None:
                values[(r, c)] = got
    if top is None:
        top = max((abs(v) for v, _ in values.values()), default=0.0)
    head = f"<th>{e(row_head)}</th>" + "".join(f"<th>{e(label)}</th>" for _, label in cols)
    body = []
    for r, rlabel in rows:
        tds = []
        for c, clabel in cols:
            if (r, c) not in values:
                tds.append('<td class="cell empty">—</td>')
                continue
            v, ref = values[(r, c)]
            text = e(fmt(v))
            href = link(r, c) if link else None
            inner = f'<a href="{e(href)}">{text}</a>' if href else text
            ref_attr = f' data-ref="{e(ref)}"' if ref else ""
            tds.append(f'<td class="cell" style="{_shade(v, top, diverging)}" title="{e(rlabel)} · {e(clabel)}: {text}"'
                       f'{ref_attr}>{inner}</td>')
        body.append(f"<tr><th>{e(rlabel)}</th>{''.join(tds)}</tr>")
    key = (f'<p class="heatmap-legend{"" if diverging else " seq"}"><span>{e(fmt(-top) if diverging else fmt(0))}</span>'
           f'<i></i><span>{e(fmt(top))}</span>{" · " + e(legend) if legend else ""}</p>')
    return (key + f'<div class="scroll"><table class="heatmap"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


# ---- SVG 坐标轴刻度 -----------------------------------------------------------------

def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start, end = math.floor(lo / step) * step, math.ceil(hi / step) * step  # 刻度覆盖全部数据
    return [round(start + i * step, 10) for i in range(round((end - start) / step) + 1)]


# ---- 点图（SVG） --------------------------------------------------------------------

def dotplot(rows: list[tuple[str, dict[str, float | None], str]], metrics: list[tuple[str, str, int]],
            fmt: Callable[[float], str], *, title: str, note: str = "") -> Html:
    """每行一个主体，同一横轴上并排几个指标的点（按 metrics 的固定颜色序号）。

    rows：[(显示名, {指标键: 值}, 附注)]；metrics：[(键, 显示名, 颜色序号)]。缺失的点不画。
    """
    values = [v for _, vals, _ in rows for v in vals.values() if v is not None]
    if not values:
        return ""
    ticks = nice_ticks(min(0.0, min(values)), max(0.0, max(values)))
    lo, hi = ticks[0], ticks[-1]
    left, right, top, row_h = 190, 700, 34, 24
    x = lambda v: left + (v - lo) / (hi - lo) * (right - left)  # noqa: E731
    height = top + row_h * len(rows) + 22
    out = []
    for t in ticks:
        out.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{height - 20}"/>'
                   f'<text class="axis" x="{x(t):.1f}" y="{height - 6}" text-anchor="middle">{e(fmt(t))}</text>')
    lx = left
    for _, label, slot in metrics:
        out.append(f'<circle cx="{lx + 5}" cy="12" r="5" style="fill:var(--c{slot + 1})"/>'
                   f'<text class="axis" x="{lx + 14}" y="16">{e(label)}</text>')
        lx += 24 + sum(12 if has_cjk(ch) else 7 for ch in label)
    for i, (label, vals, sub) in enumerate(rows):
        cy = top + row_h * i + row_h / 2
        out.append(f'<text x="0" y="{cy + 4:.1f}"{zh_mark(label)}>{e(label)}{(" · " + e(sub)) if sub else ""}</text>')
        for key, mlabel, slot in metrics:
            v = vals.get(key)
            if v is None:
                continue
            out.append(f'<circle cx="{x(v):.1f}" cy="{cy:.1f}" r="5" style="fill:var(--c{slot + 1});stroke:var(--panel);'
                       f'stroke-width:1.5"><title>{e(label)} · {e(mlabel)}: {e(fmt(v))}</title></circle>')
    svg = (f'<svg class="dotplot" viewBox="0 0 {right + 10} {height}" role="img" aria-label="{e(title)}">'
           f'<title>{e(title)}</title>{"".join(out)}</svg>')
    return (f'<figure class="chart-card"><h4>{e(title)}</h4>{svg}'
            + (f'<p class="chart-note">{e(note)}</p>' if note else "") + "</figure>")


# ---- 时间线（SVG） ------------------------------------------------------------------

def _year(value: Any) -> float | None:
    s = str(value or "")
    if len(s) >= 4 and s[:4].isdigit():
        year = int(s[:4])
        month = int(s[5:7]) if len(s) >= 7 and s[5:7].isdigit() else 1
        return year + (month - 1) / 12
    return None


def timeline(items: Iterable[tuple[str, Any, Any, str | None]], *, title: str, note: str = "") -> Html:
    """每行一个研究：从起始日期到数据截止日期的横条。items：[(名称, 起, 止, 链接)]；日期取年月。"""
    rows = [(name, _year(a), _year(b), href) for name, a, b, href in items]
    rows = [(n, a, b, h) for n, a, b, h in rows if a is not None and b is not None and b >= a]
    if not rows:
        return ""
    rows.sort(key=lambda r: (r[1], r[0]))
    ticks = nice_ticks(min(r[1] for r in rows), max(r[2] for r in rows), 6)
    lo, hi = ticks[0], ticks[-1]
    left, right, top, row_h = 280, 800, 8, 20
    x = lambda v: left + (v - lo) / (hi - lo) * (right - left)  # noqa: E731
    height = top + row_h * len(rows) + 22
    out = [f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top}" y2="{height - 20}"/>'
           f'<text class="axis" x="{x(t):.1f}" y="{height - 6}" text-anchor="middle">{int(t)}</text>' for t in ticks]
    for i, (name, a, b, href) in enumerate(rows):
        y = top + row_h * i
        label = name if len(name) <= 30 else name[:29] + "…"
        span = f"{int(a)}–{int(b)}" if int(a) != int(b) else str(int(a))
        end = x(a) + max(6.0, x(b) - x(a))  # 一两年的研究也画成可见的短条，并在条后标出年份
        bar = (f'<text x="0" y="{y + 14}">{e(label)}</text>'
               f'<rect x="{x(a):.1f}" y="{y + 5}" width="{end - x(a):.1f}" height="10" rx="3">'
               f'<title>{e(name)}: {span}</title></rect>'
               f'<text class="axis" x="{end + 4:.1f}" y="{y + 14}">{span}</text>')  # 右侧留有空白放年份
        out.append(f'<g{zh_mark(name)}>' + (f'<a href="{e(href)}">{bar}</a>' if href else bar) + '</g>')
    svg = (f'<svg class="timeline" viewBox="0 0 {right + 70} {height}" role="img" aria-label="{e(title)}">'
           f'<title>{e(title)}</title>{"".join(out)}</svg>')
    return (f'<figure class="chart-card"><h4>{e(title)}</h4><div class="scroll">{svg}</div>'
            + (f'<p class="chart-note">{e(note)}</p>' if note else "") + "</figure>")
