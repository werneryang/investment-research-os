"""研究依赖图页面（lineage.html，只有中文）：按研究展开主干，按来源反查波及范围，列出未使用的模块与断链。

图由 investment_os.lineage 从研究定义、数据集登记与源码 import 静态读出，每次构建网站时重新生成。
规模小，不画整张网状图：每项研究（依赖相同的合并）是一个可展开的条目，展开后是一棵从结论到来源的树。
"""

from __future__ import annotations

from typing import Any

from .. import lineage as lg
from .common import e, shell, stat

KIND_CLASS = {"compute": "计算", "fetch": "取数", "script": "脚本", "dataset": "数据集", "source": "来源", "config": "登记"}


def _label(graph: dict[str, Any], t: dict[str, Any]) -> str:
    n = graph["nodes"][t["id"]]
    text = f"<code>{e(t['label'])}</code>"
    if n["kind"] == "dataset" and n.get("connector"):
        text += f' <span class="muted small">接入器 {e(n["connector"])}</span>'
        if n.get("via"):
            text += f' <span class="muted small">经本地文件 {e(n["via"])}</span>'
    if n["kind"] == "source":
        text = f'{e(t["label"])} <span class="muted small">{e(n.get("source_id"))}</span>'
    return text


def _tree(graph: dict[str, Any], items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    out = []
    for t in items:
        kind = graph["nodes"][t["id"]]["kind"]
        head = (f'<span class="lin-kind lin-{e(kind)}">{e(KIND_CLASS.get(kind, kind))}</span>'
                f'<span class="lin-sig">{e(lg._sig(t["signal"]))}</span> {_label(graph, t)}')
        out.append(f"<li>{head}{_tree(graph, t['children'])}</li>")
    return f'<ul class="lin-tree">{"".join(out)}</ul>'


def _study_link(graph: dict[str, Any], sid: str, published: set[str]) -> str:
    title = graph["nodes"][f"study:{sid}"]["label"]
    if sid in published:
        return f'<a href="studies/{e(sid)}/">{e(title)}</a> <code class="small">{e(sid)}</code>'
    return f'{e(title)} <code class="small">{e(sid)}</code> <span class="muted small">（网站未发布）</span>'


def _studies(graph: dict[str, Any], published: set[str]) -> str:
    out = []
    for g in lg.groups(graph):
        head = graph["nodes"][f"study:{g[0]}"]
        ch = lg.chain(graph, g[0])
        n_ds = len(ch["data"])
        title = head["label"] if len(g) == 1 else f"{len(g)} 项研究，依赖相同（分支 {head.get('branch')}）"
        members = "" if len(g) == 1 else ("<p class=\"small\">" + "；".join(_study_link(graph, s, published) for s in g) + "</p>")
        lead = (f'<p class="small">结论：{_study_link(graph, g[0], published)}</p>' if len(g) == 1 else members)
        q = head.get("question", "")
        out.append(f"""<details class="collection lin-study" id="g-{e(g[0])}">
<summary><strong>{e(title)}</strong> <span class="muted small">分支 {e(head.get('branch'))} · 数据集 {n_ds}</span></summary>
{lead}{f'<p class="muted small">研究问题：{e(q)}</p>' if q and len(g) == 1 else ''}
<h3 class="sub">计算</h3>{_tree(graph, ch['compute'])}
{f'<h3 class="sub">登记</h3>{_tree(graph, ch["config"])}' if ch['config'] else ''}
<h3 class="sub">数据</h3>{_tree(graph, ch['data'])}
</details>""")
    return "\n".join(out)


def _impact(graph: dict[str, Any], published: set[str]) -> str:
    rows = []
    for r in lg.impact(graph):
        ds = "".join(
            f"<li><code>{e(d)}</code> → {len(s)} 项研究</li>" for d, s in r["datasets"].items())
        studies = "；".join(_study_link(graph, s, published) for s in r["studies"]) or "无"
        rows.append(f"""<tr><td>{e(r['label'])}<br><code class="small">{e(r['source'].removeprefix('src:'))}</code></td>
<td class="nowrap">{len(r['studies'])}</td>
<td><details class="basis"><summary>{len(r['datasets'])} 个数据集</summary><ul>{ds}</ul></details>
<details class="basis"><summary>受影响的研究</summary><p class="small">{studies}</p></details></td></tr>""")
    return ('<div class="scroll"><table class="compact"><thead><tr><th>来源</th><th>受影响研究数</th><th>经过的数据集与研究</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _fan_in(graph: dict[str, Any], published: set[str]) -> str:
    rows = []
    for nid, n in lg.fan_in(graph, ("compute", "fetch", "script")):
        if not n:
            continue
        node = graph["nodes"][nid]
        studies = "；".join(_study_link(graph, s, published) for s in graph["used_by"][nid])
        shared = ' <span class="chip chip-partial">所有研究共用</span>' if nid in graph["framework"] else ""
        rows.append(f"""<tr><td><code>{e(node['label'])}</code>{shared}</td><td>{e(KIND_CLASS[node['kind']])}</td>
<td class="nowrap">{n}</td><td><details class="basis"><summary>研究</summary><p class="small">{studies}</p></details></td></tr>""")
    return ('<div class="scroll"><table class="compact"><thead><tr><th>模块</th><th>类型</th><th>研究数</th><th>用到它的研究</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _unused(graph: dict[str, Any]) -> str:
    order = list(lg.KIND_LABEL)
    rows = []
    for u in sorted(graph["unused"], key=lambda u: (order.index(u["kind"]), u["label"])):
        others = "；".join(u["others"]) or "无"
        rows.append(f"<tr><td><code>{e(u['label'])}</code></td><td>{e(lg.KIND_LABEL[u['kind']])}</td>"
                    f"<td class=\"small\">{e(others)}</td></tr>")
    return ('<div class="scroll"><table class="compact"><thead><tr><th>名称</th><th>类型</th><th>研究之外的引用</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _broken(graph: dict[str, Any]) -> str:
    if not graph["broken"]:
        return '<p><span class="chip chip-pass">没有断链</span> 所有研究引用的分支、数据集、来源、接入器、登记与导入的模块都存在。</p>'
    rows = "".join(f"<tr><td><code>{e(b['from'])}</code></td><td><code>{e(b['to'])}</code></td>"
                   f"<td>{e(b['kind'])}</td><td>{e(b['detail'])}</td></tr>" for b in graph["broken"])
    return ('<div class="scroll"><table class="compact"><thead><tr><th>引用方</th><th>指向</th><th>信号</th><th>说明</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')


def lineage_page(graph: dict[str, Any], build: dict[str, Any], published: set[str]) -> str:
    c = graph["counts"]
    framework = "、".join(f"<code>{e(graph['nodes'][f]['label'])}</code>" for f in graph["framework"])
    datasets_unused = sum(1 for u in graph["unused"] if u["kind"] == "dataset")
    body = f"""
<header class="top"><div class="wrap"><h1>研究依赖图</h1>
<p class="tagline">从每项研究的结论往回追：用了哪些计算模块、哪些数据集，数据集由哪个取数模块从哪个来源取得。
审计时可以看到某个来源出错会波及哪些研究，也能找出没有任何研究用到的模块。</p></div></header>
<main class="wrap">
<section><div class="stats">
{stat("研究", str(c['studies']), "config/studies")}
{stat("模块", str(c['modules']), f"计算 {c['compute']} · 取数 {c['fetch']} · 脚本 {c['scripts']}")}
{stat("数据集", str(c['datasets']), f"已接入来源 {c['sources']} 个")}
{stat("未被研究用到", str(c['unused_modules']), f"模块、接入器与脚本；另有数据集 {datasets_unused} 个")}
{stat("断链", str(c['broken']), "引用了不存在的模块或登记")}
</div>
<p class="muted small">依赖从研究定义的 <code>branch</code>、<code>data</code>、<code>method</code>，数据集登记的接入器与来源，
以及源码的 import 静态读出（<code>src/investment_os/lineage.py</code>）；证据包经本地中间文件的环节在
<code>config/lineage.yaml</code> 声明。所有研究还经过运行框架调用的 {framework}，下面不在每项研究下重复列出。
基础设施（登记、契约、数据存储等）不画进依赖链。同一份清单的 Markdown 版在
<code>docs/lineage.md</code>。</p></section>

<section id="studies"><h2>按研究展开</h2>
<p class="muted small">点开一项研究，看从结论到来源的主干。依赖完全相同的研究合并为一条（例如各公司的年度研究）。</p>
{_studies(graph, published)}</section>

<section id="impact"><h2>来源出错会波及哪些研究</h2>
<p class="muted small">按受影响研究数排序。只计研究定义里登记的数据集；可选输入（例如交叉核验）出错时研究仍能运行，但对应核对会缺失。</p>
{_impact(graph, published)}</section>

<section id="fan-in"><h2>模块被多少研究用到</h2>
<p class="muted small">共用越多越核心，改动时影响面越大。</p>
{_fan_in(graph, published)}</section>

<section id="unused"><h2>没有研究用到的模块与数据</h2>
<p class="muted small">从任何研究都到达不了。「研究之外的引用」说明它是否还被命令行、测试、网站说明或定时取数使用，
供判断是否保留；本页不作删除建议。另有 {len(graph['candidate_sources'])} 个来源没有登记数据集（候选或已停用），不列在这里。</p>
{_unused(graph)}</section>

<section id="broken"><h2>断链</h2>{_broken(graph)}</section>
</main>"""
    return shell("研究依赖图 · Investment Research OS", body, build, page="lineage.html",
                 description="从每项研究反向追溯到计算模块、数据集与来源", chinese_only=True)
