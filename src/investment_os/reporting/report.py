"""报告与图表（模块 O）。只读取结构化研究成果，不重新计算。

同一份内容同时输出 Markdown 与独立 HTML（图表内嵌），便于存档与离线查看。
"""

from __future__ import annotations

import base64
import functools
import html
import math
import re
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from ..analytics.rates import curvature_label, spread_label  # noqa: E402
from ..research.findings import COVERAGE_LABEL, completeness, coverage_summary  # noqa: E402
from ..tenor import parse_tenor  # noqa: E402
from .company import sections as company_sections
from .industry import figures as industry_figures, sections as industry_sections  # noqa: E402

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

# 图中文字用中文，需要系统里有 CJK 字体（发布工作流安装 fonts-noto-cjk）。
# 找不到时退回英文标签，避免出现方框字。
_CJK_FONTS = ("Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans SC", "Source Han Sans SC", "PingFang SC",
              "Hiragino Sans GB", "Heiti SC", "Microsoft YaHei", "WenQuanYi Zen Hei")
_CURVE_TICKS = ("3M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y")


@functools.cache
def _cjk_font() -> str | None:
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in _CJK_FONTS if n in names), None)


def _t(zh: str, en: str) -> str:
    return zh if _cjk_font() else en


def _style() -> None:
    plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.3, "font.size": 9})
    if font := _cjk_font():
        plt.rcParams.update({"font.sans-serif": [font, "DejaVu Sans"], "axes.unicode_minus": False})


def _curve_figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    daily = result["tables"].get("daily") or []
    if not daily:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    _style()
    x = pd.to_datetime([r["date"] for r in daily])
    figs: list[tuple[str, Path]] = []

    snaps = result["results"].get("snapshots") or []
    if snaps:
        # 横轴按期限（年）的平方根排布，避免短端挤在一起；刻度标期限代码
        fig, ax = plt.subplots(figsize=(7, 3.6))
        names = {"start": _t("期初", "start"), "end": _t("期末", "end")}
        ticks: set[str] = set()
        for snap in snaps:
            tenors = sorted((k for k in snap if k not in ("label", "date")),
                            key=lambda c: parse_tenor(c).months)
            ticks.update(t for t in tenors if t in _CURVE_TICKS)
            ax.plot([math.sqrt(parse_tenor(t).months / 12) for t in tenors], [snap[t] for t in tenors],
                    marker="o", ms=3, label=f"{names.get(snap['label'], snap['label'])} {snap['date']}")
        shown = sorted(ticks, key=lambda c: parse_tenor(c).months)
        ax.set_xticks([math.sqrt(parse_tenor(t).months / 12) for t in shown], shown)
        ax.set_xlim(left=0)
        ax.set_xlabel(_t("期限（平方根刻度）", "Maturity (square-root scale)"))
        ax.set_ylabel(_t("票面收益率（%）", "Par yield (%)"))
        ax.set_title(_t("期初与期末收益率曲线", "Yield curve: start vs end of period"))
        ax.legend(frameon=False)
        figs.append(("期初与期末收益率曲线", _save(fig, out_dir / "curve_snapshots.png")))

    levels = list(result["results"].get("levels", {}))
    if levels:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for t in levels:
            ax.plot(x, [r.get(t) for r in daily], lw=1.1, label=t)
        ax.set_ylabel(_t("票面收益率（%）", "Par yield (%)"))
        ax.set_title(_t("关键期限收益率", "Key tenor yields"))
        ax.legend(frameon=False, ncol=len(levels))
        figs.append(("关键期限收益率", _save(fig, out_dir / "key_tenors.png")))

    curvature = _t("曲率", "curvature")
    spread_cols = [*((k, spread_label(k)) for k in result["results"].get("spreads", {})),
                   *((f"curvature {k}", f"{curvature} {curvature_label(k)}")
                     for k in result["results"].get("curvature", {}))]
    if spread_cols:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for col, label in spread_cols:
            ax.plot(x, [r.get(col) for r in daily], lw=1.1, label=label)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylabel("bp")
        ax.set_title(_t("利差（长端 − 短端）与蝶式曲率", "Spreads (long - short) and butterfly curvature"))
        ax.legend(frameon=False)
        figs.append(("利差与曲率", _save(fig, out_dir / "spreads.png")))
    return figs


