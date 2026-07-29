"""
growmated_knowledge.py
Core Growmated positioning, offers, ICPs, and voice — structured for use as
system-prompt building blocks in the Prospect Engine.
Source of truth: growmated.com + founder-confirmed facts (July 2026).
HARD RULE baked into every template: only claims in PROOF_BANK may be used. Never invent.
"""

BRAND = {
    "name": "Growmated",
    "site": "https://growmated.com",
    "tagline": "Your Business, Running Itself.",
    "positioning": (
        "AI operations consultancy. Most agencies sell you a tool; we figure out "
        "what your business actually needs, then build it. Consultant, not tool-vendor. "
        "Tools (GoHighLevel, Claude, APIs) are the how, never the headline."
    ),
    "founder": "Mujaddad",
    # Exactly two lines, in this order, and never "Growmated.com".
    "sign_off": "Mujaddad\nGrowmated",
    "contact": {
        "whatsapp": "+1 608 862 8986",
        "email": "mujaddad@growmated.com",
        "booking_link": "https://cal.com/mujaddad-hassan-khan-mizhwq/15min",
        "calendar_cta": "15 minutes",
    },
    "countries_served": ["US", "Canada", "UK"],
}

# The core argument, in the founder's words. Speed of first reply is the whole pitch.
LEAK_LINE = (
    "for events couples message a few booths the same night and book whoever answers first, "
    "so a slow reply costs the date."
)

SERVICES = [
    {"key": "instant_lead_response", "name": "Instant lead response",
     "blurb": "Every call and message answered in under 60 seconds, 24/7, on every channel."},
    {"key": "ai_qualification_booking", "name": "AI qualification & booking",
     "blurb": "Leads qualified in a real conversation and booked straight into the calendar."},
    {"key": "followup_engine", "name": "Follow-up that never forgets",
     "blurb": "Chases every lead across SMS, email, and social until they book or opt out."},
    {"key": "voice_sms_agents", "name": "AI voice & SMS agents",
     "blurb": "AI that calls, texts, quotes, and books — logged automatically."},
    {"key": "busywork_automation", "name": "Busywork automation",
     "blurb": "Quotes, invoices, onboarding, reminders, reviews, data entry — systemized."},
    {"key": "database_reactivation", "name": "Database reactivation",
     "blurb": "Compliant campaigns that turn dormant lead lists into booked appointments."},
    {"key": "agency_systems", "name": "Agency systems support",
     "blurb": "We help agencies run their systems: sub-account builds, A2P, deliverability."},
]

# Wording is grounded in Growmated-Capabilities-and-Case-Studies.pdf, which is client-facing
# and publishes all four with their numbers. Client names stay withheld, exactly as the PDF
# does it. Never invent numbers, and never add an entry without explicit sign-off.
#
# `signature` must appear verbatim in any message citing the entry. Without it, models keep
# the real numbers but relabel the client to match the prospect's industry ("one home services
# client we work with...", citing the photo booth result), which is fabrication.
PROOF_BANK = [
    {"id": "photobooth", "industry": "events", "signature": "photo booth",
     "claim": "We run the lead system for another photo booth company right now, every inquiry "
              "answered in under 60 seconds automatically, first leads in the calendar within "
              "48 hours of launch."},
    {"id": "chauffeur", "industry": "transportation", "signature": "chauffeur",
     "claim": "We built the booking system for a US chauffeur company: it answers calls and "
              "texts at any hour, collects the trip details, calculates the exact fare per "
              "vehicle, takes the deposit, raises the invoice, books the trip and notifies the "
              "driver, with no staff involved."},
    {"id": "consulting", "industry": "consulting", "signature": "consulting firm",
     "claim": "For a Canadian consulting firm we built AI voice and SMS qualification across "
              "multiple provinces: around 1,000 leads contacted, around 271 real "
              "conversations, 23 booked consultations."},
    {"id": "agency_scale", "industry": "agencies", "signature": "agency",
     "claim": "We run the systems behind a US marketing agency: 50+ sub-accounts built and "
              "managed, 100+ accounts taken through A2P registration, and deliverability "
              "owned across high-volume messaging."},
]

