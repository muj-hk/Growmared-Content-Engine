"""
Growmated outreach smoke test — runs prospect fixtures through the live model and
checks the output against the brand rules in growmated_knowledge.py.

Run:  python test_outreach.py
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from context_builder import (
    OUTREACH_RESPONSES_SCHEMA,
    OUTREACH_SCHEMA,
    UPWORK_RESPONSES_SCHEMA,
    UPWORK_SCHEMA,
    build_outreach_system_prompt,
    build_upwork_system_prompt,
    normalize_proof_id,
)
from growmated_knowledge import PROOF_BANK, VOICE
from intent import fields_for
from llm import MODEL, build_client, generate_json, repair_until_clean
from quality import (
    find_fabrications,
    find_violations,
    normalize_responses,
    repairable_fields,
)

load_dotenv(Path(__file__).with_name(".env"))

EFFORT = os.getenv("GROWMATED_EFFORT", "high")
VALID_PROOF_IDS = {entry["id"] for entry in PROOF_BANK} | {"market_math", "none"}

FIXTURES = [
    {
        "label": "photo booth (proof bank should match 'photobooth')",
        "text": (
            "Hi all, I run a photo booth company in Austin TX. We are drowning in inquiries from "
            "Instagram, Facebook and our website. Half the time we reply the next day and the client "
            "already booked someone else. Looking for a technical GHL partner to set up automated "
            "follow up. Reach me at sarah@luxebooths.io or 512-555-0142. - Sarah Whitfield, Luxe Booths"
        ),
        "expect_email": True,
    },
    {
        "label": "chauffeur (should match 'chauffeur')",
        "text": (
            "Anyone know a good automation person? I own a black car service in Chicago. We miss "
            "late night booking calls constantly and quoting fares by hand is killing me. "
            "DM me here. - Marcus, Apex Executive Transport"
        ),
        "expect_email": False,
    },
    {
        "label": "no-proof-fit case (should fall back to market_math or none)",
        "text": (
            "Looking for advice: I run a small independent bookshop in Leeds and I want to start "
            "emailing my customer list about new arrivals. Never done marketing before. "
            "hello@pagesleeds.co.uk"
        ),
        "expect_email": True,
    },
]


def word_count(text):
    return len(text.split())


def check(bundle, fixture):
    """Return a list of rule violations for one generated bundle."""
    extracted = bundle.get("extracted", {})
    responses = bundle.get("responses", {})
    email_body = responses.get("email_body", "") or ""
    proof = normalize_proof_id(responses.get("proof_used")) or "MISSING"

    # Shared house-style + deliverability rules, same code the app runs.
    _fields = repairable_fields(responses)
    failures = list(find_violations(_fields)) + list(find_fabrications(_fields, proof))

    if proof not in VALID_PROOF_IDS:
        failures.append(f"proof_used={proof!r} is not approved (only the one proof story is allowed)")

    # Email is drafted only when an address exists AND the routed intent allows an email.
    # A "question" correctly produces an answer and nothing else, even with an address present.
    intent = (bundle.get("routing", {}) or {}).get("intent", "post")
    email_allowed = "email" in fields_for(intent)

    if fixture["expect_email"] and email_allowed:
        if not extracted.get("email"):
            failures.append("expected an email address to be extracted, got none")
        elif not email_body.strip():
            failures.append("email address was found but email_body is empty")
    elif email_body.strip() and not fixture["expect_email"]:
        failures.append("no email address in source, but an email body was still drafted")

    return failures


UPWORK_FIXTURES = [
    {
        "label": "upwork: GHL automation (should be high fit)",
        "text": (
            "Title: GoHighLevel Expert Needed to Build Lead Follow-Up Automation\n"
            "Budget: $1,500 fixed. We are a US home services company. Leads come in from Facebook "
            "ads and our website but nobody follows up fast enough. We need automated SMS and email "
            "follow-up sequences in GoHighLevel, plus appointment booking. Must know A2P registration."
        ),
        "expect_fit": {"high", "medium"},
    },
    {
        "label": "upwork: unrelated job (should be low fit, honestly)",
        "text": (
            "Title: Illustrator needed for children's picture book\n"
            "Budget: $800. Looking for a watercolour artist to illustrate 24 pages of a "
            "children's book about a dragon. Portfolio required."
        ),
        "expect_fit": {"low"},
    },
]


def check_upwork(bundle, fixture):
    responses = bundle.get("responses", {})
    proposal = responses.get("proposal", "") or ""
    fit = (responses.get("fit_score") or "").lower()
    proof = normalize_proof_id(responses.get("proof_used")) or "MISSING"

    failures = list(find_violations(repairable_fields(responses)))

    if proof not in VALID_PROOF_IDS:
        failures.append(f"proof_used={proof!r} is not approved (only the one proof story is allowed)")
    if fit not in fixture["expect_fit"]:
        failures.append(f"fit_score={fit!r}, expected one of {sorted(fixture['expect_fit'])}")
    if not proposal.strip():
        failures.append("proposal is empty")

    lowered = proposal.lower()
    # Only a *labelled* id is a leak; bare words appear legitimately in prose.
    for entry in PROOF_BANK:
        pid = re.escape(entry["id"])
        if re.search(rf'(["\'(\[]{pid}["\')\]]|id\s*=\s*{pid})', lowered):
            failures.append(f"leaked internal proof id {entry['id']!r} into the proposal text")

    return failures


def apply_repair(client, responses, schema):
    """Mirror the app exactly: normalize typography, then repair until clean."""
    before = repairable_fields(normalize_responses(responses))
    problems = find_violations(before) + find_fabrications(
        before, normalize_proof_id(responses.get("proof_used"))
    )
    if problems:
        print(f"  repairing  : {len(problems)} violation(s) -> {problems}")
    return repair_until_clean(client, responses, schema)


def main():
    client = build_client()
    print(f"model: {MODEL}  effort: {EFFORT}")
    system_prompt = build_outreach_system_prompt()

    total_failures = 0
    for fixture in FIXTURES:
        print(f"\n=== {fixture['label']} ===")
        try:
            bundle, elapsed = generate_json(
                client, system_prompt, f"RAW TEXT:\n{fixture['text']}",
                OUTREACH_SCHEMA, effort=EFFORT,
            )
            print(f"  generated in {elapsed:.1f}s")
        except Exception as exc:
            print(f"  REQUEST FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            total_failures += 1
            continue

        bundle["responses"] = apply_repair(
            client, bundle.get("responses", {}), OUTREACH_RESPONSES_SCHEMA
        )
        responses = bundle["responses"]
        print(f"  proof_used : {responses.get('proof_used')!r}")
        print(f"  comment    : {responses.get('comment')}")
        print(f"  dm         : {responses.get('dm')}")
        print(f"  subject    : {responses.get('email_subject')}")
        print(f"  email      : {responses.get('email_body')}")

        failures = check(bundle, fixture)
        if failures:
            total_failures += len(failures)
            print("  RESULT: FAIL")
            for failure in failures:
                print(f"    - {failure}")
        else:
            print("  RESULT: PASS")

    upwork_prompt = build_upwork_system_prompt()
    for fixture in UPWORK_FIXTURES:
        print(f"\n=== {fixture['label']} ===")
        try:
            bundle, elapsed = generate_json(
                client, upwork_prompt, f"RAW TEXT:\n{fixture['text']}",
                UPWORK_SCHEMA, effort=EFFORT,
            )
            print(f"  generated in {elapsed:.1f}s")
        except Exception as exc:
            print(f"  REQUEST FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            total_failures += 1
            continue

        bundle["responses"] = apply_repair(
            client, bundle.get("responses", {}), UPWORK_RESPONSES_SCHEMA
        )
        responses = bundle["responses"]
        print(f"  fit        : {responses.get('fit_score')!r} - {responses.get('fit_reason')}")
        print(f"  proof_used : {responses.get('proof_used')!r}")
        print(f"  proposal   : {responses.get('proposal')}")

        failures = check_upwork(bundle, fixture)
        if failures:
            total_failures += len(failures)
            print("  RESULT: FAIL")
            for failure in failures:
                print(f"    - {failure}")
        else:
            print("  RESULT: PASS")

    print(f"\n{'=' * 60}")
    print("ALL CHECKS PASSED" if total_failures == 0 else f"{total_failures} CHECK(S) FAILED")
    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
