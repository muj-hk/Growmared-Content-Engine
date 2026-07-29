"""
Pipeline — mark drafts as sent and record what came back.

This is the write surface for the OUTREACH LEARNING LOG: every message logged at send time,
every outcome logged the moment it happens, reply text stored verbatim. The monthly
extraction (extract_learnings.py) reads nothing but this log, so the quality of next
month's copy depends on what gets recorded here.
"""

import streamlit as st

import db
from auth import require_login
from ui import inject_base_css, render_brand

st.set_page_config(page_title="Pipeline | Growmated Engine", page_icon="📈", layout="wide")
inject_base_css()
require_login()
render_brand()

st.title("Pipeline")
st.caption("Mark drafts sent, and log every reply verbatim. Zero-reply messages are data too.")

if not db.is_configured():
    st.error("Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY.")
    st.stop()

try:
    prospects = db.list_prospects(limit=100)
except Exception as exc:
    st.error(f"Could not load the pipeline: {type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

if not prospects:
    st.info("No prospects yet. Generate one in Prospecting first.")
    st.stop()


def _label(p: dict) -> str:
    when = (p.get("created_at") or "")[:10]
    return f"{p.get('business_name') or 'Unknown'} · {p.get('outreach_status') or '?'} · {when}"


chosen = st.selectbox("Prospect", prospects, format_func=_label)

# ----------------------------------------------------------------------------------------
# Prospect header + status
# ----------------------------------------------------------------------------------------
left, right = st.columns([3, 2])
with left:
    st.markdown(f"**{chosen.get('business_name')}**")
    if chosen.get("notes"):
        st.caption(chosen["notes"])
    meta = " · ".join(filter(None, [chosen.get("industry"), chosen.get("source"), chosen.get("email")]))
    if meta:
        st.caption(meta)
with right:
    statuses = db.OUTREACH_STATUSES
    current = chosen.get("outreach_status")
    new_status = st.selectbox(
        "Status", statuses,
        index=statuses.index(current) if current in statuses else 0,
    )
    if new_status != current and st.button("Update status", use_container_width=True):
        try:
            db.update_prospect_status(chosen["id"], new_status)
            st.rerun()
        except Exception as exc:
            st.error(f"Failed: {str(exc)[:200]}")

st.divider()

# ----------------------------------------------------------------------------------------
# Messages: send + outcome per row
# ----------------------------------------------------------------------------------------
try:
    messages = db.list_messages(chosen["id"])
except Exception as exc:
    st.error(f"Could not load messages: {type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

if not messages:
    st.info("No messages logged for this prospect.")

for msg in messages:
    sent = bool(msg.get("sent_at"))
    replied = msg.get("replied")
    icon = "📨" if not sent else ("💬" if replied else "⏳")
    outcome_note = f" · {msg.get('final_outcome')}" if msg.get("final_outcome") else ""

    with st.expander(
        f"{icon} {msg.get('channel')} · {'sent ' + msg['sent_at'][:10] if sent else 'draft'}{outcome_note}",
        expanded=not sent,
    ):
        st.code(msg.get("content") or "", language="markdown")
        attrs = " · ".join(
            f"{k}: {msg.get(k)}"
            for k in ("opener_type", "angle", "cta_type", "proof_used", "word_count")
            if msg.get(k)
        )
        if attrs:
            st.caption(attrs)

        if not sent:
            if st.button("✅ Mark sent", key=f"sent_{msg['id']}", use_container_width=True):
                try:
                    db.mark_message_sent(msg["id"])
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {str(exc)[:200]}")
            continue

        st.markdown("**Outcome**")
        if replied is not None:
            st.caption(
                f"Recorded: replied={replied}"
                + (f", {msg.get('days_to_reply')}d to reply" if msg.get("days_to_reply") is not None else "")
                + (f", quality={msg.get('reply_quality')}" if msg.get("reply_quality") else "")
            )
            if msg.get("reply_text"):
                st.code(msg["reply_text"], language="markdown")

        with st.form(f"outcome_{msg['id']}"):
            got_reply = st.radio("Did they reply?", ["Yes", "No (still silent)"], horizontal=True)
            reply_text = st.text_area(
                "Reply text — paste VERBATIM, never summarize", height=100,
                placeholder="Exactly what they wrote back...",
            )
            c1, c2, c3 = st.columns(3)
            quality = c1.selectbox("Reply quality", ["—"] + db.REPLY_QUALITIES)
            objection = c2.selectbox("Objection (if brush-off)", ["—"] + db.OBJECTION_CATEGORIES)
            outcome = c3.selectbox("Final outcome", ["—"] + db.FINAL_OUTCOMES)

            if st.form_submit_button("Save outcome", use_container_width=True):
                is_reply = got_reply == "Yes"
                if is_reply and not reply_text.strip():
                    st.warning("Paste the reply verbatim — the reply text is the gold.")
                else:
                    try:
                        db.record_outcome(
                            msg["id"], is_reply, reply_text,
                            None if quality == "—" else quality,
                            None if objection == "—" else objection,
                            None if outcome == "—" else outcome,
                        )
                        st.success("Logged.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {str(exc)[:200]}")