# Cold first-touch (public comment, first DM, cold email) stays on ONE story, per the handoff
# doc: brevity and deliverability matter more than breadth, and a stranger has no reason to
# read four case studies. Warm contexts (Upwork proposals, replies in a live thread, anything
# sent alongside the capabilities PDF) may use the whole bank, matched by industry.
COLD_PROOF_IDS = ["photobooth"]


def proofs_for(context: str = "warm") -> list[dict]:
    """Proof entries allowed in a given context. context is "cold" or "warm"."""
    if context == "cold":
        return [p for p in PROOF_BANK if p["id"] in COLD_PROOF_IDS]
    return PROOF_BANK

MARKET_MATH = [
    "~78% of buyers choose the first business that responds.",
    "The median business takes 42+ hours to reply to a new lead.",
    "Most missed callers never leave a voicemail; they call the next business.",
    "Most conversions happen after the 4th follow-up touch; most businesses stop at one.",
]

ICPS = {
    "service_business": {
        "label": "Local service businesses (US/CA/UK)",
        "pains": ["slow lead response", "missed after-hours calls", "follow-up stops after one try", "booking friction"],
        "angle": "instant_lead_response",
    },
    "transportation": {
        "label": "Chauffeur / black car / transport operators",
        "pains": ["late-night booking calls missed", "manual quoting", "dispatch chaos"],
        "angle": "voice_sms_agents",
    },
    "professional_services": {
        "label": "Accounting / legal / consulting firms",
        "pains": ["owner does the follow-up", "42-hour response times", "no-shows", "seasonal lead floods"],
        "angle": "busywork_automation",
    },
    "events": {
        "label": "Photo booth / event businesses",
        "pains": ["inquiries across web+IG+FB+SMS", "slow replies losing bookings to faster competitors"],
        "angle": "instant_lead_response",
    },
    "agencies": {
        "label": "Marketing agencies",
        "pains": ["sub-account sprawl", "A2P/deliverability failures", "fulfillment bottlenecks"],
        "angle": "agency_systems",
    },
}

VOICE = {
    "rules": [
        "Plain English. Short sentences. Confident, honest, zero hype.",
        "No em-dashes. No emoji walls. No 'game changer' language.",
        "Open with something specific about THE PROSPECT, never about Growmated.",
        "The FIRST sentence must reference a concrete detail they actually wrote (the city, the "
        "channel, the exact bottleneck, their words). A generic opener is an automatic failure.",
        "Name the specific mechanism you would build for them, not the category. "
        "'Answers the booking line at 2am and quotes the fare' beats 'automation solutions'.",
        "One proof claim max per message, chosen from PROOF_BANK by industry fit.",
        "Under 120 words for email; under 80 for DM/WhatsApp.",
        "CTA is always the free 15-minute audit, phrased as their gain: 'you keep the findings either way'.",
        "NEVER invent clients, numbers, or results. If no proof fits, use MARKET_MATH instead.",
        "Never quote a proof entry's id, or any internal label, in the message text.",
        "Write like one operator talking to another. No pitch-deck voice, no filler pleasantries.",
    ],
    # Anything vague, salesy, or interchangeable-with-any-agency belongs here.
    "banned_phrases": [
        "game changer", "revolutionize", "skyrocket", "unlock", "in today's world",
        "I hope this finds you well", "businesses like yours", "companies like yours",
        "I'd love to", "I would love to", "reach out", "touch base", "circle back",
        "leverage", "seamless", "cutting-edge", "best-in-class", "state of the art",
        "take your business to the next level", "let's hop on a call", "synergy",
        "tailored solutions", "bespoke solutions", "we specialize in",
    ],
}
