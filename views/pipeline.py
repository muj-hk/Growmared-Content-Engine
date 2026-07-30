"""
Pipeline — every lead, what was drafted for it, and what came back.

Scannable and filterable rather than a dropdown: with 148 leads a select box hides everything
that needs work. Default filter is "Needs action" so the list opens on the work, not the
archive.

Tracking is automatic where it can be: marking a message sent advances the prospect's status,
stamps first-contact and schedules the next follow-up (db.mark_message_sent).
"""

import streamlit as st

import data as data_mod
import db
from data import Snapshot
from ui import copy_block, pill, section

OPEN_STATUSES = {"Not Contacted", "Comment + DM sent", "Messaged", "Email sent",
                 "Proposal sent", "Loom sent — awaiting reply", "Negotiating"}

TONE = {
    "Not Contacted": "mute", "Bounced": "bad", "Not Interested": "bad",
    "Negotiating": "good", "Call completed": "good",
}


def render(snap: Snapshot) -> None:
    prospects = snap.prospects

    left, mid, right = st.columns([2, 1, 1])
    query = left.text_input("Search", placeholder="name, industry, city, or anything they wrote",
                            key="pipe_q", label_visibility="collapsed")
    show = mid.selectbox("Show", ["Needs action", "Open", "Everything"], key="pipe_show",
                         label_visibility="collapsed")
    sources = sorted({p.get("source") for p in prospects if p.get("source")})
    source_filter = right.multiselect("Source", sources, key="pipe_src",
                                      placeholder="Source", label_visibility="collapsed")

    def needs_action(p: dict) -> bool:
        rows = snap.messages_for(p["id"])
        return any(not m.get("sent_at") for m in rows) or any(
            m.get("sent_at") and m.get("replied") is None for m in rows)

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
                             ("business_name", "owner_name", "industry", "notes", "email",
                              "country_city", "raw_input")).lower()
        ]

    section(f"{len(visible)} lead{'s' if len(visible) != 1 else ''}", "target")
    if not visible:
        st.info("Nothing matches. Widen the filter, or switch Show to Everything.")

    for prospect in visible[:60]:
        rows = snap.messages_for(prospect["id"])
        unsent = [m for m in rows if not m.get("sent_at")]
        awaiting = [m for m in rows if m.get("sent_at") and m.get("replied") is None]
        status = prospect.get("outreach_status") or "Not Contacted"

        flag = f"  ·  {len(unsent)} to send" if unsent else (
            f"  ·  {len(awaiting)} awaiting reply" if awaiting else "")

        with st.expander(f"{prospect.get('business_name') or 'Unknown'}  ·  {status}{flag}"):
            meta = " · ".join(filter(None, [
                prospect.get("industry"), prospect.get("country_city"), prospect.get("source"),
                prospect.get("email"), (prospect.get("created_at") or "")[:10]]))
            st.markdown(
                pill(status, TONE.get(status, "info"))
                + (f'  <span style="color:#6B7280;font-size:0.8rem">{meta}</span>' if meta else ""),
                unsafe_allow_html=True)
            if prospect.get("notes"):
                st.caption(prospect["notes"])

            if prospect.get("raw_input"):
                with st.expander("What they actually posted", expanded=False):
                    copy_block(prospect["raw_input"], key=f"raw_{prospect['id']}")

            dates = []
            if prospect.get("date_first_contacted"):
                dates.append(f"first contacted {prospect['date_first_contacted']}")
            if prospect.get("next_follow_up_date"):
                dates.append(f"next follow-up {prospect['next_follow_up_date']}")
            if dates:
                st.caption(" · ".join(dates))

            with st.popover("Change status"):
                statuses = db.OUTREACH_STATUSES
                new_status = st.selectbox(
                    "Status", statuses,
                    index=statuses.index(status) if status in statuses else 0,
                    key=f"st_{prospect['id']}")
                if st.button("Save", key=f"stsave_{prospect['id']}"):
                    try:
                        db.update_prospect_status(prospect["id"], new_status)
                        data_mod.refresh()
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
                    unsafe_allow_html=True)
                if msg.get("subject"):
                    copy_block(msg["subject"], key=f"sub_{msg['id']}")
                copy_block(msg.get("content") or "", key=f"body_{msg['id']}")

                if not sent:
                    if st.button("Mark sent", key=f"sent_{msg['id']}", use_container_width=True):
                        try:
                            db.mark_message_sent(msg["id"])
                            data_mod.refresh()
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
                        copy_block(msg["reply_text"], key=f"rep_{msg['id']}")
                    continue

                with st.form(f"out_{msg['id']}"):
                    got = st.radio("What happened?", ["Replied", "Nothing yet"], horizontal=True)
                    reply_text = st.text_area(
                        "Reply text — paste VERBATIM, never summarise", height=90)
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
                                    None if objection == "—" else objection)
                                data_mod.refresh()
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Failed: {str(exc)[:200]}")

    if len(visible) > 60:
        st.caption(f"Showing the 60 most recent of {len(visible)}. Use search to narrow.")
