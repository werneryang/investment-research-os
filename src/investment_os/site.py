"""项目静态网站：把登记、数据目录、运行记录与报告汇总为可发布的静态页面（模块 O）。

网站只读取已有的结构化记录，不重新计算研究结果。输出目录可直接用于 GitHub Pages。

    <out>/index.html                   项目总览
    <out>/runs/<run_id>/report.html    完整报告（复制自 reports/，加返回导航）
    <out>/runs/<run_id>/figures/*.png  报告图表
    <out>/summary.json                 页面所示内容的机器可读摘要
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

from .data.store import DataStore
from .registry import Registry
from .runs import list_runs

STATUS_LABEL = {"success": "成功", "partial": "部分受限", "failed": "失败",
                "done": "完成", "planned": "未开始"}
VERIFY_LABEL = {"candidate": "候选", "docs_verified": "说明已核验",
                "access_verified": "接入已验证", "use_verified": "用途已验证"}
CHECK_LABEL = {"pass": "通过", "fail": "未通过", "skipped": "跳过"}
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

def _latest_runs(root: Path) -> list[dict[str, Any]]:
    """每个研究最近一次未失败的运行，及其结果与最近一次复现记录。"""
    by_study: dict[str, dict[str, Any]] = {}
    for r in list_runs(root):
        if r["status"] in (None, "failed", "running"):
            continue
        if r["study_id"] not in by_study or r["started_at"] > by_study[r["study_id"]]["started_at"]:
            by_study[r["study_id"]] = r
    out = []
    for r in sorted(by_study.values(), key=lambda x: x["study_id"]):
        run_dir = root / "runs" / r["run_id"]
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        vpath = run_dir / "verifications.jsonl"
        verifications = [json.loads(x) for x in vpath.read_text(encoding="utf-8").splitlines() if x] \
            if vpath.exists() else []
        out.append({"manifest": manifest, "result": result,
                    "verification": verifications[-1] if verifications else None})
    return out


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


def _chip(status: str | None, label: str | None = None) -> str:
    return f'<span class="chip chip-{_e(status)}">{_e(label or STATUS_LABEL.get(status or "", status))}</span>'


def _study_card(item: dict[str, Any], run_href: str) -> str:
    m, r = item["manifest"], item["result"]
    res, cov = r["results"], r["coverage"]
    stats = []
    ten = res.get("levels", {}).get("10Y")
    if ten:
        stats.append(_stat("10 年期收益率", f"{_num(ten['start'])}% → {_num(ten['end'])}%",
                           f"{_num(ten['change_bp'], 0, True)} bp"))
    for name, label in (("2Y-10Y", "2Y–10Y 利差"), ("3M-10Y", "3M–10Y 利差")):
        sp = res.get("spreads", {}).get(name)
        if sp:
            inv = sp.get("inversion")
            note = f"倒挂 {inv['inverted_days']} 天" if inv else "期间统计不输出"
            stats.append(_stat(label, f"{_num(sp['start'], 0)} → {_num(sp['end'], 0)} bp", note))
    if cov.get("expected_days"):
        stats.append(_stat("日期覆盖", f"{cov['curve_days']} / {cov['expected_days']} 天",
                           "期间完整" if cov["period_complete"] else "未能证明完整"))

    checks = []
    for key, label in (("cross_check", "交叉核验"), ("raw_spot_check", "原始快照抽查")):
        v = r["validation"].get(key)
        if v:
            checks.append(_chip(v.get("status"), f"{label} · {CHECK_LABEL.get(v.get('status'), v.get('status'))}"))
    ver = item["verification"]
    if ver:
        checks.append(_chip("pass" if ver["reproduced"] else "fail",
                            "复现 · 一致" if ver["reproduced"] else "复现 · 不一致"))
    else:
        checks.append(_chip("skipped", "复现 · 未执行"))

    figs = "".join(
        f'<img loading="lazy" src="{run_href}/figures/{f}" alt="{_e(alt)}">'
        for f, alt in (("curve_snapshots.png", "期初与期末收益率曲线"), ("spreads.png", "利差与曲率"))
        if f in item.get("figures", []))
    unsupported = "".join(f"<li>{_e(u['item'])}：{_e(u['reason'])}</li>" for u in r.get("unsupported", []))
    period = f"{r['scope'].get('start')} 至 {r['scope'].get('end')}"
    return f"""
<article class="card">
  <header class="card-head">
    <div><h3>{_e(r['title'])}</h3><p class="muted">{_e(r['question'])}</p></div>
    {_chip(m['status'])}
  </header>
  <p class="meta">研究期间 {_e(period)} · 数据截止 {_e(r['data_cutoff'])} · 运行 <code>{_e(m['run_id'])}</code></p>
  <div class="stats">{''.join(stats)}</div>
  <div class="figs">{figs}</div>
  {f'<ul class="limits">{unsupported}</ul>' if unsupported else ''}
  <footer class="card-foot"><div class="checks">{''.join(checks)}</div>
    <a class="button" href="{run_href}/report.html">完整报告 →</a></footer>
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


