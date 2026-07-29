"""
Inference layer. Two providers, one interface.

GROWMATED_PROVIDER=nvidia (default)  -> free NVIDIA endpoint
GROWMATED_PROVIDER=claude            -> Anthropic API (needs credits on the account)

NVIDIA model notes for this account, measured 2026-07-29 by sweeping all 102 catalog models
(only 26 are reachable; 61 return "Not found for account" and 10 hang until timeout):

  mistralai/mistral-nemotron      ~9s,  0 house-style violations, correct proof.  <- default
  meta/llama-3.1-70b-instruct     ~40s, 1 violation. Works but slow and swingy (8-50s).
  meta/llama-3.1-8b-instruct      ~1.5s but picks the wrong case study.
  meta/llama-3.3-70b-instruct     HANGS until timeout. Never use.
  nemotron-3-super-120b-a12b      Fast to first byte but never emits parseable JSON.
  openai/gpt-oss-20b, step-3.7-flash   Return empty content.

Claude enforces the response schema server-side; NVIDIA only takes a JSON-mode hint, so the
NVIDIA path extracts the first balanced JSON object from whatever wrapping the model adds.
"""

import json
import os
import time
from pathlib import Path

from config import get_secret

PROVIDER = (get_secret("GROWMATED_PROVIDER") or "nvidia").lower()

NVIDIA_MODEL = get_secret("GROWMATED_NVIDIA_MODEL") or "mistralai/mistral-nemotron"
CLAUDE_MODEL = get_secret("GROWMATED_CLAUDE_MODEL") or "claude-opus-5"
MODEL = CLAUDE_MODEL if PROVIDER == "claude" else NVIDIA_MODEL

# On Claude these are reasoning-effort levels. On NVIDIA there is no effort knob, so both
# modes run the same model and the toggle simply has no effect.
SPEED_MODES = {
    "🎯 Quality": {"effort": "high", "caption": f"Full reasoning. Model: {MODEL}"},
    "⚡ Fast": {"effort": "low", "caption": "Less reasoning. Check the proof banner."},
}

MAX_OUTPUT_TOKENS = 4000


class MissingKeyError(RuntimeError):
    """No credentials configured, so the UI can show setup help instead of a traceback."""


class RefusedError(RuntimeError):
    """The model declined the request."""


def load_api_key(name: str) -> str:
    """Environment first, then Streamlit secrets. Never hardcode a key."""
    return get_secret(name)


def build_client():
    if PROVIDER == "claude":
        import anthropic

        key = load_api_key("ANTHROPIC_API_KEY")
        if not key:
            raise MissingKeyError("ANTHROPIC_API_KEY is not set in .env.")
        return anthropic.Anthropic(api_key=key, timeout=120.0, max_retries=2)

    from openai import OpenAI

    key = load_api_key("NVIDIA_API_KEY")
    if not key:
        raise MissingKeyError("NVIDIA_API_KEY is not set in .env.")
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=key,
        timeout=90.0,
        # The SDK default of 2 turns a hung request into a multi-minute frozen spinner.
        max_retries=1,
    )


def extract_json(text: str):
    """NVIDIA models wrap JSON in prose or code fences. Pull out the first balanced object."""
    text = (text or "").strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in response")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in response")


def generate_json(client, system_prompt: str, user_content: str, schema: dict,
                  effort: str = "high") -> tuple[dict, float]:
    """One structured completion. Returns (parsed_payload, elapsed_seconds)."""
    started = time.monotonic()

    if PROVIDER == "claude":
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,  # caps thinking + text together on this model
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        elapsed = time.monotonic() - started
        if message.stop_reason == "refusal":
            raise RefusedError("The model declined to draft this. Check the source text.")
        text = "".join(b.text for b in message.content if b.type == "text")
        return json.loads(text), elapsed

    completion = client.chat.completions.create(
        model=NVIDIA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        max_tokens=MAX_OUTPUT_TOKENS,
        response_format={"type": "json_object"},
    )
    elapsed = time.monotonic() - started
    return extract_json(completion.choices[0].message.content), elapsed


REPAIR_SYSTEM = """You are a copy editor for Growmated. You will be given a JSON object of
outreach copy and a list of house-style violations in it.

Rewrite ONLY the fields that contain a violation. Keep every other field byte-identical.
Preserve the meaning, the specific details, and any client result already present.
Do not add new claims, numbers, or clients. Do not add placeholders. Do not use em-dashes.

How to fix each violation type:
  - link / web address / email address / phone number: DELETE it outright. Do not replace it
    with another contact route. The call to action becomes a plain request to reply, such as
    "Just reply and I will send a couple of times that work." Refer to their website as
    "your site", never by its address.
  - too many words: cut the least specific sentence. Never cut the concrete detail about
    the prospect, and never cut the sign-off.
  - banned phrase: rewrite that sentence in plain, direct English.
  - invented client work / invented statistic: DELETE the entire sentence containing it.
    Do not replace it with a different client or a different number. It is always better to
    say less than to claim something that did not happen.
  - sign-off / no line breaks: rewrite email_body with real newline characters. Short
    paragraphs separated by a blank line, then a blank line, then "Mujaddad" on its own line,
    then "Growmated" on its own line, then a blank line, then the "P.S." line if present.

Return the corrected JSON object with exactly the same keys as the input, and nothing else."""


def repair_copy(client, responses: dict, violations: list[str], schema: dict,
                effort: str = "low") -> dict:
    """Fix specific house-style violations. Falls back to the original on any error."""
    try:
        payload, _ = generate_json(
            client,
            REPAIR_SYSTEM,
            "VIOLATIONS:\n- " + "\n- ".join(violations)
            + f"\n\nJSON:\n{json.dumps(responses, ensure_ascii=False)}",
            schema,
            effort=effort,
        )
        if isinstance(payload, dict) and payload:
            merged = dict(responses)
            merged.update({k: v for k, v in payload.items() if isinstance(v, str)})
            return merged
    except Exception:
        # A style slip is never worth losing the draft over.
        pass
    return responses
