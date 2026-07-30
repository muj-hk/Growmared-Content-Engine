"""
Growmated Engine — command center.

This is not a status page. It answers one question on load: what should someone do next?
Everything here is derived from the pipeline, the outreach log and the content calendar, so
it costs nothing to keep open and needs no manual upkeep.

  Prospecting -> pages/1_Prospecting.py  -> pipeline + outreach_log
  Content     -> pages/2_Content.py      -> content_calendar
  Pipeline    -> pages/3_Pipeline.py     -> send + outcome logging
  Insights    -> pages/4_Insights.py     -> patterns and gaps

Run: streamlit run app.py
"""

import streamlit as st

import db
from auth import render_sign_out, require_login
from growmated_knowledge import BRAND as BRAND_FACTS
from growmated_knowledge import PROOF_BANK
from llm import MODEL, PROVIDER, check_dependencies, load_api_key
from ui import action_card, icon, inject_base_css, kpi_row, page_header, pill, render_brand, section

st.set_page_config(page_title="Growmated Engine", page_icon="⚡", layout="wide")
inject_base_css()
render_brand()
require_login()

page_header("Command center", BRAND_FACTS["tagline"], "chart")

with st.sidebar:
    render_sign_out()

# ------------------------------------------------------------------------------------------
# Setup problems surface here, not mid-generation.
# ------------------------------------------------------------------------------------------
KEY_NAME = "ANTHROPIC_API_KEY" if PROVIDER == "claude" else "NVIDIA_API_KEY"
key_ok = bool(load_api_key(KEY_NAME))
dependency_problem = check_dependencies()
db_ok = db.is_configured()

if not key_ok:
    st.error(f"**{KEY_NAME} is missing.** Add it to .env locally, or to the app's secrets when deployed.")
if dependency_problem:
    st.error(f"**Dependency missing.** {dependency_problem}")

prospects: list[dict] = []
messages: list[dict] = []
posts: list[dict] = []
load_error = None

if db_ok:
    try:
        client = db.get_client()
        prospects = client.table("pipeline").select("*").execute().data or []
        messages = client.table("outreach_log").select("*").execute().data or []
        posts = client.table("content_calendar").select("*").execute().data or []
    except Exception as exc:
        load_error = f"{type(exc).__name__}: {str(exc)[:200]}"
else:
    st.error("**Database not configured.** Set SUPABASE_URL and SUPABASE_KEY.")

if load_error:
    st.warning(f"Database configured but unreachable: {load_error}")

# ------------------------------------------------------------------------------------------
# Today's numbers
# ------------------------------------------------------------------------------------------
sent = [m for m in messages if m.get("sent_at")]
unsent = [m for m in messages if not m.get("sent_at")]
replied = [m for m in sent if m.get("replied")]
awaiting = [m for m in sent if m.get("replied") is None]
untouched = [p for p in prospects if (p.get("outreach_status") or "") == "Not Contacted"]
post_queue = [p for p in posts if (p.get("status") or "") not in ("Posted", "Archived")]

reply_rate = f"{len(replied) / len(sent):.0%}" if sent else "n/a"

try:
    email_q = db.email_queue(prospects, messages)
except Exception:
    email_q = {"send_now": [], "scheduled": [], "awaiting": [], "stopped": 0}

kpi_row([
    {"label": "Emails due", "value": len(email_q["send_now"]), "icon": "send",
     "note": f"{len(email_q['scheduled'])} scheduled",
     "tone": "warn" if email_q["send_now"] else None},
    {"label": "Prospects", "value": len(prospects), "icon": "target",
     "note": f"{len(untouched)} not contacted"},
    {"label": "Drafts ready", "value": len(unsent), "icon": "doc",
     "note": "waiting to be sent",
     "tone": "warn" if len(unsent) >= 5 else None},
    {"label": "Sent", "value": len(sent), "icon": "send",
     "note": f"{len(awaiting)} awaiting reply"},
    {"label": "Reply rate", "value": reply_rate, "icon": "chart",
     "note": f"{len(replied)} replies"},
    {"label": "Posts queued", "value": len(post_queue), "icon": "inbox",
     "note": "ready to publish",
     "tone": "warn" if post_queue else None},
])

