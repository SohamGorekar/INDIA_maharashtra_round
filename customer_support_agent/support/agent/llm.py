"""The language model, with a response cache and retry handling.

Supports two providers, chosen with LLM_PROVIDER in .env:

- **mistral** (default) -- free tier allows roughly 1 request/second.
- **gemini** -- free tier allows only 5 requests/minute PER MODEL, which works
  out to about one agent run per minute. Fine for single requests, painful for
  a 50-request evaluation.

Three practical problems this file solves:

1. Both free tiers throttle hard, so every call backs off and retries instead of
   dying halfway through a run.
2. Repeat runs during debugging cost quota for an answer we already have. The
   cache keys on the exact prompt, so an unchanged request is free and instant.
3. Switching provider should not mean touching the agent. Everything
   model-related lives behind `get_llm()`.
"""

import hashlib
import json
import os
import random
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

# Point at the project's own .env explicitly rather than searching upward from
# the current directory, so the key is found whether you run from the project
# root, from support/, or from an editor with a different working directory.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

PROVIDER = os.getenv("LLM_PROVIDER", "mistral").strip().lower()

# Mistral. Verified working with tool calling on a free-tier key.
#   ministral-14b-latest  default; best reasoning of the free-tier models
#   ministral-8b-latest   lighter and slightly faster
# Note: mistral-small-latest and mistral-medium-latest return a persistent 429
# on the free tier -- they are paid-tier models, not a transient throttle.
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "ministral-14b-latest")

# Gemini. Alternatives if this one is retired or busy:
#   gemini-3.7-flash, gemini-3.5-flash, gemini-flash-latest, gemini-3.1-flash-lite
# Avoid gemini-3.6-flash and gemini-3.5-flash-lite: they ignore the temperature
# setting, so runs stop being reproducible.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# Whichever provider is active. Run `python -m support.agent.models` to re-check
# what your keys can actually reach.
MODEL_NAME = MISTRAL_MODEL if PROVIDER == "mistral" else GEMINI_MODEL

# Temperature 0: the same request should produce the same decision. A support
# agent that changes its mind between runs cannot be evaluated.
TEMPERATURE = 0.0

CACHE_PATH = Path(__file__).parent / "llm_cache.db"
CACHE_ENABLED = os.getenv("LLM_CACHE", "1") != "0"

MAX_RETRIES = 6

# How long to wait after a failure, doubling each time. Gemini's limit is
# per-minute, so a short retry just fails again; Mistral's is per-second.
BASE_DELAY = 1.5 if PROVIDER == "mistral" else 8.0

# Minimum gap between calls, to stay under the limit instead of discovering it.
#   Mistral free: ~1 request/second      -> 1.2s is comfortably under
#   Gemini free:  5 requests/minute      -> one every 12s
MIN_CALL_INTERVAL = 1.2 if PROVIDER == "mistral" else 12.5


class MissingAPIKey(RuntimeError):
    pass


# --- cache -----------------------------------------------------------------


def _cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CACHE_PATH))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS responses (
               key        TEXT PRIMARY KEY,
               response   TEXT NOT NULL,
               created_at REAL NOT NULL
           )"""
    )
    return conn


def cache_key(messages, tools_signature: str) -> str:
    """Hash everything that could change the model's answer."""
    payload = json.dumps(
        {
            # Provider is part of the key so switching between Mistral and
            # Gemini does not serve one provider's answers for the other.
            "provider": PROVIDER,
            "model": MODEL_NAME,
            "temperature": TEMPERATURE,
            "tools": tools_signature,
            "messages": messages,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def cache_get(key: str) -> str | None:
    if not CACHE_ENABLED:
        return None
    conn = _cache_conn()
    try:
        row = conn.execute("SELECT response FROM responses WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def cache_put(key: str, response: str) -> None:
    if not CACHE_ENABLED:
        return
    conn = _cache_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO responses VALUES (?,?,?)", (key, response, time.time())
        )
        conn.commit()
    finally:
        conn.close()


def cache_stats() -> dict:
    """Used by the UI and the eval script to show cache size."""
    if not CACHE_PATH.exists():
        return {"entries": 0, "enabled": CACHE_ENABLED}
    conn = _cache_conn()
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM responses").fetchone()
        return {"entries": count, "enabled": CACHE_ENABLED}
    finally:
        conn.close()


def clear_cache() -> None:
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()


# --- model -----------------------------------------------------------------


def _require_key(var: str, where: str) -> str:
    """Fetch an API key, or explain exactly how to set it.

    A missing key is the most common setup mistake, and the provider libraries
    report it as an opaque auth failure, so we check first and say what to do.
    """
    value = os.getenv(var)
    if not value or value.startswith("your-key"):
        raise MissingAPIKey(
            f"{var} is not set.\n"
            f"  1. Get a key at {where}\n"
            f"  2. Add it to {ENV_PATH} as {var}=...\n"
            f"  (or switch provider with LLM_PROVIDER=mistral|gemini)"
        )
    return value


def get_llm(tools: list | None = None):
    """Return the configured chat model, with tools bound if given.

    Both branches pass max_retries=0 because retries are handled by
    invoke_with_retry below, which backs off on the specific errors the free
    tiers produce. Leaving the library's own retry on would double up.
    """
    if PROVIDER == "mistral":
        from langchain_mistralai import ChatMistralAI

        llm = ChatMistralAI(
            model=MODEL_NAME,
            temperature=TEMPERATURE,
            api_key=_require_key("MISTRAL_API_KEY", "https://console.mistral.ai/api-keys"),
            max_retries=0,
        )
    elif PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=MODEL_NAME,
            temperature=TEMPERATURE,
            google_api_key=_require_key(
                "GOOGLE_API_KEY", "https://aistudio.google.com/apikey"
            ),
            max_retries=0,
        )
    else:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER '{PROVIDER}'. Use 'mistral' or 'gemini'."
        )

    return llm.bind_tools(tools) if tools else llm


