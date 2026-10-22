"""美国财政部日度票面收益率曲线 CSV（按年下载）。"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

import pandas as pd

from ..contracts import DatasetSpec
from ..tenor import is_tenor, parse_tenor
from .base import (
    STAGING_COLUMNS,
    FetchError,
    HttpGet,
    ParsedPayload,
    RawPayload,
    empty_staging,
    fetch_with_retry,
    now_utc,
    urllib_get,
)

URL_TEMPLATE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&page&_format=csv"
)
SERIES_PREFIX = "UST_PAR_"


def series_id_for(tenor_code: str) -> str:
    return f"{SERIES_PREFIX}{tenor_code}"


class TreasuryParCurveConnector:
    name = "treasury_par_curve"

    def __init__(self, http_get: HttpGet = urllib_get, **retry: Any) -> None:
        self.http_get = http_get
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        start, end = _year_range(request)
        payloads = []
        for year in range(start, end + 1):
            url = URL_TEMPLATE.format(year=year)
            content = fetch_with_retry(url, self.http_get, **self.retry)
            if not content.strip().startswith(b"Date"):
                raise FetchError(f"{year} 年返回内容不是预期的 CSV（前 80 字节：{content[:80]!r}）")
            payloads.append(RawPayload(content=content, url=url, request={"year": year},
                                       retrieved_at=now_utc()))
        return payloads

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        text = payload.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header or header[0].strip() != "Date":
            raise FetchError("Treasury CSV 缺少 Date 列")
        columns = []
        series: dict[str, dict[str, Any]] = {}
        for idx, label in enumerate(header[1:], start=1):
            label = label.strip()
            if not is_tenor(label):
                continue  # 非期限列（如未来新增的说明列）不进入曲线
            tenor = parse_tenor(label)
            sid = series_id_for(tenor.code)
            columns.append((idx, sid))
            series[sid] = {"tenor": tenor.code, "tenor_months": tenor.months, "source_label": label}
        rows = []
        for record in reader:
            if not record or not record[0].strip():
                continue
            obs = _parse_us_date(record[0])
            for idx, sid in columns:
                raw = record[idx].strip() if idx < len(record) else ""
                rows.append((sid, obs, raw, None, None))
        if not rows:
            return ParsedPayload(empty_staging(), series)
        return ParsedPayload(pd.DataFrame(rows, columns=STAGING_COLUMNS), series)


def _parse_us_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%m/%d/%Y").date()


def _year_range(request: dict[str, Any]) -> tuple[int, int]:
    start = request.get("start")
    end = request.get("end")
    if start is None:
        raise ValueError("Treasury 下载需要 start（年份或日期）")
    start_year = int(str(start)[:4])
    end_year = int(str(end)[:4]) if end is not None else date.today().year
    if end_year < start_year:
        raise ValueError("end 早于 start")
    return start_year, end_year