# ------------------------------------------------------------------------------------------
# What to do next. Ordered by what actually costs money to ignore.
# ------------------------------------------------------------------------------------------
section("Do next", "alert")

actions: list[tuple[str, str, str]] = []

if email_q["send_now"]:
    actions.append((
        f"<strong>{len(email_q['send_now'])} cold emails are due today</strong> (openers and "
        "follow-ups whose day has arrived). Open Emails, send from Gmail, mark sent.",
        "warn", "send",
    ))

if unsent:
    actions.append((
        f"<strong>{len(unsent)} drafts are written and unsent.</strong> These are the cheapest "
        "wins available: the work is already done. Open Pipeline and send them.",
        "warn", "send",
    ))

if awaiting:
    actions.append((
        f"<strong>{len(awaiting)} sent messages have no outcome logged.</strong> Until they are "
        "recorded, reply rates are understated and nothing can be learned from them.",
        "info", "clock",
    ))

if post_queue:
    actions.append((
        f"<strong>{len(post_queue)} posts are waiting.</strong> Content written but not published "
        "earns nothing. Open Content, copy, post, mark done.",
        "warn", "inbox",
    ))

if untouched and not unsent:
    actions.append((
        f"<strong>{len(untouched)} prospects sit at 'Not Contacted'</strong> with no draft against "
        "them. Either work them or mark them dead so they stop inflating the pipeline.",
        "info", "target",
    ))

bounced = [p for p in prospects if (p.get("outreach_status") or "") == "Bounced"]
if len(bounced) >= 3:
    actions.append((
        f"<strong>{len(bounced)} addresses bounced.</strong> That is a list-quality problem, not "
        "an outreach one. Verify addresses before sending or you burn domain reputation.",
        "bad", "ban",
    ))

if actions:
    for body, tone, icon_name in actions:
        action_card(body, tone, icon_name)
else:
    action_card(
        "Nothing outstanding. Either everything is moving, or there is not enough data yet.",
        "info", "check",
    )

# ------------------------------------------------------------------------------------------
# The two tools
# ------------------------------------------------------------------------------------------
section("Tools", "target")

left, right = st.columns(2)
with left:
    st.markdown(f"##### {icon('target', 16, '#5254CC')} Prospecting", unsafe_allow_html=True)
    st.caption(
        "Paste anything a prospect wrote: a post, a hiring ad, a question, a live thread, or an "
        "Upwork job. It works out what it is, then writes only what fits, or tells you to skip."
    )
    st.page_link("pages/1_Prospecting.py", label="Open Prospecting")
    st.page_link("pages/5_Emails.py", label="Work the email queue")
    st.page_link("pages/3_Pipeline.py", label="Send and log outcomes")

with right:
    st.markdown(f"##### {icon('inbox', 16, '#5254CC')} Content", unsafe_allow_html=True)
    st.caption(
        "The posting queue. Each day's post from the scheduled chat, with the image and separate "
        "copy and tags per platform. Open a tab, copy, post, mark done."
    )
    st.page_link("pages/2_Content.py", label="Open Content")
    st.page_link("pages/4_Insights.py", label="See what is working")

# ------------------------------------------------------------------------------------------
# System state, small and out of the way
# ------------------------------------------------------------------------------------------
section("System", "info")

badges = [
    pill(f"{PROVIDER}: {MODEL}", "good" if key_ok and not dependency_problem else "bad",
         "check" if key_ok and not dependency_problem else "ban"),
    pill("Database connected" if db_ok and not load_error else "Database unavailable",
         "good" if db_ok and not load_error else "bad",
         "check" if db_ok and not load_error else "ban"),
    pill(f"{len(PROOF_BANK)} approved case studies", "info", "doc"),
]
st.markdown(" ".join(badges), unsafe_allow_html=True)
