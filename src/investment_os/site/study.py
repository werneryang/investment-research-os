"""研究页模板：问题 → 关键发现 → 可视化证据 → 方法 → 证据与限制 → 历史与复现。

所有研究共用这一结构；具体图表与发现规则由研究分支决定。地址 studies/<study_id>/ 长期不变，
始终展示最新运行。
"""

from __future__ import annotations

from typing import Any

from ..analytics.rates import curvature_label, spread_label
from ..registry import Registry
from ..research.findings import (
    COVERAGE_LABEL,
    FLAT_BP,
    changes,
    completeness,
    coverage_summary,
)
from .common import (
    CHECK_LABEL,
    CHECK_NOTES,
    RESULT_TYPE_LABEL,
    STATUS_LABEL,
    USE_LABEL,
    VERIFY_LABEL,
    check_chips,
    chip,
    e,
    num,
    shell,
    stat,
    use_scope_chip,
)
from .coverage import coverage_strip

FIGURES = (("curve_snapshots.png", "期初与期末收益率曲线"), ("key_tenors.png", "关键期限收益率"),
           ("spreads.png", "利差与曲率"))


def key_stats(result: dict[str, Any]) -> str:
    res, cov = result["results"], result["coverage"]
    stats = []
    ten = res.get("levels", {}).get("10Y")
    if ten and ten.get("observations"):
        stats.append(stat("10 年期收益率", f"{num(ten['start'])}% → {num(ten['end'])}%",
                          f"{num(ten['change_bp'], 0, True)} bp"))
    for key, sp in res.get("spreads", {}).items():
        if sp.get("observations"):
            inv = sp.get("inversion")
            if not inv:
                note = "期间统计不输出"
            elif sp.get("sample") == "observed":
                note = f"已观测 {inv['observations']} 天中倒挂 {inv['inverted_days']} 天"
            else:
                note = f"倒挂 {inv['inverted_days']} 天"
            stats.append(stat(f"{spread_label(key)} 利差", f"{num(sp['start'], 0)} → {num(sp['end'], 0)} bp", note))
    if cov.get("expected_days"):
        due = cov.get("due_days", cov["expected_days"])
        note = COVERAGE_LABEL[completeness(cov)]
        if cov.get("pending_days"):
            note += f"；另 {cov['pending_days']} 天尚未发布"
        stats.append(stat("日期覆盖", f"{due - cov.get('missing_days', 0)} / {due} 天", note))
    return f'<div class="stats">{"".join(stats)}</div>'


def findings_list(items: list[dict[str, Any]], limit: int | None = None) -> str:
    if not items:
        return '<p class="muted">该研究分支暂无规则化的关键发现。</p>'
    rows = []
    for f in items[:limit] if limit else items:
        evidence = "".join(f"<li><code>{e(k)}</code> = {e(num(v, 2) if isinstance(v, float) else v)}</li>"
                           for k, v in f["evidence"].items())
        rows.append(f'<li><span>{e(f["text"])}</span>'
                    f'<details class="basis"><summary>依据</summary><ul>{evidence}</ul></details></li>')
    return f'<ol class="findings">{"".join(rows)}</ol>'


def _method(result: dict[str, Any]) -> str:
    m = result["methods"]
    params = m.get("parameters", {})
    spreads = "、".join(spread_label(f"{a}-{b}") for a, b in params.get("spreads", []))
    curv = params.get("curvature")
    items = [
        f"<li>{e(m['description'])}</li>",
        f"<li>关键期限：{e('、'.join(params.get('key_tenors', [])))}；利差（长端 − 短端）：{e(spreads or '无')}"
        + (f"；曲率：{e(curvature_label('/'.join(curv)))}" if curv else "") + "。</li>",
        f"<li>比较基准：{e(m.get('benchmark') or '—')}。</li>",
        f"<li>覆盖要求：关键期限有效观测占应已发布观测日的比例不低于 {params.get('min_coverage', 0):.0%}，"
        "不足时依赖它的结论不输出。达到要求不等于期间完整：期间完整另需所有预期日期都有数据、且日期在日历核验范围内；"
        "有缺口的指标，期间统计只描述已观测日期。尚未到发布时间的日期单独列出，不计入覆盖。</li>",
        "<li>倒挂定义为利差严格小于 0；恰为 0 的日期单独计数，不计入倒挂。</li>",
        f"<li>关键发现由固定规则生成：变化幅度小于 {FLAT_BP:.0f} bp 记为「基本持平」；只描述，不作预测或交易判断。</li>",
        f"<li>时间规则：{e(m.get('availability_rule') or '—')}；版本策略："
        f"{e(USE_LABEL.get('point_in_time' if result['scope'].get('vintage_policy') == 'as_of' else 'descriptive'))}。</li>",
    ]
    return f'<ul class="method">{"".join(items)}</ul>'


