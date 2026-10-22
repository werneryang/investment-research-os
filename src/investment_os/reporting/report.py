"""报告与图表（模块 O）。只读取结构化研究成果，不重新计算。

同一份内容同时输出 Markdown 与独立 HTML（图表内嵌），便于存档与离线查看。
"""

from __future__ import annotations

import base64
import html
import math
import re
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..tenor import parse_tenor  # noqa: E402

RESULT_TYPE_LABEL = {"descriptive": "描述与比较", "explanatory": "解释与归因",
                     "forecast": "预测", "simulation": "情景与策略模拟"}
STATUS_LABEL = {"pass": "通过", "fail": "未通过", "skipped": "跳过"}


def _fmt(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return str(v)


# ---- 图表 -----------------------------------------------------------------

def _figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    daily = result["tables"].get("daily") or []
    if not daily:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.3, "font.size": 9})
    x = pd.to_datetime([r["date"] for r in daily])
    figs: list[tuple[str, Path]] = []

    snaps = result["results"].get("snapshots") or []
    if snaps:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for snap in snaps:
            tenors = sorted((k for k in snap if k not in ("label", "date")),
                            key=lambda c: parse_tenor(c).months)
            ax.plot([parse_tenor(t).months / 12 for t in tenors], [snap[t] for t in tenors],
                    marker="o", ms=3, label=f"{snap['label']} {snap['date']}")
        ax.set_xlabel("Maturity (years)")
        ax.set_ylabel("Par yield (%)")
        ax.set_title("Yield curve: start vs end of period")
        ax.legend(frameon=False)
        figs.append(("期初与期末收益率曲线", _save(fig, out_dir / "curve_snapshots.png")))

    levels = list(result["results"].get("levels", {}))
    if levels:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for t in levels:
            ax.plot(x, [r.get(t) for r in daily], lw=1.1, label=t)
        ax.set_ylabel("Par yield (%)")
        ax.set_title("Key tenor yields")
        ax.legend(frameon=False, ncol=len(levels))
        figs.append(("关键期限收益率", _save(fig, out_dir / "key_tenors.png")))

    spread_cols = [*result["results"].get("spreads", {}),
                   *(f"curvature {k}" for k in result["results"].get("curvature", {}))]
    if spread_cols:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for c in spread_cols:
            ax.plot(x, [r.get(c) for r in daily], lw=1.1, label=c)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylabel("bp")
        ax.set_title("Spreads (long - short) and butterfly curvature")
        ax.legend(frameon=False)
        figs.append(("利差与曲率", _save(fig, out_dir / "spreads.png")))
    return figs


