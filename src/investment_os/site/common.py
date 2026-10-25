"""网站各页面共用的格式化、组件与页面外壳。"""

from __future__ import annotations

import html
import os
import subprocess
from pathlib import Path
from typing import Any

from .i18n import HTML_LANG, L, Labels, is_en, lang

STATUS_LABEL = Labels({"success": ("成功", "Success"), "partial": ("部分受限", "Partly limited"),
                       "failed": ("失败", "Failed")})
VERIFY_LABEL = Labels({"candidate": ("候选", "Candidate"), "docs_verified": ("说明已核验", "Docs verified"),
                       "access_verified": ("接入已验证", "Access verified"), "use_verified": ("用途已验证", "Use verified")})
USE_LABEL = Labels({
    "descriptive": ("历史描述（使用最新修订数据）", "Historical description (latest revised data)"),
    "point_in_time": ("时点研究（只用当时可获知的数据）", "Point-in-time study (only data knowable at the time)"),
    "scenario": ("情景模拟（假设输入，使用最新修订数据）", "Scenario simulation (assumed inputs, latest revised data)")})
RESULT_TYPE_LABEL = Labels({"descriptive": ("描述与比较", "Description & comparison"),
                            "explanatory": ("解释与归因", "Explanation & attribution"),
                            "forecast": ("预测", "Forecast"), "simulation": ("情景与策略模拟", "Scenario & strategy simulation")})
# 风险来源分类（架构 §4），研究方向的标签
RISK_LABEL = Labels({"equity": ("股票", "Equity"), "rates": ("利率", "Rates"), "credit": ("信用", "Credit"),
                     "inflation": ("通胀", "Inflation"), "fx": ("汇率", "FX"), "commodity": ("商品", "Commodities"),
                     "liquidity": ("流动性", "Liquidity"), "instrument": ("工具结构", "Instrument structure")})
CHECK_LABEL = Labels({"pass": ("通过", "Passed"), "fail": ("未通过", "Failed"), "skipped": ("跳过", "Skipped")})
FETCH_LABEL = Labels({"created": ("新版本", "New version"), "unchanged": ("无变化", "Unchanged"), "failed": ("失败", "Failed")})
CHECK_NOTES = Labels({
    "closed_form_checks": ("平价债券价格 = 面值；解析修正久期 = 封闭解；解析久期与凸性 ≈ 有限差分完整重新定价。",
                           "Par bond price = face value; analytic modified duration = closed form; analytic duration "
                           "and convexity ≈ finite-difference full repricing."),
    "cross_check_equity": ("Damodaran 标普 500 与 French CRSP 全市场的年度回报相关系数；指数不同，只核对高度一致。",
                           "Correlation of Damodaran S&P 500 and French CRSP total-market annual returns; different "
                           "indexes, so this only checks they are highly consistent."),
    "cross_check_tbill": ("Damodaran 国库券回报与 FRED DTB3 年均利率逐年比较。",
                          "Damodaran T-bill returns compared year by year with FRED DTB3 annual average rates."),
    "cross_check_real": ("Damodaran 标普 500 实际回报与 Shiller 实际总收益的方向是否一致；口径不同，只核对方向。",
                         "Whether Damodaran S&P 500 real returns move in the same direction as Shiller's real total "
                         "return; definitions differ, so only direction is checked."),
    "monthly_drawdown": ("月度数据的最大回撤应不浅于年度数据；年度数据会低估年内跌幅。",
                         "The monthly maximum drawdown should be at least as deep as the annual one; annual data "
                         "understate intra-year declines."),
    "identity_check": ("每个共同日期核对 10Y 名义 − 实际收益率 − 盈亏平衡通胀，残差只应是取整误差。",
                       "On every common date, 10Y nominal − real yield − breakeven inflation is checked; the residual "
                       "should only be rounding."),
    "cross_check": ("Treasury 曲线 10Y 与 FRED DGS10 比对。两者同源（H.15），一致只说明接入与解析正确，不是独立验证。",
                    "Treasury curve 10Y compared with FRED DGS10. Both come from the same upstream (H.15), so "
                    "agreement only shows the download and parsing are correct; it is not independent validation."),
    "raw_spot_check": ("等距抽取标准化观测，用独立解析路径与原始下载文件逐点比对。",
                       "Evenly spaced standardized observations are compared point by point with the raw download, "
                       "using an independent parsing path."),
    "reproduce": ("发布前用该次运行固定的研究定义与数据版本重新计算，结果校验值一致；不代表其他环境或其他数据版本。",
                  "Before publishing, the run is recomputed from its pinned study definition and data versions and "
                  "the result hash matches; this says nothing about other environments or data versions."),
})
# Chart.js 随站点托管（site/assets/vendor，来源与校验值见其中 README），不依赖外部 CDN
CHART_JS = "assets/vendor/chart.umd.min.js"

