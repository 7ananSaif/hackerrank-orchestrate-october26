"""Build one observation catalog from every evidence file in the manifest."""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .evidence import (parse_image_file, parse_json_file, parse_log_file,
                       parse_pdf_file, parse_sql_file)
from .loaders import Dataset, EvidenceFile, normalise
from .model import Observation
from .preference import origin_weight


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _parse_one(root: str, entry: EvidenceFile) -> List[Observation]:
    path = os.path.join(root, "dataset", entry.file_path)
    if not os.path.exists(path):
        return []
    suffix = os.path.splitext(path)[1].lower()
    captured = entry.captured_at
    if suffix == ".sql":
        return parse_sql_file(path, entry.file_id, _read_text(path))
    if suffix == ".json":
        return parse_json_file(path, entry.file_id, captured, _read_text(path))
    if suffix in (".log", ".txt"):
        return parse_log_file(path, entry.file_id, captured, _read_text(path))
    if suffix == ".pdf":
        return parse_pdf_file(path, entry.file_id, captured)
    if suffix in (".png", ".jpg", ".jpeg"):
        return parse_image_file(path, entry.file_id, captured, root=root)
    return []
class Catalog:
    """In-memory index of every observation, keyed by resource and identifier."""

    def __init__(self, observations: List[Observation],
                 file_weight: Optional[Dict[str, int]] = None):
        self.observations = observations
        self.file_weight: Dict[str, int] = file_weight or {}
        self.by_resource: Dict[str, List[Observation]] = {}
        self.by_email: Dict[str, List[Observation]] = {}
        self.by_user: Dict[str, List[Observation]] = {}
        self.by_file: Dict[str, List[Observation]] = {}
        for observation in observations:
            if observation.resource_id:
                self.by_resource.setdefault(observation.resource_id, []).append(observation)
            for email in observation.emails:
                self.by_email.setdefault(normalise(email), []).append(observation)
            for user_id in observation.user_ids:
                self.by_user.setdefault(user_id, []).append(observation)
            self.by_file.setdefault(observation.file_id, []).append(observation)

    def weight(self, file_id: str) -> int:
        """How directly this file probes what it mentions (see preference.py)."""
        return self.file_weight.get(file_id, 2)

    def for_resource(self, resource_id: str) -> List[Observation]:
        return self.by_resource.get(resource_id, [])

    def for_subject(self, emails, user_ids) -> List[Observation]:
        seen: Dict[int, Observation] = {}
        for email in emails:
            for observation in self.by_email.get(normalise(email), []):
                seen[id(observation)] = observation
        for user_id in user_ids:
            for observation in self.by_user.get(user_id, []):
                seen[id(observation)] = observation
        return list(seen.values())

    def resource_ids_for(self, emails, user_ids) -> set:
        return {item.resource_id for item in self.for_subject(emails, user_ids)
                if item.resource_id}


def build_catalog(dataset: Dataset) -> Catalog:
    observations: List[Observation] = []
    for entry in dataset.evidence:
        observations.extend(_parse_one(dataset.root, entry))
    observations = [item for item in observations
                    if item.resource_id or item.user_ids or item.emails]
    observations.sort(key=lambda item: (item.observed_at, item.file_id, item.resource_id))
    weights = {entry.file_id: origin_weight(entry.origin) for entry in dataset.evidence}
    return Catalog(observations, weights)
