"""Reconstruct, for one case, which resources exist and in what state at audit_at."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from . import activity as activity_mod
from .catalog import Catalog
from .identity import Subject
from .loaders import Case, Dataset
from .model import Observation, ResourceState

# Resources whose meaning is fixed by their id prefix.
RETAINED_PREFIXES = {"audit_record": "security_service", "legal_hold": "legal_service"}


def latest_observation(catalog: Catalog, resource_id: str,
                       audit_at: datetime) -> Optional[Observation]:
    """The strongest observation of a resource at or before audit_at.

    Strength is "how directly this file probes the resource" first, then recency.
    A readback log that says 404 beats a bundle snapshot that merely lists the row.
    """
    candidates = [item for item in catalog.for_resource(resource_id)
                  if item.observed_at <= audit_at]
    if not candidates:
        return None
    return max(candidates,
               key=lambda item: (catalog.weight(item.file_id), item.observed_at,
                                 item.file_id))


def observation_state(observation: Observation, system: str) -> ResourceState:
    system_id = observation.system or system
    return ResourceState(
        system=system_id,
        resource_id=observation.resource_id,
        collection=observation.collection,
        present=observation.present,
        exposed=observation.exposed if observation.present else (),
        observation=observation,
        evidence_id=observation.file_id,
        source="evidence",
        attributes=dict(observation.attributes),
    )


def claim_resource_state(dataset: Dataset, resource_id: str, system: str,
                         audit_at: datetime) -> ResourceState:
    claim = activity_mod.last_claim(dataset, resource_id, audit_at)
    attributes: Dict[str, str] = {}
    if claim is not None:
        attributes["claim"] = claim.event_type
        attributes["claim_result"] = claim.reported_result
    state = activity_mod.claim_state(claim) if claim else "present"
    # With no evidence either way, a delete attempt that was submitted counts as
    # effective: only evidence may show a record that survived it.
    present = state != "deleted"
    return ResourceState(
        system=system,
        resource_id=resource_id,
        collection="",
        present=present,
        exposed=("unknown",) if present else (),
        observation=None,
        evidence_id=claim.activity_id if claim else "",
        source="activity",
        attributes=attributes,
    )


def _workflow_resources(dataset: Dataset, case: Case) -> Dict[str, str]:
    """Resources named by the case's deletion workflow, keyed to their system."""
    resources: Dict[str, str] = {}
    for item in activity_mod.workflow_activities(dataset, case):
        system = activity_mod.resource_system(item.resource_id, item.target_system)
        resources.setdefault(item.resource_id, system)
    return resources


def anchor_account(dataset: Dataset, case: Case, catalog: Optional[Catalog] = None,
                   probe_files: Optional[set] = None,
                   audit_at: Optional[datetime] = None
                   ) -> Optional[str]:
    """The account record the workflow tried to delete.

    Candidates are the account deletes near `reported_at`. When the case's probe
    file lists accounts, only those are eligible: everything else in the same
    time slot belongs to another customer's workflow.
    """
    eligible = set()
    if catalog is not None and probe_files:
        for observation in catalog.observations:
            if observation.file_id in probe_files and observation.resource_id.startswith(
                    "account_"):
                eligible.add(observation.resource_id)
    best: Optional[Tuple[float, str]] = None
    for item in activity_mod.candidate_activities(dataset, case):
        if not item.resource_id.startswith("account_"):
            continue
        if item.event_type not in ("DELETE_RECORD", "UPDATE_RECORD", "SYNC_RECORD"):
            continue
        if eligible and item.resource_id not in eligible:
            continue
        distance = abs((item.event_time - case.reported_at).total_seconds())
        if item.event_type != "DELETE_RECORD":
            distance += 3600
        if best is None or distance < best[0]:
            best = (distance, item.resource_id)
    return best[1] if best else None


def anchor_audit_record(catalog: Catalog, subject: Subject,
                        audit_at: datetime) -> Optional[str]:
    for observation in catalog.for_subject(subject.emails, [subject.user_id]):
        if observation.resource_id.startswith("audit_record_"):
            if observation.observed_at <= audit_at:
                return observation.resource_id
    return None


