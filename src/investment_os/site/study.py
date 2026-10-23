"""研究页模板：问题 → 关键发现 → 可视化证据 → 方法 → 证据与限制 → 历史与复现。

所有研究共用这一结构；具体图表与发现规则由研究分支决定。地址 studies/<study_id>/ 长期不变，
始终展示最新运行。
"""

from __future__ import annotations

from typing import Any

from ..registry import Registry
from ..research.findings import state_changes
from .collect import run_differences
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
    use_scope_chip,
)
from .renderers import Renderer, get_renderer, use_key


def chart_panel(run_href: str, available: list[str], wanted: tuple[tuple[str, str], ...],
                interactive: bool = True) -> str:
    """图表面板：静态图默认可见；交互图表加载并生成成功后才替换显示（渐进增强）。

    脚本或数据加载失败、浏览器禁用脚本时，读者仍能看到与完整报告相同的静态图。
    """
    figs = "".join(
        f'<a href="{run_href}/figures/{f}" target="_blank" rel="noopener" title="查看大图">'
        f'<img loading="lazy" src="{run_href}/figures/{f}" alt="{e(alt)}"></a>'
        for f, alt in wanted if f in available)
    static = figs or '<p class="muted small">该运行没有静态图。</p>'
    src = f' data-src="{run_href}/chart.json"' if interactive else ""
    return (f'<div class="chart-panel"{src}>'
            f'<div class="chart-static figs">{static}</div>'
            '<div class="interactive" hidden></div>'
            '<p class="chart-status small muted" role="status"></p></div>')


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


def _method(result: dict[str, Any], renderer: Renderer) -> str:
    items = renderer.method_items(result) + [
        "<li>关键发现由固定规则在运行时生成并记录（规则版本、指纹与参数见「关键发现」下方）；只描述，不作预测或交易判断。</li>"]
    return f'<ul class="method">{"".join(items)}</ul>'


def evidence_panel(item: dict[str, Any], registry: Registry, run_href: str) -> str:
    """证据面板：逐项列出证据，不汇总成一个可信度分数。"""
    m, r, ver = item["manifest"], item["result"], item["verification"]
    val = r["validation"]
    renderer = get_renderer(r["branch"])
    rows = [("研究用途", f"{e(RESULT_TYPE_LABEL.get(r['result_type'], r['result_type']))} · "
                         f"{e(USE_LABEL[use_key(r)])}；{e(renderer.use_note)}")]
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
    rows += renderer.evidence_rows(r)
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


def interpretation_note(interp: dict[str, Any] | None, branch: str) -> str:
    """发现的来源：运行时记录，还是事后用当前规则生成。"""
    if not interp:
        return ""
    params = get_renderer(branch).rule_params_label(interp.get("params", {}))
    rule = f"{interp['rule_version']}（指纹 {(interp.get('rule_fingerprint') or '—')[:8]}" \
           + (f"，{params}" if params else "") + "）"
    if interp["origin"] == "retrospective":
        return (f'<p class="small warn">以下发现由当前规则 {e(rule)} 在发布网站时事后生成；'
                "该运行当时没有记录发现，措辞可能与当时的规则不同。</p>")
    note = f'<p class="small muted">以下发现在运行时按规则 {e(rule)} 生成并记录，纳入复现校验。'
    if interp.get("rules_changed"):
        note += "当前规则已变化；这里显示的是运行当时的发现，不按新规则改写。"
    return note + "</p>"


