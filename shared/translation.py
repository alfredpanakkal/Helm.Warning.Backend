#!/usr/bin/env python3
"""
shared/translation.py — Fail-closed title translation for non-English
NAVAREA bulletins (Chile XV / Peru XVI publish Spanish titles;
the Norway XIX series is published in English but individual items
may carry Norwegian text).

Safety contract (mirrors shared/ai_escalation.py / gemini_navarea_parser):
  * GEMINI_API_KEY is read from the environment ONLY, sent in the
    x-goog-api-key header, never in the URL, argv or logs.
  * Any missing key, timeout, HTTP error or malformed response returns
    None — the ORIGINAL title is kept. Translation never blocks or fails
    an ingest (Tier data is untouched: the raw text is always the
    original Spanish).
  * Errors are logged WITHOUT the request URL or key material.
  * Model is configurable via GEMINI_MODEL_NAME; default
    gemini-3.5-flash-lite (gemini-2.5-flash-lite was retired 2026-10-22;
    never assume a model ID remains available).
"""
import json
import os
import re
import urllib.error
import urllib.request

GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEFAULT_MODEL = "gemini-3.5-flash-lite"
_TIMEOUT_S = 20

# Conservative Spanish indicator for translation triggering: accented
# characters + high-signal Spanish words common in XV/XVI titles. Pure
# English titles never trigger a translation call.
RE_SPANISH_HINT = re.compile(
    r"[áéíóúñÁÉÍÓÚÑ¿¡]"
    r"|\b(?:PLATAFORMA|PLATAFORMAS|PUERTO|CARTA|ESTRECHO|ISLA|BOYA|BOYAS"
    r"|AVISO|AVISOS|ZONA|PROHIBIDA|PROHIBIDO|INOPERATIVA|INOPERATIVO"
    r"|OPERANDO|EJERCICIO|FONDEO|NAVEGAN|NAVEGACION|MARINO|DEL|AL)\b",
    re.IGNORECASE,
)

_PROMPTS = {
    "es": (
        "Translate the following maritime navigational warning title from "
        "Spanish to English. Keep place names and vessel names unchanged. "
        "Output ONLY the English translation, with no quotes, no "
        "commentary and no explanations.\n\n"
    ),
    # NAVAREA XIX (Kystverket): the series is published in English, but
    # individual items occasionally carry Norwegian titles.
    "no": (
        "Translate the following maritime navigational warning title from "
        "Norwegian to English. Keep place names and vessel names "
        "unchanged. Output ONLY the English translation, with no quotes, "
        "no commentary and no explanations.\n\n"
    ),
}


def looks_spanish(text: str) -> bool:
    """True if the title shows clear Spanish markers worth translating."""
    if not text:
        return False
    return bool(RE_SPANISH_HINT.search(text))


# Conservative Norwegian indicator (NAVAREA XIX): the 'ae o-slash a-ring'
# letters never occur in English warning titles, and the listed words are
# high-signal Norwegian maritime vocabulary. Pure English titles never
# trigger a translation call.
RE_NORWEGIAN_HINT = re.compile(
    r"[\u00e6\u00f8\u00e5\u00c6\u00d8\u00c5]"
    r"|\b(?:VARSEL|VARSLER|FYRING|FYR|OMR\u00c5DE|OMR\u00c5DET"
    r"|\u00d8VELSE|\u00d8VELSER|GRUNN|GRUNNE|SKJERMING|SPERRING"
    r"|SPERRES|SPERRET|RAKETT|FART\u00d8Y|FART\u00d8YER|MISTET"
    r"|SEISMISK|SKYT\u00d8V|AVSTAND|HOLDE)\b",
    re.IGNORECASE,
)


def looks_norwegian(text: str) -> bool:
    """True if the title shows clear Norwegian markers worth translating."""
    if not text:
        return False
    return bool(RE_NORWEGIAN_HINT.search(text))


def detect_source_lang(text: str) -> str | None:
    """'es' for clearly Spanish, 'no' for clearly Norwegian, else None."""
    if looks_spanish(text):
        return "es"
    if looks_norwegian(text):
        return "no"
    return None


def maybe_translate_title(title: str) -> str | None:
    """Language-dispatching title translation (parser entry point).

    Translates only when the title clearly looks Spanish or Norwegian;
    returns None otherwise — and on ANY failure the caller keeps the
    original title. Fail-closed in every path, exactly like
    translate_title."""
    source_lang = detect_source_lang(title)
    if not source_lang:
        return None
    return translate_title(title, source_lang=source_lang)


def _extract_translation_text(response_body: str) -> str | None:
    try:
        data = json.loads(response_body)
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        for part in parts:
            txt = part.get("text")
            if txt and txt.strip():
                return txt.strip()
    except (ValueError, AttributeError, TypeError, IndexError, KeyError):
        return None
    return None


def translate_title(title: str, source_lang: str = "es",
                     target_lang: str = "en") -> str | None:
    """Translates a warning title via Gemini. Fail-closed: returns None
    (keep the original) on ANY problem — missing key, network error,
    timeout, malformed or implausible response."""
    if not title or not title.strip():
        return None

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("GEMINI_MODEL_NAME", "").strip() or DEFAULT_MODEL

    request_body = json.dumps({
        "contents": [{
            "parts": [{"text": _PROMPTS.get(source_lang, _PROMPTS["es"])
                       + title}],
        }],
    }).encode("utf-8")

    req = urllib.request.Request(
        GEMINI_ENDPOINT_TEMPLATE.format(model=model),
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,  # header only — never in URL/argv
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        # Redacted: no URL, no key, no response body in logs.
        print(f"⚠️ Title translation unavailable (network/API error: "
              f"{type(exc).__name__}). Keeping original title.")
        return None

    translated = _extract_translation_text(body)
    if not translated:
        print("⚠️ Title translation returned no usable text. Keeping original title.")
        return None

    # Plausibility guards: a translation must be short text, must differ
    # from the original, and must not smuggle in extra commentary.
    if translated == title.strip():
        return None
    if len(translated) > 400 or len(translated) < 3:
        return None
    if "\n" in translated:
        translated = " ".join(translated.split())
    return translated
