"""
Insights — what the data says to do differently.

Every panel answers a question that changes next week's behaviour. Nothing is shown just
because it is countable, and no pattern is reported below 3 occurrences: with small numbers a
"100% reply rate" on two messages is noise dressed as a finding.
"""

from collections import Counter, defaultdict

import streamlit as st

from data import Snapshot
from ui import bar, kpi_row, section

MIN_PATTERN = 3
WIN_QUALITIES = {"interested", "question"}


def render(snap: Snapshot) -> None:
    messages, prospects, posts = snap.messages, snap.prospects, snap.posts
    sent = [m for m in messages if m.get("sent_at")]
    drafts = [m for m in messages if not m.get("sent_at")]
    replied = snap.replied
    send_rate = (len(sent) / len(messages)) if messages else 0

    kpi_row([
        {"label": "Drafts written", "value": len(messages), "icon": "doc"},
        {"label": "Actually sent", "value": len(sent), "icon": "send"},
        {"label": "Replies", "value": len(replied), "icon": "check"},
        {"label": "Send rate", "value": f"{send_rate:.0%}", "icon": "chart",
         "tone": "bad" if messages and send_rate < 0.3 else None},
    ])

    if messages and send_rate < 0.5:
        st.warning(
            f"**{len(drafts)} drafts were never sent.** The gap between generated and sent is "
            "the most honest signal here: if the team is not sending what the tool writes, the "
            "copy is wrong, not the team. Worth reading a few and asking what stopped them."
        )

    # ---------------------------------------------------------------------------------
    section("What is working", "chart")
    st.caption(f"Only attributes with {MIN_PATTERN}+ sent messages. Everything else is noise.")

    def rates(key: str):
        groups: dict[str, list[dict]] = defaultdict(list)
        for m in sent:
            if m.get(key):
                groups[str(m[key])].append(m)
        out = []
        for value, group in groups.items():
            if len(group) < MIN_PATTERN:
                continue
            wins = sum(1 for m in group if m.get("replied")
                       and (m.get("reply_quality") in WIN_QUALITIES or not m.get("reply_quality")))
            scams = sum(1 for m in group if m.get("reply_quality") == "scam-probe")
            out.append((value, len(group), wins, scams))
        return sorted(out, key=lambda r: -(r[2] / r[1]))

    found = False
    for key, title in (("channel", "By channel"), ("opener_type", "By opener"),
                       ("angle", "By angle"), ("cta_type", "By call to action"),
                       ("template_id", "By input type"), ("proof_used", "By case study")):
        rows = rates(key)
        if not rows:
            continue
        found = True
        st.markdown(f"**{title}**")
        for value, total, wins, scams in rows:
            note = f"  ·  {scams} scam-probe (flagged, not a win)" if scams else ""
            st.write(f"{value} — {wins}/{total} replied ({wins / total:.0%}){note}")
            bar(wins / total)

    if not found:
        st.info(
            f"Nothing has {MIN_PATTERN}+ sent messages yet, so there is no pattern worth "
            "trusting. This fills in as the team marks messages sent and logs outcomes."
        )

    # ---------------------------------------------------------------------------------
    section("Gaps worth acting on", "alert")
    gaps: list[str] = []

    untouched = [p for p in prospects if (p.get("outreach_status") or "") == "Not Contacted"]
    if untouched:
        gaps.append(f"**{len(untouched)} leads are still 'Not Contacted'.** Drafted then forgotten.")

    no_outcome = [m for m in sent if m.get("replied") is None]
    if no_outcome:
        gaps.append(
            f"**{len(no_outcome)} sent messages have no outcome logged.** Reply rates above are "
            "understated until they are.")

    bounced = [p for p in prospects if (p.get("outreach_status") or "") == "Bounced"]
    if len(bounced) >= MIN_PATTERN:
        gaps.append(
            f"**{len(bounced)} leads bounced.** A list-quality problem: verify addresses before "
            "sending rather than burning domain reputation.")

    objections = Counter(m["objection_category"] for m in messages if m.get("objection_category"))
    if objections:
        top, count = objections.most_common(1)[0]
        if count >= MIN_PATTERN:
            gaps.append(
                f"**'{top}' is the most common objection ({count}x).** Recurring objections are an "
                "offer problem, not a copy problem.")

    waiting = [p for p in posts if (p.get("status") or "") not in ("Posted", "Archived")]
    if waiting:
        gaps.append(f"**{len(waiting)} posts are waiting to publish.** Written but not shipped.")

    by_industry: dict[str, list[dict]] = defaultdict(list)
    for p in prospects:
        industry = (p.get("industry") or "").strip()
        if industry:
            by_industry[industry].append(p)
    dead = [name for name, group in by_industry.items()
            if len(group) >= 5 and not any(
                (x.get("outreach_status") or "") in ("Call completed", "Negotiating", "Messaged")
                for x in group)]
    if dead:
        gaps.append(
            f"**No traction in: {', '.join(dead[:4])}.** 5+ leads each and nothing has progressed. "
            "Either the angle is wrong for them or they are the wrong ICP.")

    if gaps:
        for gap in gaps:
            st.markdown(f"- {gap}")
    else:
        st.success("No gaps flagged. Either everything is moving, or there is not enough data yet.")

    st.caption(
        "For the full monthly extraction — the 8 hardening questions answered from the log "
        "only — run `python extract_learnings.py` on the 1st."
    )