def _is_transient(exc: Exception) -> bool:
    """Errors worth waiting out: rate limits, overload, and server hiccups.

    429 is the free tier throttling us. 503 means the model is busy -- popular
    free models see this often at peak times. Both clear on their own.
    """
    text = f"{type(exc).__name__} {exc}".lower()
    return any(s in text for s in (
        "429", "resource_exhausted", "quota", "rate limit",   # throttled
        "503", "unavailable", "overloaded", "high demand",    # busy
        "500", "internal error", "deadline", "timeout",       # transient
    ))


def _is_model_missing(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "404" in text or "not_found" in text or "notfound" in text


_last_call_at = 0.0


def _wait_for_slot() -> None:
    """Pace calls so we stay under the provider's limit rather than hitting it.

    An agent run fires several calls back to back, which trips a per-second limit
    immediately. Sleeping a little before each call is far cheaper than making
    the request, getting a 429, and backing off for seconds afterwards.
    """
    global _last_call_at
    gap = time.monotonic() - _last_call_at
    if gap < MIN_CALL_INTERVAL:
        time.sleep(MIN_CALL_INTERVAL - gap)
    _last_call_at = time.monotonic()


def invoke_with_retry(model, messages):
    """Call the model, pacing requests and backing off when throttled.

    Both free tiers throttle aggressively, so this waits and retries rather than
    failing the whole run. Errors that retrying cannot fix -- a bad request, a
    missing model -- are raised immediately.
    """
    delay = BASE_DELAY
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            _wait_for_slot()
            return model.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - provider raises many types
            last_error = exc
            # Providers retire models and lock some behind paid tiers, so a 404
            # means the model name, not the request, is the problem.
            if _is_model_missing(exc):
                var = "MISTRAL_MODEL" if PROVIDER == "mistral" else "GEMINI_MODEL"
                raise RuntimeError(
                    f"The model '{MODEL_NAME}' is not available to your "
                    f"{PROVIDER} API key.\n"
                    f"Find one that is:  python -m support.agent.models\n"
                    f"Then set {var}=<name> in {ENV_PATH}"
                ) from exc
            if not _is_transient(exc):
                raise
            if attempt == MAX_RETRIES - 1:
                break
            # Jitter stops parallel runs from retrying in lockstep.
            sleep_for = delay + random.uniform(0, 1)
            reason = "model busy" if "503" in str(exc) else "rate limited"
            print(f"  [{reason}, retrying in {sleep_for:.1f}s "
                  f"({attempt + 1}/{MAX_RETRIES})]")
            time.sleep(sleep_for)
            delay *= 2

    limit = ("~1 request/second" if PROVIDER == "mistral"
             else "5 requests/minute per model")
    raise RuntimeError(
        f"{PROVIDER} kept failing after {MAX_RETRIES} attempts.\n"
        f"If this is a 429, the free tier allows {limit} -- wait and retry, "
        f"and check nothing else is using the key at the same time.\n"
        f"If this is a 503, '{MODEL_NAME}' is overloaded; pick another with\n"
        f"  python -m support.agent.models\n"
        f"Last error: {last_error}"
    )
