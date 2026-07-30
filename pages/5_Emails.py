"""
Emails — the cold-email queue.

The "Growmated x Prospecting" scheduled chat researches businesses and drafts the opener plus
three follow-ups straight into this database (see EMAIL_ENGINE_HANDOFF.md). This page is the
team's working view of that queue: what to send today, what is scheduled, what is awaiting a
reply. Sending still happens from Gmail by copy-paste; every click here keeps the tracking
honest so nobody has to read the mailbox to know where things stand.

Sequence rules enforced here, not remembered by humans:
  FU1 = opener +3 days, FU2 = +7, FU3 = +12.
  Any reply, bounce or closed status stops the whole sequence immediately.
"""

import streamlit as st

import db
from auth import require_login
from ui import copy_block, inject_base_css, kpi_row, page_header, pill, render_brand, section

st.set_page_config(page_title="Emails | Growmated Engine", page_icon="⚡", layout="wide")
inject_base_css()
render_brand()
require_login()

page_header(
    "Emails",
    "Drafted by the prospecting engine, sent from Gmail by you. Send what is due, log what happens.",
    "send",
)

if not db.is_configured():
    st.error("Supabase is not configured.")
    st.stop()

try:
    queue = db.email_queue()
except Exception as exc:
    st.error(f"Could not load the queue: {type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

send_now, scheduled, awaiting = queue["send_now"], queue["scheduled"], queue["awaiting"]

kpi_row([
    {"label": "Send today", "value": len(send_now), "icon": "send",
     "tone": "warn" if send_now else "good", "note": "openers + due follow-ups"},
    {"label": "Awaiting reply", "value": len(awaiting), "icon": "clock",
     "note": "sent, no outcome yet"},
    {"label": "Scheduled", "value": len(scheduled), "icon": "doc",
     "note": "follow-ups not yet due"},
    {"label": "Sequences stopped", "value": queue["stopped"], "icon": "ban",
     "note": "replied, bounced or closed"},
])

if not (send_now or scheduled or awaiting):
    st.info(
        "The queue is empty. Once the prospecting chat writes its drafts here "
        "(EMAIL_ENGINE_HANDOFF.md has the exact instructions to give it), today's emails "
        "appear at the top, follow-ups schedule themselves, and replies stop sequences "
        "automatically."
    )

# ------------------------------------------------------------------------------------------
# Send today
# ------------------------------------------------------------------------------------------
if send_now:
    section("Send today", "send")

    for item in send_now:
        prospect, msg = item["prospect"], item["message"]
        touch = msg.get("touch_number") or 1
        label = "Opener" if touch == 1 else f"Follow-up {touch - 1}"

        with st.expander(
            f"{prospect.get('business_name')}  ·  {label}  ·  {item['due_note']}",
            expanded=False,
        ):
            to_addr = prospect.get("email") or "(no address on the prospect)"
            st.markdown(
                pill(f"To: {to_addr}", "info", "send")
                + " " + pill(prospect.get("industry") or "unknown industry", "mute"),
                unsafe_allow_html=True,
            )
            if touch == 1 and msg.get("subject"):
                st.caption("Subject")
                copy_block(msg["subject"])
            elif touch > 1:
                st.caption("Send as a reply in the SAME Gmail thread, so the subject stays Re:")
            st.caption("Body")
            copy_block(msg.get("content") or "")

            c1, c2 = st.columns([2, 1])
            if c1.button("Mark sent", key=f"send_{msg['id']}", use_container_width=True):
                try:
                    db.mark_message_sent(msg["id"])
                    if touch == 1:
                        db.update_prospect_status(prospect["id"], "Email sent")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {str(exc)[:200]}")
            if c2.button("Bounced", key=f"bounce_{msg['id']}", use_container_width=True):
                try:
                    db.mark_bounced(prospect["id"])
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {str(exc)[:200]}")

# ------------------------------------------------------------------------------------------
# Awaiting reply: the outcome logging that keeps Insights honest
# ------------------------------------------------------------------------------------------
if awaiting:
    section("Awaiting reply", "clock")
    st.caption("When something comes back in Gmail, log it here verbatim. Replies stop the sequence.")

    for item in awaiting:
        prospect, msg = item["prospect"], item["message"]
        with st.expander(f"{prospect.get('business_name')}  ·  {item['due_note']}"):
            copy_block(msg.get("content") or "")
            with st.form(f"outcome_{msg['id']}"):
                got = st.radio("What happened?", ["Replied", "Bounced", "Still nothing"], horizontal=True)
                reply_text = st.text_area("Reply text, VERBATIM (if they replied)", height=90)
                quality = st.selectbox("Reply quality", ["—"] + db.REPLY_QUALITIES)
                if st.form_submit_button("Log it", use_container_width=True):
                    try:
                        if got == "Bounced":
                            db.mark_bounced(prospect["id"])
                        elif got == "Replied":
                            if not reply_text.strip():
                                st.warning("Paste the reply verbatim; the reply text is the gold.")
                                st.stop()
                            db.record_outcome(
                                msg["id"], True, reply_text,
                                None if quality == "—" else quality,
                            )
                        else:
                            db.record_outcome(msg["id"], False)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {str(exc)[:200]}")

# ------------------------------------------------------------------------------------------
# Scheduled follow-ups, collapsed: nothing to do, just visibility
# ------------------------------------------------------------------------------------------
if scheduled:
    section("Scheduled", "doc")
    for item in scheduled:
        prospect, msg = item["prospect"], item["message"]
        touch = msg.get("touch_number") or 1
        st.markdown(
            pill(f"{prospect.get('business_name')} · FU{touch - 1} · {item['due_note']}", "mute", "clock"),
            unsafe_allow_html=True,
        )
