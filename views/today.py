"""
Today — what to do right now, and proof the automated chats are still feeding the tool.

The health strip matters as much as the actions: both external chats write in silently, so
when one stops, nothing breaks visibly and the queue just quietly goes empty. This shows the
last time each one wrote, so a silent failure is obvious the same day.
"""

from datetime import datetime, timezone

import streamlit as st

from data import Snapshot
from ui import action_card, kpi_row, pill, section


def _age(iso: str | None) -> tuple[str, str]:
    """Human age of a timestamp, plus a tone for the pill."""
    if not iso:
        return "never", "bad"
    stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
    if hours < 1:
        return "just now", "good"
    if hours < 24:
        return f"{int(hours)}h ago", "good"
    days = int(hours // 24)
    return f"{days}d ago", "warn" if days < 2 else "bad"


def render(snap: Snapshot) -> None:
    unsent = snap.unsent
    awaiting = snap.awaiting
    untouched = [p for p in snap.prospects if (p.get("outreach_status") or "") == "Not Contacted"]
    post_queue = [p for p in snap.posts if (p.get("status") or "") not in ("Posted", "Archived")]
    email_unsent = [m for m in unsent if m.get("channel") == "Email"]

    reply_rate = "n/a"
    sent_count = len([m for m in snap.messages if m.get("sent_at")])
    if sent_count:
        reply_rate = f"{len(snap.replied) / sent_count:.0%}"

    kpi_row([
        {"label": "Leads", "value": len(snap.prospects), "icon": "target",
         "note": f"{len(untouched)} not contacted"},
        {"label": "Drafts to send", "value": len(unsent), "icon": "doc",
         "tone": "warn" if unsent else "good", "note": "work already done"},
        {"label": "Emails due", "value": len(email_unsent), "icon": "send",
         "note": "openers + follow-ups"},
        {"label": "Awaiting reply", "value": len(awaiting), "icon": "clock",
         "note": "no outcome logged"},
        {"label": "Posts waiting", "value": len(post_queue), "icon": "inbox",
         "tone": "warn" if post_queue else None, "note": "ready to publish"},
        {"label": "Reply rate", "value": reply_rate, "icon": "chart",
         "note": f"{len(snap.replied)} replies"},
    ])

    # ---------------------------------------------------------------------------------
    # Feed health. A silent chat is the failure mode that hides best.
    # ---------------------------------------------------------------------------------
    section("Automation feeds", "info")

    last_post = max((p.get("created_at") or "" for p in snap.posts), default="") or None
    email_rows = [m for m in snap.messages if m.get("channel") == "Email"]
    last_email = max((m.get("created_at") or "" for m in email_rows), default="") or None

    post_age, post_tone = _age(last_post)
    email_age, email_tone = _age(last_email)
    st.markdown(
        pill(f"Content chat wrote {post_age}", post_tone, "inbox")
        + " " + pill(f"Prospecting chat wrote {email_age}", email_tone, "send"),
        unsafe_allow_html=True,
    )
    if post_tone == "bad" or email_tone == "bad":
        st.caption(
            "A feed that has not written for over a day usually means the scheduled chat ran "
            "but its Supabase insert failed. Ask it to re-run and report the exact error."
        )

    # ---------------------------------------------------------------------------------
    # What to do, ordered by what costs money to ignore
    # ---------------------------------------------------------------------------------
    section("Do next", "alert")

    actions: list[tuple[str, str, str]] = []
    if email_unsent:
        actions.append((
            f"<strong>{len(email_unsent)} cold emails are due.</strong> Open the Emails tab, "
            "send from Gmail, mark them sent.", "warn", "send"))
    if unsent:
        actions.append((
            f"<strong>{len(unsent)} drafts are written and unsent.</strong> The work is already "
            "done; these are the cheapest wins available.", "warn", "doc"))
    if awaiting:
        actions.append((
            f"<strong>{len(awaiting)} sent messages have no outcome logged.</strong> Until they "
            "are, reply rates are understated and nothing can be learned from them.",
            "info", "clock"))
    if post_queue:
        actions.append((
            f"<strong>{len(post_queue)} posts are waiting.</strong> Written but not published "
            "earns nothing.", "warn", "inbox"))

    bounced = [p for p in snap.prospects if (p.get("outreach_status") or "") == "Bounced"]
    if len(bounced) >= 3:
        actions.append((
            f"<strong>{len(bounced)} addresses bounced.</strong> That is a list-quality problem, "
            "not an outreach one. Verify before sending or you burn domain reputation.",
            "bad", "ban"))

    if actions:
        for body, tone, icon_name in actions:
            action_card(body, tone, icon_name)
    else:
        action_card("Nothing outstanding right now.", "info", "check")
