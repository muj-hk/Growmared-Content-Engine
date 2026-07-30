"""
Emails — the cold-email queue.

The "Growmated x Prospecting" chat drafts the opener plus three follow-ups into the database
(EMAIL_ENGINE_HANDOFF.md). Sending stays manual from Gmail; every click here keeps tracking
honest so nobody reads the mailbox to work out where things stand.

Cadence and stop rules are enforced in db.email_queue, not remembered by people:
FU1 = opener +3 days, FU2 = +7, FU3 = +12; any reply, bounce or closed status stops the lot.
"""

import streamlit as st

import data as data_mod
import db
from data import Snapshot
from ui import copy_block, kpi_row, pill, section


def render(snap: Snapshot) -> None:
    try:
        queue = db.email_queue(snap.prospects, snap.messages)
    except Exception as exc:
        st.error(f"Could not build the queue: {type(exc).__name__}: {str(exc)[:200]}")
        return

    send_now, scheduled, awaiting = queue["send_now"], queue["scheduled"], queue["awaiting"]

    kpi_row([
        {"label": "Send today", "value": len(send_now), "icon": "send",
         "tone": "warn" if send_now else "good", "note": "openers + due follow-ups"},
        {"label": "Awaiting reply", "value": len(awaiting), "icon": "clock",
         "note": "sent, no outcome yet"},
        {"label": "Scheduled", "value": len(scheduled), "icon": "doc",
         "note": "not yet due"},
        {"label": "Stopped", "value": queue["stopped"], "icon": "ban",
         "note": "replied, bounced or closed"},
    ])

    if not (send_now or scheduled or awaiting):
        st.info(
            "The queue is empty. Paste the block from EMAIL_ENGINE_HANDOFF.md into the "
            "'Growmated x Prospecting' chat and its drafts land here: openers at the top, "
            "follow-ups scheduling themselves, replies stopping sequences automatically."
        )
        return

    if send_now:
        section("Send today", "send")
        for item in send_now:
            prospect, msg = item["prospect"], item["message"]
            touch = msg.get("touch_number") or 1
            label = "Opener" if touch == 1 else f"Follow-up {touch - 1}"

            with st.expander(f"{prospect.get('business_name')}  ·  {label}  ·  {item['due_note']}"):
                st.markdown(
                    pill(f"To: {prospect.get('email') or 'no address on this lead'}", "info", "send")
                    + " " + pill(prospect.get("industry") or "unknown industry", "mute"),
                    unsafe_allow_html=True)

                if touch == 1 and msg.get("subject"):
                    st.caption("Subject")
                    copy_block(msg["subject"], key=f"esub_{msg['id']}")
                elif touch > 1:
                    st.caption("Send as a reply in the SAME Gmail thread so the subject stays Re:")
                st.caption("Body")
                copy_block(msg.get("content") or "", key=f"ebody_{msg['id']}")

                c1, c2 = st.columns([2, 1])
                if c1.button("Mark sent", key=f"esend_{msg['id']}", use_container_width=True):
                    try:
                        db.mark_message_sent(msg["id"])
                        data_mod.refresh()
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {str(exc)[:200]}")
                if c2.button("Bounced", key=f"ebounce_{msg['id']}", use_container_width=True):
                    try:
                        db.mark_bounced(prospect["id"])
                        data_mod.refresh()
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {str(exc)[:200]}")

    if awaiting:
        section("Awaiting reply", "clock")
        st.caption("When something lands in Gmail, log it verbatim. A reply stops the sequence.")
        for item in awaiting:
            prospect, msg = item["prospect"], item["message"]
            with st.expander(f"{prospect.get('business_name')}  ·  {item['due_note']}"):
                copy_block(msg.get("content") or "", key=f"await_{msg['id']}")
                with st.form(f"eout_{msg['id']}"):
                    got = st.radio("What happened?", ["Replied", "Bounced", "Nothing yet"],
                                   horizontal=True)
                    reply_text = st.text_area("Reply text, VERBATIM", height=90)
                    quality = st.selectbox("Reply quality", ["—"] + db.REPLY_QUALITIES)
                    if st.form_submit_button("Log it", use_container_width=True):
                        try:
                            if got == "Bounced":
                                db.mark_bounced(prospect["id"])
                            elif got == "Replied":
                                if not reply_text.strip():
                                    st.warning("Paste the reply verbatim; it is the gold.")
                                    return
                                db.record_outcome(msg["id"], True, reply_text,
                                                  None if quality == "—" else quality)
                            else:
                                db.record_outcome(msg["id"], False)
                            data_mod.refresh()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed: {str(exc)[:200]}")

    if scheduled:
        section("Scheduled", "doc")
        for item in scheduled:
            touch = item["message"].get("touch_number") or 1
            st.markdown(
                pill(f"{item['prospect'].get('business_name')} · FU{touch - 1} · {item['due_note']}",
                     "mute", "clock"),
                unsafe_allow_html=True)
