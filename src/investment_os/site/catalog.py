"""Shared study summaries and evidence notices; classification lives in discovery.py."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .common import RESULT_TYPE_LABEL, e, span_text
from .i18n import L, te, tx
from .renderers import get_renderer
from .study import localized_findings

# 用途核验靠人工确认延长（README「日历与用途核验的维护」），尾端未延长是例行维护的滞后。核验最晚日期到
# 数据截止日不超过这些天数（约一个月，低频数据约一到两个观测期）才按维护滞后提示；超过或频率不明时按缺口提示
TAIL_LAG_DAYS = {"daily": 31, "weekly": 31, "monthly": 62, "quarterly": 123, "annual": 366}

# 首页点名的检查；其余研究专属检查只计数，名称与细节见研究页证据面板
CHECK_NAMES = {"raw_spot_check": ("原始快照抽查", "raw snapshot spot check"),
               "cross_check": ("同源检查", "same-source check"),
               "reproduce": ("固定输入重算", "pinned-input recomputation")}


@dataclass(frozen=True)
class Notice:
    level: str  # fail | warn | info
    text: str
    short: str = ""  # 精选卡片用的短句；空时用 text

    @property
    def brief(self) -> str:
        return self.short or self.text


@dataclass
class StudyView:
    id: str
    title: str  # 已转义的 HTML（未翻译时带 lang 标记）
    eyebrow: str
    finding: str  # 已转义的 HTML
    cutoff: str
    status: str
    use_note: str
    notices: list[Notice] = field(default_factory=list)
    checks: str = ""

    @property
    def failed(self) -> bool:
        return any(n.level == "fail" for n in self.notices)

    @property
    def limited(self) -> bool:
        return any(n.level == "warn" for n in self.notices)


# ---- 检查与证据提示 -----------------------------------------------------------------

def checks(item: dict[str, Any]) -> dict[str, list[str]]:
    """各项检查按通过、未通过、部分、未执行归类。跳过、状态不明或没有记录的检查算未执行，不算通过。"""
    ver, out = item["verification"], {"pass": [], "fail": [], "partial": [], "skipped": []}
    for key, v in item["result"]["validation"].items():
        if isinstance(v, dict) and "status" in v:
            out[v["status"] if v["status"] in ("pass", "fail") else "skipped"].append(key)
    if not ver:
        out["skipped"].append("reproduce")
    elif not ver["reproduced"]:
        out["fail"].append("reproduce")
    else:
        out["partial" if ver.get("scope") == "partial" else "pass"].append("reproduce")
    return out


def _check_names(keys: list[str]) -> str:
    named = [L(*CHECK_NAMES[k]) for k in keys if k in CHECK_NAMES]
    rest = len(keys) - len(named)
    if rest:
        named.append(L(f"另 {rest} 项检查", f"{rest} other check(s)") if named else L(f"{rest} 项检查", f"{rest} check(s)"))
    return L("、", ", ").join(named)


def check_note(item: dict[str, Any]) -> str:
    """检查状态的客观陈述：只说已执行的检查通过，同时写明部分执行与未执行的检查。"""
    c = checks(item)
    parts = [L(f"已执行的 {len(c['pass'])} 项检查通过", f"{len(c['pass'])} executed check(s) passed")
             if c["pass"] else L("暂无通过的检查", "No checks passed yet")]
    if c["partial"]:
        parts.append(L("部分执行：", "partly run: ") + _check_names(c["partial"]))
    if c["skipped"]:
        parts.append(L("未执行：", "not run: ") + _check_names(c["skipped"]))
    return L("；", "; ").join(parts)


def _end_of(cutoff: str) -> date:
    """数据截止日补成期末日期：2026-02 → 2026-02-28，2025 → 2025-12-31。"""
    if len(cutoff) == 4:
        return date(int(cutoff), 12, 31)
    if len(cutoff) == 7:
        y, m = map(int, cutoff.split("-"))
        return date(y, m, monthrange(y, m)[1])
    return date.fromisoformat(cutoff[:10])


# 缺口类型 → 级别：out 研究期间在核验范围外；gap 前段或中段；stale 只缺尾端但超过维护周期；tail 维护周期内的尾端
GAP_LEVEL = {"out": "warn", "gap": "warn", "stale": "warn", "tail": "info"}


def _scope_gap(use_scope: dict[str, Any], cutoff: str, frequency: str | None = None) -> tuple[str, list[list[str]]] | None:
    """一项输入的用途核验缺口：(类型, 区间)；不影响结果时返回 None。数据截止日之后的期间不影响结果。"""
    status = use_scope.get("status")
    if status == "out_of_scope":
        return "out", use_scope.get("uncovered", [])
    if status != "partial":
        return None
    end = _end_of(cutoff) if cutoff else None
    spans = [s for s in use_scope.get("uncovered", []) if end is None or date.fromisoformat(s[0]) <= end]
    if not spans:
        return None
    throughs = [b for _, b in use_scope.get("verified_ranges", [])]
    if not throughs or None in throughs or not all(s[0] > max(throughs) for s in spans):
        return "gap", spans
    lag = ((end or date.fromisoformat(spans[-1][1])) - date.fromisoformat(max(throughs))).days
    return ("tail" if lag <= TAIL_LAG_DAYS.get(frequency or "", -1) else "stale"), spans


def notices(item: dict[str, Any], frequency: dict[str, str] | None = None) -> list[Notice]:
    """一项研究的提示。frequency 为数据集 id → 频率，用于判断尾端核验滞后是否在维护周期内。"""
    r = item["result"]
    out: list[Notice] = []
    failed = checks(item)["fail"]
    if "raw_spot_check" in failed:
        out.append(Notice("fail", L("原始快照抽查有不一致", "raw snapshot spot check found mismatches")))
    if "cross_check" in failed:
        out.append(Notice("fail", L("同源检查有差异", "same-source check found differences")))
    other = [k for k in failed if k not in CHECK_NAMES]
    if other:
        out.append(Notice("fail", L(f"{len(other)} 项数据检查未通过", f"{len(other)} data check(s) failed")))
    if "reproduce" in failed:
        out.append(Notice("fail", L("固定输入重算不一致", "pinned-input recomputation differs")))
    # 同一类缺口合并成一句：输入按区间分组列出，精选卡片只说项数
    groups: dict[str, dict[str, list[str]]] = {}
    for inp in item["manifest"].get("inputs", []):
        gap = _scope_gap(inp.get("use_scope") or {}, r.get("data_cutoff", ""), (frequency or {}).get(inp["dataset_id"]))
        if gap:
            kind, spans = gap
            groups.setdefault(kind, {}).setdefault(span_text(spans), []).append(inp["dataset_id"])
    for kind, by_span in groups.items():
        n = sum(len(ids) for ids in by_span.values())
        listed = L("；", "; ").join(f'{L("、", ", ").join(ids)}{L(f"（{sp}）", f" ({sp})")}' for sp, ids in by_span.items())
        text, short = {
            "out": (L(f"研究期间在用途核验范围外：{listed}", f"study period outside use verification: {listed}"),
                    L(f"研究期间在 {n} 项输入的用途核验范围外", f"study period outside the use verification of {n} input(s)")),
            "tail": (L(f"用途核验未覆盖最新数据：{listed}", f"use verification misses the latest data: {listed}"),
                     L(f"{n} 项输入的用途核验未覆盖最新数据", f"use verification of {n} input(s) misses the latest data")),
            "stale": (L(f"用途核验滞后超过维护周期：{listed}", f"use verification lags beyond the maintenance cycle: {listed}"),
                      L(f"{n} 项输入的用途核验滞后超过维护周期", f"use verification of {n} input(s) lags beyond the maintenance cycle")),
            "gap": (L(f"用途核验未覆盖部分研究期间：{listed}", f"use verification misses part of the study period: {listed}"),
                    L(f"{n} 项输入的用途核验未覆盖部分研究期间", f"use verification of {n} input(s) misses part of the study period")),
        }[kind]
        out.append(Notice(GAP_LEVEL[kind], text, short))
    # 未输出的结论按记录的原因分类；旧结果没有分类，只说未输出，不推断原因
    withheld: dict[str, list[dict[str, Any]]] = {"data": [], "scope": [], "": []}
    for u in r.get("unsupported") or []:
        withheld[u.get("kind") if u.get("kind") in ("data", "scope") else ""].append(u)
    if withheld["data"]:
        n, items = len(withheld["data"]), L("、", ", ").join(tx(u["item"]) for u in withheld["data"])
        out.append(Notice("warn", L(f"因数据或输入不足未输出：{items}", f"withheld for lack of data or inputs: {items}"),
                          L(f"{n} 项结论因数据或输入不足未输出", f"{n} conclusion(s) withheld for lack of data or inputs")))
    if withheld["scope"]:
        n = len(withheld["scope"])
        out.append(Notice("info", L(f"{n} 项问题不在本研究回答范围内", f"{n} question(s) outside what this study answers")))
    if withheld[""]:
        n = len(withheld[""])
        out.append(Notice("info", L(f"{n} 项结论未输出，原因见研究页", f"{n} conclusion(s) not reported; reasons on the study page")))
    return out


# ---- 研究条目 -----------------------------------------------------------------------

def _finding(item: dict[str, Any]) -> str:
    """首页一句话：规则化发现 → 由已有结果字段格式化的摘要 → 研究问题。不新增计算。"""
    findings = localized_findings(item)
    if findings:
        f = findings[0]
        return e(f["text"]) if f.get("translated", True) else f'<span lang="zh-CN">{e(f["text"])}</span>'
    r = item["result"]
    summary = get_renderer(r["branch"]).home_summary(r)
    if summary:
        return e(L("结果摘要：", "Result summary: ") + summary)
    return e(L("研究问题：", "Research question: ")) + te(r.get("question", ""))


def study_view(study_id: str, item: dict[str, Any], meta: dict[str, Any],
               frequency: dict[str, str] | None = None) -> StudyView:
    r, m = item["result"], item["manifest"]
    kind = RESULT_TYPE_LABEL.get(r["result_type"], r["result_type"])
    return StudyView(id=study_id, title=te(r["title"]), eyebrow=f'{te(meta.get("label", L("研究", "Study")))} · {kind}',
                     finding=_finding(item), cutoff=r["data_cutoff"], status=m["status"],
                     use_note=get_renderer(r["branch"]).use_note, notices=notices(item, frequency), checks=check_note(item))
