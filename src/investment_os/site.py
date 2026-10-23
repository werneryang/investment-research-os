"""项目静态网站：把登记、数据目录、运行记录与报告汇总为可发布的静态页面（模块 O）。

网站只读取已有的结构化记录，不重新计算研究结果。输出目录可直接用于 GitHub Pages。

    <out>/index.html                        项目总览（每项研究的最新运行，含交互图表）
    <out>/latest/<study_id>/report.html     每项研究最新报告的稳定地址
    <out>/history/<study_id>.html           历次归档运行
    <out>/runs/<run_id>/report.html         完整报告（复制自 reports/，加返回导航）
    <out>/runs/<run_id>/figures/*.png       报告静态图
    <out>/runs/<run_id>/daily.json          交互图表数据（合格观测，不含插值）
    <out>/assets/                           样式与图表脚本（site/assets）
    <out>/summary.json                      页面所示内容的机器可读摘要
"""

from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .analytics.rates import curvature_label, spread_label
from .archive import archived_runs
from .data.store import DataStore
from .registry import Registry
from .runs import list_runs
from .tenor import is_tenor, parse_tenor

STATUS_LABEL = {"success": "成功", "partial": "部分受限", "failed": "失败",
                "done": "完成", "planned": "未开始"}
VERIFY_LABEL = {"candidate": "候选", "docs_verified": "说明已核验",
                "access_verified": "接入已验证", "use_verified": "用途已验证"}
CHECK_LABEL = {"pass": "通过", "fail": "未通过", "skipped": "跳过"}
CHECK_NOTES = {
    "cross_check": "Treasury 曲线 10Y 与 FRED DGS10 比对。两者同源（H.15），一致只说明接入与解析正确，不是独立验证。",
    "raw_spot_check": "等距抽取标准化观测，用独立解析路径与原始下载文件逐点比对。",
    "reproduce": "发布前用该次运行固定的研究定义与数据版本重新计算，结果校验值一致；不代表其他环境或其他数据版本。",
}
FETCH_LABEL = {"created": "新版本", "unchanged": "无变化", "failed": "失败"}


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _num(v: Any, digits: int = 2, signed: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v:+,.{digits}f}" if signed else f"{v:,.{digits}f}"


def _repo_url(root: Path) -> str | None:
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


# ---- 收集 -----------------------------------------------------------------