def _save(fig: Any, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---- 内容结构 -------------------------------------------------------------

def _sections(result: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """返回 [(标题, [段落字符串 | ("table", 表头, 行) | ("figure", 说明, 路径)])]。"""
    cov = result["coverage"]
    status = "部分结论受限" if result["unsupported"] or not cov.get("period_complete", True) else "完整"
    overview = [
        f"**研究问题：** {result['question']}",
        f"**成果类型：** {RESULT_TYPE_LABEL.get(result['result_type'], result['result_type'])}"
        f"　**研究分支：** {result['branch']}　**结论状态：** {status}",
        f"**研究范围：** {result['scope'].get('market', '')} · {result['scope'].get('currency', '')} · "
        f"{result['scope'].get('start')} 至 {result['scope'].get('end')} · {result['scope'].get('frequency', '')}",
        f"**数据截止：** {result['data_cutoff'] or '—'}　**生成时间：** {result['generated_at']}",
        f"**运行 ID：** `{result['run_id']}`　**结果校验值：** `{result['result_hash'][:16]}`",
    ]
    secs: list[tuple[str, list[Any]]] = [("概要", overview)]

    r = result["results"]
    body: list[Any] = []
    if r.get("levels"):
        body.append(("table", ["期限", "期初 %", "期末 %", "变化 bp", "最低 %（日期）", "最高 %（日期）", "均值 %"],
                     [[t, _fmt(v["start"]), _fmt(v["end"]), _fmt(v["change_bp"], 0),
                       f"{_fmt(v['min'])}（{v['min_date']}）", f"{_fmt(v['max'])}（{v['max_date']}）",
                       _fmt(v["mean"])] for t, v in r["levels"].items()]))
    if r.get("spreads"):
        body.append(("table", ["利差", "期初 bp", "期末 bp", "变化 bp", "最低 bp", "最高 bp", "倒挂天数 / 占比"],
                     [[k, _fmt(v["start"], 0), _fmt(v["end"], 0), _fmt(v["change_bp"], 0),
                       _fmt(v["min"], 0), _fmt(v["max"], 0),
                       f"{v['inversion']['inverted_days']} / {v['inversion']['inverted_share']:.0%}"]
                      for k, v in r["spreads"].items()]))
    if r.get("curvature"):
        body.append(("table", ["曲率", "期初 bp", "期末 bp", "变化 bp", "均值 bp"],
                     [[k, _fmt(v["start"], 0), _fmt(v["end"], 0), _fmt(v["change_bp"], 0), _fmt(v["mean"], 0)]
                      for k, v in r["curvature"].items()]))
    if result["tables"].get("curve_change"):
        body.append(("table", ["期限", "期初 %", "期末 %", "变化 bp"],
                     [[c["tenor"], _fmt(c["start"]), _fmt(c["end"]), _fmt(c["change_bp"], 0)]
                      for c in result["tables"]["curve_change"]]))
    secs.append(("主要结果", body or ["没有可支持的结果。"]))

    secs.append(("图表", [("figure", cap, path) for cap, path in result.get("_figures", [])]
                 or ["无可绘制的数据。"]))

    cov_rows = [[t, str(v["observations"]), f"{v['share']:.1%}"] for t, v in cov["tenors"].items()]
    coverage = [
        f"曲线交易日 {cov['curve_days']} 天，覆盖 {cov['first'] or '—'} 至 {cov['last'] or '—'}；"
        f"期间{'完整' if cov['period_complete'] else '未完整'}覆盖。最低覆盖要求 {cov['min_coverage']:.0%}。",
        ("table", ["期限", "有效观测", "占比"], cov_rows),
    ]
    if cov.get("excluded_rows"):
        coverage.append("排除的行（缺失或隔离）："
                        + "，".join(f"{k} {v}" for k, v in cov["excluded_rows"].items()))
    if result["unsupported"]:
        coverage.append(("table", ["不支持的结论", "原因"],
                         [[u["item"], u["reason"]] for u in result["unsupported"]]))
    secs.append(("覆盖与限制范围", coverage))

    val = []
    for name, v in result["validation"].items():
        label = {"cross_check": "交叉核验", "raw_spot_check": "原始快照抽查"}.get(name, name)
        line = f"**{label}：** {STATUS_LABEL.get(v.get('status'), v.get('status'))}"
        if name == "cross_check" and v.get("matched"):
            line += (f"；对照 {v['against']}，共同日期 {v['matched']} 天，最大差 {_fmt(v['max_abs_diff'], 4)}"
                     f"（容差 {v['tolerance']}）。{v['note']}")
        elif name == "raw_spot_check" and v.get("checked"):
            line += f"；抽查 {v['checked']} 个观测，不一致 {len(v['failures'])} 个"
        elif v.get("reason"):
            line += f"；{v['reason']}"
        val.append(line)
    secs.append(("验证", val))

    inputs = [("table", ["角色", "数据集", "版本", "来源", "核验状态"],
               [[i["role"], i["dataset_id"], f"`{i['version_id']}`", i["source_id"] or "—", i["source_status"]]
                for i in result["inputs"]])]
    m = result["methods"]
    inputs.append(f"**方法：** {m['description']}")
    if m.get("benchmark"):
        inputs.append(f"**比较基准：** {m['benchmark']}")
    if m.get("availability_rule"):
        inputs.append(f"**可用时间规则：** {m['availability_rule']}")
    secs.append(("数据与方法", inputs))
    secs.append(("限制", [f"- {x}" for x in result["limitations"]] or ["无"]))
    return secs


# ---- 渲染 -----------------------------------------------------------------

def _md(result: dict[str, Any], secs: list[tuple[str, list[Any]]], base: Path) -> str:
    out = [f"# {result['title']}", ""]
    for title, items in secs:
        out += [f"## {title}", ""]
        for it in items:
            if isinstance(it, str):
                out += [it, ""]
            elif it[0] == "table":
                _, head, rows = it
                out.append("| " + " | ".join(head) + " |")
                out.append("|" + "---|" * len(head))
                out += ["| " + " | ".join(r) + " |" for r in rows]
                out.append("")
            elif it[0] == "figure":
                _, cap, path = it
                out += [f"![{cap}]({path.relative_to(base).as_posix()})", ""]
    return "\n".join(out)


def _inline_md(text: str) -> str:
    """只处理本报告用到的 **粗体** 与 `代码`。"""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def _html(result: dict[str, Any], secs: list[tuple[str, list[Any]]]) -> str:
    parts = []
    for title, items in secs:
        parts.append(f"<h2>{html.escape(title)}</h2>")
        bullets = []
        for it in items:
            if isinstance(it, str) and it.startswith("- "):
                bullets.append(f"<li>{_inline_md(it[2:])}</li>")
                continue
            if bullets:
                parts.append("<ul>" + "".join(bullets) + "</ul>")
                bullets = []
            if isinstance(it, str):
                parts.append(f"<p>{_inline_md(it)}</p>")
            elif it[0] == "table":
                _, head, rows = it
                th = "".join(f"<th>{html.escape(h)}</th>" for h in head)
                trs = "".join("<tr>" + "".join(f"<td>{_inline_md(c)}</td>" for c in r) + "</tr>" for r in rows)
                parts.append(f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')
            elif it[0] == "figure":
                _, cap, path = it
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                parts.append(f'<figure><img alt="{html.escape(cap)}" src="data:image/png;base64,{data}">'
                             f"<figcaption>{html.escape(cap)}</figcaption></figure>")
        if bullets:
            parts.append("<ul>" + "".join(bullets) + "</ul>")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(result['title'])}</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e0d9; --accent:#2f5d8a; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161614; --fg:#ecebe6; --muted:#a3a29b; --line:#34332f; --accent:#8fb6dd; }}
  img {{ background:#fff; border-radius:4px; }} }}
body {{ background:var(--bg); color:var(--fg); margin:0; padding:24px 16px 64px;
  font:15px/1.6 -apple-system, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; }}
main {{ max-width:880px; margin:0 auto; }}
h1 {{ font-size:1.6rem; margin:0 0 1rem; }} h2 {{ font-size:1.15rem; margin:2rem 0 .6rem;
  padding-bottom:.3rem; border-bottom:1px solid var(--line); color:var(--accent); }}
table {{ border-collapse:collapse; font-size:.9rem; font-variant-numeric:tabular-nums; }}
th, td {{ border-bottom:1px solid var(--line); padding:.35rem .7rem; text-align:right; white-space:nowrap; }}
th:first-child, td:first-child {{ text-align:left; }} th {{ color:var(--muted); font-weight:600; }}
.scroll {{ overflow-x:auto; margin:.6rem 0 1rem; }}
figure {{ margin:1rem 0; }} img {{ max-width:100%; height:auto; }}
figcaption {{ color:var(--muted); font-size:.85rem; }}
code {{ font-size:.85em; }}
</style></head>
<body><main><h1>{html.escape(result['title'])}</h1>
{''.join(parts)}
</main></body></html>
"""


def write_report(root: Path, result: dict[str, Any]) -> list[Path]:
    out_dir = Path(root) / "reports" / result["study_id"] / result["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    figs = _figures(result, out_dir / "figures")
    secs = _sections({**result, "_figures": figs})
    md_path = out_dir / "report.md"
    md_path.write_text(_md(result, secs, out_dir), encoding="utf-8")
    html_path = out_dir / "report.html"
    html_path.write_text(_html(result, secs), encoding="utf-8")
    return [md_path, html_path, *(p for _, p in figs)]