def evidence_panel(item: dict[str, Any], registry: Registry, run_href: str) -> str:
    """证据面板：逐项列出证据，不汇总成一个可信度分数。"""
    m, r, ver = item["manifest"], item["result"], item["verification"]
    cov, val = r["coverage"], r["validation"]
    use = "point_in_time" if r["scope"].get("vintage_policy") == "as_of" else "descriptive"
    rows = [("研究用途", f"{e(RESULT_TYPE_LABEL.get(r['result_type'], r['result_type']))} · {e(USE_LABEL[use])}；"
                         "不是预测或交易回测")]
    for inp in m.get("inputs", []):
        if not inp.get("used", True):
            rows.append((f"输入 · {e(inp['role'])}", f'<span class="muted">未使用：{e(inp.get("reason", ""))}</span>'))
            continue
        spec = registry.datasets.get(inp["dataset_id"])
        source = registry.sources[spec.source_id].publisher if spec else inp["dataset_id"]
        rows.append((f"输入 · {e(inp['role'])}",
                     f"{e(source)} · <code>{e(inp['dataset_id'])}</code> 版本 <code>{e(inp['version_id'])}</code>"
                     f"（内容校验值 <code>{e(inp['content_hash'][:12])}</code>）· 核验状态："
                     f"{e(VERIFY_LABEL.get(inp['source_status'], inp['source_status']))}"
                     + (f"<div>{use_scope_chip(inp.get('use_scope'))}</div>" if inp.get("use_scope") else "")))
    text = e(coverage_summary(cov))
    if cov.get("expected_days") is not None:
        text += (f"<div class='small muted'>研究窗口内预期观测日 {cov['expected_days']} 天"
                 f"（日历 <code>{e(cov['calendar'])}</code>）")
        if cov.get("pending_days"):
            text += f"；评估时尚未发布 {cov['pending_days']} 天（{e('、'.join(cov['pending_dates'][:5]))}）"
        if cov.get("missing_days"):
            text += f"；应已发布但缺失 {cov['missing_days']} 天（如 {e('、'.join(cov['missing_examples'][:3]))}）"
        if cov.get("calendar_unverified"):
            text += f"；日历未核验区间 {e('、'.join(cov['calendar_unverified']))}"
        if r["scope"].get("evaluated_at"):
            text += f"；评估时间 {e(str(r['scope']['evaluated_at'])[:16].replace('T', ' '))} UTC"
        text += "</div>"
    rows.append(("日期覆盖", text))
    metric_gaps = [f"{name} 缺 {m['missing']} 天" for group in (cov.get("metrics") or {}).values()
                   for name, m in group.items() if m.get("missing")]
    if metric_gaps:
        rows.append(("指标覆盖", e("；".join(metric_gaps)) + "<span class='muted small'>（利差与曲率要求所需期限同一天都有值；"
                                                             "有缺口的指标，期间统计标为已观测样本）</span>"))
    shares = [v["share"] for v in cov.get("tenors", {}).values()]
    if shares:
        rows.append(("期限覆盖", f"关键期限最低 {min(shares):.1%}（要求 ≥ {cov.get('min_coverage', 0):.0%}）"))
    spot = val.get("raw_spot_check")
    if spot:
        rows.append(("原始快照抽查", f"{chip(spot.get('status'), CHECK_LABEL.get(spot.get('status'), ''))} "
                                   f"抽查 {spot.get('checked', 0)} 个观测，不一致 {len(spot.get('failures', []))} 个。"
                                   f"<span class='muted small'>{e(CHECK_NOTES['raw_spot_check'])}</span>"))
    cross = val.get("cross_check")
    if cross:
        detail = (f"共同日期 {cross['matched']} 天，最大差 {num(cross.get('max_abs_diff'), 4)}"
                  if cross.get("matched") else e(cross.get("reason", "")))
        rows.append(("同源一致性检查", f"{chip(cross.get('status'), CHECK_LABEL.get(cross.get('status'), ''))} "
                                     f"{detail}。<span class='muted small'>{e(CHECK_NOTES['cross_check'])}</span>"))
    if ver:
        scope = ("部分（未重算 " + "、".join(ver.get("excluded_roles", [])) + "）") if ver.get("scope") == "partial" else "完整"
        rows.append(("固定输入重算", f"{chip('pass' if ver['reproduced'] else 'fail', '一致' if ver['reproduced'] else '不一致')} "
                                   f"范围：{e(scope)}；结果校验值 <code>{e((m.get('result_hash') or '')[:16])}</code>。"
                                   f"<span class='muted small'>{e(CHECK_NOTES['reproduce'])}</span>"))
    else:
        rows.append(("固定输入重算", '<span class="muted">未执行</span>'))
    code = m.get("code", {})
    rows.append(("代码版本", f"<code>{e((code.get('git_commit') or '—')[:12])}</code>"
                            f"{'（含未提交改动）' if code.get('dirty') else ''}"))
    unsupported = r.get("unsupported", [])
    rows.append(("不支持的结论", "无" if not unsupported else
                 "<ul>" + "".join(f"<li>{e(u['item'])}：{e(u['reason'])}</li>" for u in unsupported) + "</ul>"))
    table = "".join(f"<tr><th scope='row'>{k}</th><td>{v}</td></tr>" for k, v in rows)
    limits = "".join(f"<li>{e(x)}</li>" for x in r.get("limitations", []))
    return f"""
<div class="evidence"><table>{table}</table></div>
<h3 class="sub">限制</h3><ul class="limits-list">{limits}</ul>
<p class="small muted">原始记录：<a href="{run_href}/manifest.json">运行清单</a> ·
<a href="{run_href}/result.json">结构化结果</a> · <a href="{run_href}/report.html">完整报告</a></p>"""


