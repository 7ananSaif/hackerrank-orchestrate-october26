"""Decide whether request_text authorises deletion.

Multilingual keyword heuristics run first; a cached model call refines the
verdict when a provider is configured. The default is "deletion authorised",
because blocking a real deletion request leaves personal data in place, while a
false deletion on a maintenance request only costs a wasted audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .llm import ModelClient

SYSTEM_PROMPT = (
    "You classify customer privacy requests. Answer with exactly one word: "
    "DELETE if the sender asks for their account, profile or personal data to be "
    "deleted or erased, otherwise OTHER. Requests for access, correction, export, "
    "marketing opt-out or a status question are OTHER."
)

# Stems, not whole words: "deleting", "deleted", "deletion" all match "delet".
DELETION_PHRASES = (
    "delet", "eras", "remov", "supprim", "suppress", "lösch", "loesch", "borr",
    "elimin", "excluir", "exclus", "apagar", "effacer", "verwijder", "cancell",
    "wipe", "right to be forgotten", "close my account", "close the account",
    "closed my account", "be erased", "unlink", "\u0443\u0434\u0430\u043b\u0438",
    "\u0443\u0434\u0430\u043b", "\u524a\u9664", "\u6d88\u53bb", "\u5220\u9664",
    "\uc0ad\uc81c", "hapus", "\u03b4\u03b9\u03b1\u03b3\u03c1\u03b1\u03c6",
    "usu\u0144", "t\u00f6rl", "sterge", "poista",
)

# Expressions that only appear when the writer wants to keep the account.
NON_DELETION_PHRASES = (
    "leave the account active", "keep the account as it is", "leave my profile",
    "continue using the service", "change the email address",
    "replace it with the new one", "portable format", "in place",
    "copy of my data", "export my data", "download my data", "access request",
    "marketing emails", "unsubscribe me", "opt out of marketing",
    "stop sending marketing", "do not send me marketing",
    "corregir mis datos", "rectificar mis datos", "copie de mes donn\u00e9es",
    "droit d'acc\u00e8s", "auskunftsersuchen", "berichtigung meiner daten",
)


@dataclass
class RequestVerdict:
    is_deletion: bool
    source: str
    reason: str


def _score(text: str, phrases: Sequence[str]) -> Tuple[int, List[str]]:
    lowered = text.lower()
    hits = [phrase for phrase in phrases if phrase in lowered]
    return len(hits), hits


def heuristic(text: str) -> RequestVerdict:
    delete_hits, delete_terms = _score(text, DELETION_PHRASES)
    other_hits, other_terms = _score(text, NON_DELETION_PHRASES)
    if other_hits and not delete_hits:
        return RequestVerdict(False, "heuristic", "other:" + ",".join(other_terms[:3]))
    if delete_hits:
        return RequestVerdict(True, "heuristic", "deletion:" + ",".join(delete_terms[:3]))
    return RequestVerdict(True, "heuristic", "implicit-deletion")


def classify(text: str, client: ModelClient) -> RequestVerdict:
    base = heuristic(text)
    if not client.available and client.cached(
            "request", f"{SYSTEM_PROMPT}\n{text}") is None:
        return base
    answer = client.complete("request", SYSTEM_PROMPT, text)
    if not answer:
        return base
    verdict = answer.strip().upper().startswith("DELETE")
    return RequestVerdict(verdict, "model", answer.strip()[:40])


def classify_all(texts: Dict[str, str], client: ModelClient) -> Dict[str, RequestVerdict]:
    return {case_id: classify(text, client) for case_id, text in texts.items()}
