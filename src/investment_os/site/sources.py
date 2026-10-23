"""数据资源目录：免费资源的统一索引，按类别与研究方向列出每个来源的取得方式、许可、核验状态与下一步。

内容全部来自 config/sources.yaml（来源、类别、能力缺口）与 config/datasets.yaml；
状态由核验记录得出，不在页面上手写。候选来源的索引字段是初步判断，页面上标明未经核验。
"""

from __future__ import annotations

from typing import Any

from ..contracts import VerificationStatus
from ..registry import Registry
from .common import VERIFY_LABEL, chip, e, shell

USE_SHORT = {"descriptive": "历史描述", "point_in_time": "时点研究", "scenario": "情景模拟"}

ACCESS_LABEL = {"api": "接口", "file": "文件下载", "tool": "第三方工具", "web": "网页资料", "manual": "人工导入", "": "未核验"}
SIGNUP_LABEL = {"none": "无需注册", "free_key": "免费注册或 key", "unknown": "注册要求未核验"}
REDIST_LABEL = {"allowed": "可公开再分发", "per_series": "再分发按序列确认", "restricted": "不可公开再分发",
                "unknown": "再分发未核验"}
REDIST_CHIP = {"allowed": "pass", "per_series": "partial", "restricted": "fail", "unknown": "skipped"}
STATUS_CHIP = {"candidate": "skipped", "docs_verified": "partial", "access_verified": "pass", "use_verified": "pass"}


