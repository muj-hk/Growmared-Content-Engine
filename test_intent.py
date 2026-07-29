"""
Does the router recognise what the team actually pastes, and does it stay quiet when it should?

Run: python test_intent.py
"""

import json
import sys

from context_builder import OUTREACH_SCHEMA, build_outreach_system_prompt, normalize_proof_id
from intent import fields_for
from llm import MODEL, build_client, generate_json
from quality import find_fabrications, find_violations, normalize_responses, repairable_fields

FIXTURES = [
    {
        "label": "hiring post",
        "text": ("Looking for a GoHighLevel expert to build out our lead follow up. We run a "
                 "roofing company in Dallas and leads go cold because nobody calls back. "
                 "Paid gig, ongoing if it works out."),
        "expect": {"hiring", "post"},
        "must_produce": ["dm"],
    },
    {
        "label": "open question (no pitch allowed)",
        "text": ("Quick question for the group. Does anyone know if GoHighLevel can send SMS "
                 "to Canadian numbers without a separate A2P registration? Getting mixed "
                 "answers from support."),
        "expect": {"question"},
        "must_produce": ["answer"],
        "must_not_produce": ["comment", "dm", "email_body"],
    },
    {
        "label": "someone selling TO us",
        "text": ("Hey! I'm a lead gen specialist and I help agencies like yours get 20-30 "
                 "qualified appointments a month, guaranteed. Interested in a quick chat about "
                 "how we could work together?"),
        "expect": {"offer", "skip"},
    },
    {
        "label": "live conversation with an objection",
        "text": ("ME: Worth 15 minutes to show you where the leak is? Just reply and I'll send "
                 "a couple of times.\n\n"
                 "THEM: Honestly we looked at something like this last year and it was about "
                 "$1500/mo which is way out of our range for now. Maybe later in the year.\n\n"
                 "ME: (need the next reply)"),
        "expect": {"conversation"},
        "must_produce": ["reply"],
        "expect_objection": {"price", "timing"},
    },
    {
        # A salaried job ad IS a hiring post, so the intent label matters less than the
        # decision: it must refuse to engage and say why. Either label is acceptable.
        "label": "obvious skip (salaried recruiter)",
        "text": ("We are hiring a full-time Junior Marketing Assistant, on site in Manchester, "
                 "22k-25k. Must have 1 year experience. Apply through our careers page."),
        "expect": {"skip", "hiring"},
        "expect_no_engage": True,
        "must_not_produce": ["comment", "dm", "email_body"],
    },
    {
        "label": "problem post",
        "text": ("Bit of a rant. I run a mobile car detailing business and I am drowning. "
                 "Phone rings while I'm working, I miss it, then I forget to call back. "
                 "Losing jobs every week and I don't know where to start."),
        "expect": {"problem", "post"},
        "must_produce": ["dm"],
    },
]


def main() -> int:
    client = build_client()
    prompt = build_outreach_system_prompt()
    print(f"model: {MODEL}\n")
    failures = 0

    for fx in FIXTURES:
        print(f"=== {fx['label']} ===")
        try:
            payload, elapsed = generate_json(client, prompt, f"RAW TEXT:\n{fx['text']}", OUTREACH_SCHEMA)
        except Exception as exc:
            print(f"  REQUEST FAILED: {type(exc).__name__}: {str(exc)[:160]}\n")
            failures += 1
            continue

        routing = payload.get("routing", {}) or {}
        responses = normalize_responses(payload.get("responses", {}) or {})
        detected = routing.get("intent")
        engage = routing.get("should_engage")
        produced = [k for k in ("comment", "dm", "email_body", "answer", "reply") if (responses.get(k) or "").strip()]

        print(f"  intent   : {detected!r}  engage={engage!r}  ({elapsed:.1f}s)")
        print(f"  produced : {produced or 'nothing'}")
        if routing.get("skip_reason"):
            print(f"  skip why : {routing['skip_reason']}")
        for field in produced:
            print(f"  {field}: {(responses.get(field) or '')[:150]}")

        problems = []
        if detected not in fx["expect"]:
            problems.append(f"intent {detected!r} not in expected {sorted(fx['expect'])}")
        if fx.get("expect_no_engage") and engage != "no":
            problems.append(f"should_engage was {engage!r}, expected 'no' for this input")
        for field in fx.get("must_produce", []):
            if not (responses.get(field) or "").strip():
                problems.append(f"expected {field} to be produced, it was empty")
        for field in fx.get("must_not_produce", []):
            if (responses.get(field) or "").strip():
                problems.append(f"{field} should be empty for this intent, got copy")
        if "expect_objection" in fx:
            got = responses.get("objection_category")
            if got not in fx["expect_objection"]:
                problems.append(f"objection {got!r} not in {sorted(fx['expect_objection'])}")

        # House style and fabrication still apply to whatever it did produce.
        fields = repairable_fields(responses)
        problems += find_violations(fields)
        problems += find_fabrications(fields, normalize_proof_id(responses.get("proof_used")))

        if problems:
            failures += len(problems)
            print("  RESULT: FAIL")
            for p in problems:
                print(f"    - {p}")
        else:
            print("  RESULT: PASS")
        print()

    print("=" * 60)
    print("ALL CHECKS PASSED" if not failures else f"{failures} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