def subject_observations(catalog: Catalog, subject: Subject,
                         audit_at: datetime) -> Dict[str, Observation]:
    """Latest observation per resource that is linked to the subject by id."""
    latest: Dict[str, Observation] = {}
    for observation in catalog.for_subject(subject.emails, [subject.user_id]):
        if not observation.resource_id or observation.observed_at > audit_at:
            continue
        current = latest.get(observation.resource_id)
        if current is None or (observation.observed_at, observation.file_id) > (
                current.observed_at, current.file_id):
            latest[observation.resource_id] = observation
    return latest


def primary_probe(catalog: Catalog, linked: Dict[str, Observation]) -> str:
    """The evidence file that covers the most of the subject's own resources.

    The captures are curated: one file usually holds every record of a case, so
    preferring it keeps a single case's citations internally consistent.
    """
    counts: Dict[str, int] = {}
    latest: Dict[str, datetime] = {}
    for observation in linked.values():
        counts[observation.file_id] = counts.get(observation.file_id, 0) + 1
        latest[observation.file_id] = max(latest.get(observation.file_id, observation.observed_at),
                                          observation.observed_at)
    if not counts:
        return ""
    return max(counts, key=lambda name: (counts[name], catalog.weight(name),
                                         latest[name], name))


def observation_in_file(catalog: Catalog, resource_id: str, file_id: str,
                        audit_at: datetime) -> Optional[Observation]:
    for observation in catalog.for_resource(resource_id):
        if observation.file_id == file_id and observation.observed_at <= audit_at:
            return observation
    return None


def resolve_states(dataset: Dataset, catalog: Catalog, subject: Subject, case: Case,
                   include_workflow: bool = True) -> List[ResourceState]:
    """Every resource provably linked to the subject, with its state at audit_at.

    Only evidence that carries one of the subject's identifiers is accepted, plus
    the single account record the deletion workflow targeted. Records that merely
    happen to sit in the same capture window are ignored, which is what keeps
    decoys and other customers out of the answer.
    """
    audit_at = case.audit_at
    linked = subject_observations(catalog, subject, audit_at)
    probe = primary_probe(catalog, linked)

    states: List[ResourceState] = []
    for resource_id, observation in linked.items():
        system = observation.system or activity_mod.prefix_system(resource_id)
        best = latest_observation(catalog, resource_id, audit_at) or observation
        states.append(observation_state(best, system))

    probe_files = {item.file_id for item in linked.values()}
    workflow = _workflow_resources(dataset, case) if include_workflow else {}
    known_ids = {item.resource_id for item in states}
    for resource_id, system in workflow.items():
        if resource_id.startswith("account_") or resource_id in known_ids:
            continue
        observation = (observation_in_file(catalog, resource_id, probe, audit_at)
                       or latest_observation(catalog, resource_id, audit_at))
        if observation is not None:
            # Only a record from the case's own capture or an unattributed
            # record may join; a record naming somebody else is a decoy.
            curated = observation.file_id in probe_files
            belongs_elsewhere = observation.has_identifier and not subject.matches(
                user_ids=observation.user_ids, emails=observation.emails,
                phones=observation.phones, hashes=observation.hashes)
            if curated and not belongs_elsewhere:
                states.append(observation_state(observation, system))
            continue
        claim = activity_mod.last_claim(dataset, resource_id, audit_at)
        if claim is not None and claim.reported_result in ("FAILED", "PARTIAL"):
            states.append(claim_resource_state(dataset, resource_id, system, audit_at))

    account = anchor_account(dataset, case, catalog,
                             {item.file_id for item in linked.values()}, audit_at)
    known = {state.resource_id for state in states}
    if account and account not in known:
        observation = latest_observation(catalog, account, audit_at)
        if observation is not None and subject.matches(
                user_ids=observation.user_ids, emails=observation.emails,
                phones=observation.phones, hashes=observation.hashes):
            states.append(observation_state(observation, "account_service"))
        else:
            states.append(
                claim_resource_state(dataset, account, "account_service", audit_at))

    retained = anchor_audit_record(catalog, subject, audit_at)
    if retained and retained not in {state.resource_id for state in states}:
        observation = (observation_in_file(catalog, retained, probe, audit_at)
                       or latest_observation(catalog, retained, audit_at))
        if observation is not None:
            states.append(observation_state(observation, "security_service"))
        else:
            states.append(
                claim_resource_state(dataset, retained, "security_service", audit_at))
    return states
