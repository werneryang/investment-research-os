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
French 月度对照写在本机 data/drawdown_replay/french_monthly_post_hoc.json。

补充数据（用户 2026-11-26 手动下载，放在 data/drawdown_replay/manual/，不入库）：World Gold Council
金价、发行商公布的 ETF 每股净值（SPY、XLU、XLP、XLV、XLF、HYG）、FINRA 保证金债务 Excel。净值不是
成交价，看不到市价折价；净值在除息日下跌，日收益含分红影响。保证金债务按月末后 31 天才算已发布取月份，
只有当前版本，标 post_hoc_vintage。公开输出只留百分比与比值，不留水平值。不取 ICE 高收益债利差（BAMLH0A0HYM2 等）。
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
    "DEXTAUS": ("vintaged", 7, "2014-03-18"),
    "DEXKOUS": ("vintaged", 7, "2014-03-18"),
    "NASDAQ100": ("daily", 0, None),
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
    # 复现：卡的来源视频分析的同一段行情（来源偏差最强），不是独立检验。11-26 感恩节休市，最后时点用 11-25。
    {"id": "E5", "name": "2026 年 10–11 月（复现）", "peak": "2026-10-06", "trough": "2026-11-25",
     "index": "SP500", "obs": ["2026-11-06", "2026-11-12", "2026-11-20", "2026-11-23", "2026-11-25"],
     "ice_local": True},
]

# 最近观测距截止日超过这么多天，视为当时没有可用值（如 TEDRATE 2022-01 停更）
STALE_DAYS = 21

# 数据窗口：每个事件从见顶前一年到最后观察时点（百分位用 1986 年起的全历史）
FULL_HISTORY_START = "1986-01-01"
FRENCH_INDUSTRIES = ["Utils", "NoDur", "Hlth", "Money"]
# 有版权、只在本机使用的价格序列：公开输出只留百分比变化，不留水平值
LEVELS_LOCAL_ONLY = {"SP500", "NASDAQCOM", "NASDAQ100", "CBBTCUSD"}
# ICE 高收益债利差：只在 3 年窗口内的复现（E5）取，数值只写本机文件，不进公开输出
ICE_SERIES = ["BAMLH0A0HYM2", "BAMLH0A3HYC"]
ICE_LOCAL = CACHE / "ice_local_E5.json"
FRENCH_LOCAL = CACHE / "french_monthly_post_hoc.json"  # French 不再分发原始收益，只写本机

# 用户手动下载、只在本机的补充数据（2026-11-26 下载；不入库，公开输出只留百分比与比值）
MANUAL = CACHE / "manual"
ETF_DEFENSIVE = ["XLU", "XLP", "XLV"]
ETF_ALL = ["SPY", *ETF_DEFENSIVE, "XLF", "HYG", "XLK", "SMH"]
# 每股净值的拆分断点（用户提供）：拆分日之前的净值除以比例，换成拆分后的口径
SPLITS = {"XLU": [("2025-12-05", 2.0)], "XLK": [("2025-12-05", 2.0)]}
NVDA_FILE = MANUAL / "NVDA.csv"  # 纳斯达克官网日收盘价（用户下载，未复权），只在本机
NVDA_LOCAL = CACHE / "nvda_event_windows_local.json"  # 只在本机，不进公开汇总
NVDA_EVENTS = {"resignation": "2026-11-12", "reinstatement": "2026-11-23"}  # 公告均在开盘前，第 0 天为公告当天
DOWN_DAY_WINDOW = 20      # 最近 20 个交易日里看标普下跌日（执行者自定，卡没有给窗口）
FINRA_LAG_DAYS = 31       # 月度保证金债务：月末后 31 天才算已发布（保守；FINRA 一般在次月第三周发布）


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


def daily_returns(rows: list[tuple[str, float]]) -> dict[str, float]:
    return {rows[i][0]: rows[i][1] / rows[i - 1][1] - 1 for i in range(1, len(rows))}


def down_day_stats(base: dict[str, float], others: dict[str, dict[str, float]], end: str,
                   n: int = DOWN_DAY_WINDOW) -> dict[str, Any] | None:
    """最近 n 个 base 交易日中 base 下跌的日子：各序列平均日收益与 base 的比值、同跌比例。"""
    days = sorted(d for d in base if d <= end)[-n:]
    down = [d for d in days if base[d] < 0]
    if not down:
        return {"window_days": len(days), "down_days": 0}
    b = sum(base[d] for d in down) / len(down)
    out: dict[str, Any] = {"window_days": len(days), "down_days": len(down),
                           "base_mean_pct": round(b * 100, 2)}
    for name, r in others.items():
        common = [d for d in down if d in r]
        if not common:
            continue
        m = sum(r[d] for d in common) / len(common)
        out[name] = {"mean_pct": round(m * 100, 2), "ratio_to_base": round(m / b, 2),
                     "share_also_down": round(sum(1 for d in common if r[d] < 0) / len(common), 2),
                     "days": len(common)}
    return out


