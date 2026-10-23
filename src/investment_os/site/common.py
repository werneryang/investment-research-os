"""网站各页面共用的格式化、组件与页面外壳。"""

from __future__ import annotations

import html
import os
import subprocess
from pathlib import Path
from typing import Any

STATUS_LABEL = {"success": "成功", "partial": "部分受限", "failed": "失败"}
VERIFY_LABEL = {"candidate": "候选", "docs_verified": "说明已核验",
                "access_verified": "接入已验证", "use_verified": "用途已验证"}
USE_LABEL = {"descriptive": "历史描述（使用最新修订数据）", "point_in_time": "时点研究（只用当时可获知的数据）"}
RESULT_TYPE_LABEL = {"descriptive": "描述与比较", "explanatory": "解释与归因",
                     "forecast": "预测", "simulation": "情景与策略模拟"}
CHECK_LABEL = {"pass": "通过", "fail": "未通过", "skipped": "跳过"}
FETCH_LABEL = {"created": "新版本", "unchanged": "无变化", "failed": "失败"}
CHECK_NOTES = {
    "cross_check": "Treasury 曲线 10Y 与 FRED DGS10 比对。两者同源（H.15），一致只说明接入与解析正确，不是独立验证。",
    "raw_spot_check": "等距抽取标准化观测，用独立解析路径与原始下载文件逐点比对。",
    "reproduce": "发布前用该次运行固定的研究定义与数据版本重新计算，结果校验值一致；不代表其他环境或其他数据版本。",
}
# Chart.js 随站点托管（site/assets/vendor，来源与校验值见其中 README），不依赖外部 CDN
CHART_JS = "assets/vendor/chart.umd.min.js"

NAV = (("index.html", "研究总览"), ("map.html", "研究能力地图"), ("methods.html", "数据、方法与状态"))


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


def _span_text(spans: list[list[str]]) -> str:
    return "、".join(a if a == b else f"{a} 至 {b}" for a, b in spans)


def use_scope_chip(use_scope: dict[str, Any] | None) -> str:
    """用途核验相对研究期间的位置：在范围内 / 部分在范围内（列出范围外日期）/ 范围外。"""
    if not use_scope:
        return ""
    status = use_scope.get("status")
    ranges = "；".join(f"{a or '不限'} 至 {b or '不限'}" for a, b in use_scope.get("verified_ranges", []))
    if status == "in_scope":
        return chip("pass", "用途已验证 · 在核验范围内", f"核验覆盖的观测日期：{ranges}")
    if status == "partial":
        return (chip("partial", "用途已验证 · 部分在范围内", f"核验覆盖的观测日期：{ranges}")
                + f'<span class="small warn"> 核验范围外：{e(_span_text(use_scope.get("uncovered", [])))}</span>')
    if status == "out_of_scope":
        return chip("fail", "研究期间在用途核验范围外", f"核验覆盖的观测日期：{ranges}")
    return ""


def verification_chip(ver: dict[str, Any] | None) -> str:
    if not ver:
        return chip("skipped", "固定输入重算 · 未执行", CHECK_NOTES["reproduce"])
    partial = ver.get("scope") == "partial"
    label = f"固定输入重算 · {'一致' if ver['reproduced'] else '不一致'}{'（部分）' if partial else ''}"
    note = CHECK_NOTES["reproduce"]
    if partial:
        note += f" 部分重算：未重算 {'、'.join(ver.get('excluded_roles', []))}。"
    return chip("pass" if ver["reproduced"] else "fail", label, note)


def check_chips(result: dict[str, Any], ver: dict[str, Any] | None) -> str:
    out = []
    for key, label in (("cross_check", "同源一致性检查"), ("raw_spot_check", "原始快照抽查")):
        v = result.get("validation", {}).get(key)
        if v:
            out.append(chip(v.get("status"), f"{label} · {CHECK_LABEL.get(v.get('status'), v.get('status'))}",
                            CHECK_NOTES[key]))
    out.append(verification_chip(ver))
    return "".join(out)


def shell(title: str, body: str, build: dict[str, Any], *, depth: int = 0, active: str = "",
          charts: bool = False, description: str = "") -> str:
    """所有页面共用的外壳：导航、过期提示、页脚状态。

    系统状态放在页脚，视觉权重低；只有页面过期（自动更新停滞）时才在顶部显示提示。
    """
    up = "../" * depth
    # 资源地址带内容校验值：样式或脚本改动后地址随之变化，访客不会用到浏览器缓存的旧文件
    v = build.get("asset_version", "")
    q = f"?v={v}" if v else ""
    scripts = f'<script defer src="{up}assets/charts.js{q}"></script>'
    if charts:
        scripts = f'<script defer src="{up}{CHART_JS}{q}"></script>\n' + scripts
    current = ' aria-current="page"'
    nav = "".join(f'<a href="{up}{href}"{current if href == active else ""}>{e(label)}</a>'
                  for href, label in NAV)
    repo = build.get("repo_url")
    wf = f"{repo}/actions/workflows/pages.yml" if repo else None
    badge = (f' <a href="{e(wf)}" title="最近一次自动更新的实时状态"><img class="badge" src="{e(wf)}/badge.svg" '
             f'alt="自动更新工作流状态"></a>') if wf else ""
    commit = (build.get("commit") or "")[:7]
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description or build.get('tagline', ''))}">
<link rel="stylesheet" href="{up}assets/style.css{q}">
{scripts}
</head>
<body data-built-at="{e(build['built_at'])}">
<nav class="topnav"><div class="wrap"><a class="brand" href="{up}index.html">Investment Research OS</a>
<div class="navlinks">{nav}</div></div></nav>
<div class="wrap"><div class="stale" role="status">本页已经 <span data-weekdays>?</span> 个工作日没有更新，
最近的自动更新可能失败；下列结果停留在 {e(build['built_at'][:10])} 的发布。
{f'<a href="{e(wf)}">查看自动更新记录</a>' if wf else ''}</div></div>
{body}
<footer class="bottom"><div class="wrap">
<p>页面发布于 {e(build['built_at'][:16].replace('T', ' '))} UTC（<span data-age>—</span>）{f' · 代码 <code>{e(commit)}</code>' if commit else ''}
{badge} · <a href="{up}methods.html#status">系统状态</a>{f' · <a href="{e(repo)}">GitHub</a>' if repo else ''}</p>
<p>数据来源：U.S. Department of the Treasury、Federal Reserve Bank of St. Louis（FRED），使用条款以其官网为准。
本网站是个人研究记录，只描述数据能够证明的内容，不含预测、交易或投资建议。</p>
</div></footer>
</body></html>
"""