def _bond_figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    scen = result["results"].get("scenarios", {})
    if not scen:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    _style()
    figs: list[tuple[str, Path]] = []
    focus = "10Y" if "10Y" in scen else next(iter(scen))
    rows = scen[focus]
    x = [r["shock_bp"] for r in rows]
    shock = _t("收益率冲击（bp）", "Yield shock (bp)")
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(x, [r["full_pct"] for r in rows], marker="o", ms=3, label=_t("完整重新定价", "Full repricing"))
    ax.plot(x, [r["duration_pct"] for r in rows], ls="--", label=_t("久期近似", "Duration"))
    ax.plot(x, [r["duration_convexity_pct"] for r in rows], ls=":",
            label=_t("久期 + 凸性", "Duration + convexity"))
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel(shock)
    ax.set_ylabel(_t("价格变化（%）", "Price change (%)"))
    ax.set_title(_t(f"{focus} 假设平价债券：各方法的价格变化", f"{focus} hypothetical par bond: price change by method"))
    ax.legend(frameon=False)
    figs.append((f"{focus} 价格变化：完整重新定价与近似", _save(fig, out_dir / "scenario_price.png")))

    fig, ax = plt.subplots(figsize=(7, 3.6))
    for tenor, rs in scen.items():
        ax.plot([r["shock_bp"] for r in rs], [r["duration_convexity_error_pp"] for r in rs], marker="o", ms=3,
                label=tenor)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel(shock)
    ax.set_ylabel(_t("误差（百分点）", "Error (pp)"))
    ax.set_title(_t("久期 + 凸性近似误差（相对完整重新定价）", "Duration + convexity approximation error vs full repricing"))
    ax.legend(frameon=False, ncol=len(scen))
    figs.append(("久期 + 凸性近似误差（各期限）", _save(fig, out_dir / "approx_error.png")))
    return figs


def _attribution_figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    r = result["results"]
    path = result.get("tables", {}).get("path_bp", [])
    if not r.get("long_end") or not path:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    _style()
    figs: list[tuple[str, Path]] = []
    lg, sh, sl = r["long_end"], r["short_end"], r["slope"]
    names = {"real": _t("实际收益率", "Real yield"), "breakeven": _t("盈亏平衡通胀", "Breakeven inflation"),
             "policy": _t("联邦基金利率", "Fed funds"), "spread": _t(f"{sh['tenor']} − 联邦基金", f"{sh['tenor']} − fed funds"),
             "residual": _t("残差", "Residual")}
    groups = [(f"{lg['tenor']}", {"real": lg["real"]["change_bp"], "breakeven": lg["breakeven"]["change_bp"]},
               lg["nominal"]["change_bp"]),
              (f"{sh['tenor']}", {"policy": sh["policy"]["change_bp"], "spread": sh["spread"]["change_bp"]},
               sh["nominal"]["change_bp"]),
              (sl["label"], {k: v for k, v in sl["contributions_bp"].items() if k != "residual"}, sl["change_bp"])]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    colors = {"real": "#2b5a87", "breakeven": "#8fb6dd", "policy": "#a12d2d", "spread": "#f09a9a"}
    for x, (_, parts, total) in enumerate(groups):
        pos = neg = 0.0
        for k, v in parts.items():
            base = pos if v >= 0 else neg
            ax.bar(x, v, bottom=base, color=colors[k], width=0.55,
                   label=names[k] if x == (0 if k in ("real", "breakeven") else 1) else None)
            pos, neg = (pos + v, neg) if v >= 0 else (pos, neg + v)
        ax.plot([x - 0.35, x + 0.35], [total, total], color="black", lw=1.5)
        ax.annotate(f"{total:+.0f}", (x + 0.38, total), va="center", fontsize=8)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(groups)), [g[0] for g in groups])
    ax.set_ylabel(_t("变化（bp）", "Change (bp)"))
    ax.set_title(_t(f"{r['start_date']} 至 {r['end_date']}：各部分贡献（黑线为名义变化）",
                    f"{r['start_date']} to {r['end_date']}: contributions (black line = nominal change)"))
    ax.legend(frameon=False, fontsize=8, ncol=2)
    figs.append(("各部分对 10Y、2Y 与斜率变化的贡献", _save(fig, out_dir / "attribution_bars.png")))

    dates = pd.to_datetime([row["date"] for row in path])
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for key, label, style in (("long", f"{lg['tenor']} {_t('名义', 'nominal')}", "-"), ("real", names["real"], "--"),
                              ("breakeven", names["breakeven"], ":"), ("short", f"{sh['tenor']} {_t('名义', 'nominal')}", "-"),
                              ("policy", names["policy"], "--")):
        ax.plot(dates, [row[key] for row in path], ls=style, lw=1.2, label=label)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel(_t("相对期初的累计变化（bp）", "Cumulative change from start (bp)"))
    ax.set_title(_t("逐日累计路径", "Daily cumulative path"))
    ax.legend(frameon=False, fontsize=8, ncol=3)
    figs.append(("各部分相对期初的逐日累计变化", _save(fig, out_dir / "attribution_path.png")))
    return figs