def month_end(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def latest_published_month(months: list[str], as_of: str, lag: int = FINRA_LAG_DAYS) -> str | None:
    ok = [m for m in sorted(months) if month_end(m) + timedelta(days=lag) <= date.fromisoformat(as_of)]
    return ok[-1] if ok else None


def shift_month(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) + k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def load_csv(path: Path) -> list[tuple[str, float]]:
    import csv
    with path.open() as f:
        r = csv.reader(f)
        next(r)
        return sorted((row[0], float(row[1])) for row in r if row and row[1].strip())


def apply_splits(rows: list[tuple[str, float]], splits: list[tuple[str, float]]) -> list[tuple[str, float]]:
    out = rows
    for day, ratio in splits:
        out = [(d, v / ratio if d < day else v) for d, v in out]
    return out


def load_manual() -> dict[str, Any]:
    out: dict[str, Any] = {}
    g = MANUAL / "gold_daily.csv"
    if g.exists():
        out["GOLD"] = load_csv(g)
    for t in ETF_ALL:
        f = MANUAL / "etf_daily" / f"{t}.csv"
        if f.exists():
            out[t] = apply_splits(load_csv(f), SPLITS.get(t, []))
    x = MANUAL / "finra_margin_statistics.xlsx"
    if x.exists():
        import pandas as pd
        df = pd.read_excel(x, header=0)
        col = [c for c in df.columns if str(c).startswith("Debit Balances")][0]
        out["MARGIN"] = {str(r["Year-Month"])[:7]: float(r[col]) for _, r in df.iterrows()
                         if str(r["Year-Month"])[:4].isdigit()}
    return out


def manual_point(man: dict[str, Any], peak: str, d: str) -> dict[str, Any]:
    """一个观察时点的补充指标（日度数据取观测日 ≤ d，保证金债务按发布滞后取月份）。"""
    res: dict[str, Any] = {}
    for k in ["GOLD", *ETF_ALL]:
        rows = man.get(k)
        if not rows:
            res[k] = {"missing": True}
            continue
        now = last_on_or_before(rows, d)
        if now is None or is_stale(now[0], d):
            res[k] = {"missing": True}
            continue
        pk = last_on_or_before(rows, peak)
        a20 = last_on_or_before(rows, (date.fromisoformat(now[0]) - timedelta(days=28)).isoformat())
        a5 = last_on_or_before(rows, (date.fromisoformat(now[0]) - timedelta(days=7)).isoformat())
        res[k] = {"obs_date": now[0], "basis": "nav" if k in ETF_ALL else "spot",
                  "pct_since_peak": pct_change(pk[1] if pk else None, now[1]),
                  "pct_4w": pct_change(a20[1] if a20 else None, now[1]),
                  "pct_1w": pct_change(a5[1] if a5 else None, now[1]),
                  "max_drawdown_since_peak_pct": max_drawdown_to(rows, peak, d)}
    if man.get("SPY"):
        base = daily_returns(man["SPY"])
        others = {k: daily_returns(man[k]) for k in [*ETF_DEFENSIVE, "XLF", "GOLD"] if man.get(k)}
        if all(k in others for k in ETF_DEFENSIVE):
            common = set.intersection(*(set(others[k]) for k in ETF_DEFENSIVE))
            others["DEFENSIVE_AVG"] = {x: sum(others[k][x] for k in ETF_DEFENSIVE) / 3 for x in common}
        res["spy_down_days_last20"] = down_day_stats(base, others, d)
        if man.get("SMH") and last_on_or_before(man["SMH"], d) and not is_stale(last_on_or_before(man["SMH"], d)[0], d):
            # 卡的第 2 步：主跌板块（半导体）跌的日子，大盘和防御股撑不撑得住
            smh = daily_returns(man["SMH"])
            res["smh_down_days_last20"] = down_day_stats(
                smh, {k: v for k, v in {**others, "SPY": base}.items() if k != "XLF"}, d)
        for k in ["XLU", "XLP", "XLV", "XLF", "HYG", "GOLD", "XLK", "SMH"]:
            if not res.get(k, {}).get("missing") and not res["SPY"].get("missing"):
                res[k]["rel_to_spy_since_peak_pp"] = diff(res["SPY"]["pct_since_peak"], res[k]["pct_since_peak"])
                res[k]["rel_to_spy_4w_pp"] = diff(res["SPY"]["pct_4w"], res[k]["pct_4w"])
    m = man.get("MARGIN")
    if m:
        cur = latest_published_month(list(m), d)
        pkm = latest_published_month(list(m), peak)
        if cur:
            g = lambda k: m.get(shift_month(cur, k))  # noqa: E731
            res["MARGIN_DEBIT"] = {"month_used": cur, "basis": "post_hoc_vintage",
                                   "peak_month_used": pkm,
                                   "pct_1m": pct_change(g(-1), m[cur]), "pct_3m": pct_change(g(-3), m[cur]),
                                   "pct_12m": pct_change(g(-12), m[cur]),
                                   "pct_since_peak_month": pct_change(m.get(pkm) if pkm else None, m[cur])}
            if man.get("SPY") and pkm:
                spy = man["SPY"]
                a = last_on_or_before(spy, month_end(pkm).isoformat())
                b = last_on_or_before(spy, month_end(cur).isoformat())
                a3 = last_on_or_before(spy, month_end(shift_month(cur, -3)).isoformat())
                res["MARGIN_DEBIT"]["spy_nav_pct_same_months"] = pct_change(a[1] if a else None, b[1] if b else None)
                res["MARGIN_DEBIT"]["spy_nav_pct_3m_same_months"] = pct_change(a3[1] if a3 else None, b[1] if b else None)
    return res


def window_return(rows: list[tuple[str, float]], day0: str, start: int, end: int) -> float | None:
    """第 start 到第 end 个交易日的累计收益（第 0 天为 day0，起点取第 start−1 天收盘）。"""
    days = [d for d, _ in rows]
    if day0 not in days:
        return None
    i = days.index(day0)
    a, b = i + start - 1, i + end
    if a < 0 or b >= len(rows):
        return None
    return round((rows[b][1] / rows[a][1] - 1) * 100, 2)


def nvda_windows(man: dict[str, Any]) -> dict[str, Any]:
    if not NVDA_FILE.exists():
        return {"missing": True}
    nv = load_csv(NVDA_FILE)
    out: dict[str, Any] = {}
    for name, d0 in NVDA_EVENTS.items():
        w: dict[str, Any] = {"day0": d0}
        for lab, (a, b) in {"d0": (0, 0), "d0_d1": (0, 1), "dm1_d1": (-1, 1)}.items():
            r = {"NVDA": window_return(nv, d0, a, b)}
            for bench in ["SPY", "SMH"]:
                if man.get(bench):
                    r[bench] = window_return(man[bench], d0, a, b)
                    if r["NVDA"] is not None and r[bench] is not None:
                        r[f"NVDA_minus_{bench}"] = round(r["NVDA"] - r[bench], 2)
            w[lab] = r
        out[name] = w
    return out


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


def series_rows(series: str, realtime: str | None, start: str, end: str, offline: bool,
                allow_ice: bool = False) -> list[tuple[str, float]]:
    assert allow_ice or series not in EXCLUDED
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
    ice_out: dict[str, Any] = {}
    man = load_manual()
    result["manual_inputs"] = {k: ("present" if man.get(k) else "missing") for k in ["GOLD", *ETF_ALL, "MARGIN"]}
    for ev in EVENTS:
        last_obs = ev["obs"][-1]
        win_start = (date.fromisoformat(ev["peak"]) - timedelta(days=370)).isoformat()
        current: dict[str, list[tuple[str, float]]] = {}
        for s, (kind, _lag, _fv) in SERIES.items():
            start = FULL_HISTORY_START if s in ("BAA10Y", "VIXCLS", "NFCI", "TEDRATE") else win_start
            if s == "NASDAQ100" and ev["id"] != "E5":
                current[s] = []
                continue
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
            if man:
                p["manual"] = manual_point(man, ev["peak"], d)
            if ev.get("ice_local"):
                for s_ in ICE_SERIES:
                    rows = series_rows(s_, None, "2024-01-01", last_obs, offline, allow_ice=True)
                    now = last_on_or_before(rows, d)
                    pk = last_on_or_before(rows, ev["peak"])
                    ice_out.setdefault(ev["id"], {}).setdefault(d, {})[s_] = {
                        "obs_date": now[0] if now else None, "value": now[1] if now else None,
                        "at_peak": pk[1] if pk else None,
                        "max_since_2024": max((v for day, v in rows if day <= d), default=None)}
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
    if man:
        # NVDA 事件窗口只写本机（用户 2026-11-27 决定：事件价格结果只留本机和私有仓库），不进公开汇总
        NVDA_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        NVDA_LOCAL.write_text(json.dumps(nvda_windows(man), ensure_ascii=False, indent=1) + "\n")
    ICE_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    ICE_LOCAL.write_text(json.dumps(ice_out, ensure_ascii=False, indent=1) + "\n")
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
