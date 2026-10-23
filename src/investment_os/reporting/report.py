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

from ..analytics.rates import curvature_label, spread_label  # noqa: E402
from ..research.findings import COVERAGE_LABEL, completeness, coverage_summary  # noqa: E402
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


def _mark(name: str, summary: dict[str, Any]) -> str:
    """有缺口的指标在名称后加 *：其期间统计只基于已观测日期。"""
    return f"{name} *" if summary.get("sample") == "observed" else name


def _dated(value: Any, day: str | None) -> str:
    return "—" if value is None else f"{_fmt(value)}（{day}）"


def _inversion_cells(inv: dict[str, Any] | None) -> list[str]:
    if not inv:
        return ["—", "—"]
    return [f"{inv['inverted_days']} / {inv['inverted_share']:.0%}", str(inv["zero_days"])]


# ---- 图表 -----------------------------------------------------------------

def _curve_figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
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

    spread_cols = [*((k, spread_label(k)) for k in result["results"].get("spreads", {})),
                   *((f"curvature {k}", f"curvature {curvature_label(k)}")
                     for k in result["results"].get("curvature", {}))]
    if spread_cols:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for col, label in spread_cols:
            ax.plot(x, [r.get(col) for r in daily], lw=1.1, label=label)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylabel("bp")
        ax.set_title("Spreads (long - short) and butterfly curvature")
        ax.legend(frameon=False)
        figs.append(("利差与曲率", _save(fig, out_dir / "spreads.png")))
    return figs


def _bond_figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    scen = result["results"].get("scenarios", {})
    if not scen:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.3, "font.size": 9})
    figs: list[tuple[str, Path]] = []
    focus = "10Y" if "10Y" in scen else next(iter(scen))
    rows = scen[focus]
    x = [r["shock_bp"] for r in rows]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(x, [r["full_pct"] for r in rows], marker="o", ms=3, label="Full repricing")
    ax.plot(x, [r["duration_pct"] for r in rows], ls="--", label="Duration")
    ax.plot(x, [r["duration_convexity_pct"] for r in rows], ls=":", label="Duration + convexity")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Yield shock (bp)")
    ax.set_ylabel("Price change (%)")
    ax.set_title(f"{focus} hypothetical par bond: price change by method")
    ax.legend(frameon=False)
    figs.append((f"{focus} 价格变化：完整重新定价与近似", _save(fig, out_dir / "scenario_price.png")))

    fig, ax = plt.subplots(figsize=(7, 3.6))
    for tenor, rs in scen.items():
        ax.plot([r["shock_bp"] for r in rs], [r["duration_convexity_error_pp"] for r in rs], marker="o", ms=3,
                label=tenor)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Yield shock (bp)")
    ax.set_ylabel("Error (pp)")
    ax.set_title("Duration + convexity approximation error vs full repricing")
    ax.legend(frameon=False, ncol=len(scen))
    figs.append(("久期 + 凸性近似误差（各期限）", _save(fig, out_dir / "approx_error.png")))
    return figs


_FIGURE_BUILDERS = {"rates_curve": _curve_figures, "par_bond_scenarios": _bond_figures}


def _figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    builder = _FIGURE_BUILDERS.get(result["branch"])
    return builder(result, out_dir) if builder else []