_ASSET_LABELS = {"SP500": ("标普 500", "S&P 500"), "SMALLCAP": ("小盘股", "Small caps"),
                 "TBOND10Y": ("10 年期国债", "10Y Treasury"), "BAA": ("Baa 公司债", "Baa corporate"),
                 "TBILL3M": ("国库券", "T-bills"), "REALESTATE": ("房地产", "Real estate"), "GOLD": ("黄金", "Gold")}


def _asset_figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    r = result["results"]
    nom, assets = r.get("nominal", {}), r.get("assets", [])
    if not nom:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    _style()
    label = lambda a: _t(*_ASSET_LABELS.get(a, (a, a)))  # noqa: E731
    span = f"{r['first_year']}–{r['last_year']}"
    figs: list[tuple[str, Path]] = []

    fig, ax = plt.subplots(figsize=(7, 3.8))
    for a in assets:
        ax.scatter(nom[a]["volatility"] * 100, nom[a]["geometric"] * 100, s=28)
        ax.annotate(label(a), (nom[a]["volatility"] * 100, nom[a]["geometric"] * 100), xytext=(4, 3),
                    textcoords="offset points", fontsize=8)
    ax.set_xlabel(_t("波动率（年度回报标准差，%）", "Volatility (std. of annual returns, %)"))
    ax.set_ylabel(_t("年化回报（几何平均，%）", "Annualized return (geometric, %)"))
    ax.set_title(_t(f"{span}：回报与风险（名义）", f"{span}: return and risk (nominal)"))
    figs.append(("各资产的年化回报与波动率", _save(fig, out_dir / "risk_return.png")))

    wealth = result.get("tables", {}).get("wealth_index", [])
    if wealth:
        fig, ax = plt.subplots(figsize=(7, 3.8))
        years = [w["year"] for w in wealth]
        for a in assets:
            ax.plot(years, [w[a] for w in wealth], lw=1.2, label=label(a))
        ax.set_yscale("log")
        ax.set_ylabel(_t("1 美元的累计财富（对数刻度）", "Wealth of $1 (log scale)"))
        ax.set_title(_t(f"{span}：累计财富（名义，年末）", f"{span}: cumulative wealth (nominal, year-end)"))
        ax.legend(frameon=False, fontsize=7, ncol=4)
        figs.append(("各资产 1 美元的累计财富", _save(fig, out_dir / "wealth.png")))

    corr = r.get("correlations", {})
    blocks = corr.get("periods") or [corr.get("full")]
    blocks = [b for b in blocks if b]
    if blocks:
        fig, axes = plt.subplots(1, len(blocks), figsize=(3.2 * len(blocks) + 0.6, 3.4), squeeze=False)
        for ax, b in zip(axes[0], blocks):
            m = [[b["matrix"][x][y] for y in assets] for x in assets]
            im = ax.imshow(m, vmin=-1, vmax=1, cmap="RdBu_r")
            ax.set_xticks(range(len(assets)), [label(a) for a in assets], rotation=60, fontsize=6)
            ax.set_yticks(range(len(assets)), [label(a) for a in assets], fontsize=6)
            ax.set_title(f"{b['first_year']}–{b['last_year']}", fontsize=8)
            ax.grid(False)
        fig.colorbar(im, ax=axes[0].tolist(), shrink=0.8)
        fig.suptitle(_t("年度回报的相关系数", "Correlation of annual returns"), fontsize=9)
        path = out_dir / "correlations.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        figs.append(("各时期年度回报的相关系数", path))

    rolling = result.get("tables", {}).get("rolling", [])
    if rolling:
        fig, ax = plt.subplots(figsize=(7, 3.2))
        ax.plot([x["end_year"] for x in rolling], [x["SP500"] * 100 for x in rolling], lw=1.4)
        ax.axhline(0, color="black", lw=0.8)
        w = r["rolling"]["window_years"]
        ax.set_ylabel(_t("年化回报（%）", "Annualized return (%)"))
        ax.set_title(_t(f"标普 500 的 {w} 年滚动年化回报（按截止年份）", f"S&P 500 rolling {w}-year annualized return (by end year)"))
        figs.append(("标普 500 的滚动年化回报", _save(fig, out_dir / "rolling.png")))
    return figs


