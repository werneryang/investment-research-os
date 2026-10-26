"""Import a locally prepared, self-contained evidence bundle into the version store.

The raw JSON, including per-observation provenance, is preserved. Bundles use
params.replace_snapshot; prior versions remain available in the version store.
The fingerprint in every series ID also versions changes to provenance metadata,
even when numerical values happen to stay the same.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .base import STAGING_COLUMNS, FetchError, ParsedPayload, RawPayload, now_utc


class EvidenceBundleConnector:
    name = "evidence_bundle"

    def fetch(self, dataset, request):
        path = Path(request["path"])
        return [RawPayload(path.read_bytes(), path.name, {"name": path.name}, now_utc(), "json")]

    def parse(self, dataset, payload):
        doc = json.loads(payload.content)
        if doc.get("schema") != "industry-evidence.v1" or doc.get("unit") != dataset.unit:
            raise FetchError("Evidence schema or unit does not match the registered dataset")
        fingerprint = hashlib.sha256(payload.content).hexdigest()
        meta, rows, seen = {}, [], set()
        for record in doc["records"]:
            key = record["id"]
            if key in seen:
                raise FetchError(f"Duplicate evidence ID: {key}")
            seen.add(key)
            sid = f"{fingerprint[:16]}_{key}"
            value = record.get("value")
            rows.append((sid, record["date"], "" if value is None else str(value),
                         record.get("published_at"), None))
            meta[sid] = {**record, "bundle_hash": fingerprint}
        if not rows:
            raise FetchError("Empty evidence bundle")
        meta["_bundle"] = {"hash": fingerprint, **doc.get("metadata", {})}
        return ParsedPayload(pd.DataFrame(rows, columns=STAGING_COLUMNS), meta)