def _directions(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """方向 id → 名称与所属分支。"""
    return {d["id"]: {"name": d["name"], "branch": b["id"], "branch_name": b["name"]}
            for b in content.get("branches", []) for d in b.get("directions", [])}


def catalog(registry: Registry, datasets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """每个来源一行：整体状态、已登记数据集及其状态、索引字段。也写入 summary.json。"""
    rows = []
    for src in registry.sources.values():
        ds = [{"id": d.id, "status": src.status_for(d.id).value,
               "uses": [u.value for u in src.verified_uses(d.id)],
               "has_data": (datasets.get(d.id) or {}).get("version_id") is not None}
              for d in registry.datasets.values() if d.source_id == src.id]
        rows.append({
            "id": src.id, "name": src.display_name, "publisher": src.publisher, "url": src.url, "category": src.category,
            "status": src.best_status().value, "datasets": ds, "directions": list(src.directions),
            "access": src.access, "signup": src.signup, "redistribution": src.redistribution,
            "license": src.license, "registration": src.registration, "coverage": src.coverage,
            "offers": list(src.offers), "notes": src.notes, "next_step": src.next_step,
            "alternatives": list(src.alternatives),
        })
    return rows


def _status_line(row: dict[str, Any]) -> str:
    head = chip(STATUS_CHIP[row["status"]], VERIFY_LABEL[row["status"]])
    if row["status"] != "candidate" and not row["datasets"]:
        head += ' <span class="small muted">来源说明，未登记数据集</span>'
    ds = "".join(
        f"<li><code>{e(d['id'])}</code> {e(VERIFY_LABEL[d['status']])}"
        f"{'；用途已验证：' + e('、'.join(USE_SHORT[u] for u in d['uses'])) if d['uses'] else ''}"
        f"{'' if d['has_data'] else '<span class=muted>（本次构建未取得）</span>'}</li>" for d in row["datasets"])
    return head + (f'<ul class="src-datasets small">{ds}</ul>' if ds else "")


def _card(row: dict[str, Any], dirs: dict[str, dict[str, Any]], names: dict[str, str]) -> str:
    candidate = row["status"] == "candidate" and not row["datasets"]
    link = f' · <a href="{e(row["url"])}" rel="noopener">资料入口</a>' if row["url"] else ""
    access = f"{ACCESS_LABEL.get(row['access'], row['access'])} · {SIGNUP_LABEL[row['signup']]}"
    if candidate:
        access += "（初步判断）"
    license_ = (f'<details class="basis"><summary>许可与注册说明</summary><p class="small">{e(row["license"])}</p>'
                f'<p class="small">{e(row["registration"])}</p></details>') if row["license"] else ""
    offers = "".join(f"<li>{e(x)}</li>" for x in row["offers"])
    direction_links = " ".join(
        f'<a class="chip chip-tag" href="map.html#{e(dirs[d]["branch"])}" title="{e(dirs[d]["branch_name"])}">'
        f'{e(dirs[d]["name"])}</a>' if d in dirs else chip("tag", d) for d in row["directions"])
    alts = "、".join(f'<a href="#src-{e(a)}">{e(names.get(a, a))}</a>' for a in row["alternatives"])
    alts = f"<div><dt>替代路径</dt><dd>{alts}</dd></div>" if alts else ""
    publisher = f'<div class="small muted">{e(row["publisher"])}</div>' if row["name"] != row["publisher"] else ""
    return f"""<article class="src-card" id="src-{e(row['id'])}">
<header><h4>{e(row['name'])}</h4>{publisher}<div class="small muted"><code>{e(row['id'])}</code>{link}</div></header>
<div class="src-status">{_status_line(row)}</div>
<dl>
<div><dt>取得</dt><dd>{e(access)}</dd></div>
<div><dt>许可</dt><dd>{chip(REDIST_CHIP[row['redistribution']], REDIST_LABEL[row['redistribution']])}{license_}</dd></div>
{f"<div><dt>覆盖</dt><dd>{e(row['coverage'])}</dd></div>" if row['coverage'] else ""}
{f"<div><dt>可提供</dt><dd><ul>{offers}</ul></dd></div>" if offers else ""}
{f"<div><dt>研究方向</dt><dd>{direction_links}</dd></div>" if direction_links else ""}
{alts}
{f"<div><dt>依据与限制</dt><dd>{e(row['notes'])}</dd></div>" if row['notes'] else ""}
{f"<div><dt>下一步</dt><dd>{e(row['next_step'])}</dd></div>" if row['next_step'] else ""}
</dl></article>"""


def _counts(rows: list[dict[str, Any]]) -> str:
    order = [s.value for s in VerificationStatus]
    counts = {s: sum(r["status"] == s for r in rows) for s in order}
    items = "".join(f"<li>{chip(STATUS_CHIP[s], VERIFY_LABEL[s])} <strong>{counts[s]}</strong></li>"
                    for s in reversed(order))
    return f'<ul class="src-counts">{items}</ul>'


def _by_direction(content: dict[str, Any], rows: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> str:
    out = []
    for b in content.get("branches", []):
        lines = []
        for d in b.get("directions", []):
            srcs = [r for r in rows if d["id"] in r["directions"]]
            srcs.sort(key=lambda r: [s.value for s in VerificationStatus].index(r["status"]), reverse=True)
            links = " ".join(f'<a href="#src-{e(r["id"])}" class="chip chip-{STATUS_CHIP[r["status"]]}" '
                             f'title="{e(VERIFY_LABEL[r["status"]])}">{e(r["name"])}</a>'
                             for r in srcs) or '<span class="muted">尚无候选来源</span>'
            gap = [g["name"] for g in gaps if d["id"] in (g.get("directions") or [])]
            gap_text = f'<div class="small warn">能力缺口：{e("、".join(gap))}</div>' if gap else ""
            lines.append(f"<tr><td>{e(d['name'])}</td><td>{links}{gap_text}</td></tr>")
        out.append(f"<tr class='branch'><th colspan='2'>{e(b['name'])}</th></tr>" + "".join(lines))
    return ('<div class="scroll"><table class="src-index"><thead><tr><th>研究方向</th><th>来源（按核验进度排列）</th></tr>'
            f'</thead><tbody>{"".join(out)}</tbody></table></div>')


def sources_page(content: dict[str, Any], registry: Registry, datasets: dict[str, dict[str, Any]],
                 build: dict[str, Any]) -> str:
    rows = catalog(registry, datasets)
    dirs = _directions(content)
    names = {r["id"]: r["name"] for r in rows}
    sections = []
    for cat_id, cat_name in registry.source_categories.items():
        cards = "".join(_card(r, dirs, names) for r in rows if r["category"] == cat_id)
        if cards:
            sections.append(f'<h3 class="sub" id="cat-{e(cat_id)}">{e(cat_name)}</h3><div class="src-grid">{cards}</div>')
    uncategorized = "".join(_card(r, dirs, names) for r in rows if r["category"] not in registry.source_categories)
    if uncategorized:
        sections.append(f'<h3 class="sub">未分类</h3><div class="src-grid">{uncategorized}</div>')
    toc = " · ".join(f'<a href="#cat-{e(c)}">{e(n)}</a>' for c, n in registry.source_categories.items()
                     if any(r["category"] == c for r in rows))
    gaps = "".join(f"<li><strong>{e(g['name'])}</strong>：{e(g['detail'])}</li>" for g in registry.gaps)
    body = f"""
<header class="top"><div class="wrap"><h1>数据资源目录</h1>
<p class="tagline">免费资源的统一索引：从哪里取得、核验到哪一步、能服务哪些研究、下一步做什么。</p></div></header>
<main class="wrap">
<section><h2>核验进度</h2>
{_counts(rows)}
<p class="muted small">核验分四级：候选来源（只有资料入口）→ 说明已核验 → 接入已验证（样本取得成功）→ 用途已验证（在明确范围内通过研究要求）。
状态按「来源 × 数据集 × 用途」记录，卡片上显示来源达到的最高一级，并逐个列出已登记的数据集。
一个样本取得成功不代表整个来源可用；公开取得也不等于可以自由再分发。
<strong>候选来源的取得方式、许可等字段是资料入口上的初步判断，未经核验。</strong></p>
<p class="small">本页由 <code>config/sources.yaml</code> 生成；新增候选来源只需在其中登记，开始接入（登记数据集）前须补齐架构 §5.1 的字段。</p></section>
<section><h2>按研究方向</h2>
<p class="muted small">每个研究方向可以用哪些来源，以及已知的能力缺口。点击来源跳到下方卡片。</p>
{_by_direction(content, rows, registry.gaps)}</section>
<section><h2>按类别</h2><p class="small">{toc}</p>{"".join(sections)}</section>
<section><h2>能力缺口</h2>
<p class="muted small">在取得并验证适用的免费数据之前，不承诺以下能力的完整历史研究；允许明确标记的理论分析与有限样本研究。</p>
<ul>{gaps}</ul></section>
</main>"""
    return shell("数据资源目录 · Investment Research OS", body, build, active="sources.html",
                 description="免费数据资源的索引：取得方式、许可、核验状态与可服务的研究方向")
