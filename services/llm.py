"""Shared LLM provider wrapper (contract shared with Part 1 of the submission).

Gemini is the default provider (mirrors Part 1); OpenAI can be swapped in via
.env. Every call is ONE structured-JSON request and returns a parsed dict.
Clear, user-facing errors are raised for missing keys, empty responses and
malformed JSON.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()


class LLMError(Exception):
    """Raised with a user-friendly message when the LLM call fails."""


def chat_json(system: str, user: str, schema: dict, temperature: float = 0.2) -> dict:
    """One LLM call returning a JSON dict shaped by `schema`.

    Raises LLMError with an actionable message on any failure.
    """
    if not system.strip() or not user.strip():
        raise LLMError("chat_json received an empty prompt (internal error).")
    if PROVIDER == "gemini":
        raw = _via_gemini(system, user, schema, temperature)
    elif PROVIDER == "openai":
        raw = _via_openai(system, user, schema, temperature)
    else:
        raise LLMError(f"Unknown LLM_PROVIDER '{PROVIDER}'. Use 'gemini' or 'openai'.")
    return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        raise LLMError("The LLM returned an empty response. Try generating again.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(
            "The LLM returned malformed JSON and could not be parsed "
            f"(starts with: {raw[:160]}...). Try generating again."
        ) from exc
    if not isinstance(data, dict):
        raise LLMError("The LLM returned JSON that is not an object. Try again.")
    return data


# --------------------------------------------------------------------------- #
# Gemini (default)                                                             #
# --------------------------------------------------------------------------- #

def _via_gemini(system: str, user: str, schema: dict, temperature: float) -> str:
    if not GEMINI_API_KEY:
        raise LLMError(
            "No GEMINI_API_KEY is configured. Copy .env.example to .env and add "
            "your free key from https://aistudio.google.com/apikey (or set "
            "LLM_PROVIDER=openai with an OPENAI_API_KEY)."
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise LLMError("google-genai is not installed. Run: pip install -r requirements.txt") from exc
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[system, user],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
            ),
        )
    except Exception as exc:
        raise LLMError(f"Gemini call failed: {exc}") from exc
    return resp.text or ""


# --------------------------------------------------------------------------- #
# OpenAI (swappable alternative)                                               #
# --------------------------------------------------------------------------- #

def _via_openai(system: str, user: str, schema: dict, temperature: float) -> str:
    if not OPENAI_API_KEY:
        raise LLMError(
            "LLM_PROVIDER is 'openai' but no OPENAI_API_KEY is configured. "
            "Add it to .env, or switch back to LLM_PROVIDER=gemini."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise LLMError("openai is not installed. Run: pip install -r requirements.txt") from exc
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": system
                    + "\n\nRespond with a JSON object matching this schema:\n"
                    + json.dumps(schema, indent=1),
                },
                {"role": "user", "content": user},
            ],
        )
    except Exception as exc:
        raise LLMError(f"OpenAI call failed: {exc}") from exc
    return resp.choices[0].message.content or ""