NAV = (("index.html", ("研究总览", "Overview")), ("map.html", ("研究能力地图", "Capability map")),
       ("sources.html", ("数据资源目录", "Data sources")), ("methods.html", ("数据、方法与状态", "Data, methods & status")))


def e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def num(v: Any, digits: int = 2, signed: bool = False) -> str:
    if v is None:
        return "—"
    text = f"{v:+,.{digits}f}" if signed else f"{v:,.{digits}f}"
    return text.replace("-", "−")


def chip(status: str | None, label: str, title: str | None = None) -> str:
    tip = f' title="{e(title)}"' if title else ""
    return f'<span class="chip chip-{e(status)}"{tip}>{e(label)}</span>'


def stat(label: str, value: str, note: str = "") -> str:
    return (f'<div class="stat"><div class="stat-label">{e(label)}</div>'
            f'<div class="stat-value">{value}</div><div class="stat-note">{e(note)}</div></div>')


def repo_url(root: Path) -> str | None:
    if os.environ.get("GITHUB_REPOSITORY"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        return f"{server}/{os.environ['GITHUB_REPOSITORY']}"
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root, capture_output=True,
                             text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    return url.removesuffix(".git") if url.startswith("https://") else None


def span_text(spans: list[list[str]]) -> str:
    """日期区间列表：2026-10-23、2026-10-25 至 2026-10-27。"""
    return L("、", ", ").join(a if a == b else f"{a}{L(' 至 ', ' to ')}{b}" for a, b in spans)


def root(depth: int) -> str:
    """从深度为 depth 的页面到站点根目录（assets/、runs/ 所在处）的相对前缀；英文页面多一层 en/。"""
    return "../" * (depth + (1 if is_en() else 0))


def use_scope_chip(use_scope: dict[str, Any] | None) -> str:
    """用途核验相对研究期间的位置：在范围内 / 部分在范围内（列出范围外日期）/ 范围外。"""
    if not use_scope:
        return ""
    status = use_scope.get("status")
    any_ = L("不限", "open")
    ranges = L("；", "; ").join(f"{a or any_}{L(' 至 ', ' to ')}{b or any_}" for a, b in use_scope.get("verified_ranges", []))
    tip = L("核验覆盖的观测日期：", "Observation dates covered by verification: ") + ranges
    if status == "in_scope":
        return chip("pass", L("用途已验证 · 在核验范围内", "Use verified · within scope"), tip)
    if status == "partial":
        return (chip("partial", L("用途已验证 · 部分在范围内", "Use verified · partly within scope"), tip)
                + f'<span class="small warn"> {L("核验范围外：", "Outside verified scope: ")}'
                f'{e(span_text(use_scope.get("uncovered", [])))}</span>')
    if status == "out_of_scope":
        return chip("fail", L("研究期间在用途核验范围外", "Study period outside use-verification scope"), tip)
    return ""


def verification_chip(ver: dict[str, Any] | None) -> str:
    if not ver:
        return chip("skipped", L("固定输入重算 · 未执行", "Pinned-input recomputation · not run"), CHECK_NOTES["reproduce"])
    partial = ver.get("scope") == "partial"
    label = (L("固定输入重算 · ", "Pinned-input recomputation · ")
             + (L("一致", "matches") if ver["reproduced"] else L("不一致", "differs"))
             + (L("（部分）", " (partial)") if partial else ""))
    note = CHECK_NOTES["reproduce"]
    if partial:
        note += L(f" 部分重算：未重算 {'、'.join(ver.get('excluded_roles', []))}。",
                  f" Partial recomputation: not recomputed: {', '.join(ver.get('excluded_roles', []))}.")
    return chip("pass" if ver["reproduced"] else "fail", label, note)


def check_chips(result: dict[str, Any], ver: dict[str, Any] | None) -> str:
    out = []
    for key, label in (("closed_form_checks", L("封闭解与重新定价核对", "Closed-form and repricing checks")),
                       ("identity_check", L("恒等式核对", "Identity check")),
                       ("cross_check_equity", L("股票跨来源核对", "Equity cross-source check")),
                       ("cross_check_tbill", L("国库券跨来源核对", "T-bill cross-source check")),
                       ("cross_check_real", L("实际回报方向核对", "Real-return direction check")),
                       ("monthly_drawdown", L("月度回撤核对", "Monthly drawdown check")),
                       ("cross_check", L("同源一致性检查", "Same-source consistency check")),
                       ("raw_spot_check", L("原始快照抽查", "Raw snapshot spot check"))):
        v = result.get("validation", {}).get(key)
        if v:
            out.append(chip(v.get("status"), f"{label} · {CHECK_LABEL.get(v.get('status'), v.get('status'))}",
                            CHECK_NOTES[key]))
    out.append(verification_chip(ver))
    return "".join(out)


def shell(title: str, body: str, build: dict[str, Any], *, page: str, active: str = "",
          charts: bool = False, description: str = "") -> str:
    """所有页面共用的外壳：导航、语言切换、过期提示、页脚状态。

    page 是页面在中文站点中的路径（如 index.html、studies/<id>/），英文页面位于 en/<page>。
    系统状态放在页脚，视觉权重低；只有页面过期（自动更新停滞）时才在顶部显示提示。
    """
    depth = page.count("/")
    up, tree = root(depth), "../" * depth
    # 资源地址带内容校验值：样式或脚本改动后地址随之变化，访客不会用到浏览器缓存的旧文件
    v = build.get("asset_version", "")
    q = f"?v={v}" if v else ""
    scripts = f'<script defer src="{up}assets/charts.js{q}"></script>'
    if charts:
        scripts = f'<script defer src="{up}{CHART_JS}{q}"></script>\n' + scripts
    current = ' aria-current="page"'
    nav = "".join(f'<a href="{tree}{href}"{current if href == active else ""}>{e(L(*label))}</a>'
                  for href, label in NAV)
    zh_href, en_href = "../" * (depth + 1) + page, tree + "en/" + page
    if is_en():
        switch = (f'<a class="lang-switch" href="{e(zh_href)}" hreflang="zh-CN" lang="zh-CN" data-lang="zh">中文</a>')
        alternates = (f'<link rel="alternate" hreflang="zh-CN" href="{e(zh_href)}">'
                      f'<link rel="alternate" hreflang="en" href="{e(page)}">')
    else:
        switch = f'<a class="lang-switch" href="{e(en_href)}" hreflang="en" lang="en" data-lang="en">English</a>'
        alternates = (f'<link rel="alternate" hreflang="zh-CN" href="{e(page)}">'
                      f'<link rel="alternate" hreflang="en" href="{e(en_href)}">')
    # 记住读者选择的语言：在中文页面上选过英文的读者，下次打开中文地址时转到对应的英文页面
    remember = ("" if is_en() else
                f'<script>try{{if(localStorage.getItem("lang")==="en"&&!/[?&]lang=zh/.test(location.search))'
                f'location.replace("{en_href}"+location.hash)}}catch(e){{}}</script>')
    repo = build.get("repo_url")
    wf = f"{repo}/actions/workflows/pages.yml" if repo else None
    badge = (f' <a href="{e(wf)}" title="{L("最近一次自动更新的实时状态", "Live status of the latest automatic update")}">'
             f'<img class="badge" src="{e(wf)}/badge.svg" alt="{L("自动更新工作流状态", "Automatic update workflow status")}"></a>'
             ) if wf else ""
    commit = (build.get("commit") or "")[:7]
    built = e(build['built_at'][:16].replace('T', ' '))
    stale = L(f"""本页已经 <span data-weekdays>?</span> 个工作日没有更新，
最近的自动更新可能失败；下列结果停留在 {e(build['built_at'][:10])} 的发布。
{f'<a href="{e(wf)}">查看自动更新记录</a>' if wf else ''}""",
              f"""This page has not been updated for <span data-weekdays>?</span> working days; the latest
automatic update may have failed. The results below are from the {e(build['built_at'][:10])} release.
{f'<a href="{e(wf)}">See the update log</a>' if wf else ''}""")
    footer = L(f"""<p>页面发布于 {built} UTC（<span data-age>—</span>）{f' · 代码 <code>{e(commit)}</code>' if commit else ''}
{badge} · <a href="{tree}methods.html#status">系统状态</a>{f' · <a href="{e(repo)}">GitHub</a>' if repo else ''}</p>
<p>数据来源：U.S. Department of the Treasury、Federal Reserve Bank of St. Louis（FRED），使用条款以其官网为准。
本网站是个人研究记录，只描述数据能够证明的内容，不含预测、交易或投资建议。</p>""",
               f"""<p>Published {built} UTC (<span data-age>—</span>){f' · code <code>{e(commit)}</code>' if commit else ''}
{badge} · <a href="{tree}methods.html#status">System status</a>{f' · <a href="{e(repo)}">GitHub</a>' if repo else ''}</p>
<p>Data sources: U.S. Department of the Treasury and the Federal Reserve Bank of St. Louis (FRED); their terms of use apply.
This site is a personal research record. It describes only what the data can show and contains no forecasts,
trading or investment advice.</p>""")
    return f"""<!doctype html>
<html lang="{HTML_LANG[lang()]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description or build.get('tagline', ''))}">
{alternates}
{remember}
<link rel="stylesheet" href="{up}assets/style.css{q}">
{scripts}
</head>
<body data-built-at="{e(build['built_at'])}">
<nav class="topnav"><div class="wrap"><a class="brand" href="{tree}index.html">Investment Research OS</a>
<div class="navlinks">{nav}</div>{switch}</div></nav>
<div class="wrap"><div class="stale" role="status">{stale}</div></div>
{body}
<footer class="bottom"><div class="wrap">
{footer}
</div></footer>
</body></html>
"""
