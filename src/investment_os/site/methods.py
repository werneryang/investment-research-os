"""数据、方法与系统状态：来源与核验、时间规则、日历、可靠性机制、复现方法与运行状态。"""

from __future__ import annotations

from typing import Any

from ..registry import Registry
from .common import FETCH_LABEL, STATUS_LABEL, VERIFY_LABEL, chip, e, shell


def _datasets_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for d in rows:
        counts = d["status_counts"]
        quality = " / ".join(f"{k} {v}" for k, v in counts.items()) if counts else "—"
        uses = f'<div class="small muted">用途已验证：{e("、".join(d["verified_uses"]))}</div>' if d["verified_uses"] else ""
        body.append(
            f"<tr><td><strong>{e(d['dataset_id'])}</strong><div class='small muted'>{e(d['description'])}</div></td>"
            f"<td>{e(d['source'])}</td><td>{e(d['frequency'])}</td>"
            f"<td>{'供应方历史版本' if d['vintages'] == 'supplier' else '仅当前修订'}"
            f"<div class='small muted'>{e(d['availability'])}</div></td>"
            f"<td>{e(VERIFY_LABEL.get(d['status'], d['status']))}{uses}</td>"
            f"<td>{e(d['rows']) if d['rows'] is not None else '—'}<div class='small muted'>{e(quality)}</div></td>"
            f"<td>{'是' if d['archive_data'] else '否'}</td></tr>")
    return ('<div class="scroll"><table><thead><tr><th>数据集</th><th>来源</th><th>频率</th><th>历史版本与可用时间</th>'
            '<th>核验状态</th><th>行数 / 质量</th><th>数据存档</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _calendars(registry: Registry) -> str:
    rows = "".join(
        f"<tr><td><code>{e(c.id)}</code><div class='small muted'>{e(c.description)}</div></td>"
        f"<td>{e(c.verified_from.date() if c.verified_from is not None else '—')} 至 "
        f"{e(c.verified_through.date() if c.verified_through is not None else '—')}</td>"
        f"<td class='small'>{e(c.evidence)}</td></tr>" for c in registry.calendars.values())
    return ('<div class="scroll"><table><thead><tr><th>日历</th><th>核验范围</th><th>证据</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def _guarantees(content: dict[str, Any]) -> str:
    return '<div class="guarantees">' + "".join(
        f'<div class="guarantee"><h4>{e(g["title"])}</h4><p class="muted">{e(g["detail"])}</p></div>'
        for g in content.get("guarantees", [])) + "</div>"


def _status(datasets: list[dict[str, Any]], latest: dict[str, dict[str, Any]], build: dict[str, Any]) -> str:
    repo = build.get("repo_url")
    fetch_rows = "".join(
        f"<tr><td><code>{e(d['dataset_id'])}</code></td><td>"
        + (chip("pass" if d["last_fetch"]["status"] in ("created", "unchanged") else "fail",
                FETCH_LABEL.get(d["last_fetch"]["status"], d["last_fetch"]["status"]))
           + f" <span class='small muted'>{e((d['last_fetch']['at'] or '')[:16].replace('T', ' '))}</span>"
           if d["last_fetch"] else '<span class="muted">本次构建未取得</span>')
        + "</td></tr>" for d in datasets)
    run_rows = "".join(
        f"<tr><td><code>{e(s)}</code></td><td>{chip(i['manifest']['status'], STATUS_LABEL.get(i['manifest']['status'], ''))}</td>"
        f"<td class='small'>{e(i['manifest']['started_at'][:16].replace('T', ' '))}</td>"
        f"<td class='small'><code>{e(i['manifest']['run_id'])}</code></td></tr>" for s, i in latest.items())
    wf = f"{repo}/actions/workflows/pages.yml" if repo else None
    return f"""
<p>本页发布于 {e(build['built_at'][:16].replace('T', ' '))} UTC；代码 <code>{e((build.get('commit') or '—')[:12])}</code>。
页面只在自动更新的全部必需步骤成功时发布；更新停滞超过 2 个工作日时，各页顶部会出现提示。
{f'<a href="{e(wf)}"><img class="badge" src="{e(wf)}/badge.svg" alt="自动更新工作流状态"></a> <a href="{e(wf)}">自动更新记录</a>' if wf else ''}</p>
<div class="two-col">
<div><h3 class="sub">本次构建的数据取得</h3><table class="compact"><tbody>{fetch_rows}</tbody></table></div>
<div><h3 class="sub">各研究的最新运行</h3><table class="compact"><tbody>{run_rows}</tbody></table></div>
</div>"""


def methods_page(content: dict[str, Any], registry: Registry, datasets: list[dict[str, Any]],
                 latest: dict[str, dict[str, Any]], build: dict[str, Any]) -> str:
    repo = build.get("repo_url")
    body = f"""
<header class="top"><div class="wrap"><h1>数据、方法与系统状态</h1>
<p class="tagline">研究结果有多可靠，取决于数据从哪里来、何时可知、是否完整、能否复现。</p></div></header>
<main class="wrap">
<section><h2>数据来源与核验</h2>
<p class="muted small">核验状态按「来源 × 数据集 × 用途」记录：说明已核验 → 接入已验证 → 用途已验证。
「仅当前修订」的数据只能用于使用最新修订的描述性研究；时点研究需要供应方历史版本，或本系统当时已取得的快照。</p>
{_datasets_table(datasets)}</section>
<section><h2>预期观测日历</h2>
<p class="muted small">日期覆盖对照经核验的发布日历计算。核验范围之外的日期按规则推定，研究会在限制中注明。</p>
{_calendars(registry)}</section>
<section><h2>可靠性机制</h2>{_guarantees(content)}</section>
<section><h2>复现方法</h2>
<p>每次运行的清单固定研究定义、数据版本、输入角色与代码内容校验值。结论变化的运行连同允许公开的数据
（目前只有 Treasury 曲线）保存在{f' <a href="{e(repo)}/tree/archive">archive 分支</a>' if repo else ' archive 分支'}。</p>
<pre><code>git worktree add _archive origin/archive
uv run iros archive restore _archive --with-data
uv run iros verify &lt;run_id&gt;</code></pre>
<p class="muted small">FRED 交叉核验数据未存档，复现时该部分不重算，结果标为部分复现。</p></section>
<section id="status"><h2>系统状态</h2>{_status(datasets, latest, build)}</section>
</main>"""
    return shell("数据、方法与状态 · Investment Research OS", body, build, active="methods.html")
