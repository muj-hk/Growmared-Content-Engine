"""
House-style checks, in one place.

The prompt asks the model to avoid these, but "I'd love to" and "businesses like yours" are
common enough English that a 70B model reaches for them anyway. So we detect violations after
generation and repair them, rather than trusting instructions alone.

No streamlit import here on purpose: the UI, the repair pass and the test suite all share it.
"""

import re

from growmated_knowledge import BRAND, MARKET_MATH, PROOF_BANK, VOICE

PLACEHOLDER_RE = re.compile(r"\[(your name|name|company|x|client|first name)\]", re.I)

# Deliverability rules from the handoff doc: an opening email carrying a link, a web address or
# an email address gets auto-linked by mail clients and lands in spam.
URL_RE = re.compile(r"https?://|www\.", re.I)
DOMAIN_RE = re.compile(r"\b[a-z0-9][a-z0-9-]*\.(com|net|org|io|co|ai)\b", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
PHONE_RE = re.compile(r"(\+\d[\d\s().-]{7,}\d)")

# Fields that must never carry a link, domain, email address or phone number.
NO_CONTACT_FIELDS = ("comment", "dm", "email_subject", "email_body", "proposal")

# Structural labels the model writes as a note to itself and then ships. A real DM went out
# to a prospect opening with "Anchor." Anchored to the very start, so prose that happens to
# use the word is unaffected.
LABEL_LEAK_RE = re.compile(
    r"^\s*(anchor|hook|opener|insight|angle|proof|cta|body|subject|observation|"
    r"pain[- ]mirror|value|note)\s*[:.\-]\s",
    re.I,
)

# A comment whose entire content is "sent you a DM" teaches nobody anything and reads like
# every other agency in the thread. The comment is the part strangers judge us on.
DM_ONLY_COMMENT_RE = re.compile(
    r"^\s*(hey|hi|hello)?[\s,]*[\w' ]{0,22}[\s,]*"
    r"(just\s+)?(sent|dropped|shot)\s+(you\s+)?(a\s+|an\s+)?(dm|message|pm)\b[\s.!]*$",
    re.I,
)

WORD_LIMITS = {
    # 45 was set when a comment was just "sent you a DM". Now that a comment must carry a
    # real insight in 2-3 sentences, 45 forced the repair pass to cut the substance back out.
    # 65 then let comments drift into paragraphs nobody reads in a feed: 55 is about three
    # dense sentences, which is the most a stranger will read from an unknown commenter.
    "comment": 55,
    "dm": 70,
    "email_body": 110,
    "proposal": 180,
    # `answer` and `reply` were originally uncapped, and answers ran to 507 words in
    # production. A group answer that long does not get read; it also gives away the whole
    # build for free instead of earning a conversation.
    "answer": 120,
    "reply": 75,
}

SUBJECT_WORD_LIMIT = 8

# Client results that are NOT in the capabilities PDF and therefore must never reach a
# prospect. The four PDF case studies are all in PROOF_BANK now, so this list covers only the
# accounting-firm figures, which appear nowhere published.
#
# Deliberately narrow. Earlier this list also blocked "sub-accounts" and "consulting firm",
# which became false positives the moment those case studies were approved. Anything here must
# be distinctive enough that it cannot show up in legitimate copy: bare words like "accounting"
# appear naturally when the prospect IS an accountant, and "42 hours" collides with the
# MARKET_MATH line about median reply time.
QUARANTINED_MARKERS = [
    "15 workflows",
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
    text = text.replace(" , ", ", ").replace(",,", ",")
    # ...and a doubled space, which shipped in real copy. Spaces and tabs only: collapsing
    # newlines would destroy the email paragraph structure the sign-off rule depends on.
    return re.sub(r"[ \t]{2,}", " ", text)


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
                # `or "none"` because a missing value rendered as the Python literal "None"
                # in text the team reads.
                f'invented client work ("{match.group(0)}") while claiming '
                f'proof_used="{proof_used or "none"}"'
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


# ----------------------------------------------------------------------------------------
# Sameness. The failure the team notices first is one comment that would fit under any post:
# the same words under a photo booth thread and a roofing thread. Nothing above catches it,
# because interchangeable copy breaks no rule - it is simply about nobody.
# ----------------------------------------------------------------------------------------

# Filler that survives in any context, which is exactly why it says nothing.
TEMPLATE_PHRASES = [
    "this is a common issue", "this is a common problem", "this is really common",
    "you're not alone", "you are not alone", "a lot of people struggle",
    "most businesses struggle", "many businesses face", "a lot of businesses",
    "businesses often", "in today's", "at the end of the day", "the good news is",
    "sounds like a great opportunity", "happy to help", "hope this helps",
    "hope that helps", "great post", "love this post", "totally agree",
    "couldn't agree more", "spot on", "this resonates", "feel free to reach out",
    "curious to hear your thoughts", "would love to learn more", "food for thought",
]

# Words too common to prove a message was written for this specific prospect.
_COMMON = {
    "that", "this", "with", "have", "from", "they", "them", "your", "yours", "ours",
    "will", "just", "been", "more", "when", "what", "then", "than", "only", "also",
    "some", "into", "over", "most", "like", "need", "needs", "want", "wants", "know",
    "make", "makes", "does", "doing", "said", "says", "well", "work", "works",
    "working", "thing", "things", "really", "would", "could", "should", "about",
    "there", "their", "which", "because", "still", "after", "before", "every",
    "other", "right", "thanks", "thank", "please", "sure", "going", "getting",
    "business", "businesses", "company", "companies", "help", "helping", "looking",
    "anyone", "someone", "something", "anything", "guys", "here", "were", "much",
    "even", "back", "down", "time", "times", "week", "month", "year", "using", "used",
}


def _distinctive(text: str) -> set[str]:
    """Words specific enough that sharing them proves the copy engaged with the source."""
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _COMMON}


def find_generic(fields: dict, source_text: str = "") -> list[str]:
    """Copy that could be pasted under any post, judged against what they actually wrote."""
    problems = []
    loose = _loose(" ".join(v for v in fields.values() if isinstance(v, str) and v))

    for phrase in TEMPLATE_PHRASES:
        if _loose(phrase) in loose:
            problems.append(
                f'template filler "{phrase}" - it fits any post, so it says nothing about theirs'
            )

    # Needs a real post to compare against: a two-line "DM me" gives nothing to echo.
    theirs = _distinctive(source_text)
    if len(theirs) < 12:
        return problems

    for name in ("comment", "dm", "answer", "reply"):
        text = fields.get(name) or ""
        if not text:
            continue
        shared = _distinctive(text) & theirs
        if len(shared) < 2:
            problems.append(
                f"{name} could be pasted under any post: it picks up nothing specific from "
                "what this person actually wrote"
            )

    return problems


def find_violations(fields: dict, touch: int | None = None) -> list[str]:
    """fields maps a field name (comment/dm/email_body/proposal/...) to its text.

    touch is the email touch number when known: 1 opener, 2 FU1, 3 FU2, 4 FU3. The handoff
    spec allows the booking link in FU2 and FU3 only, and follow-ups reply inside the same
    Gmail thread so only the opener carries the full sign-off. Without it we assume the
    strictest case (an opener), because that is what the generator produces.
    """
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

    # A structural label at the start of any message is a note the model forgot to delete.
    for name in ("comment", "dm", "email_body", "answer", "reply", "proposal"):
        text = fields.get(name) or ""
        leak = LABEL_LEAK_RE.match(text)
        if leak:
            problems.append(f'{name} opens with the label "{leak.group(1)}", which is not copy')

    # The comment is what the whole group reads; it has to teach something.
    comment = (fields.get("comment") or "").strip()
    if comment and DM_ONLY_COMMENT_RE.match(comment):
        problems.append(
            "comment only announces a DM and carries no insight, which is the one thing a "
            "public comment must do"
        )

    # One ask per message. A DM ending in three questions reads as a form and gets none of
    # them answered. Two allowed in `answer` (a clarifier can be legitimate), one elsewhere.
    for name, cap in (("dm", 1), ("comment", 1), ("reply", 1), ("email_body", 1), ("answer", 2)):
        text = fields.get(name) or ""
        asks = text.count("?")
        if asks > cap:
            problems.append(
                f"{name} asks {asks} questions; one ask per message, or none of them get answered"
            )

    # Deliverability: no links, domains, email addresses or phone numbers in outgoing copy.
    for name in NO_CONTACT_FIELDS:
        text = fields.get(name) or ""
        if not text:
            continue
        # FU2 and FU3 are the only messages allowed to carry the booking link. Remove just
        # that one approved link before checking, so every OTHER link is still caught.
        if name == "email_body" and (touch or 1) >= 3:
            text = text.replace(BRAND["contact"]["booking_link"], "")
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
        # Follow-ups reply inside the same Gmail thread, so only the opener repeats the
        # full sign-off. Requiring it on every touch flagged 34 correct follow-ups.
        if (touch or 1) == 1 and not re.search(r"Mujaddad\s*\n+\s*Growmated", email_body):
            problems.append("email_body is missing the two-line sign-off (Mujaddad / Growmated)")

    # A bare id like "accounting" is legitimate English; only a labelled one is a leak.
    for entry in PROOF_BANK:
        pid = re.escape(entry["id"])
        if re.search(rf'(["\'(\[]{pid}["\')\]]|id\s*=\s*{pid})', lowered):
            problems.append(f'internal proof id "{entry["id"]}" leaked into the copy')

    return problems


def repairable_fields(responses: dict) -> dict:
    """The text fields worth checking and repairing.

    `answer` and `reply` were missing here, which quietly disabled every rule written for
    them: their word limits and question caps were computed and then never applied, because
    nothing ever handed those fields to find_violations. Group answers ran long for exactly
    that reason.
    """
    return {
        key: responses.get(key)
        for key in ("comment", "dm", "email_subject", "email_body", "proposal",
                    "opening_question", "answer", "reply")
        if responses.get(key)
    }


# ----------------------------------------------------------------------------------------
# Repetition, in both directions:
#   - the same POST submitted twice (human error), which should not cost a generation
#   - two different posts producing the same SENTENCES (model error), which is what a
#     prospect would actually notice if they compared notes with someone in the same group
# ----------------------------------------------------------------------------------------

# Approved proof claims must be quoted accurately every time, so their repetition is correct
# by design and must never be counted as the model repeating itself.
_PROOF_TEXT = _loose(" ".join(entry["claim"] for entry in PROOF_BANK))


def _sentences(text: str) -> list[str]:
    """Sentences long enough that reuse is meaningful. Short ones repeat innocently."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip())
            if len(s.split()) >= 6]


def _trigrams(text: str) -> set[tuple]:
    words = re.findall(r"[a-z']+", (text or "").lower())
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def similarity(first: str, second: str) -> float:
    """Overlap of three-word phrases. 1.0 is identical, under 0.1 is unrelated."""
    a, b = _trigrams(first), _trigrams(second)
    return len(a & b) / len(a | b) if (a | b) else 0.0


DUPLICATE_INPUT_THRESHOLD = 0.55


def find_duplicate_input(text: str, prospects: list[dict]) -> dict | None:
    """The same post pasted twice. Returns the earlier lead, or None.

    Threshold is deliberately loose: a re-paste usually loses or gains a line, and the cost
    of a false positive is one extra click, while the cost of a miss is a duplicate lead and
    a wasted generation.
    """
    if len(text.split()) < 12:
        return None
    best, score = None, 0.0
    for prospect in prospects[:200]:
        previous = prospect.get("raw_input") or ""
        if len(previous.split()) < 12:
            continue
        current = similarity(text, previous)
        if current > score:
            best, score = prospect, current
    return best if score >= DUPLICATE_INPUT_THRESHOLD else None


def find_repetition(fields: dict, recent: list[dict]) -> list[str]:
    """Sentences this copy reuses from messages already written for someone else.

    Exact sentence reuse rather than a similarity score, because it is unambiguous, it is
    what a reader would actually spot, and it can be quoted back to the team.
    """
    problems = []
    for name in ("comment", "dm"):
        mine = [s for s in _sentences(fields.get(name) or "")
                if _loose(s) not in _PROOF_TEXT]
        if not mine:
            continue
        for message in recent:
            other = _loose(message.get("content") or "")
            if not other:
                continue
            reused = next((s for s in mine if _loose(s) in other), None)
            if reused:
                who = message.get("business") or "another prospect"
                problems.append(
                    f'{name} reuses a sentence already sent to {who}: "{reused[:70]}..."'
                )
                break  # one flag per field is enough to trigger a rewrite
    return problems


def excess_words(fields: dict) -> int:
    """How far over the limits the copy is, in total words.

    Lets the repair loop see that a 147 -> 123 word pass made real progress even though the
    problem COUNT did not change. Counting problems alone made the loop quit after one
    attempt on exactly the violation that needs several.
    """
    return sum(max(0, word_count(fields.get(name)) - limit)
               for name, limit in WORD_LIMITS.items())


def trim_to_limit(text: str, limit: int) -> str:
    """Drop whole trailing sentences until the text is under the limit.

    Deterministic backstop for `answer`, which is the field the model overruns most (507
    words once, and still 132 after three revision passes). A group answer's last sentence
    is a closer, not the substance, so cutting from the end keeps what matters. Never used
    on dm or email_body, where the final lines carry the ask and the sign-off.
    """
    if word_count(text) <= limit:
        return text
    kept: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if word_count(" ".join(kept + [part])) > limit:
            break
        kept.append(part)
    return " ".join(kept) if kept else text


def enforce_hard_limits(responses: dict) -> dict:
    """Last line of defence: no over-long answer ever reaches a human."""
    answer = responses.get("answer")
    if answer and word_count(answer) > WORD_LIMITS["answer"]:
        return {**responses, "answer": trim_to_limit(answer, WORD_LIMITS["answer"])}
    return responses


def final_check(responses: dict, source_text: str = "",
                proof_used: str | None = None, touch: int | None = None) -> list[str]:
    """The one gate every message passes before a human is allowed to see it.

    House style, fabrication and sameness in a single call, so no caller can accidentally
    run two of the three. Empty list means the copy is fit to send.

    touch passes straight through to find_violations. Without it the gate judged every email
    as an opener, so the touch-aware fix never actually reached the gate and 34 correct
    follow-ups would still have been flagged. Generation leaves it None, which is right:
    the generator only ever writes openers.
    """
    fields = repairable_fields(responses)
    return (find_violations(fields, touch)
            + find_fabrications(fields, proof_used)
            + find_generic(fields, source_text))