_FIGURE_BUILDERS = {"rates_curve": _curve_figures, "par_bond_scenarios": _bond_figures,
                    "curve_attribution": _attribution_figures, "asset_history": _asset_figures,
                    "industry": industry_figures}


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
            detail += (f"，未取得 {cov['pending_days']} 天（数据下载时尚未到保守可用时点，"
                       "不代表已确认尚未发布）")
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


def _attribution_sections(result: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    """曲线变化的会计分解：三行恒等式、占比与端点敏感性；「分解明细」列出共同日期与背景。"""
    r = result["results"]
    lg, sh, sl, sens = r["long_end"], r["short_end"], r["slope"], r["sensitivity"]
    pct = lambda v: "—" if v is None else _fmt(v, 0) + "%"  # noqa: E731
    rng = lambda k: ("—" if sens[k].get("min") is None else  # noqa: E731
                     f"{_fmt(sens[k]['min'], 0)}%–{_fmt(sens[k]['max'], 0)}%{'' if sens[k]['stable'] else '（不稳定）'}")
    body: list[Any] = [
        f"{r['start_date']} 至 {r['end_date']}（共同观测日 {result['coverage']['common_days']} 天）。"
        "会计恒等式分解，不估计参数，不作因果推断；占比只在名义变化不小于 "
        f"{r['thresholds']['share_min_bp']:g} bp 时给出，端点前后移动 {sens['shift_days']} 个共同日期时范围超过 "
        f"{r['thresholds']['sensitivity_max_range_pp']:g} 个百分点即视为不稳定。",
        ("table", ["项目", "期初 %", "期末 %", "变化 bp", "占名义变化", "端点敏感性范围"], [
            [f"{lg['tenor']} 名义", _fmt(lg["nominal"]["start"]), _fmt(lg["nominal"]["end"]),
             _fmt(lg["nominal"]["change_bp"], 0), "", ""],
            ["　实际收益率", _fmt(lg["real"]["start"]), _fmt(lg["real"]["end"]), _fmt(lg["real"]["change_bp"], 0),
             pct(lg["shares_pct"]["real"]), rng("real")],
            ["　盈亏平衡通胀", _fmt(lg["breakeven"]["start"]), _fmt(lg["breakeven"]["end"]),
             _fmt(lg["breakeven"]["change_bp"], 0), pct(lg["shares_pct"]["breakeven"]), rng("breakeven")],
            ["　取整残差", "", "", _fmt(lg["residual_bp"], 2), "", ""],
            [f"{sh['tenor']} 名义", _fmt(sh["nominal"]["start"]), _fmt(sh["nominal"]["end"]),
             _fmt(sh["nominal"]["change_bp"], 0), "", ""],
            ["　联邦基金有效利率", _fmt(sh["policy"]["start"]), _fmt(sh["policy"]["end"]),
             _fmt(sh["policy"]["change_bp"], 0), pct(sh["shares_pct"]["policy"]), rng("policy")],
            [f"　{sh['tenor']} − 联邦基金利率", _fmt(sh["spread"]["start"]), _fmt(sh["spread"]["end"]),
             _fmt(sh["spread"]["change_bp"], 0), pct(sh["shares_pct"]["spread"]), rng("spread")],
            [f"{sl['label']}", _fmt(sl["start"]), _fmt(sl["end"]), _fmt(sl["change_bp"], 0), "", ""],
        ]),
        ("table", ["斜率变化的组成", "bp"],
         [[{"real": "实际收益率", "breakeven": "盈亏平衡通胀", "residual": "取整残差", "policy": "− 联邦基金有效利率",
            "spread": f"− ({sh['tenor']} − 联邦基金利率)"}[k], _fmt(v, 1)] for k, v in sl["contributions_bp"].items()]),
    ]
    cov, bg = result["coverage"], r.get("background", {})
    detail = [
        f"请求期间 {cov['requested_start']} 至 {cov['requested_end']}；共同观测日 {cov['common_days']} 天，"
        f"期初 {cov['start_date']}，期末 {cov['end_date']}。各部分观测天数："
        + "，".join(f"{k} {v}" for k, v in cov["observations_by_part"].items())
        + "（联邦基金利率含周末与假日，只用与其他输入的共同日期）。",
    ]
    if "cpi_yoy" in bg:
        c = bg["cpi_yoy"]
        detail.append(f"背景（不参与分解）：CPI 同比 {c['start']['month']} 为 {_fmt(c['start']['value_pct'], 1)}%，"
                      f"{c['end']['month']} 为 {_fmt(c['end']['value_pct'], 1)}%。")
    if "fed_assets" in bg:
        f = bg["fed_assets"]
        detail.append(f"背景（不参与分解）：美联储总资产 {f['start']['date']} 为 {_fmt(f['start']['value_musd'] / 1e6, 3)} 万亿美元，"
                      f"{f['end']['date']} 为 {_fmt(f['end']['value_musd'] / 1e6, 3)} 万亿美元（{_fmt(f['change_pct'], 1)}%）。")
    return body, "分解明细与背景", detail


def _asset_sections(result: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    """长期回报与风险：名义与实际统计量、风险溢价、相关系数；「口径与核对」说明期间与交叉核对。"""
    r = result["results"]
    nom, real, assets = r["nominal"], r.get("real", {}), r["assets"]
    name = {"SP500": "标普 500", "SMALLCAP": "小盘股", "TBOND10Y": "10 年期国债", "BAA": "Baa 公司债",
            "TBILL3M": "3 个月国库券", "REALESTATE": "房地产", "GOLD": "黄金"}
    pct = lambda v: _fmt(v * 100, 1)  # noqa: E731
    body: list[Any] = [
        f"{r['first_year']}–{r['last_year']} 年（{len(result['tables']['annual_returns'])} 个完整年度）。"
        "百分比为年度回报；几何平均即期末财富的年化；最大回撤按年末财富计算。只描述历史，不是预测或配置建议。",
        ("table", ["资产", "几何平均 %", "算术平均 %", "波动率 %", "最差年份", "亏损年数", "最大回撤 %"],
         [[name.get(a, a), pct(nom[a]["geometric"]), pct(nom[a]["arithmetic"]), pct(nom[a]["volatility"]),
           f"{pct(nom[a]['worst'])}（{nom[a]['worst_year']}）", str(nom[a]["negative_years"]), pct(nom[a]["max_drawdown"])]
          for a in assets]),
    ]
    if real:
        first = next(iter(real.values()))
        infl = r.get("inflation", {})
        body.append(f"扣除通胀（{first['first_year']}–{first['last_year']} 年，CPI 12 月对 12 月，年均 "
                    f"{pct(infl.get('mean', 0))}%，最高 {pct(infl.get('max', 0))}%（{infl.get('max_year')}））：")
        body.append(("table", ["资产", "实际几何平均 %", "实际算术平均 %", "实际波动率 %"],
                     [[name.get(a, a), pct(real[a]["geometric"]), pct(real[a]["arithmetic"]), pct(real[a]["volatility"])]
                      for a in assets]))
    if r.get("equity_risk_premium"):
        body.append("股票相对无风险资产的历史超额回报（几何平均之差）：" + "，".join(
            f"相对{name[k]} {_fmt(v * 100, 1)} 个百分点" for k, v in r["equity_risk_premium"].items()) + "。")
    corr = r.get("correlations", {})
    rows = [[f"{b['first_year']}–{b['last_year']}", *(_fmt(b["matrix"]["SP500"][x], 2) for x in ("TBOND10Y", "BAA", "GOLD"))]
            for b in [corr.get("full"), *corr.get("periods", [])] if b and "SP500" in b["matrix"]]
    if rows:
        body.append(("table", ["期间", "股票与 10 年期国债", "股票与 Baa 公司债", "股票与黄金"], rows))
    sens = r.get("period_sensitivity", {}).get("stock_bond_correlation", [])
    detail = []
    if sens:
        detail.append(f"时期边界前后移动 {r['period_sensitivity']['shift_years']} 年时，股票与 10 年期国债的相关系数范围："
                      + "；".join(f"{x['period'][0]}–{x['period'][1]} {_fmt(x['min'], 2)} 至 {_fmt(x['max'], 2)}"
                                  f"（{'符号不变' if x['sign_stable'] else '符号改变'}）" for x in sens) + "。")
    me = r.get("monthly_equity") or {}
    if me:
        detail.append(f"月度股票（French CRSP 全市场总收益，{me['months']} 个月）：最大回撤 {pct(me['max_drawdown'])}%"
                      f"（{me['peak']} 至 {me['trough']}），最差单月 {pct(me['worst_month'])}%（{me['worst_month_at']}），"
                      f"年化波动率 {pct(me['annualized_volatility'])}%。")
    if r.get("rolling"):
        ro = r["rolling"]
        detail.append(f"标普 500 的 {ro['window_years']} 年滚动年化回报（{ro['windows']} 个窗口）：最低 {pct(ro['min'])}%"
                      f"（截至 {ro['min_end_year']}），最高 {pct(ro['max'])}%（截至 {ro['max_end_year']}）。")
    return body, "口径与补充统计", detail


_BRANCH_SECTIONS = {"rates_curve": _curve_sections, "par_bond_scenarios": _bond_sections,
                    "curve_attribution": _attribution_sections, "asset_history": _asset_sections,
                    "industry": industry_sections, "company": company_sections}


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
                 "closed_form_checks": "封闭解与重新定价核对", "identity_check": "恒等式核对",
                 "cross_check_equity": "股票跨来源核对", "cross_check_tbill": "国库券跨来源核对",
                 "cross_check_real": "实际回报方向核对", "monthly_drawdown": "月度回撤核对"}.get(name, name)
        line = f"**{label}：** {STATUS_LABEL.get(v.get('status'), v.get('status'))}"
        if name == "cross_check" and v.get("matched"):
            line += (f"；对照 {v['against']}，共同日期 {v['matched']} 天，最大差 {_fmt(v['max_abs_diff'], 4)}"
                     f"（容差 {v['tolerance']}）。{v['note']}")
        elif name == "closed_form_checks":
            line += (f"；{v['checked']} 项核对，未通过 {len(v['failures'])} 项（平价价格 = 面值；"
                     "解析修正久期 = 平价债券封闭解；解析久期、凸性 ≈ 有限差分完整重新定价）")
        elif name == "identity_check":
            line += (f"；{v['checked']} 个共同日期，名义 − 实际 − 盈亏平衡的最大残差 {_fmt(v['max_abs_level_residual_bp'], 2)} bp"
                     f"（容差 {v['tolerance_bp']} bp）")
        elif name == "cross_check_equity":
            line += f"；对照 {v['against']}，{v['years']} 年相关系数 {_fmt(v['correlation'], 3)}（阈值 {v['threshold']}）。{v['note']}"
        elif name == "cross_check_tbill":
            line += f"；对照 {v['against']} 年均值，{v['years']} 年最大差 {_fmt(v['max_abs_diff_pp'], 2)} 个百分点（容差 {v['tolerance_pp']}）"
        elif name == "cross_check_real":
            line += (f"；对照 {v['against']}，{v['years']} 年中方向一致的比例 {_fmt(v['same_direction_share'] * 100, 0)}%"
                     f"（阈值 {_fmt(v['threshold'] * 100, 0)}%）。{v['note']}")
        elif name == "monthly_drawdown":
            line += f"；月度 {_fmt(v['monthly'] * 100, 1)}%，年度 {_fmt(v['annual'] * 100, 1)}%。{v['note']}"
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
