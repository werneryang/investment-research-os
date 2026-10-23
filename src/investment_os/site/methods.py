"""数据、方法与系统状态：来源与核验、时间规则、日历、可靠性机制、复现方法与运行状态。"""

from __future__ import annotations

from typing import Any

from ..registry import Registry
from .common import FETCH_LABEL, STATUS_LABEL, VERIFY_LABEL, chip, e, shell
from .i18n import L, Labels, is_en, te


def _datasets_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for d in rows:
        counts = d["status_counts"]
        quality = " / ".join(f"{k} {v}" for k, v in counts.items()) if counts else "—"
        uses = (f'<div class="small muted">{L("用途已验证：", "Use verified: ")}'
                f'{e(L("、", ", ").join(d["verified_uses"]))}</div>' if d["verified_uses"] else "")
        vintages = L("供应方历史版本", "Supplier vintages") if d["vintages"] == "supplier" else L("仅当前修订", "Current revision only")
        body.append(
            f"<tr><td><strong>{e(d['dataset_id'])}</strong><div class='small muted'>{te(d['description'])}</div></td>"
            f"<td>{te(d['source'])}</td><td>{e(d['frequency'])}</td>"
            f"<td>{vintages}<div class='small muted'>{te(d['availability'])}</div></td>"
            f"<td>{e(VERIFY_LABEL.get(d['status'], d['status']))}{uses}</td>"
            f"<td>{e(d['rows']) if d['rows'] is not None else '—'}<div class='small muted'>{e(quality)}</div></td>"
            f"<td>{L('是', 'Yes') if d['archive_data'] else L('否', 'No')}</td></tr>")
    head = L("<th>数据集</th><th>来源</th><th>频率</th><th>历史版本与可用时间</th><th>核验状态</th><th>行数 / 质量</th>"
             "<th>数据存档</th>",
             "<th>Dataset</th><th>Source</th><th>Frequency</th><th>Vintages and availability</th><th>Verification</th>"
             "<th>Rows / quality</th><th>Data archived</th>")
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


CHECK_STATUS = {"up_to_date": "pass", "extendable": "partial", "partial": "partial", "blocked": "fail",
                "regression": "fail", "unavailable": "skipped"}
CHECK_STATUS_LABEL = Labels({
    "up_to_date": ("已核验到最新数据", "Verified up to the latest data"),
    "extendable": ("有待确认的延长", "Extension awaiting confirmation"),
    "partial": ("可部分延长，有异常待判断", "Partly extendable; anomalies to review"),
    "blocked": ("有异常待判断", "Anomalies to review"),
    "regression": ("已核验范围出现回归", "Regression within the verified range"),
    "unavailable": ("本次构建无法核对", "Could not be checked in this build")})


def _check_message(chk: dict[str, Any]) -> str:
    """日历核对的结论。maintenance 以中文生成；英文页面按核对结果的字段重写同一句话。"""
    if not is_en() or chk.get("status") not in CHECK_STATUS or chk.get("status") == "unavailable":
        return te(chk.get("message", ""))
    start = (chk.get("candidate_range") or [None])[0]
    through = chk.get("proposed_verified_through")
    return e({
        "up_to_date": f"Data runs to {chk.get('last_observed')} and the calendar is verified to "
                      f"{chk.get('current_verified_through')}; there are no new dates to verify",
        "regression": "Dates inconsistent with the rule appeared within the verified range; they need manual "
                      "review first, and no extension is proposed",
        "blocked": f"The first date from {start} is already anomalous; extending needs manual judgement",
        "partial": f"Can be extended to {through}; later anomalous dates need manual judgement",
        "extendable": f"Can be extended to {through}: expected and actual release dates match day by day",
    }[chk["status"]])