def _load_run(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    vpath = run_dir / "verifications.jsonl"
    verifications = [json.loads(x) for x in vpath.read_text(encoding="utf-8").splitlines() if x] \
        if vpath.exists() else []
    return {"manifest": json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")),
            "result": json.loads((run_dir / "result.json").read_text(encoding="utf-8")),
            "verification": verifications[-1] if verifications else None}


def _collect_runs(root: Path) -> dict[str, list[dict[str, Any]]]:
    """study_id → 未失败的运行，按时间从新到旧。"""
    by_study: dict[str, list[dict[str, Any]]] = {}
    for r in list_runs(root):
        if r["status"] in (None, "failed", "running"):
            continue
        # started_at 只精确到秒；同一秒的运行按清单写入时间（纳秒）区分先后
        order = (r["started_at"], (root / "runs" / r["run_id"] / "manifest.json").stat().st_mtime_ns)
        by_study.setdefault(r["study_id"], []).append({**_load_run(root, r["run_id"]), "_order": order})
    for runs in by_study.values():
        runs.sort(key=lambda x: x["_order"], reverse=True)
    return by_study


def _ordered_studies(by_study: dict[str, list[dict[str, Any]]], content: dict[str, Any]) -> list[str]:
    preferred = [s for s in content.get("study_order", []) if s in by_study]
    return preferred + sorted(s for s in by_study if s not in preferred)


def _datasets(registry: Registry, store: DataStore) -> list[dict[str, Any]]:
    log = store.fetch_log()
    rows = []
    for d in registry.datasets.values():
        src = registry.sources[d.source_id]
        v = store.latest(d.id)
        terminal = [e for e in log if e.get("dataset_id") == d.id and e.get("status") != "started"]
        last = terminal[-1] if terminal else None
        rows.append({
            "dataset_id": d.id,
            "description": d.description,
            "source": src.publisher,
            "source_id": src.id,
            "frequency": d.frequency,
            "vintages": d.vintages.value,
            "status": src.status_for(d.id).value,
            "verified_uses": [u.value for u in src.verified_uses(d.id)],
            "version_id": v.version_id if v else None,
            "rows": v.rows if v else None,
            "status_counts": v.quality.get("status_counts", {}) if v else {},
            "last_fetch": {"status": last.get("status"), "at": last.get("finished_at") or last.get("started_at")}
            if last else None,
        })
    return rows


# ---- 页面片段 -------------------------------------------------------------

def _stat(label: str, value: str, note: str = "") -> str:
    return (f'<div class="stat"><div class="stat-label">{_e(label)}</div>'
            f'<div class="stat-value">{value}</div><div class="stat-note">{_e(note)}</div></div>')


def _chip(status: str | None, label: str | None = None, title: str | None = None) -> str:
    tip = f' title="{_e(title)}"' if title else ""
    return (f'<span class="chip chip-{_e(status)}"{tip}>'
            f'{_e(label or STATUS_LABEL.get(status or "", status))}</span>')


def _study_card(item: dict[str, Any], run_href: str, study_id: str, history_count: int) -> str:
    m, r = item["manifest"], item["result"]
    res, cov = r["results"], r["coverage"]
    stats = []
    ten = res.get("levels", {}).get("10Y")
    if ten:
        stats.append(_stat("10 年期收益率", f"{_num(ten['start'])}% → {_num(ten['end'])}%",
                           f"{_num(ten['change_bp'], 0, True)} bp"))
    for name, sp in res.get("spreads", {}).items():
        label = f"{spread_label(name)} 利差"
        if sp:
            inv = sp.get("inversion")
            note = f"倒挂 {inv['inverted_days']} 天" if inv else "期间统计不输出"
            stats.append(_stat(label, f"{_num(sp['start'], 0)} → {_num(sp['end'], 0)} bp", note))
    if cov.get("expected_days"):
        stats.append(_stat("日期覆盖", f"{cov['curve_days']} / {cov['expected_days']} 天",
                           "期间完整" if cov["period_complete"] else "未能证明完整"))

    checks = []
    for key, label in (("cross_check", "同源一致性检查"), ("raw_spot_check", "原始快照抽查")):
        v = r["validation"].get(key)
        if v:
            checks.append(_chip(v.get("status"), f"{label} · {CHECK_LABEL.get(v.get('status'), v.get('status'))}",
                                CHECK_NOTES[key]))
    ver = item["verification"]
    if ver:
        partial = "（部分）" if ver.get("scope") == "partial" else ""
        checks.append(_chip("pass" if ver["reproduced"] else "fail",
                            f"固定输入重算 · {'一致' if ver['reproduced'] else '不一致'}{partial}",
                            CHECK_NOTES["reproduce"] + (f" 部分重算：未重算 {'、'.join(ver.get('excluded_roles', []))}。"
                                                       if partial else "")))
    else:
        checks.append(_chip("skipped", "固定输入重算 · 未执行", CHECK_NOTES["reproduce"]))

    figs = "".join(
        f'<a href="{run_href}/figures/{f}" target="_blank" rel="noopener" title="查看大图">'
        f'<img loading="lazy" src="{run_href}/figures/{f}" alt="{_e(alt)}"></a>'
        for f, alt in (("curve_snapshots.png", "期初与期末收益率曲线"), ("spreads.png", "利差与曲率"))
        if f in item.get("figures", []))
    unsupported = "".join(f"<li>{_e(u['item'])}：{_e(u['reason'])}</li>" for u in r.get("unsupported", []))
    period = f"{r['scope'].get('start')} 至 {r['scope'].get('end')}"
    return f"""
<article class="card">
  <header class="card-head">
    <div><h3>{_e(r['title'])}</h3><p class="muted">{_e(r['question'])}</p></div>
    {_chip(m['status'], '本次运行 · ' + STATUS_LABEL.get(m['status'], m['status']))}
  </header>
  <p class="meta">研究期间 {_e(period)} · 数据截止 {_e(r['data_cutoff'])} · 运行 <code>{_e(m['run_id'])}</code></p>
  <div class="stats">{''.join(stats)}</div>
  <div class="interactive" data-src="{run_href}/daily.json"></div>
  <details class="static-figs"><summary>静态图（与完整报告相同）</summary><div class="figs">{figs}</div></details>
  {f'<ul class="limits">{unsupported}</ul>' if unsupported else ''}
  <p class="small muted">核验说明：同源一致性检查只说明接入与解析正确；固定输入重算指发布前对该次运行的重算。悬停标签可看详细说明。</p>
  <footer class="card-foot"><div class="checks">{''.join(checks)}</div>
    <div class="card-links"><a class="button secondary" href="history/{_e(study_id)}.html">历史记录（{history_count}）</a>
    <a class="button" href="latest/{_e(study_id)}/report.html">最新完整报告 →</a></div></footer>
</article>"""


def _phases(content: dict[str, Any]) -> str:
    items = "".join(
        f'<li class="phase phase-{_e(p["status"])}"><div class="phase-id">{_e(p["id"])}</div>'
        f'<div><div class="phase-name">{_e(p["name"])} {_chip(p["status"], {"done": "完成", "partial": "部分完成", "planned": "未开始"}.get(p["status"]))}</div>'
        f'<p class="muted">{_e(p["summary"])}</p></div></li>'
        for p in content.get("phases", []))
    return f'<ol class="phases">{items}</ol>'


def _modules(content: dict[str, Any]) -> str:
    cells = "".join(
        f'<div class="module"><div class="module-id">{_e(m["id"])}</div><div class="module-name">{_e(m["name"])}</div>'
        f'<div class="muted small">{_e(m["role"])}</div><code class="small">{_e(m["code"])}</code></div>'
        for m in content.get("modules", []))
    return (f'<div class="modules">{cells}</div>'
            '<p class="muted small">流程：研究定义 → 资源接入 → 数据与版本 → 公共分析 → 研究分支 → 成果与档案；'
            '质量与验证贯穿每一步。</p>')


def _datasets_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for d in rows:
        counts = d["status_counts"]
        quality = " / ".join(f"{k} {v}" for k, v in counts.items()) if counts else "—"
        fetch = d["last_fetch"]
        fetch_cell = (f'{_chip("pass" if fetch["status"] in ("created", "unchanged") else "fail", FETCH_LABEL.get(fetch["status"], fetch["status"]))}'
                      f'<div class="small muted">{_e((fetch["at"] or "")[:16].replace("T", " "))}</div>'
                      if fetch else '<span class="muted">未取得</span>')
        uses = f'<div class="small muted">用途已验证：{_e("、".join(d["verified_uses"]))}</div>' \
            if d["verified_uses"] else ""
        body.append(
            f"<tr><td><strong>{_e(d['dataset_id'])}</strong><div class='small muted'>{_e(d['description'])}</div></td>"
            f"<td>{_e(d['source'])}</td><td>{_e(d['frequency'])}</td>"
            f"<td>{'供应方历史版本' if d['vintages'] == 'supplier' else '仅当前修订'}</td>"
            f"<td>{_e(VERIFY_LABEL.get(d['status'], d['status']))}{uses}</td>"
            f"<td>{_e(d['rows']) if d['rows'] is not None else '—'}<div class='small muted'>{_e(quality)}</div></td>"
            f"<td>{fetch_cell}</td></tr>")
    return ('<div class="scroll"><table><thead><tr><th>数据集</th><th>来源</th><th>频率</th><th>历史版本</th>'
            '<th>核验状态</th><th>行数 / 质量</th><th>最近取得</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _guarantees(content: dict[str, Any]) -> str:
    return '<div class="guarantees">' + "".join(
        f'<div class="guarantee"><h4>{_e(g["title"])}</h4><p class="muted">{_e(g["detail"])}</p></div>'
        for g in content.get("guarantees", [])) + "</div>"


CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"


def _shell(title: str, description: str, body: str, depth: int = 0, charts: bool = False) -> str:
    """所有页面共用的 HTML 外壳；depth 为相对站点根的目录层数。"""
    up = "../" * depth
    scripts = (f'<script defer src="{CHART_JS}"></script>\n<script defer src="{up}assets/charts.js"></script>'
               if charts else f'<script defer src="{up}assets/charts.js"></script>')
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}">
<link rel="stylesheet" href="{up}assets/style.css">
{scripts}
</head>
<body>
{body}
<footer class="bottom"><div class="wrap">数据来源：U.S. Department of the Treasury、Federal Reserve Bank of St. Louis（FRED）。
各来源的使用条款以其官网为准。本页内容仅为个人研究记录，只做期间描述，不含预测、交易或投资建议。</div></footer>
</body></html>
"""


def _status_bar(build: dict[str, Any]) -> str:
    """站点更新状态与研究运行状态分开：页面只有在发布流程成功时才会更新，
    所以这里显示「最近一次成功发布」的时间，并用实时徽章显示最近一次工作流结果。"""
    repo = build.get("repo_url")
    badge = ""
    if repo:
        wf = f"{repo}/actions/workflows/pages.yml"
        badge = (f'<a href="{_e(wf)}" title="最近一次自动更新的实时状态">'
                 f'<img src="{_e(wf)}/badge.svg" alt="自动更新工作流状态"></a>')
    actions = f' <a href="{_e(repo)}/actions/workflows/pages.yml">查看自动更新记录</a>' if repo else ""
    return f"""
  <div class="statusbar" data-built-at="{_e(build['built_at'])}">
    <span>站点更新：最近一次成功发布于 {_e(build['built_at'][:16].replace('T', ' '))} UTC（<span data-age>—</span>）</span>
    {badge}
  </div>
  <div class="stale" role="status">页面已经 <span data-weekdays>?</span> 个工作日没有更新，最近的自动更新可能失败；
  下列结果停留在上次成功发布时。{actions}</div>"""


def _index(content: dict[str, Any], datasets: list[dict[str, Any]], build: dict[str, Any], cards: str) -> str:
    repo = build.get("repo_url")
    ref = build.get("ref") or "main"
    links = []
    if repo:
        links.append(f'<a href="{_e(repo)}">GitHub 仓库</a>')
        links.append(f'<a href="{_e(repo)}/blob/{_e(ref)}/docs/architecture.md">架构 V0.3</a>')
        links.append(f'<a href="{_e(repo)}/blob/{_e(ref)}/docs/implementation.md">实现说明</a>')
    commit = (build.get("commit") or "")[:7]
    body = f"""
<header class="top"><div class="wrap">
  <h1>{_e(content.get('title'))}</h1>
  <p class="tagline">{_e(content.get('tagline'))}</p>
  <p class="meta">{' · '.join(([f'代码 <code>{_e(commit)}</code>'] if commit else []) + links)}</p>
  {_status_bar(build)}
</div></header>
<main class="wrap">
  <section><h2>研究成果</h2>{cards or '<p class="muted">暂无运行记录。</p>'}</section>
  <section><h2>数据来源与核验状态</h2>
    <p class="muted small">核验状态按「来源 × 数据集 × 用途」记录；「仅当前修订」的数据不能凭假定的发布延迟用于过去时点的研究。</p>
    {_datasets_table(datasets)}</section>
  <section><h2>可靠性机制</h2>{_guarantees(content)}</section>
  <section id="about"><h2>关于项目</h2>
    <h3 class="sub">建设进度</h3>{_phases(content)}
    <h3 class="sub">系统结构</h3>{_modules(content)}</section>
</main>"""
    return _shell(content.get("title", ""), content.get("tagline", ""), body, charts=True)


def _history_metrics(result: dict[str, Any]) -> tuple[str, str, str]:
    res = result.get("results", {})
    ten = res.get("levels", {}).get("10Y")
    sp = res.get("spreads", {}).get("2Y-10Y")
    return (f"{_num(ten['end'])}%" if ten else "—",
            f"{_num(ten['change_bp'], 0, True)}" if ten else "—",
            f"{_num(sp['end'], 0)}" if sp else "—")


def _verify_cell(ver: dict[str, Any] | None) -> str:
    if not ver:
        return "—"
    text = "一致" if ver["reproduced"] else "不一致"
    if ver.get("scope") == "partial":
        text += f"（部分，未重算 {'、'.join(ver.get('excluded_roles', []))}）"
    return _e(text)


def _history_page(study_id: str, runs: list[dict[str, Any]], archived: dict[str, Any] | None,
                  content: dict[str, Any]) -> str:
    title = runs[0]["result"]["title"]
    rows = []
    for item in runs:
        m, r = item["manifest"], item["result"]
        ten_end, ten_chg, sp_end = _history_metrics(r)
        ver = item["verification"]
        note = ""
        if archived is not None:
            note = archived[m["run_id"]]["reason"] if m["run_id"] in archived else "本次发布的最新运行（结论与上一归档相同，未单独归档）"
        rows.append(
            f"<tr><td>{_e(m['started_at'][:16].replace('T', ' '))}</td>"
            f"<td>{_e(r['scope'].get('start'))} 至 {_e(r['scope'].get('end'))}</td>"
            f"<td>{_e(r['data_cutoff'])}</td><td>{_chip(m['status'])}</td>"
            f"<td>{ten_end}</td><td>{ten_chg}</td><td>{sp_end}</td>"
            f"<td>{_verify_cell(ver)}</td>"
            f"<td><a href=\"../runs/{_e(m['run_id'])}/report.html\">报告</a>"
            f"<div class='small muted'>{_e(note)}</div></td></tr>")
    body = f"""
<header class="top"><div class="wrap">
  <nav class="crumbs"><a href="../index.html">← 返回项目总览</a></nav>
  <h1>{_e(title)} · 历史记录</h1>
  <p class="meta">共 {len(runs)} 次运行，从新到旧。只有实质结论（结果、覆盖、限制、核验结论）变化时才归档新运行；
  每份报告的地址固定不变。最新报告的稳定地址：<a href="../latest/{_e(study_id)}/report.html">latest/{_e(study_id)}/report.html</a></p>
</div></header>
<main class="wrap"><section>
<div class="scroll"><table><thead><tr><th>运行时间（UTC）</th><th>研究期间</th><th>数据截止</th><th>状态</th>
<th>10Y 期末</th><th>10Y 变化 bp</th><th>10Y − 2Y 期末 bp</th><th>固定输入重算</th><th>报告</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section></main>"""
    return _shell(f"{title} · 历史记录", content.get("tagline", ""), body, depth=1)


def _daily_json(result: dict[str, Any]) -> dict[str, Any]:
    """交互图表数据：直接取结果中的合格日度表，不插值、不填补。"""
    res = result.get("results", {})
    daily = result.get("tables", {}).get("daily", [])
    columns = {k for row in daily for k in row if k != "date"}
    tenors = sorted((c for c in columns if is_tenor(c)), key=lambda c: parse_tenor(c).months)
    return {
        "run_id": result.get("run_id"),
        "levels": list(res.get("levels", {})),
        "tenors": [{"code": t, "months": parse_tenor(t).months} for t in tenors],
        "spreads": [{"key": k, "label": spread_label(k)} for k in res.get("spreads", {})],
        "curvature": [{"key": f"curvature {k}", "label": curvature_label(k)} for k in res.get("curvature", {})],
        "rows": daily,
    }


def _copy_report(root: Path, manifest: dict[str, Any], dest: Path) -> list[str]:
    """复制报告与图表，并在报告顶部加返回导航。返回复制的图表文件名。"""
    dest.mkdir(parents=True, exist_ok=True)
    figures = []
    for out in manifest.get("outputs", []):
        src = root / out["path"]
        if src.name == "report.html":
            text = src.read_text(encoding="utf-8").replace(
                "<main><h1>",
                '<main><p style="margin:0 0 1rem"><a href="../../index.html">← 返回项目总览</a></p><h1>', 1)
            (dest / "report.html").write_text(text, encoding="utf-8")
        elif src.suffix == ".png":
            (dest / "figures").mkdir(exist_ok=True)
            shutil.copy2(src, dest / "figures" / src.name)
            figures.append(src.name)
    return figures


def build_site(root: Path, out: Path, archive: Path | None = None) -> Path:
    """生成网站。给出 archive 时，历史页标注每次运行的归档原因。"""
    root, out = Path(root), Path(out)
    content = yaml.safe_load((root / "site" / "content.yaml").read_text(encoding="utf-8")) or {}
    registry, store = Registry.load(root), DataStore(root)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(root / "site" / "assets", out / "assets")
    archived = archived_runs(archive) if archive is not None else None

    by_study = _collect_runs(root)
    studies = _ordered_studies(by_study, content)
    cards, latest_items = [], []
    for study_id in studies:
        runs = by_study[study_id]
        if archived is not None:
            # 历史页只列已归档（地址长期有效）的运行，以及本次发布的最新运行
            runs = [r for i, r in enumerate(runs) if i == 0 or r["manifest"]["run_id"] in archived]
        for item in runs:
            run_id = item["manifest"]["run_id"]
            dest = out / "runs" / run_id
            item["figures"] = _copy_report(root, item["manifest"], dest)
            (dest / "daily.json").write_text(json.dumps(_daily_json(item["result"]), ensure_ascii=False),
                                             encoding="utf-8")
        latest = runs[0]
        latest_dir = out / "latest" / study_id
        latest_dir.mkdir(parents=True)
        shutil.copy2(out / "runs" / latest["manifest"]["run_id"] / "report.html", latest_dir / "report.html")
        (out / "history").mkdir(exist_ok=True)
        (out / "history" / f"{study_id}.html").write_text(_history_page(study_id, runs, archived, content),
                                                          encoding="utf-8")
        cards.append(_study_card(latest, f"runs/{latest['manifest']['run_id']}", study_id, len(runs)))
        latest_items.append(latest)

    datasets = _datasets(registry, store)
    commit = latest_items[0]["manifest"]["code"].get("git_commit") if latest_items else None
    build = {
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "commit": os.environ.get("GITHUB_SHA") or commit,
        "ref": os.environ.get("GITHUB_SHA") or commit,
        "repo_url": _repo_url(root),
    }
    (out / "index.html").write_text(_index(content, datasets, build, "".join(cards)), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    summary = {
        "build": build,
        "datasets": datasets,
        "runs": [{
            "run_id": i["manifest"]["run_id"], "study_id": i["manifest"]["study_id"],
            "status": i["manifest"]["status"], "result_hash": i["manifest"].get("result_hash"),
            "code": i["manifest"]["code"], "inputs": i["manifest"].get("inputs", []),
            "data_cutoff": i["result"]["data_cutoff"], "coverage": {
                k: i["result"]["coverage"].get(k)
                for k in ("expected_days", "curve_days", "period_complete", "calendar_unverified")},
            "unsupported": i["result"].get("unsupported", []),
            "validation": {k: v.get("status") for k, v in i["result"]["validation"].items()},
            "reproduced": i["verification"]["reproduced"] if i["verification"] else None,
            "history": len(by_study[i["manifest"]["study_id"]]),
        } for i in latest_items],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                                      encoding="utf-8")
    return out / "index.html"
