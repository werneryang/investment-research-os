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
TYPES = {"kpi", "bar", "line", "hbar", "group", "stack", "slope", "matrix", "range",
         "waterfall", "funnel", "tree", "timeline", "scenario"}
EVIDENCE = {"fact": "事实", "calc": "计算", "infer": "推断", "fwd": "展望"}
# 报告正文里的证据标签，渲染时换成带颜色的标签
BODY_TAGS = {"【事实】": "fact", "【计算】": "calc", "【推断】": "infer", "【展望】": "fwd"}
REF = re.compile(r"(?P<rec>[A-Z]):(?P<path>[A-Za-z0-9_.{}\[\]-]+)\Z")
VAR = re.compile(r"\{#(?P<name>[a-z_]+)\}")
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
        data = yaml.safe_load(full.read_text(encoding="utf-8"))
        if rel not in note["body"] and not supplements_linked_record(root, data, note["body"]):
            raise FigureError(f"{path.name}: 报告正文没有链接记录 {rel}")
        records[key] = {"path": rel, "data": data}
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


def supplements_linked_record(root: Path, data: Any, body: str) -> bool:
    """补充记录（supplemental-*）可以不在正文里直接链接，条件是：它声明补充的记录已被正文链接，
    且那份记录的哈希与声明一致（原记录没有被改过）。"""
    import hashlib

    if not isinstance(data, dict) or not str(data.get("record_type", "")).startswith("supplemental"):
        return False
    sup = data.get("supplements") or {}
    rel = str(sup.get("path", ""))
    full = Path(root) / rel
    if not (rel.startswith(RECORD_DIR) and rel in body and full.is_file() and not full.is_symlink()):
        return False
    return hashlib.sha256(full.read_bytes()).hexdigest() == sup.get("sha256")


