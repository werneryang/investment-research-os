"""测试夹具：离线运行，网络请求由假的 http_get 提供。"""

from __future__ import annotations

import shutil
import urllib.error
from pathlib import Path

import pytest

from investment_os.connectors.fred import FredGraphCsvConnector
from investment_os.connectors.treasury import URL_TEMPLATE, TreasuryParCurveConnector
from investment_os.data import DataStore, ingest
from investment_os.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 2023 年末与 2024 年初的结构（含 4 Mo），2024 年 1 月 15 日为假日不出现
TREASURY_2024 = """Date,"1 Mo","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
01/05/2024,5.54,5.51,5.48,5.43,5.24,4.84,4.40,4.18,4.01,4.03,4.05,4.37,4.21
01/04/2024,5.55,5.51,5.47,5.41,5.25,4.84,4.38,4.17,3.99,4.00,3.99,4.31,4.14
01/03/2024,5.54,5.51,5.48,5.42,5.25,4.81,4.33,4.09,3.90,3.92,3.91,4.24,4.07
01/02/2024,5.55,5.54,5.46,5.41,5.24,4.80,4.33,4.09,3.93,3.95,3.95,4.25,4.08
"""

# 2025 年新增 1.5 Month 列
TREASURY_2025 = """Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
01/03/2025,4.41,4.40,4.36,4.33,4.29,4.25,4.18,4.28,4.33,4.42,4.53,4.60,4.86,4.82
01/02/2025,4.41,4.39,4.36,4.33,4.30,4.24,4.17,4.25,4.29,4.38,4.47,4.57,4.86,4.79
"""

DGS10_2024 = """observation_date,DGS10
2024-01-02,3.95
2024-01-03,3.91
2024-01-04,3.99
2024-01-05,4.05
"""


class FakeHttp:
    """按 URL 返回预设内容；未登记的 URL 视为网络错误。"""

    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        resp = self.responses.get(url)
        if resp is None:
            raise urllib.error.URLError(f"no route to {url}")
        if isinstance(resp, Exception):
            raise resp
        return resp


def treasury_url(year: int) -> str:
    return URL_TEMPLATE.format(year=year)


def dgs10_url(start: str, end: str) -> str:
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd={start}&coed={end}"


NO_RETRY = {"attempts": 1, "sleep": lambda s: None}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """临时项目根：复制真实 config，数据与运行记录写在临时目录。"""
    shutil.copytree(PROJECT_ROOT / "config", tmp_path / "config")
    return tmp_path


@pytest.fixture
def registry(project: Path) -> Registry:
    return Registry.load(project)


@pytest.fixture
def store(project: Path) -> DataStore:
    return DataStore(project)


def treasury_connector(responses: dict[int, str | Exception]) -> TreasuryParCurveConnector:
    http = FakeHttp({treasury_url(y): (v.encode() if isinstance(v, str) else v)
                     for y, v in responses.items()})
    return TreasuryParCurveConnector(http_get=http, **NO_RETRY)


def dgs10_connector(start: str, end: str, body: str = DGS10_2024) -> FredGraphCsvConnector:
    return FredGraphCsvConnector(http_get=FakeHttp({dgs10_url(start, end): body.encode()}), **NO_RETRY)


@pytest.fixture
def loaded(project, registry, store):
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: TREASURY_2024}))
    ingest(registry, store, "fred_dgs10", {"start": "2024-01-01", "end": "2024-01-05"},
           dgs10_connector("2024-01-01", "2024-01-05"))
    return project
