"""事件窗口的价格反应：市场模型异常收益与累计异常收益（方法卡 event-study-abnormal-return）。

首例是 NVIDIA 首席执行官离任与回任（事件事实见 config/events/nvda_ceo_transition_2026.yaml）。

用法：

    uv run python scripts/event_window_returns.py

只在本机运行，结果不进公开仓库、不上网站（用户 2026-11-27 决定）：
- 个股与 SPY、QQQ 的日度 K 线取自 legosmos 数据湖（用户自己的 IB 行情订阅，只供自用）。
  路径由环境变量 IROS_LEGOSMOS_DAILY_BARS 给出（指向 view=daily_bars 目录），也可写在项目根目录 .env。
- SMH 用发行商公布的每股净值（data/drawdown_replay/manual/etf_daily/SMH.csv，用户下载，只在本机），
  只作行业基准的敏感性比较。
- 输出写到 data/event_windows/（不入库），交给 company-dossiers 使用。

口径（MacKinlay 1997；卡没写的标“整理时补充”）：
- 收益：收盘价对收盘价的简单收益。K 线是 IB 的 TRADES（成交价，不含分红调整）；价格指数与净值也不含分红。
- 第 0 天：开盘前接受的申报以当天为第 0 天，收盘后接受的以下一交易日为第 0 天，非交易日以下一交易日为第 0 天
  （开盘前与非交易日两条是卡的整理时补充）。
- 估计窗口：第一个事件第 0 天之前第 -140 至 -21 个交易日（120 天，卡 p.15）；两个事件共用同一估计窗口，
  避免回任事件的参数被离任期间的收益污染（整理时补充）。
- 正常收益：市场模型 R = α + β·Rm（默认，卡第 4 步）；另报市场调整模型（R − Rm）作对照。
- CAR 的方差含参数估计误差（式 9、11）；θ = CAR / sd(CAR)。单次事件功效很低（卡第 6 步），θ 只作参考。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import date, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "event_windows"
SMH_NAV = ROOT / "data" / "drawdown_replay" / "manual" / "etf_daily" / "SMH.csv"
ENV_VAR = "IROS_LEGOSMOS_DAILY_BARS"

STUDY_ID = "event_window_nvda_ceo_transition_2026"
TICKER = "NVDA"
BENCHMARKS = ["SPY", "QQQ", "SMH"]
PRIMARY = "SPY"
EVENTS = [  # 申报接受时间取自 config/events/nvda_ceo_transition_2026.yaml
    {"id": "departure", "label": "离任 8-K", "accession": "0001045810-26-000082",
     "accepted_at": "2026-11-12T08:52:41-05:00"},
    {"id": "return", "label": "回任 8-K", "accession": "0001045810-26-000090",
     "accepted_at": "2026-11-23T08:57:54-05:00"},
]
EST_START, EST_END = -140, -21  # 相对第一个事件第 0 天的交易日
WINDOWS = [(0, 0), (0, 1), (-1, 1), (0, 2), (-5, -1), (-20, -1)]
AR_DAYS = (-5, 2)
OPEN, CLOSE = time(9, 30), time(16, 0)


# ---------- 纯计算（有测试） ----------

def day0_for(accepted_at: str, trading_days: list[date]) -> date:
    """申报接受时间 → 第 0 天（美东时间）。开盘前或交易时段：当天；收盘后：下一交易日；非交易日：下一交易日。"""
    ts = pd.Timestamp(accepted_at).tz_convert("America/New_York")
    d, t = ts.date(), ts.time()
    later = [x for x in trading_days if x > d]
    if d in trading_days and t < CLOSE:
        return d
    if not later:
        raise ValueError(f"{accepted_at} 之后没有交易日数据")
    return later[0]


def returns(prices: pd.Series) -> pd.Series:
    """按日期排序的价格 → 简单收益（第一天无收益，去掉）。"""
    s = prices.sort_index()
    return (s / s.shift(1) - 1).dropna()


def market_model(r: np.ndarray, rm: np.ndarray) -> dict[str, Any]:
    """OLS：r = α + β·rm + ε。返回参数、残差方差（除以 L1−2）与 (X'X)^-1。"""
    if len(r) != len(rm) or len(r) < 3:
        raise ValueError("估计窗口长度不足或个股与基准长度不一致")
    X = np.column_stack([np.ones(len(rm)), rm])
    xtx_inv = np.linalg.inv(X.T @ X)
    a, b = xtx_inv @ X.T @ r
    resid = r - (a + b * rm)
    s2 = float(resid @ resid / (len(r) - 2))
    ss_tot = float(((r - r.mean()) ** 2).sum())
    return {"alpha": float(a), "beta": float(b), "sigma2": s2, "xtx_inv": xtx_inv, "n": len(r),
            "r2": 1 - float(resid @ resid) / ss_tot if ss_tot else float("nan")}


def car_stats(r: np.ndarray, rm: np.ndarray, mm: dict[str, Any]) -> dict[str, float]:
    """事件窗口内的 CAR 及其方差；方差含参数估计误差：V = σ²(I + X*(X'X)^-1 X*')，Var(CAR) = 1'V1。"""
    ar = r - (mm["alpha"] + mm["beta"] * rm)
    Xs = np.column_stack([np.ones(len(rm)), rm])
    V = mm["sigma2"] * (np.eye(len(rm)) + Xs @ mm["xtx_inv"] @ Xs.T)
    var = float(np.ones(len(rm)) @ V @ np.ones(len(rm)))
    car = float(ar.sum())
    return {"car": car, "sd": var ** 0.5, "theta": car / var ** 0.5, "days": len(rm)}


def window_slice(index: list[date], day0: date, lo: int, hi: int) -> list[date] | None:
    """以第 0 天为原点、按交易日计的 [lo, hi]；超出数据范围返回 None。"""
    i = index.index(day0)
    if i + lo < 0 or i + hi >= len(index):
        return None
    return index[i + lo:i + hi + 1]


# ---------- 取数 ----------

def bars_root() -> Path:
    path = os.environ.get(ENV_VAR)
    env = ROOT / ".env"
    if not path and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(f"{ENV_VAR}="):
                path = line.split("=", 1)[1].strip()
    if not path:
        sys.exit(f"缺少 {ENV_VAR}（指向 legosmos 的 view=daily_bars 目录；写在环境变量或项目根目录 .env）")
    root = Path(path)
    if not root.is_dir():
        sys.exit(f"{ENV_VAR} 指向的目录不存在：{root}（共享盘是否已挂载？）")
    return root


def load_bars(root: Path, symbol: str) -> tuple[pd.Series, dict[str, Any]]:
    """读 legosmos 某只股票的全部日度分区，返回收盘价序列与输入指纹（文件数、合并哈希）。"""
    files = sorted(glob.glob(str(root / "date=*" / f"symbol={symbol}" / "exchange=*" / "part-*.parquet")))
    if not files:
        sys.exit(f"legosmos 里没有 {symbol} 的日度 K 线")
    frames, digest = [], hashlib.sha256()
    for f in files:
        b = Path(f).read_bytes()
        digest.update(hashlib.sha256(b).digest())
        frames.append(pd.read_parquet(f))
    df = pd.concat(frames)
    if df["trade_date"].duplicated().any():
        sys.exit(f"{symbol} 有重复交易日")
    flagged = int(df["data_quality_flag"].map(lambda x: len(x) if x is not None else 0).sum())
    s = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["trade_date"]).dt.date).sort_index()
    return s, {"files": len(files), "sha256_of_file_hashes": digest.hexdigest(), "first": str(s.index[0]),
               "last": str(s.index[-1]), "source": sorted(df["source"].unique().tolist()),
               "what_to_show": "TRADES", "quality_flags": flagged}


