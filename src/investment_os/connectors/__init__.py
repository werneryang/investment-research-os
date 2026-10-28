"""来源适配器。新来源实现 Connector 接口并在此注册（architecture §9.2）。"""

from __future__ import annotations

from typing import Any

from .base import Connector, FetchError, ParsedPayload, RawPayload
from .damodaran import DamodaranXlsConnector
from .eia import EiaPetXlsConnector
from .evidence import EvidenceBundleConnector
from .fred import FredApiVintagesConnector, FredGraphCsvConnector
from .french import FrenchLibraryConnector
from .manual import ManualCsvConnector
from .shiller import ShillerXlsConnector
from .treasury import TreasuryParCurveConnector

_CONNECTORS = {
    c.name: c
    for c in (TreasuryParCurveConnector, FredGraphCsvConnector, FredApiVintagesConnector,
              FrenchLibraryConnector, DamodaranXlsConnector, ShillerXlsConnector,
              ManualCsvConnector, EvidenceBundleConnector, EiaPetXlsConnector)
}


def get_connector(name: str, **kwargs: Any) -> Connector:
    try:
        cls = _CONNECTORS[name]
    except KeyError:
        raise ValueError(f"未注册的接入器：{name}；可用：{', '.join(sorted(_CONNECTORS))}") from None
    return cls(**kwargs)


__all__ = ["Connector", "FetchError", "ParsedPayload", "RawPayload", "get_connector"]