def _save(fig: Any, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---- 内容结构 -------------------------------------------------------------

def _curve_sections(result: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    """收益率曲线描述研究：主要结果表与覆盖说明。"""
    cov = result["coverage"]
    state = completeness(cov)
    r = result["results"]
    body: list[Any] = []
    if r.get("levels"):
        first = next(iter(r["levels"].values()))
        note = (f"变化以首个有效观测（{first.get('start_date', '—')}）为基准，"
                f"至最后有效观测（{first.get('end_date', '—')}）；不是跨年末口径，也不是持有期回报。")
        if state in ("insufficient", "no_calendar"):
            note += "标为 — 的期间统计因覆盖不足而不输出。"
        elif any(v.get("sample") == "observed" for group in ("levels", "spreads", "curvature")
                 for v in r.get(group, {}).values()):
            note += "标 * 的指标有缺口，其最低、最高、均值与倒挂天数只基于已观测日期，不能推及整个期间。"
        body.append(note)
        body.append(("table", ["期限", "期初 %", "期末 %", "变化 bp", "最低 %（日期）", "最高 %（日期）", "均值 %"],
                     [[_mark(t, v), _fmt(v["start"]), _fmt(v["end"]), _fmt(v["change_bp"], 0),
                       _dated(v["min"], v["min_date"]), _dated(v["max"], v["max_date"]),
                       _fmt(v["mean"])] for t, v in r["levels"].items()]))
    if r.get("spreads"):
        body.append("倒挂定义为利差严格小于 0；恰为 0 的日期单独列出，不计入倒挂。")
        body.append(("table", ["利差（长端 − 短端）", "期初 bp", "期末 bp", "变化 bp", "最低 bp", "最高 bp",
                               "倒挂天数 / 占比", "零利差天数"],
                     [[_mark(spread_label(k), v), _fmt(v["start"], 0), _fmt(v["end"], 0), _fmt(v["change_bp"], 0),
                       _fmt(v["min"], 0), _fmt(v["max"], 0), *_inversion_cells(v["inversion"])]
                      for k, v in r["spreads"].items()]))
    if r.get("curvature"):
        body.append(("table", ["曲率", "期初 bp", "期末 bp", "变化 bp", "均值 bp"],
                     [[_mark(curvature_label(k), v), _fmt(v["start"], 0), _fmt(v["end"], 0), _fmt(v["change_bp"], 0),
                       _fmt(v["mean"], 0)] for k, v in r["curvature"].items()]))
    if result["tables"].get("curve_change"):
        body.append(("table", ["期限", "期初 %", "期末 %", "变化 bp"],
                     [[c["tenor"], _fmt(c["start"]), _fmt(c["end"]), _fmt(c["change_bp"], 0)]
                      for c in result["tables"]["curve_change"]]))
    results_part = body
    cov_rows = [[t, str(v["observations"]), f"{v['share']:.1%}"] for t, v in cov["tenors"].items()]
    detail = ""
    if cov.get("expected_days") is not None:
        detail = f"研究窗口内预期观测日 {cov['expected_days']} 天（日历 {cov['calendar']}）"
        if cov.get("pending_days"):
            detail += f"，评估时尚未发布 {cov['pending_days']} 天"
        if cov.get("missing_days"):
            detail += f"，应已发布但缺失 {cov['missing_days']} 天（如 {'、'.join(cov['missing_examples'][:3])}）"
        detail += "。"
    reason = f"（{cov['incomplete_reason']}）" if cov.get("incomplete_reason") else ""
    coverage_part = [
        f"{coverage_summary(cov)}{reason}；覆盖 {cov['first'] or '—'} 至 {cov['last'] or '—'}。{detail}"
        f"覆盖要求 {cov['min_coverage']:.0%}（决定期间统计能否输出；期间完整另需无缺失且日历已核验）。",
        ("table", ["期限", "有效观测", "占比（分母为应已发布的观测日）"
                   if cov.get("tenor_denominator") in ("due_days", "expected_days") else "占比（分母为实际观测日）"],
         cov_rows),
    ]
    if cov.get("excluded_rows"):
        coverage_part.append("排除的行（缺失或隔离）："
                        + "，".join(f"{k} {v}" for k, v in cov["excluded_rows"].items()))
    return results_part, "覆盖与限制范围", coverage_part


def _bond_sections(result: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    """假设平价债券情景：债券性质、情景损益与近似误差；「假设与输入」说明基准日与假设。"""
    r = result["results"]
    body: list[Any] = [
        f"基准日 {r['base_date']}：各期限按当日票面收益率构造票息等于收益率的假设平价债券。"
        "价格变化为相对基准价格的百分比；误差 = 近似 − 完整重新定价（百分点）。不是预测，冲击幅度不代表概率。",
        ("table", ["期限", "票息 = 收益率 %", "价格", "麦考利久期（年）", "修正久期（年）", "凸性", "DV01（每 100 面值）"],
         [[t, _fmt(b["yield_pct"]), _fmt(b["price"], 4), _fmt(b["macaulay_duration"], 3),
           _fmt(b["modified_duration"], 3), _fmt(b["convexity"], 2), _fmt(b["dv01"], 4)]
          for t, b in r["bonds"].items()]),
    ]
    for tenor, rows in r["scenarios"].items():
        body.append(("table", [f"{tenor} 冲击 bp", "完整重新定价 %", "久期近似 %", "久期 + 凸性 %",
                               "久期误差 pp", "久期 + 凸性误差 pp"],
                     [[f"{x['shock_bp']:+.0f}", _fmt(x["full_pct"], 3), _fmt(x["duration_pct"], 3),
                       _fmt(x["duration_convexity_pct"], 3), _fmt(x["duration_error_pp"], 3),
                       _fmt(x["duration_convexity_error_pp"], 4)] for x in rows]))
    cov = result["coverage"]
    assumptions = [
        f"基准日 {cov['base_date']}（研究窗口终点 {cov['window_end']}，相隔 {cov['days_before_window_end']} 天）；"
        f"窗口内曲线日 {cov['curve_days_in_window']} 天，基准日为所有所需期限同时有值的最后一天。",
        f"使用期限：{'、'.join(cov['tenors_used'])}（请求 {'、'.join(cov['tenors_requested'])}）。",
    ]
    return body, "假设与输入", assumptions


_BRANCH_SECTIONS = {"rates_curve": _curve_sections, "par_bond_scenarios": _bond_sections}


def _sections(result: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """返回 [(标题, [段落字符串 | ("table", 表头, 行) | ("figure", 说明, 路径)])]。"""
    if result["branch"] == "rates_curve":
        state = completeness(result["coverage"])
        status = ("部分结论受限" if result["unsupported"] or state not in ("complete", "complete_to_date")
                  else COVERAGE_LABEL[state])
    else:
        status = "部分结论受限" if result["unsupported"] else "完整"
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

    branch_sections = _BRANCH_SECTIONS.get(result["branch"])
    results_part, coverage_title, coverage_part = (
        branch_sections(result) if branch_sections else
        (["该研究分支暂无报告模板。"], "覆盖与限制范围", []))
    secs.append(("主要结果", results_part or ["没有可支持的结果。"]))

    secs.append(("图表", [("figure", cap, path) for cap, path in result.get("_figures", [])]
                 or ["无可绘制的数据。"]))

    if result["unsupported"]:
        coverage_part = [*coverage_part, ("table", ["不支持的结论", "原因"],
                                          [[u["item"], u["reason"]] for u in result["unsupported"]])]
    secs.append((coverage_title, coverage_part or ["无"]))

    val = []
    for name, v in result["validation"].items():
        label = {"cross_check": "交叉核验", "raw_spot_check": "原始快照抽查",
                 "closed_form_checks": "封闭解与重新定价核对"}.get(name, name)
        line = f"**{label}：** {STATUS_LABEL.get(v.get('status'), v.get('status'))}"
        if name == "cross_check" and v.get("matched"):
            line += (f"；对照 {v['against']}，共同日期 {v['matched']} 天，最大差 {_fmt(v['max_abs_diff'], 4)}"
                     f"（容差 {v['tolerance']}）。{v['note']}")
        elif name == "closed_form_checks":
            line += (f"；{v['checked']} 项核对，未通过 {len(v['failures'])} 项（平价价格 = 面值；"
                     "解析修正久期 = 平价债券封闭解；解析久期、凸性 ≈ 有限差分完整重新定价）")
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
a {{ color:var(--accent); }}
a:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; border-radius:2px; }}
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
