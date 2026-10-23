"""日历与用途核验的维护：用已取得的数据核对发布日历，提出带证据的延长建议，经人确认后写入登记。

流程：
1. ``check_calendar``：比较日历规则与数据集最新版本的实际发布日期。已核验范围内也重新比对
   （发现回归）；待核验的新日期只检查到最后一个有数据的日期，之后的日期无法判断。
2. 规则说应发布但没有数据（可能是临时休市），或规则说休市却有数据：记为异常，延长停在第一个异常的前一天。
   异常需要人判断（例如追加 additional_closures），工具不自动处理。
3. ``build_proposal``：生成延长建议——新的日历核验条目，以及为与日历范围相接的用途核验追加新记录
   （覆盖新增日期，原记录不改写）。
4. ``apply_proposal``：不加 confirm 时只显示将写入的内容；确认后写入配置，重新加载登记验证，失败则还原。
   建议过时（登记已变化）时拒绝。CI 只运行检查并报告，不写入。
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .connectors.base import now_utc
from .contracts import VerificationStatus
from .data.store import DataStore
from .quality import ok_rows
from .registry import Registry


def _iso(d: pd.Timestamp | date) -> str:
    return pd.Timestamp(d).date().isoformat()


def check_calendar(root: Path, calendar_id: str | None = None, dataset_id: str | None = None) -> dict[str, Any]:
    reg, store = Registry.load(root), DataStore(root)
    if calendar_id is None:
        if len(reg.calendars) != 1:
            raise ValueError(f"请用 --calendar 指定日历：{', '.join(reg.calendars)}")
        calendar_id = next(iter(reg.calendars))
    cal = reg.calendars[calendar_id]
    linked = sorted(d.id for d in reg.datasets.values() if d.calendar == calendar_id)
    if dataset_id is None:
        if not linked:
            raise ValueError(f"没有数据集使用日历 {calendar_id}")
        dataset_id = linked[0]
    elif dataset_id not in linked:
        raise ValueError(f"数据集 {dataset_id} 不使用日历 {calendar_id}")
    if cal.verified_from is None or cal.verified_through is None:
        raise ValueError(f"日历 {calendar_id} 没有核验范围，先人工登记首次核验")

    frame, version = store.load(dataset_id)
    observed = pd.DatetimeIndex(sorted(set(pd.to_datetime(ok_rows(frame)["observation_at"]))))
    if not len(observed):
        raise ValueError(f"数据集 {dataset_id} 没有合格观测")
    last_obs = observed.max()
    vf, vt = cal.verified_from, cal.verified_through

    # 已核验范围内的回归检查
    reg_end = min(vt, last_obs)
    in_verified = observed[(observed >= vf) & (observed <= reg_end)]
    expected_verified = cal.expected_dates(vf, reg_end)
    regressions = {"missing": [_iso(d) for d in expected_verified.difference(in_verified)],
                   "unexpected": [_iso(d) for d in in_verified.difference(expected_verified)]}

    start = vt + pd.Timedelta(days=1)
    out: dict[str, Any] = {
        "calendar": calendar_id,
        "dataset": dataset_id,
        "dataset_version": version.version_id,
        "content_hash": version.content_hash,
        "version_created_at": version.created_at,
        "verified_from": _iso(vf),
        "current_verified_through": _iso(vt),
        "last_observed": _iso(last_obs),
        "regressions": regressions,
        "checked_at": now_utc().isoformat(),
    }
    if start > last_obs:
        out.update({"candidate_range": None, "expected_days": 0, "observed_days": 0,
                    "anomalies": {"missing": [], "unexpected": []}, "proposed_verified_through": None,
                    "status": "up_to_date",
                    "message": f"数据只到 {_iso(last_obs)}，日历已核验到 {_iso(vt)}，没有可核验的新日期"})
        if regressions["missing"] or regressions["unexpected"]:
            out.update(status="regression", message="已核验范围内出现与规则不一致的日期，需先人工处理，不提出延长")
        return out

    expected = cal.expected_dates(start, last_obs)
    obs = observed[(observed >= start) & (observed <= last_obs)]
    missing, unexpected = expected.difference(obs), obs.difference(expected)
    anomalies = sorted(list(missing) + list(unexpected))
    through = last_obs if not anomalies else anomalies[0] - pd.Timedelta(days=1)
    extendable = through >= start and not regressions["missing"] and not regressions["unexpected"]
    out.update({
        "candidate_range": [_iso(start), _iso(last_obs)],
        "expected_days": int(len(expected)),
        "observed_days": int(len(obs)),
        "anomalies": {"missing": [_iso(d) for d in missing], "unexpected": [_iso(d) for d in unexpected]},
        "proposed_verified_through": _iso(through) if extendable else None,
    })
    if regressions["missing"] or regressions["unexpected"]:
        out.update(status="regression", message="已核验范围内出现与规则不一致的日期，需先人工处理，不提出延长")
    elif not extendable:
        out.update(status="blocked", message=f"{_iso(start)} 起第一个日期即为异常，需人工判断后再延长")
    elif anomalies:
        out.update(status="partial", message=f"可延长到 {_iso(through)}；之后有异常日期需人工判断")
    else:
        out.update(status="extendable", message=f"可延长到 {_iso(through)}：预期与实际发布日期逐日一致")
    return out


def _latest_run_checks(root: Path, dataset_id: str, use: str) -> dict[str, Any] | None:
    """使用该数据集与用途的最近一次成功运行及其核验结论，作为用途延长的补充证据。"""
    best = None
    for path in (Path(root) / "runs").glob("*/manifest.json"):
        m = json.loads(path.read_text(encoding="utf-8"))
        if m.get("status") != "success":
            continue
        if not any(i.get("dataset_id") == dataset_id and i.get("use") == use and i.get("used", True)
                   for i in m.get("inputs", [])):
            continue
        if best is None or m.get("started_at", "") > best[0].get("started_at", ""):
            best = (m, path.parent)
    if best is None:
        return None
    m, run_dir = best
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    return {"run_id": m["run_id"], "study_id": m["study_id"],
            "validation": {k: (v or {}).get("status") for k, v in result.get("validation", {}).items()}}


def build_proposal(root: Path, check: dict[str, Any]) -> dict[str, Any]:
    """把检查结果整理成可确认、可写入的建议。没有可延长的日期时 applicable 为 False。"""
    reg = Registry.load(root)
    proposal = {"kind": "calendar_extension", "created_at": now_utc().isoformat(), "check": check,
                "applicable": check.get("proposed_verified_through") is not None}
    if not proposal["applicable"]:
        return proposal
    new_from = (date.fromisoformat(check["current_verified_through"]) + timedelta(days=1)).isoformat()
    new_through = check["proposed_verified_through"]
    evidence = (f"{check['checked_at'][:10]} 用 {check['dataset']} 版本 {check['dataset_version']}"
                f"（内容校验值 {check['content_hash'][:12]}）逐日比对 {new_from} 至 {new_through}："
                f"规则预期与实际发布日期一致；已核验范围 {check['verified_from']} 至 "
                f"{check['current_verified_through']} 无回归。由 iros calendar check 生成，经用户确认后写入。")
    proposal["calendar_entry"] = {"date": now_utc().date().isoformat(), "from": new_from, "through": new_through,
                                  "dataset": check["dataset"], "version": check["dataset_version"],
                                  "content_hash": check["content_hash"], "evidence": evidence}
    records = []
    for d in (s for s in reg.datasets.values() if s.calendar == check["calendar"]):
        source = reg.sources[d.source_id]
        for rec in source.verification:
            if (rec.dataset != d.id or rec.status is not VerificationStatus.USE_VERIFIED
                    or rec.valid_through is None or rec.valid_through.isoformat() != check["current_verified_through"]):
                continue
            run = _latest_run_checks(root, d.id, rec.use.value)
            run_text = (f"；最近一次使用该数据与用途的成功运行 {run['run_id']} 的核验："
                        + "、".join(f"{k} {v}" for k, v in run["validation"].items())) if run else ""
            records.append({"source_id": source.id, "record": {
                "dataset": d.id, "status": "use_verified", "use": rec.use.value,
                "date": now_utc().date().isoformat(), "valid_from": new_from, "valid_through": new_through,
                "evidence": (f"沿用 {rec.date} 登记的用途核验方法与范围，延伸到日历新核验的日期。"
                             f"日历核验：{evidence}{run_text}"),
                "scope": f"同 {rec.date} 的用途核验记录，观测日期 {new_from} 至 {new_through}。"}})
    proposal["use_records"] = records
    return proposal


def render_markdown(check: dict[str, Any], proposal: dict[str, Any] | None = None) -> str:
    lines = [f"### 日历核验：{check['calendar']}（{check['dataset']}）", "",
             f"- 结论：**{check['message']}**",
             f"- 已核验：{check['verified_from']} 至 {check['current_verified_through']}；数据最后一个观测日 {check['last_observed']}",
             f"- 数据版本：`{check['dataset_version']}`（内容校验值 `{check['content_hash'][:12]}`）"]
    if check.get("candidate_range"):
        a, b = check["candidate_range"]
        lines.append(f"- 待核验日期 {a} 至 {b}：规则预期 {check['expected_days']} 天，实际有数据 {check['observed_days']} 天")
    for kind, label in (("missing", "规则预期发布但没有数据"), ("unexpected", "规则判为休市却有数据")):
        if check["anomalies"].get(kind):
            lines.append(f"- 异常（{label}）：{'、'.join(check['anomalies'][kind])}")
        if check["regressions"].get(kind):
            lines.append(f"- **已核验范围内回归**（{label}）：{'、'.join(check['regressions'][kind])}")
    if proposal and proposal.get("applicable"):
        lines.append(f"- 建议：日历核验延长到 {check['proposed_verified_through']}；"
                     f"追加 {len(proposal.get('use_records', []))} 条用途核验记录（原记录不改写）。"
                     "需人工确认后用 `iros calendar apply <建议文件> --confirm` 写入。")
    return "\n".join(lines) + "\n"


# ---- 写入（需确认） ---------------------------------------------------------------

def _yaml_str(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)


def _calendar_text(text: str, calendar_id: str, new_through: str, entry: dict[str, Any]) -> str:
    lines = text.splitlines(keepends=True)
    head = next(i for i, ln in enumerate(lines) if ln.rstrip("\n") == f"  {calendar_id}:")
    end = next((i for i in range(head + 1, len(lines)) if re.match(r"^  \S", lines[i]) or re.match(r"^\S", lines[i])),
               len(lines))
    while end > head + 1 and not lines[end - 1].strip():
        end -= 1
    block = lines[head:end]
    found = False
    for i, ln in enumerate(block):
        if re.match(r"^    verified_through: ", ln):
            block[i] = f"    verified_through: {_yaml_str(new_through)}\n"
            found = True
    if not found:
        raise ValueError(f"日历 {calendar_id} 中没有 verified_through")
    if not any(re.match(r"^    checks:\s*$", ln) for ln in block):
        block.append("    # 每次延长核验范围追加一条，原条目不改写\n    checks:\n")
    item = [f"      - date: {_yaml_str(entry['date'])}\n"] + [
        f"        {k}: {_yaml_str(str(entry[k]))}\n"
        for k in ("from", "through", "dataset", "version", "content_hash", "evidence")]
    if block and not block[-1].endswith("\n"):
        block[-1] += "\n"
    return "".join(lines[:head] + block + item + lines[end:])


def _sources_text(text: str, source_id: str, record: dict[str, Any]) -> str:
    lines = text.splitlines(keepends=True)
    head = next(i for i, ln in enumerate(lines) if ln.rstrip("\n") == f"  - id: {source_id}")
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("  - id: ")), len(lines))
    while end > head + 1 and not lines[end - 1].strip():
        end -= 1
    keys = ("status", "use", "date", "valid_from", "valid_through", "evidence", "scope")
    item = [f"      - dataset: {record['dataset']}\n"] + [f"        {k}: {_yaml_str(str(record[k]))}\n" for k in keys]
    if lines[end - 1] and not lines[end - 1].endswith("\n"):
        lines[end - 1] += "\n"
    return "".join(lines[:end] + item + lines[end:])


def apply_proposal(root: Path, proposal: dict[str, Any], confirm: bool = False) -> dict[str, Any]:
    root = Path(root)
    if proposal.get("kind") != "calendar_extension" or not proposal.get("applicable"):
        raise ValueError("该建议没有可写入的延长")
    check = proposal["check"]
    reg = Registry.load(root)
    cal = reg.calendars[check["calendar"]]
    if cal.verified_through is None or cal.verified_through.date().isoformat() != check["current_verified_through"]:
        raise ValueError(f"建议已过时：日历当前核验到 {cal.verified_through.date() if cal.verified_through else '—'}，"
                         f"建议基于 {check['current_verified_through']}；请重新运行 iros calendar check")
    cal_path, src_path = root / "config" / "calendars.yaml", root / "config" / "sources.yaml"
    old_cal, old_src = cal_path.read_text(encoding="utf-8"), src_path.read_text(encoding="utf-8")
    new_cal = _calendar_text(old_cal, check["calendar"], check["proposed_verified_through"], proposal["calendar_entry"])
    new_src = old_src
    for item in proposal.get("use_records", []):
        new_src = _sources_text(new_src, item["source_id"], item["record"])
    summary = {"confirmed": confirm, "calendar": check["calendar"],
               "verified_through": [check["current_verified_through"], check["proposed_verified_through"]],
               "use_records": len(proposal.get("use_records", []))}
    if not confirm:
        summary["preview"] = {"calendars.yaml": _diff(old_cal, new_cal), "sources.yaml": _diff(old_src, new_src)}
        return summary
    cal_path.write_text(new_cal, encoding="utf-8")
    src_path.write_text(new_src, encoding="utf-8")
    try:
        after = Registry.load(root)
        through = after.calendars[check["calendar"]].verified_through.date().isoformat()
        if through != check["proposed_verified_through"]:
            raise ValueError(f"写入后日历核验到 {through}，与建议不符")
        for item in proposal.get("use_records", []):
            rec = item["record"]
            source = after.sources[item["source_id"]]
            if not any(v.status is VerificationStatus.USE_VERIFIED and v.dataset == rec["dataset"]
                       and v.valid_through and v.valid_through.isoformat() == rec["valid_through"]
                       for v in source.verification):
                raise ValueError(f"写入后找不到 {rec['dataset']} 的新用途核验记录")
    except Exception:
        cal_path.write_text(old_cal, encoding="utf-8")
        src_path.write_text(old_src, encoding="utf-8")
        raise
    return summary


def _diff(old: str, new: str) -> str:
    import difflib
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), n=1))
