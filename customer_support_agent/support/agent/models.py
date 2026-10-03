"""Find out which models your API keys can actually use.

Providers retire models and move others behind paid tiers, so a model that
worked last month may fail today. This script calls each candidate with a real
tool to confirm it works -- being listed by the API is not the same as being
usable on your plan.

    python -m support.agent.models              # test the active provider
    python -m support.agent.models --provider gemini
    python -m support.agent.models --all        # just list, don't test
"""

import argparse
import json
import os
import time
import urllib.request

from langchain_core.tools import tool

from support.agent.llm import ENV_PATH, MODEL_NAME, PROVIDER

# Chat models worth considering, best first. Image, TTS, OCR, audio and coding
# models are excluded -- they can't drive this agent.
CANDIDATES = {
    "mistral": [
        "ministral-14b-latest",
        "ministral-8b-latest",
        "ministral-3b-latest",
        "mistral-small-latest",
        "mistral-medium-latest",
        "magistral-small-latest",
    ],
    "gemini": [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
    ],
}

# Accept requests but ignore the temperature setting, which breaks
# reproducibility -- the same request can produce different decisions.
IGNORES_TEMPERATURE = {"gemini-3.6-flash", "gemini-3.5-flash-lite"}

# Seconds between tests, to stay inside each free tier while probing.
PROBE_GAP = {"mistral": 2.0, "gemini": 13.0}


@tool
def get_order(order_id: str) -> dict:
    """Look up an order by its id."""
    return {"order_id": order_id, "price": 999}


def _key(provider: str) -> str:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    var = "MISTRAL_API_KEY" if provider == "mistral" else "GOOGLE_API_KEY"
    value = os.getenv(var)
    if not value or value.startswith("your-key"):
        raise SystemExit(f"{var} is not set in {ENV_PATH}")
    return value


def list_all(provider: str, key: str) -> list[str]:
    """Every model the key can see. Listed does not mean usable."""
    if provider == "mistral":
        req = urllib.request.Request(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
        return sorted(
            m["id"] for m in data.get("data", [])
            if m.get("capabilities", {}).get("function_calling")
        )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models"
        f"?key={key}&pageSize=200"
    )
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)
    return sorted(
        m["name"].replace("models/", "") for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    )


def test_model(provider: str, name: str, key: str) -> tuple[bool, str]:
    """Call the model with a tool and report whether it actually worked."""
    try:
        if provider == "mistral":
            from langchain_mistralai import ChatMistralAI

            llm = ChatMistralAI(model=name, temperature=0, api_key=key, max_retries=0)
        else:
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=name, temperature=0, google_api_key=key, max_retries=0
            )

        started = time.time()
        response = llm.bind_tools([get_order]).invoke(
            "Look up order ORD-0045 using the tool."
        )
        elapsed = time.time() - started

        calls = getattr(response, "tool_calls", [])
        if calls and calls[0]["name"] == "get_order":
            return True, f"works, calls tools correctly ({elapsed:.1f}s)"
        # Answering without using the tool means it cannot drive this agent.
        return False, "responded but did not call the tool"
    except Exception as exc:  # noqa: BLE001
        text = str(exc).replace("\n", " ")
        if "404" in text or "NOT_FOUND" in text:
            return False, "not available to this key (404)"
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            # On Mistral a persistent 429 usually means paid-tier-only, not a
            # transient throttle.
            return False, "429 - rate limited, or not on your tier"
        return False, text[:68]


def main():
    parser = argparse.ArgumentParser(description="Check which models you can use")
    parser.add_argument("--provider", choices=["mistral", "gemini"], default=PROVIDER)
    parser.add_argument("--all", action="store_true",
                        help="list every visible model instead of testing")
    args = parser.parse_args()

    provider = args.provider
    key = _key(provider)

    if args.all:
        names = list_all(provider, key)
        print(f"{len(names)} {provider} models support tool calling:\n")
        for name in names:
            print(f"  {name}")
        print("\nListed does not mean usable -- run without --all to test.")
        return

    active = f" (currently active: {MODEL_NAME})" if provider == PROVIDER else ""
    print(f"Testing {provider} models{active}\n")
    print(f"{'model':<26} result")
    print("-" * 70)

    working = []
    for name in CANDIDATES[provider]:
        ok, note = test_model(provider, name, key)
        if ok and name in IGNORES_TEMPERATURE:
            note += "  (ignores temperature - not reproducible)"
        print(f"{name:<26} {'OK   ' if ok else 'FAIL '} {note}")
        if ok and name not in IGNORES_TEMPERATURE:
            working.append(name)
        time.sleep(PROBE_GAP[provider])

    var = "MISTRAL_MODEL" if provider == "mistral" else "GEMINI_MODEL"
    print()
    if not working:
        print("Nothing worked. If everything says 429, wait a minute and retry.")
    elif provider == PROVIDER and MODEL_NAME in working:
        print(f"'{MODEL_NAME}' is working. Nothing to change.")
    else:
        print(f"Usable: {', '.join(working)}")
        print(f"To use one, set in {ENV_PATH}:")
        print(f"  LLM_PROVIDER={provider}")
        print(f"  {var}={working[0]}")


if __name__ == "__main__":
    main()