CSS = """
:root{--bg:#f7f6f2;--panel:#fff;--fg:#1c1c1a;--muted:#66655f;--line:#e3e1da;--accent:#2b5a87;
--ok:#1f7a4d;--ok-bg:#e3f2ea;--warn:#8a5a00;--warn-bg:#fbefd5;--bad:#a12d2d;--bad-bg:#f8e1e1;--mute-bg:#ecebe6}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--panel:#1d1d1b;--fg:#ecebe6;--muted:#a3a29b;--line:#33322e;
--accent:#8fb6dd;--ok:#7fd1a5;--ok-bg:#183326;--warn:#f0c46b;--warn-bg:#3a2e14;--bad:#f09a9a;--bad-bg:#3d1c1c;--mute-bg:#2a2a27}
.figs img{background:#fff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",
"Noto Sans CJK SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:0 16px}
header.top{padding:48px 0 24px;border-bottom:1px solid var(--line)}
header.top h1{font-size:2rem;margin:0 0 .3rem}
.tagline{font-size:1.05rem;color:var(--muted);margin:0 0 1rem}
.meta{color:var(--muted);font-size:.85rem;margin:.4rem 0}
section{padding:36px 0;border-bottom:1px solid var(--line)}
h2{font-size:1.25rem;margin:0 0 1rem}
h3{font-size:1.1rem;margin:0 0 .2rem}h4{margin:0 0 .3rem;font-size:.98rem}
.muted{color:var(--muted)}.small{font-size:.82rem}
a{color:var(--accent)}code{font-size:.85em;word-break:break-all}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:20px}
.card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.card-head p{margin:0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}
.stat{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.stat-label{color:var(--muted);font-size:.8rem}.stat-value{font-size:1.15rem;font-weight:600;
font-variant-numeric:tabular-nums}.stat-note{color:var(--muted);font-size:.8rem}
.figs{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.figs img{width:100%;height:auto;border:1px solid var(--line);border-radius:6px}
.limits{color:var(--warn);font-size:.88rem}
.card-foot{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;margin-top:16px}
.checks{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.78rem;white-space:nowrap;
background:var(--mute-bg);color:var(--muted)}
.chip-success,.chip-pass,.chip-done{background:var(--ok-bg);color:var(--ok)}
.chip-partial{background:var(--warn-bg);color:var(--warn)}
.chip-failed,.chip-fail{background:var(--bad-bg);color:var(--bad)}
.button{display:inline-block;padding:7px 14px;border-radius:6px;background:var(--accent);color:var(--bg);
text-decoration:none;font-size:.9rem}
.phases{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.phase{display:flex;gap:14px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.phase p{margin:.2rem 0 0}.phase-id{font-weight:700;color:var(--accent);min-width:2.2em}
.phase-planned{opacity:.75}.phase-name{font-weight:600}
.modules{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.module{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
.module-id{font-weight:700;color:var(--accent)}.module-name{font-weight:600}
.guarantees{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.guarantee{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.guarantee p{margin:0;font-size:.9rem}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem;background:var(--panel)}
th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
footer.bottom{padding:28px 0 56px;color:var(--muted);font-size:.85rem}
"""


def _page(content: dict[str, Any], runs: list[dict[str, Any]], datasets: list[dict[str, Any]],
          build: dict[str, Any], cards: str) -> str:
    repo = build.get("repo_url")
    links = []
    if repo:
        links.append(f'<a href="{_e(repo)}">GitHub 仓库</a>')
        links.append(f'<a href="{_e(repo)}/blob/{_e(build.get("ref") or "main")}/docs/architecture.md">架构 V0.3</a>')
        links.append(f'<a href="{_e(repo)}/blob/{_e(build.get("ref") or "main")}/docs/implementation.md">实现说明</a>')
    commit = (build.get("commit") or "")[:7]
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(content.get('title'))}</title>
<meta name="description" content="{_e(content.get('tagline'))}">
<style>{CSS}</style></head>
<body>
<header class="top"><div class="wrap">
  <h1>{_e(content.get('title'))}</h1>
  <p class="tagline">{_e(content.get('tagline'))}</p>
  <p class="meta">页面构建于 {_e(build['built_at'][:16].replace('T', ' '))} UTC
  {f' · 代码 <code>{_e(commit)}</code>' if commit else ''}
  {' · ' + ' · '.join(links) if links else ''}</p>
  <p class="meta">本页由定时任务重新取得免费数据、运行研究并复现校验后自动生成；只做期间描述，不含预测、交易或投资建议。</p>
</div></header>
<main class="wrap">
  <section><h2>研究成果</h2>{cards or '<p class="muted">暂无运行记录。</p>'}</section>
  <section><h2>建设进度</h2>{_phases(content)}</section>
  <section><h2>系统结构</h2>{_modules(content)}</section>
  <section><h2>数据来源与核验状态</h2>
    <p class="muted small">核验状态按「来源 × 数据集 × 用途」记录；「仅当前修订」的数据不能凭假定的发布延迟用于过去时点的研究。</p>
    {_datasets_table(datasets)}</section>
  <section><h2>可靠性机制</h2>{_guarantees(content)}</section>
</main>
<footer class="bottom"><div class="wrap">数据来源：U.S. Department of the Treasury、Federal Reserve Bank of St. Louis（FRED）。
各来源的使用条款以其官网为准。本页内容仅为个人研究记录。</div></footer>
</body></html>
"""


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


def build_site(root: Path, out: Path) -> Path:
    root, out = Path(root), Path(out)
    content = yaml.safe_load((root / "site" / "content.yaml").read_text(encoding="utf-8")) or {}
    registry, store = Registry.load(root), DataStore(root)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    runs = _latest_runs(root)
    cards = []
    for item in runs:
        run_id = item["manifest"]["run_id"]
        item["figures"] = _copy_report(root, item["manifest"], out / "runs" / run_id)
        cards.append(_study_card(item, f"runs/{run_id}"))
    datasets = _datasets(registry, store)
    commit = runs[0]["manifest"]["code"].get("git_commit") if runs else None
    build = {
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "commit": os.environ.get("GITHUB_SHA") or commit,
        "ref": os.environ.get("GITHUB_SHA") or commit,
        "repo_url": _repo_url(root),
    }
    (out / "index.html").write_text(_page(content, runs, datasets, build, "".join(cards)), encoding="utf-8")
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
        } for i in runs],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                                      encoding="utf-8")
    return out / "index.html"
