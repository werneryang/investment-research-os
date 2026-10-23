"""首页（研究总览）：按研究框架组织。已有研究或数据的分支展开到研究方向与研究，规划中的分支合并为一行；
研究焦点在其方向下显示关键数字与证据摘要，图表、完整发现与证据留在研究页。"""

from __future__ import annotations

from typing import Any

from .capability import CATEGORIES, category_chip, risk_chips
from .common import RESULT_TYPE_LABEL, STATUS_LABEL, chip, e, shell
from .renderers import get_renderer
from .study import findings_list


def _evidence_summary(item: dict[str, Any]) -> str:
    r, ver = item["result"], item["verification"]
    val = r["validation"]
    renderer = get_renderer(r["branch"])
    parts = list(renderer.evidence_summary(r))
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
    parts.append(f"用途：{renderer.use_note}")
    return " · ".join(e(p) for p in parts)


def _focus(study_id: str, item: dict[str, Any], meta: dict[str, Any]) -> str:
    m, r = item["manifest"], item["result"]
    renderer = get_renderer(r["branch"])
    return f"""
<li class="study-row focus">
  <div class="card-head"><div><p class="eyebrow">研究焦点 · {e(meta.get('label', '研究'))}</p>
    <a class="study-title" href="studies/{e(study_id)}/">{e(r['title'])}</a></div>
    {chip(m['status'], '本次运行 · ' + STATUS_LABEL.get(m['status'], m['status']))}</div>
  <p class="meta">研究期间 {e(r['scope'].get('start'))} 至 {e(r['scope'].get('end'))} · 数据截止 {e(r['data_cutoff'])}
  · {e(RESULT_TYPE_LABEL.get(r['result_type'], r['result_type']))}</p>
  {renderer.key_stats(r)}
  <h4 class="sub">关键发现</h4>{findings_list(item['findings'], limit=2)}
  <p class="evidence-line small">证据：{_evidence_summary(item)}</p>
  <a href="studies/{e(study_id)}/">完整研究：图表、方法、证据与历史 →</a>
</li>"""


def _study_row(study_id: str, item: dict[str, Any], meta: dict[str, Any]) -> str:
    r = item["result"]
    first = item["findings"][0]["text"] if item["findings"] else "暂无规则化发现"
    kind = RESULT_TYPE_LABEL.get(r["result_type"], r["result_type"])
    return (f'<li class="study-row"><div><p class="eyebrow">{e(meta.get("label", "研究"))} · {e(kind)}</p>'
            f'<a class="study-title" href="studies/{e(study_id)}/">{e(r["title"])}</a>'
            f'<p class="muted small">{e(first)}</p></div>'
            f'<div class="small muted nowrap">数据截止 {e(r["data_cutoff"])}<br>'
            f'{chip(item["manifest"]["status"], STATUS_LABEL.get(item["manifest"]["status"], ""))}</div></li>')


def _studies(ids: list[str], latest: dict[str, dict[str, Any]], metas: dict[str, Any], focus: str | None) -> str:
    return "".join((_focus if s == focus else _study_row)(s, latest[s], metas.get(s, {})) for s in ids)