def _history(study_id: str, runs: list[dict[str, Any]], archived: dict[str, Any] | None,
             repo: str | None, up: str, renderer: Renderer) -> str:
    timeline = []
    chronological = list(reversed(runs))
    for prev, cur in zip(chronological, chronological[1:]):  # noqa: B905 - 相邻两次运行
        diffs = state_changes((prev.get("interpretation") or {}).get("state", {}),
                              (cur.get("interpretation") or {}).get("state", {}))
        if diffs:
            timeline.append({"item": cur, "diffs": diffs, "between": run_differences(prev, cur)})
    if timeline:
        change_rows = "".join(
            f"<tr><td class=\"nowrap\">{e(t['item']['result']['data_cutoff'])}</td>"
            f"<td>{'<br>'.join(e(d['item'] + '：' + d['from'] + ' → ' + d['to']) for d in t['diffs'])}</td>"
            f"<td class='small'>{'<br>'.join(e(x) for x in t['between']) or '—'}</td>"
            f"<td><a class=\"nowrap\" href=\"{up}runs/{e(t['item']['manifest']['run_id'])}/report.html\">报告</a></td></tr>"
            for t in reversed(timeline))
        change_html = ('<p class="small muted">「两次运行之间的差异」只列出可以客观比较的项目（研究窗口、数据版本、代码、解释规则），'
                       '不推断变化的原因；滚动窗口移动、数据修订、方法或规则修改都可能带来结论变化。</p>'
                       '<div class="scroll"><table><thead><tr><th>数据截止</th><th>结论变化</th>'
                       '<th>两次运行之间的差异</th><th></th></tr></thead>'
                       f'<tbody>{change_rows}</tbody></table></div>')
    else:
        # 列出的运行可能含本次发布、未单独归档的最新运行，归档数分开计
        listed = f"在列出的 {len(runs)} 次运行中"
        if archived is not None:
            listed += f"（其中已归档 {sum(r['manifest']['run_id'] in archived for r in runs)} 次）"
        change_html = (f'<p class="muted">{listed}，定性状态'
                       f'（{e(renderer.state_description)}）没有变化。</p>')
    rows = []
    for item in runs:
        m, r = item["manifest"], item["result"]
        note = ""
        if archived is not None:
            note = (archived[m["run_id"]]["reason"] if m["run_id"] in archived
                    else "本次发布的最新运行（结论与上一归档相同，未单独归档）")
        ver = item["verification"]
        rows.append(
            f"<tr><td class=\"nowrap\">{e(m['started_at'][:16].replace('T', ' '))}</td>"
            f"<td class=\"nowrap\">{e(r['data_cutoff'])}</td>"
            f"<td>{chip(m['status'], STATUS_LABEL.get(m['status'], m['status']))}</td>"
            + "".join(f"<td>{e(fn(r))}</td>" for _, fn in renderer.history_columns) +
            f"<td>{'一致' if ver and ver['reproduced'] else ('不一致' if ver else '—')}"
            f"{'（部分）' if ver and ver.get('scope') == 'partial' else ''}</td>"
            f"<td><a class=\"nowrap\" href=\"{up}runs/{e(m['run_id'])}/report.html\">报告</a>"
            f"<div class='small muted'>{e(note)}</div></td></tr>")
    archive_link = f' <a href="{e(repo)}/tree/archive">运行档案（archive 分支）</a>' if repo else ""
    columns = "".join(f"<th>{e(label)}</th>" for label, _ in renderer.history_columns)
    return f"""
<h3 class="sub">发现变化记录</h3>{change_html}
<h3 class="sub">历次运行</h3>
<div class="scroll"><table><thead><tr><th>运行时间（UTC）</th><th>数据截止</th><th>状态</th>{columns}
<th>固定输入重算</th><th>报告</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
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
    renderer = get_renderer(r["branch"])
    body = f"""
<header class="top"><div class="wrap">
  <p class="eyebrow">{e(meta.get('label', '研究'))} · {e(RESULT_TYPE_LABEL.get(r['result_type'], ''))}</p>
  <h1>{e(r['title'])}</h1>
  <p class="meta">研究期间 {e(r['scope'].get('start'))} 至 {e(r['scope'].get('end'))} · 数据截止 {e(r['data_cutoff'])}
  · {chip(m['status'], '本次运行 · ' + STATUS_LABEL.get(m['status'], m['status']))}</p>
</div></header>
<main class="wrap">
<section><h2>研究问题</h2><p class="lead">{e(r['question'])}</p></section>
<section><h2>关键发现</h2>{findings_list(latest['findings'])}{interpretation_note(latest.get('interpretation'), r['branch'])}{renderer.key_stats(r)}</section>
<section><h2>可视化证据</h2>
  {chart_panel(run_href, latest.get("figures", []), renderer.figures, renderer.chart_data(r) is not None)}
  <h3 class="sub">{e(renderer.coverage_title)}</h3>{renderer.coverage_section(r)}
</section>
<section><h2>方法</h2>{_method(r, renderer)}</section>
<section><h2>证据与限制</h2>
  <div class="checks">{check_chips(r, latest['verification'])}</div>
  {evidence_panel(latest, registry, run_href)}</section>
<section id="history"><h2>历史与复现</h2>{_history(study_id, runs, archived, build.get('repo_url'), up, renderer)}</section>
</main>"""
    return shell(f"{r['title']} · Investment Research OS", body, build, depth=2, charts=True,
                 description=r["question"])


def redirect(target: str) -> str:
    return (f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={e(target)}">'
            f'<link rel="canonical" href="{e(target)}"><p>已移至 <a href="{e(target)}">{e(target)}</a></p>')
