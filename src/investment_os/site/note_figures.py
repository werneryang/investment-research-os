"""研究报告（notes）的图块：从公开走查记录取数，画成不依赖脚本的 SVG，插入报告页面。

报告正文是从 company-dossiers 复制的原文，导入后不改动；图块写在本仓库
`config/note_figures/<报告 id>.yaml`，按报告的二级标题定位插入。规则见 docs/note-figures.md。

- 数字只有一份：图里的每个数值都是记录字段的引用（`R:quarter_inputs.FY27Q3.revenue`），不接受手填数字。
  记录必须在 methodology/records/ 下，且报告正文已经链接到它。
- 每张图：结论式标题、口径副标题、图、数据表（可展开）、出处行（自动列出用到的字段）。
- 颜色只用 style.css 的 --c1…--c8 固定顺序；展望值用浅色虚线框，不画成实心。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .common import e

SCHEMA = "note-figures.v1"
SPEC_DIR = "config/note_figures"
RECORD_DIR = "methodology/records/"
PUBLIC_REPO = "https://github.com/werneryang/investment-research-os"
TYPES = {"kpi", "bar", "line", "hbar", "group"}
EVIDENCE = {"fact": "事实", "calc": "计算", "infer": "推断", "fwd": "展望"}
# 报告正文里的证据标签，渲染时换成带颜色的标签
BODY_TAGS = {"【事实】": "fact", "【计算】": "calc", "【推断】": "infer", "【展望】": "fwd"}
REF = re.compile(r"(?P<rec>[A-Z]):(?P<path>[A-Za-z0-9_.{}\[\]-]+)\Z")
TEMPLATE = re.compile(r"\{(?P<rec>[A-Z]):(?P<path>[A-Za-z0-9_.\[\]-]+)(?:\*(?P<factor>[0-9.]+))?(?::(?P<fmt>[^}]+))?\}")


class FigureError(ValueError):
    pass


# ---- 读取与取数 ------------------------------------------------------------------

def spec_path(root: Path, note_id: str) -> Path:
    return Path(root) / SPEC_DIR / f"{note_id}.yaml"


def load_spec(root: Path, note: dict) -> dict | None:
    """读取并完整解析一份报告的图块；没有图块文件时返回 None。任何引用不成立都报错，不静默跳过。"""
    from ..notes import boundary_issues  # 同一道公开边界检查

    path = spec_path(root, note["id"])
    if not path.exists():
        return None
    if path.is_symlink():
        raise FigureError(f"{path.name}: 图块文件不能是符号链接")
    text = path.read_text(encoding="utf-8")
    # 引文长度检查针对复制来的正文（YAML 的引号字符串会被误算成引文）；其余边界检查照常
    issues = [i.code for i in boundary_issues(text) if i.code != "long_quote_review"]
    if issues:
        raise FigureError(f"{path.name}: 未通过公开边界检查 {issues}")
    spec = yaml.safe_load(text)
    if not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA or spec.get("note") != note["id"]:
        raise FigureError(f"{path.name}: schema_version 或 note 不符")
    records = {}
    for key, rel in (spec.get("records") or {}).items():
        rel = str(rel)
        full = (Path(root) / rel)
        if not (re.fullmatch(r"[A-Z]", str(key)) and rel.startswith(RECORD_DIR) and rel.endswith(".yaml")
                and ".." not in rel and full.is_file() and not full.is_symlink()):
            raise FigureError(f"{path.name}: 记录 {key} 必须是 {RECORD_DIR} 下的 yaml 文件")
        if rel not in note["body"]:
            raise FigureError(f"{path.name}: 报告正文没有链接记录 {rel}")
        records[key] = {"path": rel, "data": yaml.safe_load(full.read_text(encoding="utf-8"))}
    if not records:
        raise FigureError(f"{path.name}: 没有声明 records")
    ctx = Ctx(records)
    figures = []
    for fig in spec.get("figures") or []:
        if not isinstance(fig, dict) or fig.get("type") not in TYPES or not fig.get("section"):
            raise FigureError(f"{path.name}: 图块缺少 type/section")
        if fig.get("position", "start") not in ("start", "end"):
            raise FigureError(f"{path.name}: position 只能是 start 或 end")
        try:
            figures.append({"section": fig["section"], "position": fig.get("position", "start"),
                            "html": render(fig, ctx)})
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise FigureError(f"{path.name} · {fig.get('id', fig['type'])}: {exc}") from None
    return {"figures": figures}


class Ctx:
    """取数上下文：记下每张图用到的字段，用于出处行。"""

    def __init__(self, records: dict):
        self.records = records
        self.used: list[tuple[str, str]] = []

    def get(self, ref: str, x: str | None = None) -> float:
        m = REF.match(str(ref))
        if not m:
            raise ValueError(f"引用格式应为 R:path：{ref!r}")
        rec, path = m["rec"], m["path"]
        if "{x}" in path:
            if x is None:
                raise ValueError(f"{ref} 含 {{x}} 但没有 x")
            path = path.replace("{x}", x)
        if rec not in self.records:
            raise ValueError(f"未声明的记录 {rec}")
        value: Any = self.records[rec]["data"]
        for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
            value = value[int(part[1:-1])] if part.startswith("[") else value[part]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{rec}:{path} 不是数值")
        self.used.append((rec, m["path"]))
        return float(value)

    def num(self, spec: Any, x: str | None = None) -> float:
        """数值只能来自记录：字符串引用，或 {ref, scale}，或 {sum: [...], scale}。"""
        if isinstance(spec, str):
            return self.get(spec, x)
        if isinstance(spec, dict):
            scale = float(spec.get("scale", 1))
            if "sum" in spec:
                return sum(self.num(s, x) for s in spec["sum"]) * scale
            return self.get(spec["ref"], x) * scale
        raise ValueError(f"数值必须引用记录字段，不接受手填：{spec!r}")

    def text(self, template: str) -> str:
        """文字里的 {R:path*0.001:.1f}：按格式代入记录数值。"""
        def sub(m: re.Match) -> str:
            v = self.get(f"{m['rec']}:{m['path']}") * float(m["factor"] or 1)
            return format(v, m["fmt"] or "g")
        return TEMPLATE.sub(sub, template or "")

    def take_used(self) -> list[tuple[str, str]]:
        used, self.used = list(dict.fromkeys(self.used)), []
        return used


# ---- 插入报告 ------------------------------------------------------------------

def evidence_tags(html_text: str) -> str:
    for raw, cls in BODY_TAGS.items():
        html_text = html_text.replace(raw, f'<span class="ev ev-{cls}">{EVIDENCE[cls]}</span>')
    return html_text


def render_body(md, body: str, spec: dict | None) -> str:
    """按二级标题把图块插到节首（标题之后）或节末（下一个二级标题之前）。每个图块的节都必须存在。"""
    tokens = md.parse(body)
    heads = [i for i, t in enumerate(tokens) if t.type == "heading_open" and t.tag == "h2"]
    figures = (spec or {}).get("figures", [])
    inserts: dict[int, list[str]] = {}
    for fig in figures:
        hit = [i for i in heads if tokens[i + 1].content.strip().startswith(fig["section"])]
        if len(hit) != 1:
            raise FigureError(f"图块的节「{fig['section']}」在报告中匹配到 {len(hit)} 处，应恰好 1 处")
        i = hit[0]
        if fig["position"] == "start":
            at = i + 3  # heading_open, inline, heading_close
        else:
            later = [h for h in heads if h > i]
            at = later[0] if later else len(tokens)
        inserts.setdefault(at, []).append(fig["html"])
    out, last = [], 0
    for at in sorted(inserts):
        out.append(md.renderer.render(tokens[last:at], md.options, {}))
        out.extend(inserts[at])
        last = at
    out.append(md.renderer.render(tokens[last:], md.options, {}))
    return evidence_tags("".join(out))


# ---- 图 --------------------------------------------------------------------------

def fmt(v: float, digits: int = 1, unit: str = "") -> str:
    return f"{v:,.{digits}f}{unit if unit == '%' else ''}"


def tag(evidence: str | None) -> str:
    if not evidence:
        return ""
    if evidence not in EVIDENCE:
        raise ValueError(f"evidence 只能是 {sorted(EVIDENCE)}")
    return f' <span class="ev ev-{evidence}">{EVIDENCE[evidence]}</span>'


def render(fig: dict, ctx: Ctx) -> str:
    kind = fig["type"]
    if kind == "kpi":
        return kpi(fig, ctx)
    if kind == "group":
        parts, tables = [], []
        for p in fig["panels"]:
            svg, table = PLOTS[p["type"]](p, ctx)
            parts.append(f'<div class="nf-panel"><p class="nf-mini">{e(p.get("title", ""))}{tag(p.get("evidence"))}</p>'
                         f'{legend(p)}{svg}</div>')
            tables.append(table)
        return frame(fig, ctx, f'<div class="nf-multi">{"".join(parts)}</div>', "".join(tables))
    svg, table = PLOTS[kind](fig, ctx)
    return frame(fig, ctx, legend(fig) + f'<div class="nf-plot">{svg}</div>', table)


def frame(fig: dict, ctx: Ctx, body: str, table: str) -> str:
    title, sub = ctx.text(fig["title"]), ctx.text(fig.get("subtitle", ""))
    note_text = ctx.text(fig["note"]) if fig.get("note") else ""
    used = ctx.take_used()
    by_rec: dict[str, list[str]] = {}
    for rec, path in used:
        by_rec.setdefault(rec, []).append(path)
    src = " · ".join(f'{rec} <a href="{e(PUBLIC_REPO + "/blob/main/" + ctx.records[rec]["path"])}">{e(Path(ctx.records[rec]["path"]).name)}</a>'
                     for rec in by_rec)
    fields = "".join(f'<p class="nf-fields">{rec} 字段：' + "、".join(f"<code>{e(p)}</code>" for p in paths) + "</p>"
                     for rec, paths in by_rec.items())
    lead = f'{e(fig["source"])} · ' if fig.get("source") else ""
    note = f'<p class="nf-note">{e(note_text)}</p>' if note_text else ""
    return (f'<figure class="nf" id="fig-{e(fig.get("id", ""))}" aria-label="{e(fig["title"])}">'
            f'<p class="nf-title">{e(title)}{tag(fig.get("evidence"))}</p>'
            f'<p class="nf-sub">{e(sub)}</p>{body}{note}'
            f'<details class="nf-data"><summary>数据表与字段</summary>{table}{fields}</details>'
            f'<p class="nf-src">出处：{lead}{src}</p></figure>')


def legend(fig: dict) -> str:
    items = fig.get("legend")
    if items is None:
        series = fig.get("series") or []
        items = [{"label": s["label"], "slot": i + 1, "mark": "line"} for i, s in enumerate(series)] if len(series) > 1 else []
        if fig["type"] == "bar" and fig.get("guide"):
            items = [{"label": fig.get("bar_label", "已报告"), "slot": 1}, {"label": "指引（展望）", "mark": "hatch"}]
    if not items:
        return ""
    out = []
    for it in items:
        mark = it.get("mark", "box")
        cls = {"line": "nf-k-line", "hatch": "nf-k-hatch", "box": "nf-k-box", "prior": "nf-k-prior"}[mark]
        out.append(f'<span><i class="{cls} nf-s{it.get("slot", 1)}"></i>{e(it["label"])}</span>')
    return f'<p class="nf-legend">{"".join(out)}</p>'


def kpi(fig: dict, ctx: Ctx) -> str:
    tiles, rows = [], []
    for it in fig["items"]:
        v = ctx.num(it["value"])
        shown = fmt(v, it.get("digits", 1), it.get("unit", ""))
        unit = "" if it.get("unit") == "%" else it.get("unit", "")
        note = ctx.text(it.get("note", ""))
        tiles.append(f'<div class="nf-kpi"><div class="nf-k">{e(it["label"])}{tag(it.get("evidence"))}</div>'
                     f'<div class="nf-v">{e(shown)}</div><div class="nf-n">{e(" · ".join(x for x in (unit, note) if x))}</div></div>')
        rows.append((it["label"], shown + (f" {unit}" if unit else "")))
    used = ctx.take_used()
    src = " · ".join(sorted({f'{r} <a href="{e(PUBLIC_REPO + "/blob/main/" + ctx.records[r]["path"])}">{e(Path(ctx.records[r]["path"]).name)}</a>' for r, _ in used}))
    fields = "、".join(f"<code>{e(p)}</code>" for _, p in used)
    return (f'<div class="nf-kpis" id="fig-{e(fig.get("id", ""))}">{"".join(tiles)}</div>'
            f'<p class="nf-src">数字出处：{src}：{fields}</p>')


def table_html(head: list[str], rows: list[list[str]]) -> str:
    return ('<table><tr>' + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows) + "</table>")


def nice_scale(v: float) -> tuple[float, float]:
    """零起点坐标：取 1/2/2.5/5×10^k 的刻度步长，3–5 个刻度，返回 (上限, 步长)。"""
    import math
    if v <= 0:
        return 1.0, 0.25
    for k in range(math.floor(math.log10(v)) - 2, math.floor(math.log10(v)) + 2):
        for m in (1, 2, 2.5, 5):
            step = m * 10 ** k
            n = math.ceil(v / step - 1e-9)
            if 3 <= n <= 5:
                return n * step, step
    return v, v / 4


def nice_max(v: float) -> float:
    return nice_scale(v)[0]


def ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    return [lo + (hi - lo) * i / n for i in range(n + 1)]


def zero_ticks(top: float) -> list[float]:
    t, step = nice_scale(top)
    return [step * i for i in range(round(t / step) + 1)]


def tick_text(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 10 or v == int(v) else f"{v:g}"


def bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    r = max(0.0, min(r, w / 2, h))
    return f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z"


def svg_open(w: int, h: int, title: str) -> str:
    wide = " nf-wide" if w > 400 else ""  # 宽图在手机上保持可读字号，在图内横向滚动
    return f'<svg class="nf-svg{wide}" viewBox="0 0 {w} {h}" role="img" aria-label="{e(title)}">'


def bar(fig: dict, ctx: Ctx) -> tuple[str, str]:
    xs = [str(x) for x in fig["x"]]
    vals = [ctx.num(fig["value"], x) for x in xs]
    d, unit = fig.get("digits", 1), fig.get("unit", "")
    guide = fig.get("guide")
    g = None
    if guide:
        g = {k: ctx.num(guide[k]) for k in ("mid", "low", "high")}
    wide = fig.get("width", 640)
    W, H, L, R, T, B = wide, fig.get("height", 240), 44, 12, 18, 28
    top = nice_max(max(vals + ([g["high"]] if g else []) + ([fig["ref_line"]] if fig.get("ref_line") else [])))
    y = lambda v: T + (H - T - B) * (1 - v / top)
    n = len(xs) + (1 if g else 0)
    band = (W - L - R) / n
    bw = band * 0.56
    hl = set(str(h) for h in fig.get("highlight", []))
    label = set(str(h) for h in fig.get("label", [xs[-1]]))
    out = [svg_open(W, H, fig["title"] if "title" in fig else "")]
    for t in zero_ticks(top):
        out.append(f'<line class="nf-grid" x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="nf-axis" x="{L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{tick_text(t)}</text>')
    if fig.get("ref_line") is not None:
        rl = float(fig["ref_line"])
        out.append(f'<line class="nf-ref" x1="{L}" x2="{W - R}" y1="{y(rl):.1f}" y2="{y(rl):.1f}"/>')
    for i, (x, v) in enumerate(zip(xs, vals)):
        bx = L + band * i + (band - bw) / 2
        slot = 2 if x in hl else 1
        tip = f"{x}：{fmt(v, d, unit)}" + (f"（环比 {(v / vals[i - 1] - 1) * 100:+.1f}%）" if i and fig.get("tip_change") else "")
        out.append(f'<g><title>{e(tip)}</title><path class="nf-s{slot}" d="{bar_path(bx, y(v), bw, y(0) - y(v))}"/>'
                   f'<rect class="nf-hit" x="{L + band * i:.1f}" y="{T}" width="{band:.1f}" height="{H - T - B}"/></g>')
        if x in label or x in hl:
            out.append(f'<text class="nf-lbl" x="{bx + bw / 2:.1f}" y="{y(v) - 6:.1f}" text-anchor="middle">{fmt(v, d, unit)}</text>')
        out.append(f'<text class="nf-axis" x="{bx + bw / 2:.1f}" y="{H - 9}" text-anchor="middle">{e(fig.get("x_short", {}).get(x, x))}</text>')
    rows = [[x, fmt(v, d, unit)] for x, v in zip(xs, vals)]
    if g:
        bx = L + band * len(xs) + (band - bw) / 2
        cx = bx + bw / 2
        out.append(f'<g><title>{e(guide["label"])} 指引：中点 {fmt(g["mid"], d)}，区间 {fmt(g["low"], d)}–{fmt(g["high"], d)}</title>'
                   f'<path class="nf-guide" d="{bar_path(bx, y(g["mid"]), bw, y(0) - y(g["mid"]))}"/>'
                   f'<line class="nf-whisker" x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(g["high"]):.1f}" y2="{y(g["low"]):.1f}"/>'
                   + "".join(f'<line class="nf-whisker" x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>' for v in (g["high"], g["low"]))
                   + f'<rect class="nf-hit" x="{L + band * len(xs):.1f}" y="{T}" width="{band:.1f}" height="{H - T - B}"/></g>'
                   f'<text class="nf-lbl" x="{cx:.1f}" y="{y(g["high"]) - 6:.1f}" text-anchor="middle">{fmt(g["mid"], d)}</text>'
                   f'<text class="nf-axis" x="{cx:.1f}" y="{H - 9}" text-anchor="middle">{e(guide["label"])}</text>')
        rows.append([guide["label"] + "（指引）", f'{fmt(g["mid"], d)}（{fmt(g["low"], d)}–{fmt(g["high"], d)}）'])
    out.append(f'<line class="nf-axisline" x1="{L}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/></svg>')
    return "".join(out), table_html([fig.get("x_name", "期间"), fig.get("value_name", unit or "数值")], rows)


def line(fig: dict, ctx: Ctx) -> tuple[str, str]:
    xs = [str(x) for x in fig["x"]]
    series = [(s["label"], [ctx.num(s["value"], x) for x in xs]) for s in fig["series"]]
    d, unit = fig.get("digits", 1), fig.get("unit", "")
    lo, hi = float(fig["y_min"]), float(fig["y_max"])  # 坐标范围是版式，不是数据
    allv = [v for _, vs in series for v in vs]
    if min(allv) < lo or max(allv) > hi:
        raise ValueError("数据超出 y_min/y_max")
    W, H, L, R, T, B = fig.get("width", 320), fig.get("height", 200), 38, 44, 12, 26
    y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))
    x = lambda i: L + 8 + (W - L - R - 16) * i / max(1, len(xs) - 1)
    out = [svg_open(W, H, fig.get("title", ""))]
    for t in ticks(lo, hi, int(fig.get("ticks", 2))):
        out.append(f'<line class="nf-grid" x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="nf-axis" x="{L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{tick_text(t)}{"%" if unit == "%" else ""}</text>')
    for k, (name, vs) in enumerate(series, 1):
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vs))
        out.append(f'<polyline class="nf-line nf-s{k}" points="{pts}"/>'
                   f'<circle class="nf-dot nf-s{k}" cx="{x(len(vs) - 1):.1f}" cy="{y(vs[-1]):.1f}" r="4"/>'
                   f'<text class="nf-lbl" x="{x(len(vs) - 1) + 8:.1f}" y="{y(vs[-1]) + 4:.1f}">{fmt(vs[-1], d)}</text>')
    step = (W - L - R - 16) / max(1, len(xs) - 1)
    for i, lab in enumerate(xs):
        tip = f"{lab}：" + "；".join(f"{n} {fmt(vs[i], d, unit)}" for n, vs in series)
        out.append(f'<g><title>{e(tip)}</title><rect class="nf-hit" x="{x(i) - step / 2:.1f}" y="{T}" width="{step:.1f}" height="{H - T - B}"/></g>'
                   f'<text class="nf-axis" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{e(fig.get("x_short", {}).get(lab, lab))}</text>')
    out.append("</svg>")
    rows = [[lab] + [fmt(vs[i], d, unit) for _, vs in series] for i, lab in enumerate(xs)]
    return "".join(out), table_html([fig.get("x_name", "期间")] + [n for n, _ in series], rows)


def hbar(fig: dict, ctx: Ctx) -> tuple[str, str]:
    rows = []
    for r in fig["rows"]:
        rows.append({"label": r["label"], "kind": r.get("kind", ""), "contingent": bool(r.get("contingent")),
                     "v": ctx.num(r["value"]), "prior": ctx.num(r["prior"]) if r.get("prior") else None,
                     "note": ctx.text(r.get("note", ""))})
    d = fig.get("digits", 0)
    W, rh, T, L, R = 640, 48, 4, 200, 56
    H = T + len(rows) * rh + 4
    top = nice_max(max(max(r["v"], r["prior"] or 0) for r in rows))
    x = lambda v: L + (W - L - R) * v / top
    out = [svg_open(W, H, fig["title"])]
    for i, r in enumerate(rows):
        yb = T + i * rh + 8
        tip = f'{r["label"]}：{fmt(r["v"], d)}' + (f'（上期 {fmt(r["prior"], d)}）' if r["prior"] is not None else "") + (f'；{r["note"]}' if r["note"] else "")
        out.append(f'<g><title>{e(tip)}</title>'
                   f'<text class="nf-lbl" x="0" y="{yb + 12}">{e(r["label"])}</text>'
                   f'<text class="nf-axis" x="0" y="{yb + 28}">{e(r["kind"])}</text>'
                   f'<rect class="{"nf-s4" if r["contingent"] else "nf-s1"}" x="{L}" y="{yb}" width="{x(r["v"]) - L:.1f}" height="16" rx="3"/>'
                   + (f'<line class="nf-prior" x1="{x(r["prior"]):.1f}" x2="{x(r["prior"]):.1f}" y1="{yb - 3}" y2="{yb + 19}"/>' if r["prior"] is not None else "")
                   + f'<text class="nf-lbl" x="{x(r["v"]) + 6:.1f}" y="{yb + 12}">{fmt(r["v"], d)}</text>'
                   f'<rect class="nf-hit" x="0" y="{yb - 8}" width="{W}" height="{rh}"/></g>')
    out.append("</svg>")
    table = table_html(["项目", "性质", "本期", "上期", "说明"],
                       [[r["label"], r["kind"], fmt(r["v"], d), "" if r["prior"] is None else fmt(r["prior"], d), r["note"]] for r in rows])
    return "".join(out), table


PLOTS = {"bar": bar, "line": line, "hbar": hbar}
