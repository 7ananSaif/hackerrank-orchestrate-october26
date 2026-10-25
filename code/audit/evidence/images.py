"""Image evidence: console screenshots read once by a vision model and cached.

No OCR binary is available, so `code/cache/image_facts.json` holds the facts a
vision model extracted for each screenshot, keyed by the manifest file_id. The
loader is deterministic: it replays that cache and never calls a model at run
time.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List

from ..loaders import parse_time
from ..model import Observation

CACHE_NAME = os.path.join("code", "cache", "image_facts.json")


def _cache_path(root: str) -> str:
    return os.path.join(root, CACHE_NAME)


def load_cache(root: str) -> Dict[str, dict]:
    path = _cache_path(root)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return {}


def file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_image_file(path: str, file_id: str, fallback_time, root: str = ".",
                     raw: str = "") -> List[Observation]:
    cache = load_cache(root)
    entry = cache.get(file_id)
    if not entry:
        return []
    out: List[Observation] = []
    for record in entry.get("records", []):
        stamped = parse_time(record.get("observed_at", "")) or fallback_time
        out.append(
            Observation(
                system=record.get("system", ""),
                resource_id=record.get("resource_id", ""),
                collection=record.get("collection", "customer_screens"),
                file_id=file_id,
                observed_at=stamped,
                present=bool(record.get("present", True)),
                user_ids=tuple(record.get("user_ids", ())),
                emails=tuple(value.lower() for value in record.get("emails", ())),
                phones=tuple(record.get("phones", ())),
                hashes=tuple(value.lower() for value in record.get("hashes", ())),
                names=tuple(record.get("names", ())),
                exposed=tuple(record.get("exposed", ())),
                attributes=dict(record.get("attributes", {})),
            )
        )
    return out
