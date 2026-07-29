"""
House-style checks, in one place.

The prompt asks the model to avoid these, but "I'd love to" and "businesses like yours" are
common enough English that a 70B model reaches for them anyway. So we detect violations after
generation and repair them, rather than trusting instructions alone.

No streamlit import here on purpose: the UI, the repair pass and the test suite all share it.
"""

import re

from growmated_knowledge import MARKET_MATH, PROOF_BANK, VOICE

PLACEHOLDER_RE = re.compile(r"\[(your name|name|company|x|client|first name)\]", re.I)

# Deliverability rules from the handoff doc: an opening email carrying a link, a web address or
# an email address gets auto-linked by mail clients and lands in spam.
URL_RE = re.compile(r"https?://|www\.", re.I)
DOMAIN_RE = re.compile(r"\b[a-z0-9][a-z0-9-]*\.(com|net|org|io|co|ai)\b", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
PHONE_RE = re.compile(r"(\+\d[\d\s().-]{7,}\d)")

# Fields that must never carry a link, domain, email address or phone number.
NO_CONTACT_FIELDS = ("comment", "dm", "email_subject", "email_body", "proposal")

WORD_LIMITS = {
    "comment": 45,
    "dm": 80,
    "email_body": 110,
    "proposal": 180,
}

SUBJECT_WORD_LIMIT = 8

# Distinctive fragments of the quarantined client stories in growmated_knowledge.UNVERIFIED_CLAIMS.
# Only the one approved proof story may be told, so these must never reach a prospect.
# Deliberately specific: bare words like "accounting" or "chauffeur" appear legitimately when
# the prospect is in that industry, and "A2P registration" is a skill, not a client result.
QUARANTINED_MARKERS = [
    "accounting firm",
    "consulting firm",
    "1,000 dials",
    "1000 dials",
    "271",
    "23 booked",
    "15 workflows",
    "42 hours",
    "sub-accounts",
    "sub accounts",
    "100+ accounts",
]


# Typographic characters models emit that house style forbids. These are mechanical
# substitutions, so fix them deterministically instead of spending an LLM repair pass on
# something a dictionary lookup handles perfectly.
PUNCTUATION_FIXES = {
    "—": ", ",   # em dash
    "–": "-",    # en dash
    "’": "'",    # right single quote
    "‘": "'",    # left single quote
    "“": '"',    # left double quote
    "”": '"',    # right double quote
    "…": "...",  # ellipsis
    " ": " ",    # non-breaking space
}


def normalize_punctuation(text: str) -> str:
    for bad, good in PUNCTUATION_FIXES.items():
        text = text.replace(bad, good)
    # An em dash replaced mid-sentence can leave a doubled separator.
    return text.replace(" , ", ", ").replace(",,", ",")


def normalize_responses(responses: dict) -> dict:
    """Apply the mechanical fixes to every text field before anything else looks at it."""
    return {
        key: normalize_punctuation(value) if isinstance(value, str) else value
        for key, value in responses.items()
    }


def word_count(text: str) -> int:
    return len((text or "").split())


def _loose(text: str) -> str:
    """Collapse punctuation and whitespace so phrase matching survives the model's formatting.

    Without this, a banned phrase like "game changer" slips through as "game-changer" and
    "best-in-class" slips through as "best in class".
    """
    return re.sub(r"[\s\-_/]+", " ", (text or "").lower())


# Percentages that legitimately appear in approved material. Anything else in the copy is
# a number the model made up.
_APPROVED_NUMBERS = set(re.findall(r"\d+", " ".join(MARKET_MATH)))
_APPROVED_NUMBERS |= set(re.findall(r"\d+", " ".join(e["claim"] for e in PROOF_BANK)))

# First-person claims about work done for a client. Legitimate only when the message is
# actually citing the one approved proof story.
_CLIENT_CLAIM_RE = re.compile(
    # "we helped", "we've helped", "we have worked with", "I'd built ... for"
    r"\b(?:we|i)\s*(?:'ve|'d|\s+have|\s+had)?\s+"
    r"(?:helped|worked with|partnered|completed|delivered|did this for|"
    r"built (?:this |it |a |an )?for|run (?:this |it |the )?(?:\w+\s+){0,3}for|"
    r"set (?:this |it )?up for)\b"
    # "one of our illustrators recently completed", "our client saw"
    r"|\bone of our\b"
    r"|\bour\s+(?:\w+\s+){0,2}(?:recently\s+)?(?:completed|delivered|built|helped|achieved|saw)\b"
    r"|\bour\s+(?:client|clients|customer|customers)\b",
    re.I,
)
_STAT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+x\b", re.I)

# Multipliers written as words dodge the digit check entirely ("can triple engagement").
_WORD_STAT_RE = re.compile(
    r"\b(?:double|triple|quadruple|tenfold|ten-fold)\s+(?:your\s+|their\s+|the\s+)?\w+",
    re.I,
)


def find_fabrications(fields: dict, proof_used: str | None) -> list[str]:
    """Catch invented clients and invented numbers.

    The proof banner only tells you *which* id was claimed. It cannot tell you the copy
    invented "we helped a bookshop and saw a 30% lift" while reporting proof_used='none'.
    This is the highest-stakes failure for outreach, so it gets its own check.
    """
    problems = []
    blob = " ".join(v for v in fields.values() if isinstance(v, str) and v)
    citing_real_proof = proof_used in {e["id"] for e in PROOF_BANK}

    if not citing_real_proof:
        match = _CLIENT_CLAIM_RE.search(blob)
        if match:
            problems.append(
                f'invented client work ("{match.group(0)}") while claiming proof_used="{proof_used}"'
            )
    else:
        # Citing a real story is only honest if the client is described accurately. Models
        # keep the real numbers but relabel the client to match the prospect's industry
        # ("one home services client we work with...", citing the photo booth result).
        entry = next(p for p in PROOF_BANK if p["id"] == proof_used)
        signature = (entry.get("signature") or "").lower()
        if signature and signature not in blob.lower():
            problems.append(
                f'cites the "{proof_used}" story but never says "{entry["signature"]}", '
                "so the client has been relabelled"
            )

    for stat in _STAT_RE.findall(blob):
        digits = re.sub(r"\D", "", stat)
        if digits and digits not in _APPROVED_NUMBERS:
            problems.append(f'invented statistic "{stat.strip()}" - not in approved material')

    for claim in _WORD_STAT_RE.findall(blob):
        problems.append(f'invented performance claim "{claim.strip()}" - no data supports it')

    return problems


def find_violations(fields: dict) -> list[str]:
    """fields maps a field name (comment/dm/email_body/proposal/...) to its text."""
    problems = []
    blob = " ".join(v for v in fields.values() if v)
    lowered = blob.lower()
    loose = _loose(blob)

    for phrase in VOICE["banned_phrases"]:
        if _loose(phrase) in loose:
            problems.append(f'banned phrase "{phrase}"')

    placeholder = PLACEHOLDER_RE.search(blob)
    if placeholder:
        problems.append(f'unfilled placeholder "{placeholder.group(0)}"')

    if "—" in blob:
        problems.append("em-dash (house style forbids it)")

    for name, limit in WORD_LIMITS.items():
        count = word_count(fields.get(name))
        if count > limit:
            problems.append(f"{name} is {count} words, limit is {limit}")

    subject = fields.get("email_subject") or ""
    if subject and word_count(subject) > SUBJECT_WORD_LIMIT:
        problems.append(f"email_subject is {word_count(subject)} words, limit is {SUBJECT_WORD_LIMIT}")

    # Deliverability: no links, domains, email addresses or phone numbers in outgoing copy.
    for name in NO_CONTACT_FIELDS:
        text = fields.get(name) or ""
        if not text:
            continue
        if URL_RE.search(text):
            problems.append(f"{name} contains a link, which sends the email to spam")
        elif DOMAIN_RE.search(text):
            problems.append(f"{name} contains a web address, which mail clients auto-link into spam")
        if EMAIL_RE.search(text):
            problems.append(f"{name} contains an email address, which must never appear in the body")
        if PHONE_RE.search(text):
            problems.append(f"{name} contains a phone number, which must not be dumped into the copy")

    for marker in QUARANTINED_MARKERS:
        if marker in lowered:
            problems.append(f'told a non-approved client story ("{marker}")')

    # A cold email that arrives as one unbroken block reads as spam and needs hand-formatting
    # every time. The sign-off must be its own two lines.
    email_body = fields.get("email_body") or ""
    if email_body:
        if "\n" not in email_body:
            problems.append("email_body has no line breaks, it will send as one block of text")
        if not re.search(r"Mujaddad\s*\n+\s*Growmated", email_body):
            problems.append("email_body is missing the two-line sign-off (Mujaddad / Growmated)")

    # A bare id like "accounting" is legitimate English; only a labelled one is a leak.
    for entry in PROOF_BANK:
        pid = re.escape(entry["id"])
        if re.search(rf'(["\'(\[]{pid}["\')\]]|id\s*=\s*{pid})', lowered):
            problems.append(f'internal proof id "{entry["id"]}" leaked into the copy')

    return problems


def repairable_fields(responses: dict) -> dict:
    """The text fields worth checking and repairing."""
    return {
        key: responses.get(key)
        for key in ("comment", "dm", "email_subject", "email_body", "proposal", "opening_question")
        if responses.get(key)
    }
