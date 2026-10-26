#!/usr/bin/env python3
"""Retrieve original guidance evidence and historical Damodaran snapshots.

The archive page's visible date controls the snapshot year, not the filename:
pedata24.xls is linked as January 2025. Unrecognized headers/missing cases fail.
"""
from __future__ import annotations

import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import xlrd
import yaml

from investment_os.cli import load_env_file

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/"data/industry"


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def clean(s):
    p = Text(); p.feed(s)
    return re.sub(r"\s+", " ", unescape(" ".join(p.parts))).strip()


def cached(url, extension):
    name = hashlib.sha256(url.encode()).hexdigest()[:20]+"."+extension
    path = BASE/"sources"/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        ua = os.environ.get("SEC_USER_AGENT", "investment-research-os personal research")
        with urlopen(Request(url, headers={"User-Agent": ua}), timeout=60) as response:
            content = response.read()
        path.write_bytes(content)
    content = path.read_bytes()
    return content, {"url": url, "path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest()}


def guidance():
    records = []
    for case in yaml.safe_load((ROOT/"config/industry-guidance.yaml").read_text())["cases"]:
        evidence = {}
        for kind in ("forecast", "actual"):
            raw, ref = cached(case[kind+"_url"], "html")
            text = clean(raw.decode("utf-8", errors="replace"))
            anchor = case[kind+"_anchor"]
            if anchor not in text:
                raise ValueError(f"{case['id']}: {kind} anchor absent: {anchor}")
            evidence[kind] = {**ref, "locator": case[kind+"_locator"], "short_excerpt": anchor}
        records.append({"id": case["id"], "date": case["actual_date"], "value": case["actual"]*1e9,
                        "low": case["low"]*1e9, "high": case["high"]*1e9,
                        "company": case["company"], "forecast_date": case["forecast_date"], "actual_date": case["actual_date"],
                        "forecast_target": case["target"], "actual_target": case["target"],
                        "forecast_basis": "GAAP consolidated reported USD revenue", "actual_basis": "GAAP consolidated reported USD revenue",
                        "kind": "management_guidance", "revises": case.get("revises"),
                        "precision_note": case.get("precision_note"), "evidence": evidence,
                        "human_status": "unreviewed"})
        print("guidance", case["id"], "source anchors verified", flush=True)
    (BASE/"guidance.json").write_text(json.dumps({"schema": "industry-evidence.v1", "unit": "USD", "records": records,
        "metadata": {"selection": "Six companies; six targets from calendar 2020–2025 plus Intel FY2022 revision case; purposive sample, not an exhaustive panel"}}, ensure_ascii=False, allow_nan=False))


def valuation():
    archive = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html"
    raw, archive_ref = cached(archive, "html")
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw.decode(), re.I|re.S)
    urls = {}
    for href, label in links:
        match = re.search(r"/(pedata|margin)\d{2}\.xls$", href)
        when = re.fullmatch(r"1/(\d{2})", clean(label).strip(" ,"))
        if match and when and 10 <= int(when[1]) <= 25:
            urls[(match[1], 2000+int(when[1]))] = urljoin(archive, href)
    for kind in ("pedata", "margin"):
        urls[(kind, 2026)] = f"https://pages.stern.nyu.edu/~adamodar/pc/datasets/{kind}.xls"
    records, skipped, snapshots = [], [], []
    desired = {"Current PE": "current_pe", "Trailing PE": "trailing_pe", "Forward PE": "forward_pe",
               "Price/Current EPS": "current_pe", "Price/Trailing EPS": "trailing_pe", "Price/Forward PE": "forward_pe",
               "Net Margin": "net_margin", "Net margin": "net_margin", "Gross Margin": "gross_margin",
               "Pre-tax Unadjusted Operating Margin": "operating_margin", "Pre-tax Operating Margin": "operating_margin"}
    for (kind, year), url in sorted(urls.items()):
        content, ref = cached(url, "xls")
        book = xlrd.open_workbook(file_contents=content)
        sheet, header = None, None
        for candidate in book.sheets():
            for r in range(min(30, candidate.nrows)):
                cells = [re.sub(r"\s+", " ", str(v)).strip() for v in candidate.row_values(r)]
                if cells[0] in ("Industry Name", "Industry name", "Industry"):
                    sheet, header = candidate, r
                    break
            if sheet: break
        if sheet is None:
            raise ValueError(f"Industry header absent in {url}")
        titles = [re.sub(r"\s+", " ", str(v)).strip() for v in sheet.row_values(header)]
        selected = [(i, desired[t]) for i,t in enumerate(titles) if t in desired]
        if not selected:
            raise ValueError(f"No supported valuation columns: {url}: {titles}")
        count_col = next((i for i,t in enumerate(titles) if t.lower() in ("number of firms", "number of companies")), None)
        count = 0
        for r in range(header+1, sheet.nrows):
            industry = str(sheet.cell_value(r, 0)).strip()
            if not industry or industry.lower().startswith(("total", "market", "source", "note")):
                continue
            # Only rows containing the firm's count are industry rows; never parse footer notes.
            firms = sheet.cell_value(r, count_col) if count_col is not None else None
            if not isinstance(firms, float):
                continue
            for col, metric in selected:
                cell = sheet.cell(r,col)
                if cell.ctype != xlrd.XL_CELL_NUMBER:
                    skipped.append({"year": year, "industry": industry, "metric": metric, "raw": str(cell.value)})
                    continue
                token = hashlib.sha256(industry.encode()).hexdigest()[:10]
                records.append({"id": f"{year}_{metric}_{token}", "date": f"{year}-01-01", "value": float(cell.value),
                                "industry": industry, "metric": metric, "firms": int(firms),
                                "snapshot_year": year, "source_url": url, "source_sha256": ref["sha256"],
                                "locator": f"{sheet.name}!R{r+1}C{col+1}", "header": titles[col],
                                "classification": "Damodaran original industry labels; not French/SIC/NAICS",
                                "time_note": "January snapshot label from archive; not a certified point-in-time investable vintage"})
                count += 1
        snapshots.append({"kind": kind, "snapshot_year": year, "rows": count, **ref})
        print("valuation", kind, year, count, flush=True)
    (BASE/"valuation.json").write_text(json.dumps({"schema": "industry-evidence.v1", "unit": "ratio", "records": records,
        "metadata": {"archive_page": archive_ref, "snapshots": snapshots, "missing_cells": skipped,
                     "classification_changes": "Source warns that providers and industry categories changed over time; do not stitch unmatched labels"}}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    load_env_file(ROOT/".env")
    guidance()
    valuation()
