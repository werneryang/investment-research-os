"""首页展示模型：研究的归属、集合、证据提示与首屏精选，与页面布局分开。

- 归属：一项研究可以属于多个研究方向（关系保留在 content.yaml 的 directions.studies）。首页只在主方向列出
  完整条目，其他方向给出「另见」链接。主方向默认是框架顺序中第一个列出该研究的方向，可用
  studies.<id>.primary_direction 指定。
- 集合（content.yaml 的 collections）：同一方向下的一组同类研究收成一个入口，由 lead 研究代表。
- 证据提示分三级，先拆事实再定级别：fail 是已执行的检查明确失败；warn 是用途核验缺口落在研究期间的
  前段或中段，或研究期间整体在核验范围外；info 是只缺最新尾端的核验、数据截止日之后的期间、或因数据
  不足不输出的结论（研究边界）。没有记录的检查算未执行，不算通过。
- 精选：content.yaml 的 featured 显式指定，与目录顺序分开；检查失败的研究不进入精选。

这里只决定选什么、归在哪里、提示什么；文字按当前语言生成，布局在 home.py。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .common import RESULT_TYPE_LABEL, e, span_text
from .i18n import L, te
from .renderers import get_renderer
from .study import localized_findings

FEATURED_MAX = 4

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


@dataclass
class CollectionView:
    id: str
    name: str
    lead: StudyView
    members: list[tuple[StudyView, dict[str, Any]]]  # 成员及其结果（集合表格用）


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


def _end_of(cutoff: str) -> str:
    """数据截止日补成可按字符串比较的日期：2026-08 → 2026-08-31，2025 → 2025-12-31。"""
    return cutoff + "-31" if len(cutoff) == 7 else cutoff + "-12-31" if len(cutoff) == 4 else cutoff


def _scope_gap(use_scope: dict[str, Any], cutoff: str) -> tuple[str, list[list[str]]] | None:
    """一项输入的用途核验缺口：(级别, 区间)；不影响结果时返回 None。

    数据截止日之后的期间不影响结果；缺口全部在核验范围最晚日期之后（只缺最新尾端）为 info；
    其余（前段、中段、整体在范围外、范围不明）为 warn。"""
    status = use_scope.get("status")
    if status == "out_of_scope":
        return "warn", use_scope.get("uncovered", [])
    if status != "partial":
        return None
    spans = [s for s in use_scope.get("uncovered", []) if not cutoff or s[0] <= _end_of(cutoff)]
    if not spans:
        return None
    throughs = [b for _, b in use_scope.get("verified_ranges", [])]
    tail = bool(throughs) and None not in throughs and all(s[0] > max(throughs) for s in spans)
    return ("info" if tail else "warn"), spans


def notices(item: dict[str, Any]) -> list[Notice]:
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
    groups: dict[tuple[str, str], dict[str, list[str]]] = {}
    for inp in item["manifest"].get("inputs", []):
        gap = _scope_gap(inp.get("use_scope") or {}, r.get("data_cutoff", ""))
        if gap:
            level, spans = gap
            kind = "out" if (inp.get("use_scope") or {}).get("status") == "out_of_scope" else level
            groups.setdefault((level, kind), {}).setdefault(span_text(spans), []).append(inp["dataset_id"])
    for (level, kind), by_span in groups.items():
        n = sum(len(ids) for ids in by_span.values())
        listed = L("；", "; ").join(f'{L("、", ", ").join(ids)}{L(f"（{sp}）", f" ({sp})")}' for sp, ids in by_span.items())
        text, short = {
            "out": (L(f"研究期间在用途核验范围外：{listed}", f"study period outside use verification: {listed}"),
                    L(f"研究期间在 {n} 项输入的用途核验范围外", f"study period outside the use verification of {n} input(s)")),
            "info": (L(f"用途核验未覆盖最新数据：{listed}", f"use verification misses the latest data: {listed}"),
                     L(f"{n} 项输入的用途核验未覆盖最新数据", f"use verification of {n} input(s) misses the latest data")),
            "warn": (L(f"用途核验未覆盖部分研究期间：{listed}", f"use verification misses part of the study period: {listed}"),
                     L(f"{n} 项输入的用途核验未覆盖部分研究期间", f"use verification of {n} input(s) misses part of the study period")),
        }[kind]
        out.append(Notice(level, text, short))
    if r.get("unsupported"):
        n = len(r["unsupported"])
        out.append(Notice("info", L(f"{n} 项结论因数据不足未输出", f"{n} conclusion(s) withheld for lack of data")))
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


def study_view(study_id: str, item: dict[str, Any], meta: dict[str, Any]) -> StudyView:
    r, m = item["result"], item["manifest"]
    kind = RESULT_TYPE_LABEL.get(r["result_type"], r["result_type"])
    return StudyView(id=study_id, title=te(r["title"]), eyebrow=f'{te(meta.get("label", L("研究", "Study")))} · {kind}',
                     finding=_finding(item), cutoff=r["data_cutoff"], status=m["status"],
                     use_note=get_renderer(r["branch"]).use_note, notices=notices(item), checks=check_note(item))


# ---- 归属、集合与精选 ---------------------------------------------------------------

def primary_directions(branches: list[dict[str, Any]], metas: dict[str, Any]) -> dict[str, str]:
    """每项研究的主方向 id。指定的主方向必须是列出该研究的方向之一，否则构建失败。"""
    listed: dict[str, list[str]] = {}
    for b in branches:
        for d, _ in b["directions"]:
            for s in d.get("studies", []):
                listed.setdefault(s, []).append(d["id"])
    out = {}
    for s, dirs in listed.items():
        chosen = (metas.get(s) or {}).get("primary_direction", dirs[0])
        if chosen not in dirs:
            raise ValueError(f"研究 {s} 的 primary_direction {chosen} 没有列出该研究")
        out[s] = chosen
    return out


def collection_of(collections: dict[str, Any], primary: dict[str, str]) -> dict[str, str]:
    """成员研究 → 集合 id。lead 与成员必须同属一个主方向，避免集合拆散在不同方向。"""
    out = {}
    for cid, c in collections.items():
        for s in [c["lead"], *c.get("members", [])]:
            if s in primary and primary[s] != primary.get(c["lead"]):
                raise ValueError(f"集合 {cid} 的成员 {s} 与 lead 不在同一主方向")
            out[s] = cid
    return out


def featured(content: dict[str, Any], views: dict[str, StudyView], order: list[str]) -> list[StudyView]:
    """首屏精选：按 featured 配置；没有可用配置时取目录顺序的第一项。检查失败的研究不进入精选。"""
    picks = [views[s] for s in content.get("featured", []) if s in views and not views[s].failed]
    if not picks:
        picks = [views[s] for s in order if s in views and not views[s].failed][:1]
    return picks[:FEATURED_MAX]