def _calendars(registry: Registry, checks: dict[str, Any]) -> str:
    rows = []
    for c in registry.calendars.values():
        chk = checks.get(c.id, {})
        status = CHECK_STATUS.get(chk.get("status"), "skipped")
        label = CHECK_STATUS_LABEL.get(chk.get("status"), "—")
        history = (f"<div class='small muted'>{L(f'延长记录 {len(c.checks)} 条', f'{len(c.checks)} extension record(s)')}</div>"
                   if c.checks else "")
        rows.append(
            f"<tr><td><code>{e(c.id)}</code><div class='small muted'>{te(c.description)}</div></td>"
            f"<td>{e(c.verified_from.date() if c.verified_from is not None else '—')}{L(' 至 ', ' to ')}"
            f"{e(c.verified_through.date() if c.verified_through is not None else '—')}{history}</td>"
            f"<td>{chip(status, label)}<div class='small'>{_check_message(chk)}</div></td>"
            f"<td class='small'>{te(c.evidence)}</td></tr>")
    head = L("<th>日历</th><th>核验范围</th><th>本次核对</th><th>首次核验证据</th>",
             "<th>Calendar</th><th>Verified range</th><th>This check</th><th>Initial verification evidence</th>")
    note = L("核对由 <code>iros calendar check</code> 用最新数据完成，只报告不写入；"
             "延长核验范围与相应的用途核验需要人工确认后用 <code>iros calendar apply --confirm</code> 写入。",
             "The check is run by <code>iros calendar check</code> on the latest data and only reports; extending the "
             "verified range and the matching use verification needs a person to confirm, then "
             "<code>iros calendar apply --confirm</code> writes it.")
    return (f'<div class="scroll"><table><thead><tr>{head}'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div><p class="small muted">{note}</p>')


def _guarantees(content: dict[str, Any]) -> str:
    return '<div class="guarantees">' + "".join(
        f'<div class="guarantee"><h4>{te(g["title"])}</h4><p class="muted">{te(g["detail"])}</p></div>'
        for g in content.get("guarantees", [])) + "</div>"


def _status(datasets: list[dict[str, Any]], latest: dict[str, dict[str, Any]], build: dict[str, Any]) -> str:
    repo = build.get("repo_url")
    fetch_rows = "".join(
        f"<tr><td><code>{e(d['dataset_id'])}</code></td><td>"
        + (chip("pass" if d["last_fetch"]["status"] in ("created", "unchanged") else "fail",
                FETCH_LABEL.get(d["last_fetch"]["status"], d["last_fetch"]["status"]))
           + f" <span class='small muted'>{e((d['last_fetch']['at'] or '')[:16].replace('T', ' '))}</span>"
           if d["last_fetch"] else f'<span class="muted">{L("本次构建未取得", "Not fetched in this build")}</span>')
        + "</td></tr>" for d in datasets)
    run_rows = "".join(
        f"<tr><td><code>{e(s)}</code></td><td>{chip(i['manifest']['status'], STATUS_LABEL.get(i['manifest']['status'], ''))}</td>"
        f"<td class='small'>{e(i['manifest']['started_at'][:16].replace('T', ' '))}</td>"
        f"<td class='small'><code>{e(i['manifest']['run_id'])}</code></td></tr>" for s, i in latest.items())
    wf = f"{repo}/actions/workflows/pages.yml" if repo else None
    built, commit = e(build['built_at'][:16].replace('T', ' ')), e((build.get('commit') or '—')[:12])
    badge = (f'<a href="{e(wf)}"><img class="badge" src="{e(wf)}/badge.svg" '
             f'alt="{L("自动更新工作流状态", "Automatic update workflow status")}"></a> '
             f'<a href="{e(wf)}">{L("自动更新记录", "Update log")}</a>') if wf else ""
    intro = L(f"""本页发布于 {built} UTC；代码 <code>{commit}</code>。
页面只在自动更新的全部必需步骤成功时发布；更新停滞超过 2 个工作日时，各页顶部会出现提示。""",
              f"""This page was published {built} UTC; code <code>{commit}</code>.
Pages are published only when every required step of the automatic update succeeds; if updates stall for more than
2 working days, a notice appears at the top of each page.""")
    return f"""
<p>{intro}
{badge}</p>
<div class="two-col">
<div><h3 class="sub">{L("本次构建的数据取得", "Data fetched in this build")}</h3><table class="compact"><tbody>{fetch_rows}</tbody></table></div>
<div><h3 class="sub">{L("各研究的最新运行", "Latest run of each study")}</h3><table class="compact"><tbody>{run_rows}</tbody></table></div>
</div>"""


def methods_page(content: dict[str, Any], registry: Registry, datasets: list[dict[str, Any]],
                 latest: dict[str, dict[str, Any]], build: dict[str, Any],
                 calendar_checks: dict[str, Any] | None = None) -> str:
    repo = build.get("repo_url")
    archive = f' <a href="{e(repo)}/tree/archive">{L("archive 分支", "archive branch")}</a>' if repo else L(" archive 分支", " archive branch")
    body = f"""
<header class="top"><div class="wrap"><h1>{L("数据、方法与系统状态", "Data, methods and system status")}</h1>
<p class="tagline">{L("研究结果有多可靠，取决于数据从哪里来、何时可知、是否完整、能否复现。",
                      "How reliable a result is depends on where the data comes from, when it was knowable, whether it is "
                      "complete and whether it can be reproduced.")}</p></div></header>
<main class="wrap">
<section><h2>{L("数据来源与核验", "Data sources and verification")}</h2>
<p class="muted small">{L("""核验状态按「来源 × 数据集 × 用途」记录：说明已核验 → 接入已验证 → 用途已验证。
「仅当前修订」的数据只能用于使用最新修订的描述性研究；时点研究需要供应方历史版本，或本系统当时已取得的快照。""",
"""Verification is recorded per source × dataset × use: docs verified → access verified → use verified.
Data with only the current revision can serve only descriptive studies on the latest revision; point-in-time studies
need supplier vintages or snapshots this system had already taken at the time.""")}</p>
{_datasets_table(datasets)}</section>
<section><h2>{L("预期观测日历", "Expected observation calendars")}</h2>
<p class="muted small">{L("日期覆盖对照经核验的发布日历计算。核验范围之外的日期按规则推定，研究会在限制中注明。",
                          "Date coverage is measured against a verified release calendar. Dates outside the verified "
                          "range are inferred by rule, and studies say so in their limitations.")}</p>
{_calendars(registry, calendar_checks or {})}</section>
<section><h2>{L("可靠性机制", "Reliability safeguards")}</h2>{_guarantees(content)}</section>
<section><h2>{L("复现方法", "How to reproduce")}</h2>
<p>{L(f"""每次运行的清单固定研究定义、数据版本、输入角色与代码内容校验值。结论变化的运行连同允许公开的数据
（目前只有 Treasury 曲线）保存在{archive}。""",
      f"""Each run's manifest pins the study definition, data versions, input roles and code content hash. Runs whose
conclusions changed are kept, with the data that may be redistributed (currently only the Treasury curve), on the{archive}.""")}</p>
<pre><code>git worktree add _archive origin/archive
uv run iros archive restore _archive --with-data
uv run iros verify &lt;run_id&gt;</code></pre>
<p class="muted small">{L("FRED 交叉核验数据未存档，复现时该部分不重算，结果标为部分复现。",
                          "The FRED cross-check data is not archived, so that part is not recomputed and the result is "
                          "marked as partial reproduction.")}</p></section>
<section id="status"><h2>{L("系统状态", "System status")}</h2>{_status(datasets, latest, build)}</section>
</main>"""
    return shell(L("数据、方法与状态", "Data, methods & status") + " · Investment Research OS", body, build,
                 page="methods.html", active="methods.html")
