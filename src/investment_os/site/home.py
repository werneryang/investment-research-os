"""首页（研究总览）：以研究发现为主体，证据摘要紧随其后，系统建设只做导航入口。"""

from __future__ import annotations

from typing import Any

from .common import STATUS_LABEL, chip, e, shell
from .study import findings_list, key_stats


def _evidence_summary(item: dict[str, Any]) -> str:
    r, ver = item["result"], item["verification"]
    cov, val = r["coverage"], r["validation"]
    parts = []
    if cov.get("expected_days"):
        parts.append(f"日期覆盖 {cov['curve_days']}/{cov['expected_days']} 天"
                     f"（{'完整' if cov['period_complete'] else '未能证明完整'}）")
    spot = val.get("raw_spot_check")
    if spot and spot.get("checked"):
        parts.append(f"原始快照抽查 {spot['checked']} 点{'一致' if spot['status'] == 'pass' else '有不一致'}")
    cross = val.get("cross_check")
    if cross and cross.get("matched"):
        parts.append(f"同源检查 {cross['matched']} 天{'一致' if cross['status'] == 'pass' else '有差异'}")
    if ver:
        parts.append(f"固定输入重算{'一致' if ver['reproduced'] else '不一致'}"
                     f"{'（部分）' if ver.get('scope') == 'partial' else ''}")
    for inp in item["manifest"].get("inputs", []):
        scope = inp.get("use_scope") or {}
        if scope.get("status") == "partial":
            spans = "、".join(a if a == b else f"{a} 至 {b}" for a, b in scope.get("uncovered", []))
            parts.append(f"用途核验部分在范围内（{inp['dataset_id']} 范围外：{spans}）")
        elif scope.get("status") == "out_of_scope":
            parts.append(f"研究期间在 {inp['dataset_id']} 的用途核验范围外")
        elif scope.get("status") == "in_scope":
            parts.append(f"{inp['dataset_id']} 用途已验证")
    parts.append("用途：历史描述，不是预测或交易回测")
    return " · ".join(e(p) for p in parts)


def _featured(study_id: str, item: dict[str, Any], meta: dict[str, Any]) -> str:
    m, r = item["manifest"], item["result"]
    run_href = f"runs/{m['run_id']}"
    return f"""
<article class="card featured">
  <header class="card-head">
    <div><p class="eyebrow">研究焦点 · {e(meta.get('label', '研究'))}</p><h2 class="h-feature">{e(r['title'])}</h2>
    <p class="muted">{e(r['question'])}</p></div>
    {chip(m['status'], '本次运行 · ' + STATUS_LABEL.get(m['status'], m['status']))}
  </header>
  <p class="meta">研究期间 {e(r['scope'].get('start'))} 至 {e(r['scope'].get('end'))} · 数据截止 {e(r['data_cutoff'])}</p>
  <h3 class="sub">关键发现</h3>{findings_list(item['findings'], limit=4)}
  {key_stats(r)}
  <div class="interactive" data-src="{run_href}/daily.json"></div>
  <p class="evidence-line small">证据：{_evidence_summary(item)}</p>
  <div class="card-links"><a class="button" href="studies/{e(study_id)}/">查看完整研究：方法、证据与历史 →</a></div>
</article>"""


def _study_row(study_id: str, item: dict[str, Any], meta: dict[str, Any]) -> str:
    r = item["result"]
    first = item["findings"][0]["text"] if item["findings"] else "暂无规则化发现"
    return (f'<li class="study-row"><div><p class="eyebrow">{e(meta.get("label", "研究"))}</p>'
            f'<a class="study-title" href="studies/{e(study_id)}/">{e(r["title"])}</a>'
            f'<p class="muted small">{e(first)}</p></div>'
            f'<div class="small muted nowrap">数据截止 {e(r["data_cutoff"])}<br>'
            f'{chip(item["manifest"]["status"], STATUS_LABEL.get(item["manifest"]["status"], ""))}</div></li>')


def home_page(studies: list[str], latest: dict[str, dict[str, Any]], content: dict[str, Any],
              build: dict[str, Any], capability_summary: dict[str, int]) -> str:
    metas = content.get("studies", {})
    featured = studies[0] if studies else None
    rest = studies[1:] if featured else []
    focus = _featured(featured, latest[featured], metas.get(featured, {})) if featured else \
        '<p class="muted">暂无研究运行记录。</p>'
    rows = "".join(_study_row(s, latest[s], metas.get(s, {})) for s in rest)
    body = f"""
<header class="hero"><div class="wrap">
  <h1>{e(content.get('title'))}</h1>
  <p class="tagline">{e(content.get('tagline'))}</p>
  <p class="meta">公开免费数据 · 可追溯的版本 · 历史结果可复现 · 只描述数据能证明的内容</p>
</div></header>
<main class="wrap">
  <section>{focus}</section>
  <section><h2>全部研究</h2>
    <ul class="study-list">{_study_row(featured, latest[featured], metas.get(featured, {})) if featured else ''}{rows}</ul>
  </section>
  <section class="about-strip">
    <div><h3>这些发现有多可靠？</h3><p class="muted small">每项研究都有证据面板：数据来源与版本、覆盖、核验、复现与限制，
    不汇总成一个笼统的可信度分数。</p><a href="methods.html">数据、方法与状态 →</a></div>
    <div><h3>系统现在能研究什么？</h3><p class="muted small">已有研究的领域 {capability_summary.get('active', 0)} 个；
    已接入数据、尚无研究 {capability_summary.get('data_only', 0) + capability_summary.get('registered', 0)} 个；
    规划中 {capability_summary.get('planned', 0)} 个。</p>
    <a href="map.html">研究能力地图 →</a></div>
  </section>
</main>"""
    return shell(content.get("title", ""), body, build, charts=True)

