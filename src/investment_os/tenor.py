"""期限标识：统一 "10 Yr"、"1.5 Month"、"6 Wk"、"10Y" 等写法。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UNIT_ALIASES = {
    "w": "W", "wk": "W", "wks": "W", "week": "W", "weeks": "W",
    "m": "M", "mo": "M", "mos": "M", "month": "M", "months": "M",
    "y": "Y", "yr": "Y", "yrs": "Y", "year": "Y", "years": "Y",
}
_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*$")


@dataclass(frozen=True, order=True)
class Tenor:
    months: float
    code: str  # 规范写法，如 "1.5M"、"10Y"、"6W"

    def __str__(self) -> str:
        return self.code


def parse_tenor(text: str) -> Tenor:
    m = _PATTERN.match(text)
    if not m:
        raise ValueError(f"无法识别的期限：{text!r}")
    qty_text, unit_text = m.groups()
    unit = _UNIT_ALIASES.get(unit_text.lower())
    if unit is None:
        raise ValueError(f"无法识别的期限单位：{text!r}")
    qty = float(qty_text)
    months = {"W": qty * 12 / 52, "M": qty, "Y": qty * 12}[unit]
    qty_code = qty_text.rstrip("0").rstrip(".") if "." in qty_text else qty_text
    return Tenor(months=months, code=f"{qty_code}{unit}")


def is_tenor(text: str) -> bool:
    try:
        parse_tenor(text)
    except ValueError:
        return False
    return True
