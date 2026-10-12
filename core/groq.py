"""Groq free tier: gpt-oss (open-weight) for the report and chat, Whisper for speech.

Groq exposes an OpenAI-compatible API, so plain `requests` is enough.
Model order: the big model first, the small one when the big one is rate
limited or down. Every call carries its full context, so a fallback model
answers with the same facts.
"""
from __future__ import annotations

import os

import requests

BASE = "https://api.groq.com/openai/v1"
CHAT_MODELS = [m.strip() for m in os.getenv("GROQ_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b").split(",") if m.strip()]
STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
TIMEOUT_S = 45


class GroqError(Exception):
    pass


class GroqNoKey(GroqError):
    pass


def api_key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip()


def _headers() -> dict:
    key = api_key()
    if not key:
        raise GroqNoKey("No GROQ_API_KEY in .env.")
    return {"Authorization": f"Bearer {key}"}


def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 1400, json_mode: bool = False) -> tuple[str, str]:
    """Return (text, model_used). Tries each model in CHAT_MODELS once."""
    headers = _headers()
    errors = []
    for model in CHAT_MODELS:
        body = {"model": model, "messages": messages, "temperature": temperature, "max_completion_tokens": max_tokens}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"  # keeps answers fast; the task is reading, not math
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(f"{BASE}/chat/completions", json=body, headers=headers, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            errors.append(f"{model}: {type(e).__name__}")
            continue
        if r.status_code == 401:
            raise GroqError("Groq rejected GROQ_API_KEY (401). Check .env.")
        if r.status_code >= 400:
            errors.append(f"{model}: HTTP {r.status_code}")
            continue
        try:
            text = r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError):
            errors.append(f"{model}: bad response")
            continue
        if text.strip():
            return text, model
        errors.append(f"{model}: empty answer")
    raise GroqError("Groq is unavailable right now (" + "; ".join(errors) + ").")


def transcribe(audio: bytes, filename: str, mime: str, language: str | None = None) -> str:
    """Speech to text with Whisper on Groq."""
    data = {"model": STT_MODEL, "response_format": "json", "temperature": "0"}
    if language:
        data["language"] = language
    try:
        r = requests.post(
            f"{BASE}/audio/transcriptions",
            headers=_headers(),
            files={"file": (filename, audio, mime)},
            data=data,
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise GroqError(f"Transcription failed ({type(e).__name__}).") from e
    if r.status_code == 429:
        raise GroqError("Speech limit reached for now. Type your idea instead.")
    if r.status_code >= 400:
        raise GroqError(f"Transcription failed (HTTP {r.status_code}).")
    return (r.json().get("text") or "").strip()