def _history(study_id: str, runs: list[dict[str, Any]], archived: dict[str, Any] | None,
             repo: str | None, up: str) -> str:
    timeline = changes([r["result"] for r in reversed(runs)])
    if timeline:
        change_rows = "".join(
            f"<tr><td>{e(c['data_cutoff'])}</td><td>{e(c['item'])}</td><td>{e(c['from'])} → {e(c['to'])}</td>"
            f"<td><a href=\"{up}runs/{e(c['run_id'])}/report.html\">报告</a></td></tr>" for c in reversed(timeline))
        change_html = ('<div class="scroll"><table><thead><tr><th>数据截止</th><th>项目</th><th>变化</th><th></th>'
                       f'</tr></thead><tbody>{change_rows}</tbody></table></div>')
    else:
        change_html = f'<p class="muted">在已归档的 {len(runs)} 次运行中，定性状态（利差是否倒挂、变陡或变平、覆盖是否完整）没有变化。</p>'
    rows = []
    for item in runs:
        m, r = item["manifest"], item["result"]
        ten = r["results"].get("levels", {}).get("10Y") or {}
        sp = r["results"].get("spreads", {}).get("2Y-10Y") or {}
        note = ""
        if archived is not None:
            note = (archived[m["run_id"]]["reason"] if m["run_id"] in archived
                    else "本次发布的最新运行（结论与上一归档相同，未单独归档）")
        ver = item["verification"]
        rows.append(
            f"<tr><td>{e(m['started_at'][:16].replace('T', ' '))}</td><td>{e(r['data_cutoff'])}</td>"
            f"<td>{chip(m['status'], STATUS_LABEL.get(m['status'], m['status']))}</td>"
            f"<td>{num(ten.get('end')) + '%' if ten.get('end') is not None else '—'}</td>"
            f"<td>{num(sp.get('end'), 0)}</td>"
            f"<td>{'一致' if ver and ver['reproduced'] else ('不一致' if ver else '—')}"
            f"{'（部分）' if ver and ver.get('scope') == 'partial' else ''}</td>"
            f"<td><a href=\"{up}runs/{e(m['run_id'])}/report.html\">报告</a>"
            f"<div class='small muted'>{e(note)}</div></td></tr>")
    archive_link = f' <a href="{e(repo)}/tree/archive">运行档案（archive 分支）</a>' if repo else ""
    return f"""
<h3 class="sub">发现变化记录</h3>{change_html}
<h3 class="sub">历次运行</h3>
<div class="scroll"><table><thead><tr><th>运行时间（UTC）</th><th>数据截止</th><th>状态</th><th>10Y 期末</th>
<th>10Y − 2Y 期末 bp</th><th>固定输入重算</th><th>报告</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="small muted">只有实质结论（结果、覆盖、限制、核验结论）变化时才归档新运行，报告地址长期有效。
日后复现：<code>iros archive restore &lt;档案&gt; --with-data</code> 后 <code>iros verify &lt;run_id&gt;</code>；
未归档数据的可选输入（FRED 交叉核验）不重算，标为部分复现。{archive_link}</p>"""


