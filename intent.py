"""
What did the team actually paste?

The tool used to assume one shape: a post from a stranger, producing comment + DM + email.
In practice the team pastes hiring posts, complaints, open questions, people selling TO us,
and live threads with a prospect. Those need different outputs, and some need none at all.

`skip` is a first-class answer. A tool that always produces copy trains the team to send copy
that should not be sent.
"""

INTENTS = {
    "hiring": {
        "label": "Hiring / looking for help",
        "hint": "Actively looking to pay someone",
        "fields": ["comment", "dm", "email"],
        "guidance": "They are buying. Lead with the mechanism you would build, name the risk they carry, ask one qualifying question.",
    },
    "problem": {
        "label": "Describing a problem",
        "hint": "Venting or stuck, not yet buying",
        "fields": ["comment", "dm", "email"],
        "guidance": "Useful before interested. The comment must give a specific they can act on without hiring anyone.",
    },
    "question": {
        "label": "Asking a question",
        "hint": "An open question in a group",
        "fields": ["answer"],
        "guidance": "Answer it properly and STOP. No pitch, no DM tease, no CTA. The value IS the answer.",
    },
    "offer": {
        "label": "Someone selling to us",
        "hint": "A vendor pitching their services",
        "fields": ["dm"],
        "guidance": "Not a prospect. Only engage if there is a real partnership angle. Never pitch at someone pitching us.",
    },
    "conversation": {
        "label": "Live conversation / reply",
        "hint": "An ongoing thread. Paste it all",
        "fields": ["reply"],
        "guidance": "Write only the next message. Do not repeat points already made or reintroduce yourself. Name any objection and address it directly.",
    },
    "profile": {
        "label": "Profile / company page",
        "hint": "A profile with no specific post",
        "fields": ["dm", "email"],
        "guidance": "No post to react to, so hook from what their business visibly does. No comment.",
    },
    "post": {
        "label": "General post",
        "hint": "Worth engaging, none of the above",
        "fields": ["comment", "dm", "email"],
        "guidance": "Standard first touch.",
    },
    "skip": {
        "label": "Not worth engaging",
        "hint": "Spam, salaried job ad, out of geography, nothing to work with",
        "fields": [],
        "guidance": "No copy. should_engage = no, with the real reason in one line.",
    },
}

# Intents that are a live/warm thread and may therefore use the full proof bank.
WARM_INTENTS = {"conversation"}


def context_for(intent: str) -> str:
    """Cold first-touch or a warm thread? Decides which proofs are allowed."""
    return "warm" if intent in WARM_INTENTS else "cold"


def fields_for(intent: str) -> list[str]:
    return INTENTS.get(intent, INTENTS["post"])["fields"]


def guidance_block() -> str:
    """The routing table, rendered for the prompt. Kept terse: prompt size costs latency."""
    return "\n".join(
        f'  {name} ({spec["hint"]}) -> {spec["guidance"]}'
        for name, spec in INTENTS.items()
    )