class Ctx:
    """取数上下文：记下每张图用到的字段，用于出处行。"""

    def __init__(self, records: dict):
        self.records = records
        self.used: list[tuple[str, str]] = []
        self.vars: dict[str, int] = {}  # 图自己数出来的条数，只供标题代入（{#n_total}）

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

    def raw(self, ref: str) -> Any:
        """取记录里的列表或文字（图里的名称、分类、期间标签），同样记入出处行。"""
        m = REF.match(str(ref))
        if not m or m["rec"] not in self.records:
            raise ValueError(f"引用格式或记录不成立：{ref!r}")
        value: Any = self.records[m["rec"]]["data"]
        for part in re.findall(r"[^.\[\]]+|\[\d+\]", m["path"]):
            value = value[int(part[1:-1])] if part.startswith("[") else value[part]
        self.used.append((m["rec"], m["path"]))
        return value

    def num(self, spec: Any, x: str | None = None) -> float:
        """数值只能来自记录：字符串引用，或 {ref, scale}，或 {sum: [...], scale}，
        或 {by_x: {期间: 引用}}（个别期间的字段位置不同，例如由累计数推得的季度）。"""
        if isinstance(spec, str):
            return self.get(spec, x)
        if isinstance(spec, dict):
            scale = float(spec.get("scale", 1))
            if "by_x" in spec:
                return self.num(spec["by_x"][x], x) * scale
            if "sum" in spec:
                return sum(self.num(s, x) for s in spec["sum"]) * scale
            return self.get(spec["ref"], x) * scale
        raise ValueError(f"数值必须引用记录字段，不接受手填：{spec!r}")

    def text(self, template: str) -> str:
        """文字里的 {R:path*0.001:.1f}：按格式代入记录数值。"""
        def sub(m: re.Match) -> str:
            v = self.get(f"{m['rec']}:{m['path']}") * float(m["factor"] or 1)
            return format(v, m["fmt"] or "g")
        return VAR.sub(lambda m: str(self.vars[m["name"]]), TEMPLATE.sub(sub, template or ""))

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
    heads = [i for i, t in enumerate(tokens) if t.type == "heading_open" and t.tag in ("h2", "h3")]
    figures = (spec or {}).get("figures", [])
    inserts: dict[int, list[str]] = {}
    for fig in figures:
        hit = [i for i in heads if tokens[i + 1].content.strip().startswith(fig["section"])]
        if len(hit) != 1:
            raise FigureError(f"图块的节「{fig['section']}」在报告中匹配到 {len(hit)} 处，应恰好 1 处")
        i = hit[0]
        if fig["position"] == "start":
            at = i + 3  # heading_open, inline, heading_close
        else:  # 节末 = 下一个同级或更高级标题之前（三级标题只到下一个二、三级标题）
            later = [h for h in heads if h > i and (tokens[i].tag == "h3" or tokens[h].tag == "h2")]
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
    return (f'<figure class="nf" id="fig-{e(fig.get("id", ""))}" aria-label="{e(title)}">'
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


def stack(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """收入结构条：一根 100% 横条，各类相加必须等于总额，占比必须等于各类 ÷ 总额。"""
    d, unit = fig.get("digits", 1), fig.get("unit", "")
    total = ctx.num(fig["total"])
    parts = [{"label": p["label"], "v": ctx.num(p["value"]), "share": ctx.num(p["share"]), "note": ctx.text(p.get("note", ""))}
             for p in fig["parts"]]
    if abs(sum(p["v"] for p in parts) - total) > 1e-6:
        raise ValueError("各类合计与总额不符")
    for p in parts:
        if abs(p["share"] - p["v"] / total * 100) > 0.01:
            raise ValueError(f"{p['label']} 的占比与 数值÷总额 不符")
    W, H, gap = 400, 32, 2  # 单根横条按手机宽度画，不触发图内横向滚动
    x0, out = 0.0, [svg_open(W, H, fig["title"])]
    for k, p in enumerate(parts, 1):
        w = W * p["v"] / total
        tip = f'{p["label"]}：{p["v"]:,.0f}，占 {p["share"]:.{d}f}%'
        out.append(f'<g><title>{e(tip)}</title><rect class="nf-s{k}" x="{x0:.1f}" y="4" width="{max(w - gap, 1):.1f}" height="{H - 8}" rx="2"/></g>')
        x0 += w
    out.append("</svg>")
    rows = "".join(f'<li><i class="nf-sw nf-s{k}"></i><span class="nf-r-name">{e(p["label"])}</span>'
                   f'<b>{p["v"]:,.0f}</b><b>{p["share"]:.{d}f}%</b>'
                   + (f'<span class="nf-r-note">{e(p["note"])}</span>' if p["note"] else "") + "</li>"
                   for k, p in enumerate(parts, 1))
    table = table_html(["类别", f'数值（{unit}）' if unit else "数值", "占比"],
                       [[p["label"], f'{p["v"]:,.0f}', f'{p["share"]:.{d}f}%'] for p in parts]
                       + [["合计", f"{total:,.0f}", "100%"]])
    return "".join(out) + f'<ul class="nf-rows">{rows}</ul>', table


def slope(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """依赖斜率图：每家一条线；期间与数值按记录里的两张并列列表配对，不假设顺序。
    下限值（只披露「至少 x%」）画空心点，不画进折线。"""
    xs = [str(x) for x in fig["x"]]
    lo, hi = float(fig["y_min"]), float(fig["y_max"])
    unit = fig.get("unit", "%")
    series = []
    for k, s in enumerate(fig["series"], 1):
        periods, vals = ctx.raw(s["periods"]), ctx.raw(s["values"])
        if len(periods) != len(vals):
            raise ValueError(f"{s['label']}：期间与数值个数不同")
        by = {str(p): float(v) for p, v in zip(periods, vals)}
        if any(x not in by for x in xs):
            raise ValueError(f"{s['label']}：记录里没有期间 {xs}")
        series.append({"label": s["label"], "slot": s.get("slot", k), "vals": [by[x] for x in xs], "prefix": s.get("prefix", "")})
    bounds = []
    for b in fig.get("lower_bounds", []):
        period = str(ctx.raw(b["period"]))
        if period not in xs:
            raise ValueError(f"{b['label']}：下限的期间 {period} 不在 x 中")
        bounds.append({"label": b["label"], "v": ctx.num(b["value"]), "i": xs.index(period), "slot": b.get("slot", 4)})
    allv = [v for s in series for v in s["vals"]] + [b["v"] for b in bounds]
    if min(allv) < lo or max(allv) > hi:
        raise ValueError("数据超出 y_min/y_max")
    W, H, L, R, T, B = 640, fig.get("height", 270), 84, 190, 14, 28  # 左侧留出刻度与起点数值两列
    y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))
    x = lambda i: L + 10 + (W - L - R - 10) * i / max(1, len(xs) - 1)
    out = [svg_open(W, H, fig["title"])]
    for t in ticks(lo, hi, 4):
        out.append(f'<line class="nf-grid" x1="40" x2="{W - R + 6}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="nf-axis" x="34" y="{y(t) + 4:.1f}" text-anchor="end">{tick_text(t)}{unit}</text>')
    for i, lab in enumerate(xs):
        out.append(f'<text class="nf-axis" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{e(lab)}</text>')
    for s in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s["vals"]))
        tip = f'{s["label"]}：' + "；".join(f"{lab} {s['prefix']}{v:g}{unit}" for lab, v in zip(xs, s["vals"]))
        last = len(xs) - 1
        out.append(f'<g><title>{e(tip)}</title><polyline class="nf-line nf-s{s["slot"]}" points="{pts}"/>'
                   + "".join(f'<circle class="nf-dot nf-s{s["slot"]}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="{4 if i == last else 3}"/>'
                             for i, v in enumerate(s["vals"]))
                   + f'<text class="nf-lbl" x="{x(0) - 8:.1f}" y="{y(s["vals"][0]) + 4:.1f}" text-anchor="end">{s["prefix"]}{s["vals"][0]:g}</text>'
                   f'<text class="nf-lbl" x="{x(last) + 10:.1f}" y="{y(s["vals"][last]) + 4:.1f}">{e(s["label"])} {s["prefix"]}{s["vals"][last]:g}{unit}</text>'
                   f'<rect class="nf-hit" x="{L}" y="{y(max(s["vals"])) - 8:.1f}" width="{W - L - R:.1f}" height="{y(min(s["vals"])) - y(max(s["vals"])) + 16:.1f}"/></g>')
    for b in bounds:
        out.append(f'<g><title>{e(b["label"])}：至少 {b["v"]:g}{unit}（下限，非点值）</title>'
                   f'<circle class="nf-lb nf-s{b["slot"]}" cx="{x(b["i"]):.1f}" cy="{y(b["v"]):.1f}" r="5"/>'
                   f'<text class="nf-lbl" x="{x(b["i"]) + 10:.1f}" y="{y(b["v"]) + 4:.1f}">{e(b["label"])} ≥{b["v"]:g}{unit}</text></g>')
    out.append("</svg>")
    rows = [[s["label"]] + [f'{s["prefix"]}{v:g}{unit}' for v in s["vals"]] for s in series]
    rows += [[b["label"]] + ["" if i != b["i"] else f'≥{b["v"]:g}{unit}（下限）' for i in range(len(xs))] for b in bounds]
    return "".join(out), table_html(["供应商"] + xs, rows)