def study_page(study_id: str, runs: list[dict[str, Any]], archived: dict[str, Any] | None,
               registry: Registry, content: dict[str, Any], build: dict[str, Any]) -> str:
    latest = runs[0]
    m, r = latest["manifest"], latest["result"]
    up = "../../"
    run_href = f"{up}runs/{m['run_id']}"
    meta = content.get("studies", {}).get(study_id, {})
    figs = "".join(
        f'<a href="{run_href}/figures/{f}" target="_blank" rel="noopener" title="查看大图">'
        f'<img loading="lazy" src="{run_href}/figures/{f}" alt="{e(alt)}"></a>'
        for f, alt in FIGURES if f in latest.get("figures", []))
    body = f"""
<header class="top"><div class="wrap">
  <p class="eyebrow">{e(meta.get('label', '研究'))} · {e(RESULT_TYPE_LABEL.get(r['result_type'], ''))}</p>
  <h1>{e(r['title'])}</h1>
  <p class="meta">研究期间 {e(r['scope'].get('start'))} 至 {e(r['scope'].get('end'))} · 数据截止 {e(r['data_cutoff'])}
  · {chip(m['status'], '本次运行 · ' + STATUS_LABEL.get(m['status'], m['status']))}</p>
</div></header>
<main class="wrap">
<section><h2>研究问题</h2><p class="lead">{e(r['question'])}</p></section>
<section><h2>关键发现</h2>{findings_list(latest['findings'])}{key_stats(r)}</section>
<section><h2>可视化证据</h2>
  <div class="interactive" data-src="{run_href}/daily.json"></div>
  <h3 class="sub">数据覆盖</h3>{coverage_strip(r)}
  <details class="static-figs"><summary>静态图（与完整报告相同）</summary><div class="figs">{figs}</div></details>
</section>
<section><h2>方法</h2>{_method(r)}</section>
<section><h2>证据与限制</h2>
  <div class="checks">{check_chips(r, latest['verification'])}</div>
  {evidence_panel(latest, registry, run_href)}</section>
<section id="history"><h2>历史与复现</h2>{_history(study_id, runs, archived, build.get('repo_url'), up)}</section>
</main>"""
    return shell(f"{r['title']} · Investment Research OS", body, build, depth=2, charts=True,
                 description=r["question"])


def redirect(target: str) -> str:
    return (f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={e(target)}">'
            f'<link rel="canonical" href="{e(target)}"><p>已移至 <a href="{e(target)}">{e(target)}</a></p>')