def _shared_data(dirs: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    """同一分支内有研究的方向共用的数据集；只展示登记中已经明确的关系。"""
    users: dict[str, list[str]] = {}
    for d, st in dirs:
        if st.get("runs"):
            for ds in d.get("datasets", []):
                users.setdefault(ds, []).append(d["name"])
    shared = [(ds, names) for ds, names in users.items() if len(names) > 1]
    return "".join(f'<p class="small muted">共享数据：<code>{e(ds)}</code> 同时支撑「{e("」「".join(names))}」，'
                   f'各自回答不同问题。</p>' for ds, names in shared)


def _direction(d: dict[str, Any], st: dict[str, Any], ordered: list[str], latest: dict[str, dict[str, Any]],
               metas: dict[str, Any], focus: str | None) -> str:
    ids = sorted((s for s in d.get("studies", []) if s in latest), key=ordered.index)
    if ids:
        inner = f'<ul class="study-list">{_studies(ids, latest, metas, focus)}</ul>'
    else:
        have = [x["id"] for x in st["datasets"] if x["has_data"]]
        gap = d.get("cannot_answer", [])
        inner = (f'<p class="small muted">{"已接入 " + "、".join(f"<code>{e(x)}</code>" for x in have) if have else "数据已登记，本次构建未取得"}'
                 f'；尚无研究。{"还不能回答：" + e(gap[0]) if gap else ""}</p>')
    return (f'<div class="direction"><h4>{e(d["name"])} {risk_chips(d)} {category_chip(st["category"])}</h4>'
            f'<p class="small muted">{e(d.get("summary", ""))}</p>{inner}</div>')


def _branch_card(b: dict[str, Any], ordered: list[str], latest: dict[str, dict[str, Any]],
                 metas: dict[str, Any], focus: str | None) -> str:
    shown = [(d, st) for d, st in b["directions"] if st["category"] != "planned"]
    planned = [d["name"] for d, st in b["directions"] if st["category"] == "planned"]
    rest = (f'<p class="small muted planned-line">本分支规划中：{e(" · ".join(planned))}</p>' if planned else "")
    return f"""
<article class="card branch-card" id="{e(b['id'])}">
  <header class="card-head"><div><p class="eyebrow">研究分支</p><h3>{e(b['name'])}</h3>
    <p class="muted">{e(b.get('question', ''))}</p></div>{category_chip(b['category'])}</header>
  {"".join(_direction(d, st, ordered, latest, metas, focus) for d, st in shown)}
  {_shared_data(b['directions'])}{rest}
</article>"""


def home_page(studies: list[str], latest: dict[str, dict[str, Any]], content: dict[str, Any],
              build: dict[str, Any], branches: list[dict[str, Any]]) -> str:
    metas = content.get("studies", {})
    focus = studies[0] if studies else None
    # 有研究的分支在前；同类保持 content.yaml 的顺序
    open_ = sorted((b for b in branches if b["category"] != "planned"),
                   key=lambda b: CATEGORIES.index(b["category"]))
    planned = [b for b in branches if b["category"] == "planned"]
    cards = "".join(_branch_card(b, studies, latest, metas, focus) for b in open_)
    planned_line = (f'<p class="planned-line">规划中的分支：{e(" · ".join(b["name"] for b in planned))}'
                    f' · <a href="map.html">各分支还缺什么 →</a></p>' if planned else "")
    placed = {s for b in branches for d, _ in b["directions"] for s in d.get("studies", [])}
    unplaced = [s for s in studies if s not in placed]
    unplaced_html = (f'<h3>未归入研究方向的研究</h3><p class="muted small">在 site/content.yaml 的研究框架中登记所属方向。</p>'
                     f'<ul class="study-list">{_studies(unplaced, latest, metas, focus)}</ul>' if unplaced else "")
    body = f"""
<header class="hero"><div class="wrap">
  <h1>{e(content.get('title'))}</h1>
  <p class="tagline">{e(content.get('tagline'))}</p>
  <p class="meta">公开免费数据 · 可追溯的版本 · 历史结果可复现 · 只描述数据能证明的内容</p>
</div></header>
<main class="wrap">
  <section><h2>研究框架</h2>
    <p class="muted">研究按 {len(branches)} 个研究分支组织，分支下是研究方向，标签是涉及的风险来源。
    下面展开已有研究或数据的分支，规划中的分支列在最后。</p>
    {'' if latest else '<p class="muted">暂无研究运行记录。</p>'}
    {cards}{planned_line}{unplaced_html}
  </section>
  <section class="about-strip">
    <div><h3>这些发现有多可靠？</h3><p class="muted small">每项研究都有证据面板：数据来源与版本、覆盖、核验、复现与限制，
    不汇总成一个笼统的可信度分数。</p><a href="methods.html">数据、方法与状态 →</a></div>
    <div><h3>每个方向能回答什么？</h3><p class="muted small">各研究方向能回答与还不能回答的问题、数据与用途核验状态、
    规划中的方向还缺什么，以及建设进度。</p>
    <a href="map.html">研究能力地图 →</a></div>
  </section>
</main>"""
    return shell(content.get("title", ""), body, build)
