"""Optional model layer configured from the environment.

The pipeline never depends on a model to reach an answer: every call site has a
deterministic fallback. With no key (or AUDIT_LLM_PROVIDER=none) the client
reports itself as unavailable, the fallbacks are used and the run is fully
reproducible and offline.

Environment variables (all optional; keys are read from the environment only,
never written to the cache, the usage log or the output):

  AUDIT_LLM_PROVIDER   none | auto | anthropic | openai        (default: auto)
                       auto = anthropic if ANTHROPIC_API_KEY is set, else
                       openai if OPENAI_API_KEY is set, else none.
  ANTHROPIC_API_KEY    key for the anthropic provider
  OPENAI_API_KEY       key for the openai provider
  AUDIT_MODEL          model id override; empty = provider default
  AUDIT_LLM_TIMEOUT    per-call timeout in seconds              (default: 60)
  AUDIT_MAX_TOKENS     completion token limit                   (default: 1024)
  AUDIT_PRICE_INPUT    USD per 1M input tokens, overrides the PRICES table
  AUDIT_PRICE_OUTPUT   USD per 1M output tokens, overrides the PRICES table

A `.env` file in the repository root is read as a convenience, but it never
overrides a variable that is already set in the real environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

CACHE_DIR = os.path.join("code", "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "llm_cache.json")
USAGE_FILE = os.path.join("code", "evaluation", "usage_log.jsonl")

PROVIDERS = ("anthropic", "openai")
KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
DEFAULT_MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4o-mini"}

# USD per 1M tokens (input, output), used only for the cost estimate in the
# usage report. Claude rates are the published ones for prompts up to 100K
# tokens; confirm against the provider's pricing page or override with
# AUDIT_PRICE_INPUT / AUDIT_PRICE_OUTPUT.
PRICES: Dict[str, Tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-5-mini": (0.25, 2.00),
}

_OFF_VALUES = {"none", "off", "offline", "0", "false", "no"}
_NO_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")
_MAX_CONSECUTIVE_FAILURES = 3

_warned = set()


def _warn(message: str) -> None:
    """Print each distinct warning once; never include credentials."""
    if message not in _warned:
        _warned.add(message)
        print(f"[llm] {message}", file=sys.stderr)


def _load_dotenv(root: str) -> None:
    """Load KEY=VALUE pairs from <root>/.env without overriding the environment."""
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8-sig") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name = name.strip()
                if name.startswith("export "):
                    name = name[len("export ") :].strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                elif " #" in value:
                    value = value.split(" #", 1)[0].strip()
                if name and value and name not in os.environ:
                    os.environ[name] = value
    except OSError:
        pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_number(name: str, default: float, cast=float):
    raw = _env(name)
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        _warn(f"{name} is not a number; using {default}")
        return default
    return value if value > 0 else default


@dataclass
class Usage:
    provider: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    price: Optional[Tuple[float, float]] = None

    @property
    def price_known(self) -> bool:
        return self.price is not None

    @property
    def cost(self) -> Optional[float]:
        """Estimated USD cost, or None when calls were made at an unknown price."""
        if self.calls == 0:
            return 0.0
        if self.price is None:
            return None
        prompt_price, completion_price = self.price
        return (
            self.input_tokens * prompt_price + self.output_tokens * completion_price
        ) / 1e6


class _SdkMissing(RuntimeError):
    pass


def _key(kind: str, payload: str, model: str) -> str:
    return hashlib.sha256(f"{kind}|{model}|{payload}".encode("utf-8")).hexdigest()


class ModelClient:
    """Tiny wrapper: env configuration, disk cache, usage accounting."""

    def __init__(self, root: str):
        self.root = root
        _load_dotenv(root)
        self.cache_path = os.path.join(root, CACHE_FILE)
        self.usage_path = os.path.join(root, USAGE_FILE)
        self.cache: Dict[str, str] = self._load_cache()
        self.provider, self.api_key, self.model = self._configure()
        self.timeout = _env_number("AUDIT_LLM_TIMEOUT", 60.0)
        self.max_tokens = int(_env_number("AUDIT_MAX_TOKENS", 1024, int))
        self.usage = Usage(
            provider=self.provider, model=self.model, price=self._resolve_price()
        )
        self._client = None
        self._failures = 0
        self._disabled = False

    # -- configuration ---------------------------------------------------
    def _configure(self) -> Tuple[str, str, str]:
        choice = _env("AUDIT_LLM_PROVIDER", "auto").lower() or "auto"
        keys = {name: _env(var) for name, var in KEY_VARS.items()}

        if choice in _OFF_VALUES:
            provider = "none"
        elif choice in PROVIDERS:
            provider = choice
            if not keys[choice]:
                _warn(
                    f"AUDIT_LLM_PROVIDER={choice} but {KEY_VARS[choice]} is not set; "
                    "running offline"
                )
                provider = "none"
        else:
            if choice != "auto":
                _warn(f"unknown AUDIT_LLM_PROVIDER={choice!r}; using auto")
            provider = next((name for name in PROVIDERS if keys[name]), "none")

        # The default model also names the cache entries when running offline,
        # so a committed cache replays for the provider that filled it.
        hint = (
            provider
            if provider != "none"
            else (choice if choice in PROVIDERS else "anthropic")
        )
        model = _env("AUDIT_MODEL") or DEFAULT_MODELS[hint]
        return provider, keys.get(provider, ""), model

    def _resolve_price(self) -> Optional[Tuple[float, float]]:
        base = PRICES.get(self.model)
        price_in = _env_number("AUDIT_PRICE_INPUT", -1.0)
        price_out = _env_number("AUDIT_PRICE_OUTPUT", -1.0)
        if price_in < 0 and price_out < 0:
            return base
        if base is None and (price_in < 0 or price_out < 0):
            return None
        return (
            price_in if price_in >= 0 else base[0],
            price_out if price_out >= 0 else base[1],
        )

    @property
    def available(self) -> bool:
        return self.provider != "none" and not self._disabled

    # -- cache -----------------------------------------------------------
    def _load_cache(self) -> Dict[str, str]:
        if not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self) -> None:
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(self.cache, handle, indent=2, sort_keys=True)

    def cached(self, kind: str, payload: str) -> Optional[str]:
        return self.cache.get(_key(kind, payload, self.model))

    def remember(self, kind: str, payload: str, answer: str) -> None:
        self.cache[_key(kind, payload, self.model)] = answer
        self._save_cache()

    # -- provider calls --------------------------------------------------
    def _sdk_client(self):
        if self._client is not None:
            return self._client
        if self.provider == "anthropic":
            try:
                from anthropic import Anthropic
            except ImportError as exc:
                raise _SdkMissing(
                    "anthropic SDK not installed (pip install anthropic)"
                ) from exc
            self._client = Anthropic(api_key=self.api_key, timeout=self.timeout)
        else:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise _SdkMissing(
                    "openai SDK not installed (pip install openai)"
                ) from exc
            self._client = OpenAI(api_key=self.api_key, timeout=self.timeout)
        return self._client

    def _describe(self, exc: Exception) -> str:
        """One-line, credential-free description of a provider error."""
        status = getattr(exc, "status_code", None)
        message = getattr(exc, "message", None) or str(exc)
        text = (
            type(exc).__name__
            + (f" (HTTP {status})" if status else "")
            + f": {message}"
        )
        text = " ".join(str(text).split())
        if self.api_key:
            text = text.replace(self.api_key, "***")
        text = re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "sk-***", text)
        return text[:400]

    def _call(self, system_prompt: str, user_prompt: str) -> Tuple[str, int, int]:
        client = self._sdk_client()
        if self.provider == "anthropic":
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(
                getattr(block, "text", "") or ""
                for block in response.content
                if getattr(block, "type", "") == "text"
            )
            usage = response.usage
            return (
                text.strip(),
                int(getattr(usage, "input_tokens", 0) or 0),
                int(getattr(usage, "output_tokens", 0) or 0),
            )

        params = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if not self.model.startswith(_NO_TEMPERATURE_PREFIXES):
            params["temperature"] = 0
        response = client.chat.completions.create(**params)
        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        return (
            text,
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
        )

    def complete(
        self, kind: str, system_prompt: str, user_prompt: str
    ) -> Optional[str]:
        """Cached completion; returns None when no provider is usable."""
        payload = f"{system_prompt}\n{user_prompt}"
        hit = self.cached(kind, payload)
        if hit is not None:
            return hit
        if not self.available:
            return None
        started = time.time()
        try:
            answer, prompt_tokens, completion_tokens = self._call(
                system_prompt, user_prompt
            )
        except _SdkMissing as exc:
            _warn(f"{exc}; using the deterministic fallback")
            self._disabled = True
            return None
        except Exception as exc:  # network, auth, rate limit, bad model id...
            self._failures += 1
            _warn(
                f"{self.provider} call failed - {self._describe(exc)}; using the fallback"
            )
            if self._failures >= _MAX_CONSECUTIVE_FAILURES:
                _warn(
                    "too many consecutive failures; model calls disabled for this run"
                )
                self._disabled = True
            return None
        self._failures = 0

        self.usage.calls += 1
        self.usage.input_tokens += prompt_tokens
        self.usage.output_tokens += completion_tokens
        self._log(kind, prompt_tokens, completion_tokens, time.time() - started)
        if not answer:
            return None
        self.remember(kind, payload, answer)
        return answer

    def _log(
        self, kind: str, prompt_tokens: int, completion_tokens: int, elapsed: float
    ) -> None:
        os.makedirs(os.path.dirname(self.usage_path), exist_ok=True)
        record = {
            "kind": kind,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "elapsed_seconds": round(elapsed, 3),
        }
        with open(self.usage_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def summary(self) -> Dict[str, object]:
        cost = self.usage.cost
        return {
            "provider": self.provider,
            "model": self.model if self.provider != "none" else "none",
            "calls": self.usage.calls,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "estimated_cost_usd": round(cost, 6) if cost is not None else None,
            "price_known": self.usage.price_known,
            "disabled": self._disabled,
        }
