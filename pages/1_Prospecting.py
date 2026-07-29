"""
Prospecting tool — turn a raw dump into ready-to-send outreach.

Two input modes:
  Social / profile -> public comment + DM + cold email
  Upwork job       -> a single tailored proposal with an honest fit score
"""

import streamlit as st

import db
from auth import require_login
from context_builder import (
    OUTREACH_RESPONSES_SCHEMA,
    OUTREACH_SCHEMA,
    UPWORK_RESPONSES_SCHEMA,
    UPWORK_SCHEMA,
    build_outreach_system_prompt,
    build_upwork_system_prompt,
    normalize_proof_id,
)
from growmated_knowledge import PROOF_BANK
from intent import INTENTS
import json

from llm import (
    PROVIDER,
    SPEED_MODES,
    MissingDependencyError,
    MissingKeyError,
    build_client,
    generate_json,
    repair_until_clean,
)
from quality import (
    find_fabrications,
    find_violations,
    normalize_responses,
    repairable_fields,
)
from ui import (
    inject_base_css,
    render_brand,
    render_proof_banner,
    render_quality_warnings,
    sanitize_text,
)

st.set_page_config(page_title="Prospecting | Growmated Engine", page_icon="🎯", layout="wide")
inject_base_css()
require_login()

VALID_PROOF_IDS = {entry["id"] for entry in PROOF_BANK}

MODES = {
    "💬 Social post / profile": {
        "key": "social",
        "prompt": build_outreach_system_prompt,
        "schema": OUTREACH_SCHEMA,
        "repair_schema": OUTREACH_RESPONSES_SCHEMA,
        "placeholder": "Paste a Facebook post, LinkedIn profile, group thread or email...",
        "default_source": "Facebook Post",
    },
    "📄 Upwork job post": {
        "key": "upwork",
        "prompt": build_upwork_system_prompt,
        "schema": UPWORK_SCHEMA,
        "repair_schema": UPWORK_RESPONSES_SCHEMA,
        "placeholder": "Paste the full Upwork job posting, including budget and skills if shown...",
        "default_source": "Upwork",
    },
}

if "prospect_history" not in st.session_state:
    st.session_state.prospect_history = []

render_brand()

st.title("Prospecting")
st.caption("Paste a raw dump. Get outreach grounded in real Growmated proof, ready to send.")

# ----------------------------------------------------------------------------------------
# Controls
# ----------------------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Settings")
    mode_label = st.radio("Input type", list(MODES), index=0)
    mode = MODES[mode_label]

    speed_label = st.radio("Model", list(SPEED_MODES), index=0)
    st.caption(SPEED_MODES[speed_label]["caption"])

    source = st.selectbox(
        "Source", db.SOURCES,
        index=db.SOURCES.index(mode["default_source"]) if mode["default_source"] in db.SOURCES else 0,
    )

    save_to_db = st.toggle("Save to pipeline", value=True, help="Writes to Supabase so the team shares one history.")
    if not db.is_configured():
        st.warning("Supabase not configured. Results stay in this browser session only.")

    if st.session_state.get("last_latency"):
        st.caption(f"⏱️ Last generation: {st.session_state.last_latency:.1f}s")

    st.divider()
    if st.button("🗑️ Clear this session", use_container_width=True):
        st.session_state.prospect_history = []
        st.rerun()

# ----------------------------------------------------------------------------------------
# Input
# ----------------------------------------------------------------------------------------
raw_input = st.chat_input(mode["placeholder"])

if raw_input:
    payload_text = sanitize_text(raw_input)
    with st.spinner(f"Analysing and drafting ({speed_label})..."):
        try:
            client = build_client()
            effort = SPEED_MODES[speed_label]["effort"]
            payload, elapsed = generate_json(
                client,
                mode["prompt"](),
                f"RAW TEXT:\n{payload_text}",
                mode["schema"],
                effort=effort,
            )
            # Mechanical typography fixes first, so the LLM repair pass only handles
            # things that actually need rewriting.
            responses = normalize_responses(payload.get("responses", {}) or {})

            # The prompt asks for house style, but common phrasing slips through. Repair it
            # rather than shipping copy the team has to hand-edit every time.
            responses = repair_until_clean(client, responses, mode["repair_schema"])

            st.session_state.last_latency = elapsed

            item = {
                "extracted": payload.get("extracted", {}) or {},
                "routing": payload.get("routing", {}) or {},
                "responses": responses,
                "mode": mode["key"],
                "raw": payload_text,
                "saved_id": None,
                "save_error": None,
            }

            # Nothing to file if the honest answer was "skip" - saving it would pollute the
            # pipeline with rows nobody will ever action.
            engage = item["routing"].get("should_engage", "yes") != "no"
            if save_to_db and db.is_configured() and engage:
                try:
                    item["saved_id"] = db.save_prospect(
                        item["extracted"], item["responses"], payload_text, mode["key"], source,
                        intent=item["routing"].get("intent"),
                    )
                except Exception as exc:  # surface, never silently drop the draft
                    item["save_error"] = str(exc)[:300]

            st.session_state.prospect_history.append(item)
            st.rerun()

        except (MissingKeyError, MissingDependencyError) as exc:
            st.error(f"**Setup needed.** {exc}")
        except json.JSONDecodeError:
            st.error(
                "**The model returned something that was not valid JSON.** This is usually "
                "transient. Try again, and if it keeps happening switch the model in the "
                "sidebar."
            )
        except Exception as exc:
            name = type(exc).__name__
            status = getattr(exc, "status_code", None)
            if "InternalServer" in name or "ServiceUnavailable" in name or (status or 0) >= 500:
                st.error(
                    f"**The {PROVIDER} endpoint is returning server errors.** Nothing is wrong "
                    "with your input; the provider is having problems. Wait a few minutes and "
                    "retry. If it persists, set `GROWMATED_PROVIDER=claude` in the app's "
                    "secrets to switch provider."
                )
            elif "RateLimit" in name:
                st.error("**Rate limited by the provider.** Wait a moment and try again.")
            elif "Timeout" in name:
                st.error(
                    "**The model took too long and the request timed out.** The endpoint is "
                    "busy. Try again, or switch to Fast in the sidebar."
                )
            elif "Connection" in name or "APIConnection" in name:
                st.error(
                    "**Could not reach the model endpoint.** Check the connection and try again."
                )
            elif "Authentication" in name or "PermissionDenied" in name:
                st.error(
                    "**The API key was rejected.** Check the provider key in the app's secrets."
                )
            else:
                st.error(f"**Generation failed.** {name}: {str(exc)[:400]}")

