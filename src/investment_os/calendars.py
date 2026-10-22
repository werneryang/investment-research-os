"""预期观测日历：判断「应当有观测的日期」，用于日期覆盖检查。

日历只描述某个数据集的发布日集合，不是通用交易所日历。每个日历的规则
须用真实数据核验，并在 config/calendars.yaml 中记录证据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    USFederalHolidayCalendar,
)


class _GoodFridayCalendar(AbstractHolidayCalendar):
    rules = [GoodFriday]


_HOLIDAY_RULES: dict[str, type[AbstractHolidayCalendar]] = {
    "us_federal": USFederalHolidayCalendar,
    "good_friday": _GoodFridayCalendar,
}


@dataclass(frozen=True)
class CalendarSpec:
    id: str
    description: str
    holiday_rules: tuple[str, ...]
    additional_closures: tuple[pd.Timestamp, ...]
    evidence: str

    def expected_dates(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        """[start, end] 内的预期观测日：工作日减去节假日规则与额外休市日。"""
        days = pd.bdate_range(start, end)
        for rule in self.holiday_rules:
            days = days.difference(_HOLIDAY_RULES[rule]().holidays(start, end))
        return days.difference(pd.DatetimeIndex(self.additional_closures))


def load_calendars(doc: dict[str, Any]) -> dict[str, CalendarSpec]:
    out = {}
    for cal_id, item in (doc.get("calendars") or {}).items():
        rules = tuple(item.get("holiday_rules") or ())
        unknown = [r for r in rules if r not in _HOLIDAY_RULES]
        if unknown:
            raise ValueError(f"日历 {cal_id} 含未知规则：{unknown}；可用：{sorted(_HOLIDAY_RULES)}")
        if not item.get("evidence"):
            raise ValueError(f"日历 {cal_id} 需要核验证据")
        out[cal_id] = CalendarSpec(
            id=cal_id,
            description=item.get("description", ""),
            holiday_rules=rules,
            additional_closures=tuple(pd.Timestamp(str(d)) for d in item.get("additional_closures") or ()),
            evidence=item["evidence"],
        )
    return out
