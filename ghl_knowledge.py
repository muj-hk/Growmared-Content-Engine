"""
Domain knowledge the copy leans on: GoHighLevel mechanics and adjacent stack facts.

This is what makes an answer sound like the person who has built it, not a content writer.
Injected SELECTIVELY by keyword (relevant_knowledge), because prompt size costs latency and
money: a chauffeur post about missed calls does not need the calendar race-condition notes.

Keep entries short, factual and operational. No selling language in here, ever - this is the
engineering brain, not the pitch.
"""

import re

# Each section: (trigger regex, knowledge block). Blocks are terse on purpose.
_SECTIONS: list[tuple[str, str, str]] = [
    ("a2p", r"a2p|10dlc|sms.*(fail|block|deliver)|text.*(fail|block)|carrier",
     "A2P/10DLC: US SMS from GHL silently fails or gets carrier-filtered until the A2P "
     "registration (brand + campaign) is approved. Register FIRST, before building SMS "
     "automations. Sole props have a lower-volume path. Approval usually days, not hours. "
     "Filtered messages still show as sent in GHL, which is why owners think automation "
     "'works' while nothing arrives."),

    ("calendar", r"calendar|double.?book|booking.*(slot|conflict)|appointment.*(clash|overlap)|free.?slot",
     "GHL calendars: double-booking is usually a race (two submissions read the slot as free "
     "before either writes) or a stale pre-selected slot in a form/survey/SMS link. Fixes: "
     "slot interval = appointment duration, one assigned user, book only through the live "
     "widget, and for API/workflow bookings re-check free slots immediately before creating. "
     "Google/Outlook sync issues are almost always an expired OAuth token that still LOOKS "
     "connected in the sub-account."),

    ("missed_call", r"missed.?call|after.?hours|don'?t answer|no answer|voicemail|call.?back",
     "Missed-call text-back: the naive version leaks - it sends one text, the caller replies "
     "with a question, and nobody answers until morning. Built right, the auto-text asks a "
     "qualifying question (what/where/when), the conversation continues via AI or templates, "
     "and it books. Most missed callers never leave a voicemail; they dial the next business. "
     "A2P must be approved or the text-back never arrives."),

    ("workflow", r"workflow|automation|trigger|follow.?up|nurture|sequence|pipeline",
     "GHL workflows: the classic failures are duplicate contacts spawning duplicate "
     "sequences (dedupe on phone AND email, decide which wins), no stop-on-reply branch so "
     "leads keep getting chased after answering, and time-window sends that queue overnight "
     "then blast at 8am. Every sequence needs: stop conditions, a reply branch, and an exit "
     "to a slow nurture instead of ending cold."),

    ("integration", r"housecall|hcp|servicetitan|jobber|zapier|make\.com|make |webhook|integrat|api|sync|duplicate record",
     "Integrations: GHL has no native two-way sync with Housecall Pro/Jobber/ServiceTitan; "
     "plan webhooks plus Make (Make over Zapier when you need branching/error handling and "
     "volume pricing). The decision that prevents duplicate-record hell: ONE system of "
     "record per stage - GHL owns pre-sale (lead, conversation, estimate), the field tool "
     "owns post-sale (job, invoice), and the handoff is one webhook at 'sold'. Sync fields "
     "one-directionally; two-way field sync is where duplicates come from."),

    ("voice_ai", r"voice ?ai|ai (agent|receptionist|answer)|phone (bot|agent)|conversation ?ai|chatbot",
     "Voice/conversation AI in GHL: works when scoped to a job (answer, qualify, quote, "
     "book) with a human-handoff branch, not as an open chatbot. Timezone math is the classic "
     "silent bug - free-slot lookups return calendar-timezone times and LLMs doing offset "
     "arithmetic break around DST. Fix deterministically in the workflow, not in the prompt. "
     "Log every call/text back to the contact record or the team flies blind."),

    ("deliverability", r"deliverab|spam|inbox|open rate|bounce|domain|dmarc|spf|dkim|warm",
     "Email deliverability: dedicated sending domain with SPF/DKIM/DMARC, warmed gradually. "
     "Links, image-heavy templates and mixed transactional/marketing sends are what flag "
     "cold email. Bounces above ~2-3% start burning the domain - verify addresses before "
     "sending, not after. One bad blast can undo weeks of warming."),

    ("agency", r"sub.?account|snapshot|white.?label|saas mode|agency|client account",
     "Agency operations in GHL: snapshots are the leverage (build once, deploy per client) "
     "but they do NOT carry over integrations, phone numbers, or A2P - each sub-account "
     "still needs its own registration and connections. That per-account compliance work is "
     "what most agencies underestimate at scale."),

    ("reviews", r"review|reputation|google (business|profile|maps)|gbp",
     "Reviews: GHL review requests work best as a workflow step triggered at job completion, "
     "with the direct Google review link, one reminder max. Gating (asking happy/unhappy "
     "first and only routing happy people to Google) violates Google's policy and gets "
     "profiles suspended."),
]

_MAX_SECTIONS = 3  # keep the injection small; more sections = slower + costlier every call


def relevant_knowledge(text: str) -> str:
    """The knowledge blocks this input actually touches, or empty string."""
    lowered = (text or "").lower()
    hits = [block for _, pattern, block in _SECTIONS if re.search(pattern, lowered)]
    if not hits:
        return ""
    picked = hits[:_MAX_SECTIONS]
    return (
        "\nDOMAIN FACTS - ground every technical claim in these; never contradict them, and "
        "never invent mechanics beyond them:\n"
        + "\n".join(f"  - {block}" for block in picked)
    )