def matrix(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """层次 × 时态矩阵：归类来自记录里的结构化字段，图只负责排版。
    校验：每个关系恰好归一个格子，且与走查记录登记的关系完全一致。"""
    items, layers, tenses = ctx.raw(fig["items"]), ctx.raw(fig["layers"]), ctx.raw(fig["tenses"])
    ids = [i["id"] for i in items]
    universe = [r["id"] for r in ctx.raw(fig["universe"])]
    if len(set(ids)) != len(ids) or set(ids) != set(universe):
        raise ValueError(f"归类的关系 id 与走查记录不一致：缺 {sorted(set(universe) - set(ids))}，多 {sorted(set(ids) - set(universe))}")
    lay, ten = {x["id"]: x["label"] for x in layers}, {x["id"]: x["label"] for x in tenses}
    for i in items:
        if i["layer"] not in lay or i["tense"] not in ten:
            raise ValueError(f"{i['id']}：层次或时态不在登记的取值里")
    ctx.vars.update({"n_total": len(items), **{f"n_{t}": sum(i["tense"] == t for i in items) for t in ten}})
    head = "".join(f'<th scope="col" class="nf-t-{t}">{e(ten[t])}<span>{ctx.vars[f"n_{t}"]}</span></th>' for t in ten)
    body = []
    for lid in lay:
        cells = []
        for tid in ten:
            hit = [i for i in items if i["layer"] == lid and i["tense"] == tid]
            if not hit:
                cells.append('<td class="nf-mx-0">—</td>')
                continue
            names = "、".join(e(i["label"]) + ("*" if i.get("future_component") else "") for i in hit)
            cells.append(f'<td class="nf-mx-c nf-t-{tid}"><b>{len(hit)}</b><span>{names}</span></td>')
        body.append(f'<tr><th scope="row">{e(lay[lid])}</th>{"".join(cells)}</tr>')
    html_text = f'<table class="nf-mx"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    table = table_html(["关系 id", "名称", "层次", "时态", "另含未来条款"],
                       [[i["id"], i["label"], lay[i["layer"]], ten[i["tense"]], "是" if i.get("future_component") else ""] for i in items])
    return html_text, table


def range_plot(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """指引对比图：每个期间一个虚线框（管理层给的区间，横线为中点），有实际值的画实心点。
    实际值落在区间外用第 2 色，只表示「在区间外」，不称失败或达成。纵轴不从零开始，由 y_min/y_max 声明。"""
    d, unit = fig.get("digits", 1), fig.get("unit", "")
    lo, hi = float(fig["y_min"]), float(fig["y_max"])
    rows = []
    for r in fig["rows"]:
        row = {"label": r["label"], "low": ctx.num(r["low"]), "high": ctx.num(r["high"]),
               "mid": ctx.num(r["mid"]) if r.get("mid") is not None else None,
               "actual": ctx.num(r["actual"]) if r.get("actual") is not None else None}
        if row["low"] > row["high"]:
            raise ValueError(f"{r['label']}：区间下限大于上限")
        rows.append(row)
    allv = [v for r in rows for v in (r["low"], r["high"], r["mid"], r["actual"]) if v is not None]
    if min(allv) < lo or max(allv) > hi:
        raise ValueError("数据超出 y_min/y_max")
    W, H, L, R, T, B = fig.get("width", 320), fig.get("height", 220), 40, 12, 20, 28
    y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))
    band = (W - L - R) / len(rows)
    bw = band * 0.46
    out = [svg_open(W, H, fig.get("title", ""))]
    for t in ticks(lo, hi, int(fig.get("ticks", 4))):
        out.append(f'<line class="nf-grid" x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="nf-axis" x="{L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{tick_text(t)}</text>')
    table = []
    for i, r in enumerate(rows):
        cx = L + band * i + band / 2
        outside = r["actual"] is not None and not (r["low"] <= r["actual"] <= r["high"])
        tip = f'{r["label"]}：指引区间 {fmt(r["low"], d)}–{fmt(r["high"], d)}' + (f'，中点 {fmt(r["mid"], d)}' if r["mid"] is not None else "") \
            + (f'；实际 {fmt(r["actual"], d)}（{"在区间外" if outside else "在区间内"}）' if r["actual"] is not None else "")
        g = [f'<title>{e(tip)}</title>',
             f'<rect class="nf-guide" x="{cx - bw / 2:.1f}" y="{y(r["high"]):.1f}" width="{bw:.1f}" height="{y(r["low"]) - y(r["high"]):.1f}" rx="2"/>']
        if r["mid"] is not None:
            g.append(f'<line class="nf-whisker" x1="{cx - bw / 2:.1f}" x2="{cx + bw / 2:.1f}" y1="{y(r["mid"]):.1f}" y2="{y(r["mid"]):.1f}"/>')
        if r["actual"] is not None:
            g.append(f'<circle class="nf-dot nf-s{2 if outside else 1}" cx="{cx:.1f}" cy="{y(r["actual"]):.1f}" r="5"/>'
                     f'<text class="nf-lbl" x="{cx + 10:.1f}" y="{y(r["actual"]) + 4:.1f}">{fmt(r["actual"], d)}</text>')
        elif r["mid"] is not None:
            g.append(f'<text class="nf-lbl" x="{cx:.1f}" y="{y(r["high"]) - 6:.1f}" text-anchor="middle">{fmt(r["mid"], d)}</text>')
        else:  # 没有中点也没有实际值：直接标区间两端
            g.append(f'<text class="nf-lbl" x="{cx:.1f}" y="{y(r["high"]) - 6:.1f}" text-anchor="middle">{fmt(r["low"], d)}–{fmt(r["high"], d)}</text>')
        g.append(f'<rect class="nf-hit" x="{cx - band / 2:.1f}" y="{T}" width="{band:.1f}" height="{H - T - B}"/>')
        out.append("<g>" + "".join(g) + "</g>")
        out.append(f'<text class="nf-axis" x="{cx:.1f}" y="{H - 9}" text-anchor="middle">{e(fig.get("x_short", {}).get(r["label"], r["label"]))}</text>')
        table.append([r["label"], fmt(r["low"], d), fmt(r["high"], d), "" if r["mid"] is None else fmt(r["mid"], d),
                      "" if r["actual"] is None else fmt(r["actual"], d) + ("（区间外）" if outside else "（区间内）")])
    out.append("</svg>")
    return "".join(out), table_html(["期间", "区间下限", "区间上限", "中点", "实际"], table)


# ---- 第三批图型：瀑布、阶段条、层级树、时间线、情景区间 / 敏感性 ----------------------

def ev_word(evidence: str | None) -> str:
    """SVG 里不能放 HTML 标签，证据级别写成文字；同样只接受四种取值。"""
    tag(evidence)
    return EVIDENCE[evidence] if evidence else ""


def check_axis(values: list[float], lo: float, hi: float) -> None:
    if lo >= hi:
        raise ValueError("坐标范围下限必须小于上限")
    if min(values) < lo or max(values) > hi:
        raise ValueError("数据超出坐标范围")


