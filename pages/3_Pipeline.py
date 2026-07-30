"""
Pipeline — every lead the team has logged, and what to do with it.

Replaces the old one-prospect-at-a-time dropdown, which made 139 leads feel untracked: you
could not see what you had, what was untouched, or what was waiting. This is a scannable,
filterable list where the common actions happen inline.

Tracking is as automatic as it can be. Marking a message sent advances the prospect's status
by itself (db.CHANNEL_STATUS) and never downgrades one the team has already moved past, so
nobody has to remember to keep a status field in sync.
"""

import streamlit as st

import db
from auth import require_login
from ui import copy_block, inject_base_css, kpi_row, page_header, pill, render_brand, section

st.set_page_config(page_title="Pipeline | Growmated Engine", page_icon="⚡", layout="wide")
inject_base_css()
render_brand()
require_login()

page_header(
    "Pipeline",
    "Every lead you have logged. Send, then record what came back.",
    "target",
)

if not db.is_configured():
    st.error("Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY.")
    st.stop()

try:
    client = db.get_client()
    prospects = client.table("pipeline").select("*").order("created_at", desc=True).execute().data or []
    all_msgs = client.table("outreach_log").select("*").execute().data or []
except Exception as exc:
    st.error(f"Could not load the pipeline: {type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

msgs_by_prospect: dict[str, list[dict]] = {}
for msg in all_msgs:
    if msg.get("pipeline_id"):
        msgs_by_prospect.setdefault(msg["pipeline_id"], []).append(msg)

OPEN_STATUSES = {"Not Contacted", "Comment + DM sent", "Messaged", "Email sent",
                 "Proposal sent", "Loom sent — awaiting reply", "Negotiating"}

unsent_total = sum(
    1 for m in all_msgs if not m.get("sent_at")
)
awaiting_total = sum(
    1 for m in all_msgs if m.get("sent_at") and m.get("replied") is None
)
replied_total = sum(1 for m in all_msgs if m.get("replied"))

kpi_row([
    {"label": "Leads", "value": len(prospects), "icon": "target",
     "note": f"{sum(1 for p in prospects if (p.get('outreach_status') or '') == 'Not Contacted')} not contacted"},
    {"label": "Drafts unsent", "value": unsent_total, "icon": "doc",
     "tone": "warn" if unsent_total else None, "note": "written, not sent"},
    {"label": "Awaiting reply", "value": awaiting_total, "icon": "clock",
     "note": "sent, no outcome logged"},
    {"label": "Replies", "value": replied_total, "icon": "check",
     "note": "logged so far"},
])

# ------------------------------------------------------------------------------------------
# Filters. Default view is what needs work, not everything ever created.
# ------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="gm-section" style="margin-top:4px">Filter</div>', unsafe_allow_html=True)
    query = st.text_input("Search", placeholder="name, industry, notes...")
    show = st.radio(
        "Show",
        ["Needs action", "Open", "Everything"],
        index=0,
        help="Needs action = has an unsent draft, or was sent with no outcome logged yet.",
    )
    sources = sorted({p.get("source") for p in prospects if p.get("source")})
    source_filter = st.multiselect("Source", sources)
    if st.button("Refresh", use_container_width=True):
        st.rerun()


def needs_action(p: dict) -> bool:
    rows = msgs_by_prospect.get(p["id"], [])
    return any(not m.get("sent_at") for m in rows) or any(
        m.get("sent_at") and m.get("replied") is None for m in rows
    )


visible = prospects
if show == "Needs action":
    visible = [p for p in visible if needs_action(p)]
elif show == "Open":
    visible = [p for p in visible if (p.get("outreach_status") or "") in OPEN_STATUSES]
if source_filter:
    visible = [p for p in visible if p.get("source") in source_filter]
if query.strip():
    q = query.lower().strip()
    visible = [
        p for p in visible
        if q in " ".join(str(p.get(k) or "") for k in
                         ("business_name", "owner_name", "industry", "notes", "email")).lower()
    ]

section(f"{len(visible)} lead{'s' if len(visible) != 1 else ''}", "target")

if not visible:
    st.info("Nothing matches. Widen the filter, or switch Show to Everything.")

TONE = {
    "Not Contacted": "mute", "Bounced": "bad", "Not Interested": "bad",
    "Negotiating": "good", "Call completed": "good", "Client": "good",
}

for prospect in visible[:60]:
    rows = sorted(msgs_by_prospect.get(prospect["id"], []), key=lambda m: m.get("created_at") or "")
    unsent = [m for m in rows if not m.get("sent_at")]
    awaiting = [m for m in rows if m.get("sent_at") and m.get("replied") is None]
    status = prospect.get("outreach_status") or "Not Contacted"

    flag = ""
    if unsent:
        flag = f"  ·  {len(unsent)} to send"
    elif awaiting:
        flag = f"  ·  {len(awaiting)} awaiting reply"

    header = f"{prospect.get('business_name') or 'Unknown'}  ·  {status}{flag}"

    with st.expander(header, expanded=False):
        meta = " · ".join(filter(None, [
            prospect.get("industry"), prospect.get("source"),
            prospect.get("email"), (prospect.get("created_at") or "")[:10],
        ]))
        st.markdown(
            pill(status, TONE.get(status, "info"))
            + (f'  <span style="color:#6B7280;font-size:0.8rem">{meta}</span>' if meta else ""),
            unsafe_allow_html=True,
        )
        if prospect.get("notes"):
            st.caption(prospect["notes"])

        # Status is normally automatic; this is the manual override.
        with st.popover("Change status", use_container_width=False):
            statuses = db.OUTREACH_STATUSES
            new_status = st.selectbox(
                "Status", statuses,
                index=statuses.index(status) if status in statuses else 0,
                key=f"status_{prospect['id']}",
            )
            if st.button("Save", key=f"savestatus_{prospect['id']}"):
                try:
                    db.update_prospect_status(prospect["id"], new_status)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {str(exc)[:200]}")

        if not rows:
            st.caption("No drafts logged against this lead.")
            continue

        for msg in rows:
            sent = bool(msg.get("sent_at"))
            replied = msg.get("replied")
            state = "not sent" if not sent else ("replied" if replied else "awaiting reply")
            st.markdown(
                f"**{msg.get('channel')}** &nbsp;<span style='color:#6B7280;font-size:0.8rem'>"
                f"{state}{' · ' + msg['sent_at'][:10] if sent else ''}</span>",
                unsafe_allow_html=True,
            )
            if msg.get("subject"):
                copy_block(msg["subject"], key=f"subj_{msg['id']}")
            copy_block(msg.get("content") or "", key=f"body_{msg['id']}")

            if not sent:
                if st.button("Mark sent", key=f"sent_{msg['id']}", use_container_width=True):
                    try:
                        db.mark_message_sent(msg["id"])  # advances prospect status too
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {str(exc)[:200]}")
                continue

            if replied is not None:
                bits = [f"replied={replied}"]
                if msg.get("days_to_reply") is not None:
                    bits.append(f"{msg['days_to_reply']}d to reply")
                if msg.get("reply_quality"):
                    bits.append(msg["reply_quality"])
                st.caption("Logged: " + ", ".join(bits))
                if msg.get("reply_text"):
                    copy_block(msg["reply_text"], key=f"reply_{msg['id']}")
                continue

            with st.form(f"outcome_{msg['id']}"):
                got = st.radio("What happened?", ["Replied", "Nothing yet"], horizontal=True)
                reply_text = st.text_area(
                    "Reply text — paste VERBATIM, never summarise", height=90,
                    placeholder="Exactly what they wrote back...",
                )
                c1, c2 = st.columns(2)
                quality = c1.selectbox("Reply quality", ["—"] + db.REPLY_QUALITIES)
                objection = c2.selectbox("Objection", ["—"] + db.OBJECTION_CATEGORIES)
                if st.form_submit_button("Log outcome", use_container_width=True):
                    is_reply = got == "Replied"
                    if is_reply and not reply_text.strip():
                        st.warning("Paste the reply verbatim — the reply text is the gold.")
                    else:
                        try:
                            db.record_outcome(
                                msg["id"], is_reply, reply_text,
                                None if quality == "—" else quality,
                                None if objection == "—" else objection,
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {str(exc)[:200]}")

if len(visible) > 60:
    st.caption(f"Showing the 60 most recent of {len(visible)}. Use search or filters to narrow.")