def load_nav(path: Path) -> tuple[pd.Series, dict[str, Any]]:
    df = pd.read_csv(path)
    s = pd.Series(df["nav_usd"].astype(float).values, index=pd.to_datetime(df["date"]).dt.date).sort_index()
    return s, {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "first": str(s.index[0]), "last": str(s.index[-1]), "kind": "发行商每股净值（不是成交价）"}


# ---------- 计算 ----------

def compute(prices: dict[str, pd.Series]) -> dict[str, Any]:
    r = returns(prices[TICKER])
    days = list(r.index)
    day0s = {e["id"]: day0_for(e["accepted_at"], days) for e in EVENTS}
    est = window_slice(days, day0s[EVENTS[0]["id"]], EST_START, EST_END)
    if est is None:
        raise ValueError("估计窗口超出个股数据范围")
    out: dict[str, Any] = {"day0": {k: str(v) for k, v in day0s.items()},
                           "estimation_window": {"start": str(est[0]), "end": str(est[-1]), "days": len(est),
                                                 "relative_to": EVENTS[0]["id"], "range": [EST_START, EST_END]},
                           "benchmarks": {}}
    for bench in BENCHMARKS:
        if bench not in prices:
            continue
        rm_all = returns(prices[bench])
        common = [d for d in days if d in rm_all.index]
        missing_est = [d for d in est if d not in rm_all.index]
        if missing_est:
            out["benchmarks"][bench] = {"skipped": f"估计窗口缺 {len(missing_est)} 天基准收益"}
            continue
        mm = market_model(r.loc[est].values, rm_all.loc[est].values)
        res: dict[str, Any] = {"model": {k: mm[k] for k in ("alpha", "beta", "sigma2", "r2", "n")}, "events": {}}
        for e in EVENTS:
            d0 = day0s[e["id"]]
            ev: dict[str, Any] = {"ar": {}, "car": {}, "car_market_adjusted": {}}
            lo, hi = AR_DAYS
            for k in range(lo, hi + 1):
                w = window_slice(common, d0, k, k)
                if w:
                    ev["ar"][str(k)] = {"date": str(w[0]), "r": float(r[w[0]]), "rm": float(rm_all[w[0]]),
                                        "ar": float(r[w[0]] - mm["alpha"] - mm["beta"] * rm_all[w[0]])}
            for lo, hi in WINDOWS:
                w = window_slice(common, d0, lo, hi)
                key = f"[{lo},{hi}]"
                if w is None:
                    ev["car"][key] = None
                    continue
                ev["car"][key] = car_stats(r.loc[w].values, rm_all.loc[w].values, mm)
                ev["car_market_adjusted"][key] = float((r.loc[w] - rm_all.loc[w]).sum())
            res["events"][e["id"]] = ev
        # 离任第 0 天到回任次日，整段的累计异常收益
        w = [d for d in common if day0s["departure"] <= d <= day0s["return"]]
        nxt = window_slice(common, day0s["return"], 1, 1)
        if nxt:
            w = w + nxt
        res["span_departure_to_return_plus1"] = car_stats(r.loc[w].values, rm_all.loc[w].values, mm) | {
            "start": str(w[0]), "end": str(w[-1])}
        out["benchmarks"][bench] = res
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args()
    root = bars_root()
    prices, inputs = {}, {}
    for sym in [TICKER, "SPY", "QQQ"]:
        prices[sym], inputs[sym] = load_bars(root, sym)
    if SMH_NAV.exists():
        prices["SMH"], inputs["SMH"] = load_nav(SMH_NAV)
    result = {
        "study": STUDY_ID, "method_card": "event-study-abnormal-return", "ticker": TICKER,
        "primary_benchmark": PRIMARY, "events": EVENTS, "inputs": inputs,
        "rules": {"returns": "收盘对收盘简单收益；TRADES 成交价与净值都不含分红调整",
                  "day0": "开盘前或交易时段接受：当天；收盘后：下一交易日；非交易日：下一交易日（后两条为整理时补充）",
                  "estimation": "第一个事件第 0 天前 -140 至 -21 个交易日，两个事件共用",
                  "variance": "含参数估计误差（MacKinlay 式 9、11）"},
        "limitations": [
            "单家公司单次事件，检验功效很低；θ 只作参考（卡第 6 步）。",
            "NVDA 在 SPY、QQQ、SMH 里都是大权重，基准含事件公司本身，异常收益会被低估（卡待补充 G01，没有处理）。",
            "收益不含分红：估计窗口里的基准除息日会略压低 α；NVDA 的季度分红很小。",
            "SMH 用发行商每股净值，不是收盘价。",
            "回任事件之后只有两个交易日数据（到 2026-11-25）。",
            "离任与回任之间还有其他市场事件（2026-11 的市场下跌），市场模型只扣掉了与基准同步的部分。",
        ],
        **compute(prices),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{STUDY_ID}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    p = result["benchmarks"][PRIMARY]
    print(f"wrote {path.relative_to(ROOT)}；估计窗口 {result['estimation_window']['start']}–"
          f"{result['estimation_window']['end']}；{PRIMARY} β={p['model']['beta']:.2f} R²={p['model']['r2']:.2f}")


if __name__ == "__main__":
    main()
