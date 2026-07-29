"""
Insights — the numbers Growmated needs to make decisions, not a vanity dashboard.

Every panel here exists to answer a question that changes what the team does next week.
Nothing is shown just because it is countable. All of it is computed from the pipeline and
the outreach log, so it costs nothing to look at and requires no manual data entry.
"""

from collections import Counter, defaultdict

import streamlit as st

import db
from auth import require_login
from ui import inject_base_css, render_brand

st.set_page_config(page_title="Insights | Growmated Engine", page_icon="📊", layout="wide")
inject_base_css()
require_login()
render_brand()

st.title("Insights")
st.caption("What the data says to do differently. Computed from the pipeline and outreach log.")

if not db.is_configured():
    st.error("Supabase is not configured.")
    st.stop()

try:
    client = db.get_client()
    prospects = client.table("pipeline").select("*").execute().data or []
    messages = client.table("outreach_log").select("*").execute().data or []
    posts = client.table("content_calendar").select("*").execute().data or []
except Exception as exc:
    st.error(f"Could not load data: {type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

MIN_PATTERN = 3  # per the learning-log spec: a pattern needs 3+ occurrences
WIN_QUALITIES = {"interested", "question"}

sent = [m for m in messages if m.get("sent_at")]
drafts = [m for m in messages if not m.get("sent_at")]
replied = [m for m in sent if m.get("replied")]

# ------------------------------------------------------------------------------------------
# The honest headline: is the tool's output actually being used?
# ------------------------------------------------------------------------------------------
st.subheader("Is the tool earning its keep?")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Drafts written", len(messages))
c2.metric("Actually sent", len(sent))
c3.metric("Replies", len(replied))
send_rate = (len(sent) / len(messages)) if messages else 0
c4.metric("Send rate", f"{send_rate:.0%}")

if messages and send_rate < 0.5:
    st.warning(
        f"**{len(drafts)} drafts were never sent.** The gap between generated and sent is the "
        "most honest signal in the system: if the team is not sending what the tool writes, "
        "the copy is wrong, not the team. Worth reading a few unsent drafts to see why."
    )
elif not messages:
    st.info("No drafts logged yet. Generate a few in Prospecting and the panels below fill in.")

st.divider()

# ------------------------------------------------------------------------------------------
# What is working: only patterns with enough evidence to act on
# ------------------------------------------------------------------------------------------
st.subheader("What is working")
st.caption(f"Only showing attributes with {MIN_PATTERN}+ sent messages. Everything else is noise.")


def rates(key: str) -> list[tuple[str, int, int, int]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in sent:
        if m.get(key):
            groups[str(m[key])].append(m)
    out = []
    for value, group in groups.items():
        if len(group) < MIN_PATTERN:
            continue
        wins = sum(
            1 for m in group
            if m.get("replied") and (m.get("reply_quality") in WIN_QUALITIES or not m.get("reply_quality"))
        )
        scams = sum(1 for m in group if m.get("reply_quality") == "scam-probe")
        out.append((value, len(group), wins, scams))
    return sorted(out, key=lambda row: -(row[2] / row[1]))


any_pattern = False
for key, title in (
    ("channel", "By channel"),
    ("opener_type", "By opener"),
    ("angle", "By angle"),
    ("cta_type", "By call to action"),
    ("proof_used", "By case study"),
):
    rows = rates(key)
    if not rows:
        continue
    any_pattern = True
    st.markdown(f"**{title}**")
    for value, total, wins, scams in rows:
        note = f"  ·  ⚠️ {scams} scam-probe" if scams else ""
        st.write(f"{value} — {wins}/{total} replied ({wins/total:.0%}){note}")
        st.progress(wins / total)

if not any_pattern:
    st.info(
        f"Nothing has {MIN_PATTERN}+ sent messages yet, so there is no pattern worth trusting. "
        "This fills in as the team logs sends and outcomes in Pipeline."
    )

st.divider()

# ------------------------------------------------------------------------------------------
# Gaps: things that need a decision
# ------------------------------------------------------------------------------------------
st.subheader("Gaps worth acting on")

gaps: list[str] = []

# Prospects sitting untouched.
untouched = [p for p in prospects if (p.get("outreach_status") or "") == "Not Contacted"]
if untouched:
    gaps.append(f"**{len(untouched)} prospects are still 'Not Contacted'.** Drafted and then forgotten.")

# Sent but no outcome recorded, so the log cannot learn from them.
no_outcome = [m for m in sent if m.get("replied") is None]
if no_outcome:
    gaps.append(
        f"**{len(no_outcome)} sent messages have no outcome recorded.** Until these are logged, "
        "the reply rates above are understated and the monthly extraction has less to work with."
    )

# Bounced email is a data-quality problem, not an outreach problem.
bounced = [p for p in prospects if (p.get("outreach_status") or "") == "Bounced"]
if len(bounced) >= MIN_PATTERN:
    gaps.append(
        f"**{len(bounced)} prospects bounced.** That is a list-quality issue: verify addresses "
        "before sending rather than burning domain reputation."
    )

# Objection concentration tells you what to fix in the offer, not the copy.
objections = Counter(m["objection_category"] for m in messages if m.get("objection_category"))
if objections:
    top, count = objections.most_common(1)[0]
    if count >= MIN_PATTERN:
        gaps.append(
            f"**'{top}' is the most common objection ({count}×).** Recurring objections are an "
            "offer problem, not a copy problem. Worth addressing before the first reply."
        )

# Content waiting to go out.
waiting = [p for p in posts if (p.get("status") or "") not in ("Posted", "Archived")]
if waiting:
    gaps.append(f"**{len(waiting)} posts are waiting to be published.** Content written but not shipped.")

# Industries that never reply.
by_industry: dict[str, list[dict]] = defaultdict(list)
for prospect in prospects:
    industry = (prospect.get("industry") or "").strip()
    if industry:
        by_industry[industry].append(prospect)
dead_industries = [
    name for name, group in by_industry.items()
    if len(group) >= 5 and not any(
        (p.get("outreach_status") or "") in ("Call completed", "Negotiating", "Messaged") for p in group
    )
]
if dead_industries:
    gaps.append(
        f"**No traction in: {', '.join(dead_industries[:4])}.** 5+ prospects each and nothing "
        "has progressed. Either the angle is wrong for them or they are the wrong ICP."
    )

if gaps:
    for gap in gaps:
        st.markdown(f"- {gap}")
else:
    st.success("No gaps flagged. Either everything is moving, or there is not enough data yet.")

st.divider()
st.caption(
    "For the full monthly extraction, including the 8 hardening questions answered from the "
    "log only, run `python extract_learnings.py` on the 1st."
)