def waterfall(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """增长归因瀑布：起点 → 若干增减项 → 终点。起点加各项必须等于终点（可声明 tolerance，
    用于记录里各项已四舍五入的情形），对不上就报错；残差写进数据表。展望项画成虚线框。"""
    d, unit = fig.get("digits", 1), fig.get("unit", "")
    pick = lambda it: {"label": it["label"], "v": ctx.num(it["value"]), "ev": it.get("evidence"),
                       "note": ctx.text(it.get("note", ""))}
    start, end = pick(fig["start"]), pick(fig["end"])
    steps = [pick(s) for s in fig["steps"]]
    if not steps:
        raise ValueError("瀑布图至少要有一个增减项")
    for it in [start, *steps, end]:
        ev_word(it["ev"])
    tol = float(fig.get("tolerance", 0))
    if tol < 0:
        raise ValueError("tolerance 不能为负")
    gap = start["v"] + sum(s["v"] for s in steps) - end["v"]
    if abs(gap) > tol + 1e-9:
        raise ValueError(f"起点加各项为 {fmt(start['v'] + sum(s['v'] for s in steps), d)}，终点为 {fmt(end['v'], d)}，"
                         f"相差 {gap:+.{d + 2}f}，超出容差 {tol:g}")
    levels, run = [start["v"]], start["v"]
    for s in steps:
        run += s["v"]
        levels.append(run)
    lo = float(fig.get("y_min", 0))  # 版式参数：截断纵轴时在副标题写明
    if min(levels + [end["v"]]) < lo:
        raise ValueError("累计值低于 y_min（瀑布图从 y_min 起画，不能有更低的累计值）")
    top = nice_max(max(levels + [end["v"]]))
    if top <= lo:
        raise ValueError("y_min 不低于最大累计值")
    W, H, L, R, T, B = fig.get("width", 640), fig.get("height", 260), 44, 12, 22, 42
    y = lambda v: T + (H - T - B) * (1 - (v - lo) / (top - lo))
    n = len(steps) + 2
    band = (W - L - R) / n
    bw = band * 0.6
    out = [svg_open(W, H, fig.get("title", ""))]
    for t in (zero_ticks(top) if lo == 0 else ticks(lo, top, 4)):
        out.append(f'<line class="nf-grid" x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="nf-axis" x="{L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{tick_text(t)}</text>')
    cols = [(start, lo, start["v"], "total")] + [(s, levels[i], levels[i + 1], "up" if s["v"] >= 0 else "down")
                                                for i, s in enumerate(steps)] + [(end, lo, end["v"], "total")]
    for i, (it, a, b, kind) in enumerate(cols):
        bx = L + band * i + (band - bw) / 2
        cx = bx + bw / 2
        y1, y2 = y(max(a, b)), y(min(a, b))
        cls = "nf-guide" if it["ev"] == "fwd" else {"total": "nf-s1", "up": "nf-s3", "down": "nf-s8"}[kind]
        shown = fmt(it["v"], d, unit) if kind == "total" else f'{"+" if it["v"] >= 0 else "−"}{fmt(abs(it["v"]), d, unit)}'
        tip = f'{it["label"]}：{shown}' + (f'（累计 {fmt(b, d, unit)}）' if kind != "total" else "") \
            + (f'，{EVIDENCE[it["ev"]]}' if it["ev"] else "") + (f'；{it["note"]}' if it["note"] else "")
        out.append(f'<g><title>{e(tip)}</title><rect class="{cls}" x="{bx:.1f}" y="{y1:.1f}" width="{bw:.1f}" '
                   f'height="{max(y2 - y1, 1):.1f}" rx="2"/>'
                   f'<rect class="nf-hit" x="{L + band * i:.1f}" y="{T}" width="{band:.1f}" height="{H - T - B}"/></g>'
                   f'<text class="nf-lbl" x="{cx:.1f}" y="{y1 - 6:.1f}" text-anchor="middle">{e(shown)}</text>'
                   f'<text class="nf-axis" x="{cx:.1f}" y="{H - 24}" text-anchor="middle">{e(fig.get("x_short", {}).get(it["label"], it["label"]))}</text>')
        if it["ev"]:
            out.append(f'<text class="nf-axis" x="{cx:.1f}" y="{H - 10}" text-anchor="middle">{ev_word(it["ev"])}</text>')
        if i < n - 1:  # 连接线：本列的终止水平到下一列
            out.append(f'<line class="nf-ref" x1="{bx + bw:.1f}" x2="{bx + band:.1f}" y1="{y(b):.1f}" y2="{y(b):.1f}"/>')
    out.append(f'<line class="nf-axisline" x1="{L}" x2="{W - R}" y1="{y(lo):.1f}" y2="{y(lo):.1f}"/></svg>')
    rows = [[it["label"], fmt(it["v"], d, unit), fmt(b, d, unit), EVIDENCE.get(it["ev"] or "", ""), it["note"]]
            for it, _, b, _ in cols]
    rows.append(["起点 + 各项 − 终点（残差）", f"{gap:+.{d + 2}f}", "", "", f"容差 {tol:g}"])
    return "".join(out), table_html(["项目", unit or "数值", "累计", "证据", "说明"], rows)


def funnel(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """客户转化阶段条：每阶段一个量，单位必须相同（可用 unit_ref 从记录读单位）；
    后一阶段大于前一阶段就报错，除非该阶段写 allow_increase 并在 note 里说明。"""
    d, unit = fig.get("digits", 0), fig.get("unit")
    if not unit:
        raise ValueError("funnel 必须声明 unit，各阶段的量同一单位")
    stages = []
    for s in fig["stages"]:
        u = str(ctx.raw(s["unit_ref"])) if s.get("unit_ref") else str(s.get("unit", unit))
        if u != unit:
            raise ValueError(f"{s['label']} 的单位「{u}」与图的单位「{unit}」不同，不能画在同一组阶段条里")
        st = {"label": s["label"], "v": ctx.num(s["value"]), "ev": s.get("evidence"), "note": ctx.text(s.get("note", ""))}
        ev_word(st["ev"])
        if st["v"] < 0:
            raise ValueError(f"{s['label']} 为负数")
        if stages and st["v"] > stages[-1]["v"]:
            if not s.get("allow_increase"):
                raise ValueError(f"{s['label']}（{fmt(st['v'], d)}）大于上一阶段 {stages[-1]['label']}"
                                 f"（{fmt(stages[-1]['v'], d)}）；确属口径如此，写 allow_increase 并在 note 说明")
            if not st["note"]:
                raise ValueError(f"{s['label']} 声明了 allow_increase，必须在 note 里说明原因")
        stages.append(st)
    if len(stages) < 2:
        raise ValueError("funnel 至少要有两个阶段")
    W, rh, T, L, R = 640, 46, 4, 190, 70
    H = T + len(stages) * rh
    top = max(s["v"] for s in stages) or 1.0
    x = lambda v: (W - L - R) * v / top
    out = [svg_open(W, H, fig.get("title", ""))]
    rows = []
    for i, s in enumerate(stages):
        yb = T + i * rh + 6
        conv = s["v"] / stages[i - 1]["v"] * 100 if i and stages[i - 1]["v"] else None
        w = max(x(s["v"]), 1)
        bx = L + (W - L - R - w) / 2  # 居中画，形似漏斗；长度与量成正比
        cls = "nf-guide" if s["ev"] == "fwd" else "nf-s1"
        tip = f'{s["label"]}：{fmt(s["v"], d)} {unit}' + (f'（上一阶段的 {conv:.0f}%）' if conv is not None else "") \
            + (f'；{s["note"]}' if s["note"] else "")
        out.append(f'<g><title>{e(tip)}</title>'
                   f'<text class="nf-lbl" x="0" y="{yb + 13}">{e(s["label"])}</text>'
                   f'<text class="nf-axis" x="0" y="{yb + 29}">{e(" · ".join(t for t in (ev_word(s["ev"]), f"上一阶段的 {conv:.0f}%" if conv is not None else "") if t))}</text>'
                   f'<rect class="{cls}" x="{bx:.1f}" y="{yb}" width="{w:.1f}" height="22" rx="3"/>'
                   f'<text class="nf-lbl" x="{W - R + 8}" y="{yb + 15}">{fmt(s["v"], d)}</text>'
                   f'<rect class="nf-hit" x="0" y="{yb - 6}" width="{W}" height="{rh}"/></g>')
        rows.append([s["label"], fmt(s["v"], d), "" if conv is None else f"{conv:.1f}%", EVIDENCE.get(s["ev"] or "", ""), s["note"]])
    out.append("</svg>")
    return "".join(out), table_html(["阶段", unit, "占上一阶段", "证据", "说明"], rows)


LIFECYCLE = {"growth": "成长", "mature": "成熟", "cyclical": "周期", "declining": "衰退"}
RELATIONS = {"additive": ("可加", "+"), "substitute": ("替代", "⇄"), "upstream_downstream": ("上下游", "→"),
             "overlap": ("部分重叠", "∩")}


def tree(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """层级树：大类 → 子类 → 交易市场。节点与关系都来自记录的结构化字段，网站不判断归类。
    校验：节点 id 不重复、父节点存在且无环、生命周期与关系类型在登记取值内、关系两端都存在。
    只有声明 aggregation: sum 的父节点才按子项合计表示（子项合计必须等于父节点，且子项之间
    不能有上下游、替代或重叠关系）；其余父节点标「子项不相加」，图上从不画堆叠或合计条。"""
    nodes, rels = ctx.raw(fig["nodes"]), ctx.raw(fig.get("relations")) if fig.get("relations") else []
    d, unit = fig.get("digits", 1), fig.get("unit", "")
    tol = float(fig.get("tolerance", 0))
    by: dict[str, dict] = {}
    for n in nodes:
        nid = str(n["id"])
        if nid in by:
            raise ValueError(f"节点 id 重复：{nid}")
        v = n.get("value")
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            raise ValueError(f"{nid} 的 value 不是数值")
        if n.get("lifecycle") is not None and n["lifecycle"] not in LIFECYCLE:
            raise ValueError(f"{nid} 的生命周期 {n['lifecycle']!r} 不在 {sorted(LIFECYCLE)} 里")
        if n.get("aggregation") not in (None, "sum"):
            raise ValueError(f"{nid} 的 aggregation 只能是 sum 或不写")
        by[nid] = {"id": nid, "label": str(n["label"]), "parent": None if n.get("parent") is None else str(n["parent"]),
                   "lifecycle": n.get("lifecycle"), "v": None if v is None else float(v), "agg": n.get("aggregation"), "kids": []}
    for n in by.values():
        if n["parent"] is not None:
            if n["parent"] not in by:
                raise ValueError(f"{n['id']} 的父节点 {n['parent']} 不存在")
            by[n["parent"]]["kids"].append(n["id"])
    for n in by.values():  # 无环
        seen, cur = set(), n["id"]
        while cur is not None:
            if cur in seen:
                raise ValueError(f"层级有环：{n['id']}")
            seen.add(cur)
            cur = by[cur]["parent"]
    def ancestors(nid: str) -> set[str]:
        out_, cur = set(), by[nid]["parent"]
        while cur is not None:
            out_.add(cur)
            cur = by[cur]["parent"]
        return out_
    edges = []
    for r in rels:
        a, b, kind = str(r["from"]), str(r["to"]), r["type"]
        for nid in (a, b):
            if nid not in by:
                raise ValueError(f"关系指向不存在的节点：{nid}")
        if kind not in RELATIONS:
            raise ValueError(f"关系类型 {kind!r} 不在 {sorted(RELATIONS)} 里")
        if a == b:
            raise ValueError(f"关系的两端是同一个节点：{a}")
        if kind != "additive" and (a in ancestors(b) or b in ancestors(a)):
            raise ValueError(f"{a} 与 {b} 在同一支上，不能标{RELATIONS[kind][0]}关系")
        edges.append({"from": a, "to": b, "type": kind, "note": str(r.get("note", ""))})
    for n in by.values():
        if n["agg"] != "sum":
            continue
        kids = n["kids"]
        if not kids or n["v"] is None or any(by[k]["v"] is None for k in kids):
            raise ValueError(f"{n['id']} 声明子项相加，但它或子项缺少 value")
        total = sum(by[k]["v"] for k in kids)
        if abs(total - n["v"]) > tol + 1e-9:
            raise ValueError(f"{n['id']} 的子项合计 {fmt(total, d)} 与节点值 {fmt(n['v'], d)} 不符")
        bad = [x for x in edges if x["type"] != "additive" and x["from"] in kids and x["to"] in kids]
        if bad:
            raise ValueError(f"{n['id']} 的子项之间有{RELATIONS[bad[0]['type']][0]}关系（{bad[0]['from']}–{bad[0]['to']}），不能按相加汇总")
    order: list[tuple[str, int]] = []

    def walk(nid: str, depth: int) -> None:
        order.append((nid, depth))
        for k in by[nid]["kids"]:
            walk(k, depth + 1)
    for n in by.values():
        if n["parent"] is None:
            walk(n["id"], 0)
    row = {nid: i for i, (nid, _) in enumerate(order)}
    rh, T, ind = 28, 8, 18
    G = 470  # 关系弧线起点（右侧留白）
    W = max(640, G + 40 + 16 * len(edges))
    H = T + len(order) * rh + 4
    yc = lambda i: T + i * rh + rh / 2
    out = [svg_open(W, H, fig.get("title", "")),
           '<defs><marker id="nf-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0,0L8,4L0,8Z" class="nf-arrowhead"/></marker></defs>']
    for i, (nid, depth) in enumerate(order):
        n = by[nid]
        x0 = depth * ind
        if n["parent"] is not None:
            pi, pd = row[n["parent"]], depth - 1
            px = pd * ind + 5
            out.append(f'<path class="nf-tree-link" d="M{px},{yc(pi) + 7:.1f}V{yc(i):.1f}H{x0 + 1}"/>')
        mark = "Σ 子项相加" if n["agg"] == "sum" else ("子项不相加" if n["kids"] else "")
        tip = f'{n["label"]}' + (f'：{fmt(n["v"], d)} {unit}' if n["v"] is not None else "") \
            + (f'；{LIFECYCLE[n["lifecycle"]]}' if n["lifecycle"] else "") + (f'；{mark}' if mark else "")
        out.append(f'<g><title>{e(tip)}</title>'
                   f'<circle class="nf-tree-node{" nf-tree-leaf" if not n["kids"] else ""}" cx="{x0 + 5}" cy="{yc(i):.1f}" r="4"/>'
                   f'<text class="{"nf-lbl" if depth == 0 else "nf-tree-t"}" x="{x0 + 14}" y="{yc(i) + 4:.1f}">{e(n["label"])}</text>'
                   + (f'<text class="nf-lc nf-lc-{n["lifecycle"]}" x="270" y="{yc(i) + 4:.1f}">{LIFECYCLE[n["lifecycle"]]}</text>' if n["lifecycle"] else "")
                   + (f'<text class="nf-lbl" x="380" y="{yc(i) + 4:.1f}" text-anchor="end">{fmt(n["v"], d)}</text>' if n["v"] is not None else "")
                   + (f'<text class="nf-axis" x="388" y="{yc(i) + 4:.1f}">{mark}</text>' if mark else "")
                   + f'<rect class="nf-hit" x="0" y="{yc(i) - rh / 2:.1f}" width="{G}" height="{rh}"/></g>')
    for k, x in enumerate(edges):
        y1, y2 = yc(row[x["from"]]), yc(row[x["to"]])
        bulge = 24 + 16 * k
        name, sym = RELATIONS[x["type"]]
        arrow = ' marker-end="url(#nf-arrow)"' if x["type"] == "upstream_downstream" else ""
        tip = f'{by[x["from"]]["label"]} {sym} {by[x["to"]]["label"]}：{name}' + (f'；{x["note"]}' if x["note"] else "")
        out.append(f'<g><title>{e(tip)}</title><path class="nf-rel nf-rel-{x["type"]}"{arrow} '
                   f'd="M{G},{y1:.1f}C{G + bulge},{y1:.1f} {G + bulge},{y2:.1f} {G + 2},{y2:.1f}"/>'
                   f'<text class="nf-rel-t" x="{G + bulge * 0.75 + 3:.1f}" y="{(y1 + y2) / 2 + 4:.1f}">{sym}</text></g>')
    out.append("</svg>")
    used_kinds = list(dict.fromkeys(x["type"] for x in edges))
    key = ('<p class="nf-legend">' + "".join(f'<span><i class="nf-k-rel nf-rel-{t}"></i>{RELATIONS[t][1]} {RELATIONS[t][0]}</span>'
                                             for t in used_kinds) + "</p>") if used_kinds else ""
    table = table_html(["节点", "上级", "生命周期", unit or "数值", "汇总"],
                       [["　" * dp + by[nid]["label"], by[by[nid]["parent"]]["label"] if by[nid]["parent"] else "",
                         LIFECYCLE.get(by[nid]["lifecycle"] or "", ""), "" if by[nid]["v"] is None else fmt(by[nid]["v"], d),
                         "子项相加" if by[nid]["agg"] == "sum" else ("子项不相加" if by[nid]["kids"] else "")] for nid, dp in order])
    if edges:
        table += table_html(["从", "到", "关系", "说明"],
                            [[by[x["from"]]["label"], by[x["to"]]["label"], RELATIONS[x["type"]][0], x["note"]] for x in edges])
    return "".join(out) + key, table


def as_date(v: Any, what: str):
    import datetime as dt
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            pass
    raise ValueError(f"{what} 的日期不合法：{v!r}（应为 YYYY-MM-DD）")


TL_STATUS = {"occurred": "已发生", "pending": "待兑现"}


def timeline(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """催化剂与待兑现事项时间线：事件点（date）或区间（start、end），状态只能是 occurred / pending。
    事件来自记录里的列表。日期不合法、区间倒置、id 重复报错；给了 as_of 时，标「已发生」的事件
    不能晚于查阅日。已发生画实心，待兑现画浅色虚线。"""
    import datetime as dt
    evs, ids = [], set()
    for ev in ctx.raw(fig["events"]):
        eid = str(ev["id"])
        if eid in ids:
            raise ValueError(f"事件 id 重复：{eid}")
        ids.add(eid)
        if ev.get("status") not in TL_STATUS:
            raise ValueError(f"{eid} 的状态 {ev.get('status')!r} 只能是 {sorted(TL_STATUS)}")
        if "date" in ev:
            a = b = as_date(ev["date"], eid)
        else:
            a, b = as_date(ev["start"], eid), as_date(ev["end"], eid)
            if b < a:
                raise ValueError(f"{eid} 的区间倒置：{a} 晚于 {b}")
        evs.append({"id": eid, "label": str(ev["label"]), "a": a, "b": b, "point": "date" in ev,
                    "status": ev["status"], "note": str(ev.get("note", ""))})
    if not evs:
        raise ValueError("timeline 没有事件")
    as_of = as_date(ctx.raw(fig["as_of"]), "as_of") if fig.get("as_of") else None
    if as_of:
        late = [x for x in evs if x["status"] == "occurred" and x["a"] > as_of]
        if late:
            raise ValueError(f"{late[0]['id']} 标为已发生，但日期 {late[0]['a']} 晚于查阅日 {as_of}")
    evs.sort(key=lambda x: (x["a"], x["b"]))
    lo = min([x["a"] for x in evs] + ([as_of] if as_of else []))
    hi = max([x["b"] for x in evs] + ([as_of] if as_of else []))
    span = max((hi - lo).days, 30)
    pad = dt.timedelta(days=max(10, span // 20))
    lo, hi = lo - pad, hi + pad
    W, rh, T, L, R, B = fig.get("width", 640), 30, 6, 210, 16, 26
    H = T + len(evs) * rh + B
    x = lambda d_: L + (W - L - R) * (d_ - lo).days / (hi - lo).days
    out = [svg_open(W, H, fig.get("title", ""))]
    months = (hi.year - lo.year) * 12 + hi.month - lo.month
    step = next(s for s in (1, 2, 3, 6, 12, 24, 60) if months / s <= 6)
    tk = dt.date(lo.year, lo.month, 1)
    while tk <= hi:
        if tk >= lo and (tk.month - 1) % min(step, 12) == 0:
            out.append(f'<line class="nf-grid" x1="{x(tk):.1f}" x2="{x(tk):.1f}" y1="{T}" y2="{H - B}"/>'
                       f'<text class="nf-axis" x="{x(tk):.1f}" y="{H - 8}" text-anchor="middle">{tk:%Y-%m}</text>')
        m = tk.month - 1 + step
        tk = dt.date(tk.year + m // 12, m % 12 + 1, 1)
    if as_of:
        out.append(f'<line class="nf-ref" x1="{x(as_of):.1f}" x2="{x(as_of):.1f}" y1="{T}" y2="{H - B}"/>'
                   f'<text class="nf-axis" x="{x(as_of) + 4:.1f}" y="{T + 9}">查阅日 {as_of}</text>')
    for i, ev in enumerate(evs):
        yc = T + i * rh + rh / 2
        when = str(ev["a"]) if ev["point"] else f'{ev["a"]} 至 {ev["b"]}'
        tip = f'{ev["label"]}：{when}，{TL_STATUS[ev["status"]]}' + (f'；{ev["note"]}' if ev["note"] else "")
        pend = ev["status"] == "pending"
        if ev["point"]:
            mark = f'<circle class="{"nf-tl-pend" if pend else "nf-dot nf-s1"}" cx="{x(ev["a"]):.1f}" cy="{yc:.1f}" r="5"/>'
        else:
            mark = (f'<rect class="{"nf-guide" if pend else "nf-s1"}" x="{x(ev["a"]):.1f}" y="{yc - 6:.1f}" '
                    f'width="{max(x(ev["b"]) - x(ev["a"]), 3):.1f}" height="12" rx="3"/>')
        out.append(f'<g><title>{e(tip)}</title><line class="nf-grid" x1="{L}" x2="{W - R}" y1="{yc:.1f}" y2="{yc:.1f}"/>'
                   f'<text class="nf-lbl" x="0" y="{yc + 4:.1f}">{e(ev["label"])}</text>{mark}'
                   f'<rect class="nf-hit" x="0" y="{yc - rh / 2:.1f}" width="{W}" height="{rh}"/></g>')
    out.append("</svg>")
    key = ('<p class="nf-legend"><span><i class="nf-s1"></i>已发生</span>'
           '<span><i class="nf-k-hatch"></i>待兑现</span></p>')
    table = table_html(["事件", "日期", "状态", "说明"],
                       [[ev["label"], str(ev["a"]) if ev["point"] else f'{ev["a"]} 至 {ev["b"]}', TL_STATUS[ev["status"]], ev["note"]]
                        for ev in evs])
    return key + "".join(out), table


def scenario(fig: dict, ctx: Ctx) -> tuple[str, str]:
    """情景区间（mode: range，默认）：每个情景一行，low–high 浅色虚线框，可选中点；
    或敏感性条（mode: sensitivity，龙卷风式）：每个输入取低、取高时结论的值，从 base 向两侧画，
    按影响幅度自动排序（不按声明顺序）。都可叠一条参考线（如现价，reference）。
    情景值和敏感性值都是假设下的结果，一律画成浅色虚线框，不画实心。坐标范围由 x_min/x_max 声明。"""
    d, unit = fig.get("digits", 1), fig.get("unit", "")
    lo, hi = float(fig["x_min"]), float(fig["x_max"])
    mode = fig.get("mode", "range")
    if mode not in ("range", "sensitivity"):
        raise ValueError("scenario 的 mode 只能是 range 或 sensitivity")
    ref = {"label": fig["reference"]["label"], "v": ctx.num(fig["reference"]["value"])} if fig.get("reference") else None
    base = {"label": fig["base"]["label"], "v": ctx.num(fig["base"]["value"])} if mode == "sensitivity" else None
    rows = []
    for r in fig["rows"]:
        row = {"label": r["label"], "low": ctx.num(r["low"]), "high": ctx.num(r["high"]),
               "mid": ctx.num(r["mid"]) if r.get("mid") is not None else None, "note": ctx.text(r.get("note", "")),
               "low_label": r.get("low_label", "输入取低"), "high_label": r.get("high_label", "输入取高")}
        if mode == "range":
            if row["low"] > row["high"]:
                raise ValueError(f"{r['label']}：区间下限大于上限")
            if row["mid"] is not None and not row["low"] <= row["mid"] <= row["high"]:
                raise ValueError(f"{r['label']}：中点不在区间内")
        elif row["mid"] is not None:
            raise ValueError(f"{r['label']}：敏感性条不用 mid")
        rows.append(row)
    if not rows:
        raise ValueError("scenario 没有 rows")
    check_axis([v for r in rows for v in (r["low"], r["high"], r["mid"]) if v is not None]
               + [x["v"] for x in (ref, base) if x], lo, hi)
    if mode == "sensitivity":
        rows.sort(key=lambda r: -abs(r["high"] - r["low"]))
    W, rh, T, L, R, B = fig.get("width", 640), 36, 8, 150, 16, 26
    H = T + len(rows) * rh + B
    x = lambda v: L + (W - L - R) * (v - lo) / (hi - lo)
    out = [svg_open(W, H, fig.get("title", ""))]
    for t in ticks(lo, hi, int(fig.get("ticks", 4))):
        out.append(f'<line class="nf-grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{T}" y2="{H - B}"/>'
                   f'<text class="nf-axis" x="{x(t):.1f}" y="{H - 8}" text-anchor="middle">{tick_text(t)}{"%" if unit == "%" else ""}</text>')
    table = []
    for i, r in enumerate(rows):
        yc = T + i * rh + rh / 2
        if mode == "range":
            tip = f'{r["label"]}：{fmt(r["low"], d, unit)}–{fmt(r["high"], d, unit)}' + (f'，中点 {fmt(r["mid"], d, unit)}' if r["mid"] is not None else "")
            g = (f'<rect class="nf-guide" x="{x(r["low"]):.1f}" y="{yc - 9:.1f}" width="{max(x(r["high"]) - x(r["low"]), 2):.1f}" height="18" rx="3"/>'
                 + (f'<line class="nf-whisker" x1="{x(r["mid"]):.1f}" x2="{x(r["mid"]):.1f}" y1="{yc - 9:.1f}" y2="{yc + 9:.1f}"/>' if r["mid"] is not None else "")
                 + f'<text class="nf-lbl" x="{x(r["high"]) + 6:.1f}" y="{yc + 4:.1f}">{fmt(r["mid"] if r["mid"] is not None else r["high"], d, unit)}</text>')
            table.append([r["label"], fmt(r["low"], d), fmt(r["high"], d), "" if r["mid"] is None else fmt(r["mid"], d), r["note"]])
        else:
            bx = x(base["v"])
            g = ""
            for side, cls in (("low", "nf-guide"), ("high", "nf-guide2")):
                xv = x(r[side])
                g += f'<rect class="{cls}" x="{min(bx, xv):.1f}" y="{yc - 9:.1f}" width="{max(abs(xv - bx), 1):.1f}" height="18" rx="2"/>'
            left, right = sorted((r["low"], r["high"]))
            g += (f'<text class="nf-axis" x="{x(left) - 4:.1f}" y="{yc + 4:.1f}" text-anchor="end">{fmt(left, d, unit)}</text>'
                  f'<text class="nf-axis" x="{x(right) + 4:.1f}" y="{yc + 4:.1f}">{fmt(right, d, unit)}</text>')
            tip = f'{r["label"]}：{r["low_label"]} → {fmt(r["low"], d, unit)}；{r["high_label"]} → {fmt(r["high"], d, unit)}（基准 {fmt(base["v"], d, unit)}）'
            table.append([r["label"], fmt(r["low"], d), fmt(r["high"], d), fmt(abs(r["high"] - r["low"]), d), r["note"]])
        tip += f'；{r["note"]}' if r["note"] else ""
        out.append(f'<g><title>{e(tip)}</title><text class="nf-lbl" x="0" y="{yc + 4:.1f}">{e(r["label"])}</text>{g}'
                   f'<rect class="nf-hit" x="0" y="{yc - rh / 2:.1f}" width="{W}" height="{rh}"/></g>')
    for mark, cls in ((base, "nf-whisker"), (ref, "nf-refval")):
        if mark:
            out.append(f'<g><title>{e(mark["label"])}：{fmt(mark["v"], d, unit)}</title>'
                       f'<line class="{cls}" x1="{x(mark["v"]):.1f}" x2="{x(mark["v"]):.1f}" y1="{T - 4}" y2="{H - B}"/></g>')
    out.append("</svg>")
    items = []
    if mode == "sensitivity":
        items += [f'<span><i class="nf-k-hatch"></i>{e(rows[0]["low_label"])}</span>',
                  f'<span><i class="nf-k-hatch2"></i>{e(rows[0]["high_label"])}</span>',
                  f'<span><i class="nf-k-prior"></i>{e(base["label"])} {fmt(base["v"], d, unit)}</span>']
    else:
        items.append('<span><i class="nf-k-hatch"></i>情景区间（竖线为中点）</span>')
    if ref:
        items.append(f'<span><i class="nf-k-refval"></i>{e(ref["label"])} {fmt(ref["v"], d, unit)}</span>')
    head = ["情景", "下限", "上限", "中点", "说明"] if mode == "range" else ["输入", rows[0]["low_label"], rows[0]["high_label"], "幅度", "说明"]
    extra = [[x_["label"], fmt(x_["v"], d), "", "", "参考线" if x_ is ref else "基准"] for x_ in (base, ref) if x_]
    return f'<p class="nf-legend">{"".join(items)}</p>' + "".join(out), table_html(head, table + extra)


PLOTS = {"range": range_plot, "bar": bar, "line": line, "hbar": hbar, "stack": stack, "slope": slope, "matrix": matrix,
         "waterfall": waterfall, "funnel": funnel, "tree": tree, "timeline": timeline, "scenario": scenario}