# ----------------------------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------------------------
if not st.session_state.prospect_history:
    st.info("Paste a dump below to generate your first bundle.")

for idx, item in enumerate(reversed(st.session_state.prospect_history)):
    ext, resp = item["extracted"], item["responses"]
    routing = item.get("routing", {}) or {}
    detected = routing.get("intent") or "post"
    title = ext.get("name") or "Prospect"
    company = ext.get("company")
    header = f"{title} · {company}" if company else title
    label = INTENTS.get(detected, {}).get("label", detected)

    with st.expander(f"{header}  ·  {label}", expanded=(idx == 0)):
        # Not worth engaging is a real answer, and the loudest thing on the card.
        if routing.get("should_engage") == "no" or detected == "skip":
            st.warning(
                f"**Skip this one.** {routing.get('skip_reason') or 'Not a fit.'}"
            )

        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**Need:** {ext.get('intent', 'N/A')}")
            st.markdown(f"**Industry:** {ext.get('industry', 'N/A')}")
        with right:
            if ext.get("email"):
                st.markdown(f"**Email:** {ext['email']}")
            if ext.get("phone"):
                st.markdown(f"**Phone:** {ext['phone']}")
            if ext.get("budget"):
                st.markdown(f"**Budget:** {ext['budget']}")
            if ext.get("stack"):
                st.markdown(f"**Stack:** {ext['stack']}")

        proof_id = normalize_proof_id(resp.get("proof_used"))
        render_proof_banner(proof_id, VALID_PROOF_IDS)
        render_quality_warnings(resp, proof_id)

        if item.get("save_error"):
            st.warning(f"Draft generated but not saved to pipeline: {item['save_error']}")
        elif item.get("saved_id"):
            st.caption("💾 Saved to pipeline")

        st.divider()

        if item["mode"] == "upwork":
            # The bid decision comes first: whether to spend connects matters more than the copy.
            bid = (resp.get("bid") or "").lower()
            bid_style = {
                "bid": ("✅", st.success),
                "maybe": ("🟡", st.warning),
                "skip": ("⛔", st.error),
            }.get(bid, ("⚪", st.info))
            icon, writer = bid_style
            writer(f"{icon} **{bid.upper() or 'UNSCORED'}** — {resp.get('bid_reason', 'no reason given')}")

            fit = (resp.get("fit_score") or "unknown").lower()
            st.caption(f"Fit: {fit} · {resp.get('fit_reason', '')}")
            if resp.get("red_flags"):
                st.caption(f"⚠️ Red flags: {resp['red_flags']}")
            if resp.get("client_risk"):
                st.caption(f"Client's likely worry: {resp['client_risk']}")

            st.caption("Paste into Upwork:")
            st.code(resp.get("proposal", "N/A"), language="markdown")
            if resp.get("questions_to_ask"):
                st.caption("Ask before quoting a number:")
                st.code(resp["questions_to_ask"], language="markdown")
        else:
            # Render only what this intent produced, so nobody sends an irrelevant channel.
            available = [
                (name, title, caption)
                for name, title, caption in (
                    ("comment", "Comment", "Drop under their post:"),
                    ("dm", "DM", "Send via Messenger / LinkedIn:"),
                    ("answer", "Answer", "Post this as the answer. No pitch attached, by design:"),
                    ("reply", "Reply", "The next message in this thread:"),
                )
                if (resp.get(name) or "").strip()
            ]
            has_email = bool((resp.get("email_body") or "").strip())
            if has_email:
                available.append(("email", "Email", None))

            if not available:
                st.info("No copy generated for this one, which is the correct output for a skip.")
            else:
                tabs = st.tabs([title for _, title, _ in available])
                for tab, (name, _, caption) in zip(tabs, available):
                    with tab:
                        if name == "email":
                            st.caption(f"Send to: **{ext.get('email', 'unknown')}**")
                            st.text_input("Subject", value=resp.get("email_subject", ""), key=f"subj_{idx}")
                            st.code(resp.get("email_body", ""), language="markdown")
                        else:
                            st.caption(caption)
                            st.code(resp.get(name, ""), language="markdown")

            objection = resp.get("objection_category")
            if objection and objection != "none":
                st.caption(f"Objection detected: **{objection}**")
