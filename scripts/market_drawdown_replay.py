"""市场下跌层级诊断的历史事件回放：取数与计算（方法卡 market-drawdown-layer-diagnosis 的执行实测）。

用法（需要项目根目录 .env 里的 FRED_API_KEY）：

    uv run python scripts/market_drawdown_replay.py            # 取数（有缓存则复用）并计算
    uv run python scripts/market_drawdown_replay.py --offline  # 只用缓存计算

时点规则（每个观察时点 D 只用 D 当天收盘后已经公布的数据）：

- 日度行情收盘值（利率、利差、VIX、指数、比特币）：取当前版本，观测日 ≤ D。这类序列不做修订。
- 周度或有修订的序列（NFCI 及其分项、STLFSI4、美元广义指数）：D 不早于该序列在 ALFRED 的
  首个版本日时，取 realtime_start = realtime_end = D 的历史版本（当时实际公布的值）；早于首个
  版本日时，只能取当前版本并按发布滞后截断（观测日 ≤ D − 滞后天数），并标 post_hoc_vintage。
- French 12 行业月度收益只在本机（data/normalized/），是当前版本且按月，回放时点当时还没有公布，
  一律标 post_hoc，只作事后对照。

缓存写在 data/drawdown_replay/（不入库）；输出写在 methodology/records/market-drawdown-replay-metrics.json
（只含每个时点的汇总值，不含原始序列；标普 500、纳斯达克、比特币有版权，只留百分比变化）。
French 月度对照写在本机 data/drawdown_replay/french_monthly_post_hoc.json。不取 ICE 高收益债利差（BAMLH0A0HYM2 等）。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "drawdown_replay"
OUT = ROOT / "methodology" / "records" / "market-drawdown-replay-metrics.json"
API = "https://api.stlouisfed.org/fred/"
EXCLUDED = {"BAMLH0A0HYM2", "BAMLH0A3HYC"}  # ICE：许可受限、只保留 3 年历史，不用于回放

# 序列 → (类型, 发布滞后天数, ALFRED 首个版本日)。首个版本日来自 series/vintagedates，2026-11-26 查询。
SERIES: dict[str, tuple[str, int, str | None]] = {
    "DGS10": ("daily", 0, None),
    "DFII10": ("daily", 0, None),
    "BAA10Y": ("daily", 0, None),
    "VIXCLS": ("daily", 0, None),
    "VXVCLS": ("daily", 0, None),
    "TEDRATE": ("daily", 0, None),
    "CBBTCUSD": ("daily", 0, None),
    "NASDAQCOM": ("daily", 0, None),
    "SP500": ("daily", 0, None),
    "DTWEXBGS": ("vintaged", 7, "2019-02-04"),
    "DEXJPUS": ("vintaged", 7, "2014-03-18"),
    "NFCI": ("vintaged", 5, "2011-05-25"),
    "NFCILEVERAGE": ("vintaged", 5, "2011-05-25"),
    "NFCICREDIT": ("vintaged", 5, "2011-05-25"),
    "NFCIRISK": ("vintaged", 5, "2011-05-25"),
    "STLFSI4": ("vintaged", 6, "2022-11-10"),
}

EVENTS: list[dict[str, Any]] = [
    {"id": "E1", "name": "2022 年加息熊市", "peak": "2022-01-03", "trough": "2022-10-12",
     "index": "SP500", "obs": ["2022-02-03", "2022-06-16", "2022-10-12"]},
    {"id": "E2", "name": "2008 年金融危机", "peak": "2007-10-09", "trough": "2009-03-09",
     "index": "NASDAQCOM", "obs": ["2008-09-19", "2008-10-10", "2009-03-09"]},
    {"id": "E3", "name": "2020 年 3 月", "peak": "2020-02-19", "trough": "2020-03-23",
     "index": "SP500", "obs": ["2020-03-09", "2020-03-18", "2020-03-23"]},
    {"id": "E4", "name": "2024 年 8 月日元套息平仓", "peak": "2024-07-10", "trough": "2024-08-19",
     "index": "SP500", "obs": ["2024-08-02", "2024-08-05", "2024-08-19"]},
]

# 最近观测距截止日超过这么多天，视为当时没有可用值（如 TEDRATE 2022-01 停更）
STALE_DAYS = 21

# 数据窗口：每个事件从见顶前一年到最后观察时点（百分位用 1986 年起的全历史）
FULL_HISTORY_START = "1986-01-01"
FRENCH_INDUSTRIES = ["Utils", "NoDur", "Hlth", "Money"]
# 有版权、只在本机使用的价格序列：公开输出只留百分比变化，不留水平值
LEVELS_LOCAL_ONLY = {"SP500", "NASDAQCOM", "CBBTCUSD"}
FRENCH_LOCAL = CACHE / "french_monthly_post_hoc.json"  # French 不再分发原始收益，只写本机


# ---------- 纯计算（有测试） ----------

def parse_obs(payload: dict[str, Any]) -> list[tuple[str, float]]:
    """FRED observations JSON → [(日期, 值)]，跳过 '.' 缺值。"""
    rows = []
    for o in payload.get("observations", []):
        v = o.get("value", ".")
        if v not in (".", ""):
            rows.append((o["date"], float(v)))
    return rows


def last_on_or_before(rows: list[tuple[str, float]], d: str) -> tuple[str, float] | None:
    best = None
    for day, v in rows:
        if day <= d:
            best = (day, v)
        else:
            break
    return best


def cutoff_for(kind: str, lag: int, first_vintage: str | None, asof: str) -> tuple[str, str]:
    """返回 (观测截止日, 版本口径)。版本口径：current / alfred / post_hoc_vintage。"""
    if kind == "daily":
        return asof, "current"
    if first_vintage and asof >= first_vintage:
        return asof, "alfred"
    return (date.fromisoformat(asof) - timedelta(days=lag)).isoformat(), "post_hoc_vintage"


def is_stale(obs_date: str, cutoff: str, days: int = STALE_DAYS) -> bool:
    return (date.fromisoformat(cutoff) - date.fromisoformat(obs_date)).days > days


def pct_change(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or a == 0:
        return None
    return round((b / a - 1) * 100, 2)


def diff(a: float | None, b: float | None, scale: float = 1.0) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a) * scale, 2)


def percentile_rank(rows: list[tuple[str, float]], d: str, value: float) -> float | None:
    hist = [v for day, v in rows if day <= d]
    if not hist:
        return None
    return round(100 * sum(1 for v in hist if v <= value) / len(hist), 1)


def max_drawdown_to(rows: list[tuple[str, float]], peak: str, d: str) -> float | None:
    seg = [v for day, v in rows if peak <= day <= d]
    if not seg:
        return None
    return round((min(seg) / seg[0] - 1) * 100, 2)


# ---------- 取数 ----------

def api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("FRED_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("缺少 FRED_API_KEY（放在项目根目录 .env）")
    return key


def fetch_json(endpoint: str, params: dict[str, str], cache_file: Path, offline: bool) -> dict[str, Any]:
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    if offline:
        raise FileNotFoundError(f"离线模式缺少缓存 {cache_file.relative_to(ROOT)}")
    q = dict(params, api_key=api_key(), file_type="json")
    url = API + endpoint + "?" + urllib.parse.urlencode(q)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                payload = json.load(r)
            break
        except Exception:  # noqa: BLE001 — 重试后再抛
            if attempt == 2:
                raise
            time.sleep(3)
    time.sleep(0.6)  # FRED 限 120 次/分钟
    payload.pop("api_key", None)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload))
    return payload


def series_rows(series: str, realtime: str | None, start: str, end: str, offline: bool) -> list[tuple[str, float]]:
    assert series not in EXCLUDED
    params = {"series_id": series, "observation_start": start, "observation_end": end}
    tag = "current"
    if realtime:
        params.update(realtime_start=realtime, realtime_end=realtime)
        tag = f"rt{realtime}"
    f = CACHE / series / f"{tag}_{start}_{end}.json"
    return parse_obs(fetch_json("series/observations", params, f, offline))


def french_monthly() -> dict[str, dict[str, float]]:
    """本机 French 12 行业价值加权月收益与市场月收益（%）。没有本机数据时返回空。"""
    try:
        import pandas as pd
    except ImportError:
        return {}
    out: dict[str, dict[str, float]] = {}
    files = sorted(glob.glob(str(ROOT / "data/normalized/french_ind12_vw/*.parquet")))
    ff = sorted(glob.glob(str(ROOT / "data/normalized/french_ff3/*.parquet")))
    if not files or not ff:
        return {}
    ind = pd.read_parquet(files[-1])
    for ind_name in FRENCH_INDUSTRIES:
        s = ind[ind.series_id == f"IND12VW_{ind_name}"]
        out[ind_name] = {str(r.observation_at)[:7]: float(r.value) for r in s.itertuples()}
    f3 = pd.read_parquet(ff[-1])
    mkt = f3[f3.series_id == "FF3_Mkt-RF"].set_index("observation_at").value
    rf = f3[f3.series_id == "FF3_RF"].set_index("observation_at").value
    out["Mkt"] = {str(k)[:7]: round(float(mkt[k] + rf[k]), 2) for k in mkt.index if k in rf.index}
    out["_versions"] = {"ind12": Path(files[-1]).stem, "ff3": Path(ff[-1]).stem}  # type: ignore[assignment]
    return out


# ---------- 计算 ----------

def months_between(a: str, b: str) -> list[str]:
    y, m = int(a[:4]), int(a[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= b[:7]:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def compute(offline: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    french = french_monthly()
    result: dict[str, Any] = {
        "generated_by": "scripts/market_drawdown_replay.py",
        "method_card": "market-drawdown-layer-diagnosis",
        "point_in_time_rule": "见脚本文档字符串",
        "french_versions": french.pop("_versions", None) if french else None,
        "french_monthly_post_hoc": "本机 data/drawdown_replay/french_monthly_post_hoc.json（不入库）",
        "events": [],
    }
    french_out: dict[str, Any] = {}
    for ev in EVENTS:
        last_obs = ev["obs"][-1]
        win_start = (date.fromisoformat(ev["peak"]) - timedelta(days=370)).isoformat()
        current: dict[str, list[tuple[str, float]]] = {}
        for s, (kind, _lag, _fv) in SERIES.items():
            start = FULL_HISTORY_START if s in ("BAA10Y", "VIXCLS", "NFCI", "TEDRATE") else win_start
            try:
                current[s] = series_rows(s, None, start, last_obs, offline)
            except Exception as e:  # noqa: BLE001 — 记缺口，不中断
                current[s] = []
                print(f"[gap] {ev['id']} {s}: {e}", file=sys.stderr)
        idx = ev["index"]
        peak_px = last_on_or_before(current[idx], ev["peak"])
        points = []
        for d in ev["obs"]:
            p: dict[str, Any] = {"as_of": d, "values": {}}
            for s, (kind, lag, fv) in SERIES.items():
                cut, basis = cutoff_for(kind, lag, fv, d)
                if basis == "alfred":
                    start = FULL_HISTORY_START if s == "NFCI" else win_start
                    try:
                        rows = series_rows(s, d, start, d, offline)
                    except Exception as e:  # noqa: BLE001
                        print(f"[gap] {ev['id']} {s}@{d}: {e}", file=sys.stderr)
                        rows = []
                else:
                    rows = current[s]
                now = last_on_or_before(rows, cut)
                if now is None or is_stale(now[0], cut):
                    p["values"][s] = {"basis": basis, "missing": True,
                                      "last_obs": now[0] if now else None}
                    continue
                at_peak = last_on_or_before(rows, ev["peak"])
                a20 = last_on_or_before(rows, (date.fromisoformat(now[0]) - timedelta(days=28)).isoformat())
                a5 = last_on_or_before(rows, (date.fromisoformat(now[0]) - timedelta(days=7)).isoformat())
                v: dict[str, Any] = {"basis": basis, "obs_date": now[0], "value": now[1],
                                     "at_peak": at_peak[1] if at_peak else None}
                if s in ("DGS10", "DFII10", "BAA10Y", "TEDRATE"):
                    v["chg_since_peak_bp"] = diff(v["at_peak"], now[1], 100)
                    v["chg_4w_bp"] = diff(a20[1] if a20 else None, now[1], 100)
                    v["chg_1w_bp"] = diff(a5[1] if a5 else None, now[1], 100)
                elif s in ("NFCI", "NFCILEVERAGE", "NFCICREDIT", "NFCIRISK", "STLFSI4", "VIXCLS", "VXVCLS"):
                    v["chg_since_peak"] = diff(v["at_peak"], now[1])
                    v["chg_4w"] = diff(a20[1] if a20 else None, now[1])
                    v["chg_1w"] = diff(a5[1] if a5 else None, now[1])
                else:
                    v["pct_since_peak"] = pct_change(v["at_peak"], now[1])
                    v["pct_4w"] = pct_change(a20[1] if a20 else None, now[1])
                    v["pct_1w"] = pct_change(a5[1] if a5 else None, now[1])
                if s in ("BAA10Y", "VIXCLS", "NFCI", "TEDRATE"):
                    v["pctile_since_1986"] = percentile_rank(rows, cut, now[1])
                if s in LEVELS_LOCAL_ONLY:
                    v.pop("value"); v.pop("at_peak")
                p["values"][s] = v
            vix, vxv = p["values"].get("VIXCLS", {}), p["values"].get("VXVCLS", {})
            if vix.get("value") and vxv.get("value"):
                p["vix_over_vix3m"] = round(vix["value"] / vxv["value"], 3)
            if peak_px:
                p["index_drawdown_from_peak_pct"] = max_drawdown_to(current[idx], ev["peak"], d)
            points.append(p)
        fr = {}
        if french:
            for m in months_between(ev["peak"], ev["trough"]):
                fr[m] = {k: french[k].get(m) for k in ["Mkt", *FRENCH_INDUSTRIES]}
        result["events"].append({
            "id": ev["id"], "name": ev["name"], "peak": ev["peak"], "trough": ev["trough"],
            "index": idx, "index_peak_date": peak_px[0] if peak_px else None, "points": points,
        })
        french_out[ev["id"]] = fr
    return result, french_out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    res, french = compute(args.offline)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    FRENCH_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    FRENCH_LOCAL.write_text(json.dumps(french, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} and {FRENCH_LOCAL.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
