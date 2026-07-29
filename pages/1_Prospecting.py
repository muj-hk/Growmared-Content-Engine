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
import json

from llm import (
    SPEED_MODES,
    MissingDependencyError,
    MissingKeyError,
    build_client,
    generate_json,
    repair_copy,
)
from quality import (
    find_fabrications,
    find_violations,
    normalize_responses,
    repairable_fields,
)
from ui import inject_base_css, render_proof_banner, render_quality_warnings, sanitize_text

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

st.title("🎯 Prospecting")
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
            fields = repairable_fields(responses)
            violations = find_violations(fields) + find_fabrications(
                fields, normalize_proof_id(responses.get("proof_used"))
            )
            if violations:
                responses = repair_copy(client, responses, violations, mode["repair_schema"])

            st.session_state.last_latency = elapsed

            item = {
                "extracted": payload.get("extracted", {}) or {},
                "responses": responses,
                "mode": mode["key"],
                "raw": payload_text,
                "saved_id": None,
                "save_error": None,
            }

            if save_to_db and db.is_configured():
                try:
                    item["saved_id"] = db.save_prospect(
                        item["extracted"], item["responses"], payload_text, mode["key"], source
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
            if "Timeout" in name:
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
    title = ext.get("name") or "Prospect"
    company = ext.get("company")
    header = f"{title} · {company}" if company else title

    with st.expander(f"🎯 {header}", expanded=(idx == 0)):
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
            fit = (resp.get("fit_score") or "unknown").lower()
            fit_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(fit, "⚪")
            st.markdown(f"{fit_icon} **Fit: {fit}** — {resp.get('fit_reason', 'no reason given')}")
            st.caption("Paste into Upwork:")
            st.code(resp.get("proposal", "N/A"), language="markdown")
            if resp.get("opening_question"):
                st.caption("Closing question:")
                st.code(resp["opening_question"], language="markdown")
        else:
            tab_comment, tab_dm, tab_email = st.tabs(["💬 Comment", "✉️ DM", "📧 Email"])
            with tab_comment:
                st.caption("Drop under their post:")
                st.code(resp.get("comment", "N/A"), language="markdown")
            with tab_dm:
                st.caption("Send via Messenger / LinkedIn:")
                st.code(resp.get("dm", "N/A"), language="markdown")
            with tab_email:
                if ext.get("email"):
                    st.caption(f"Send to: **{ext['email']}**")
                    st.text_input("Subject", value=resp.get("email_subject", ""), key=f"subj_{idx}")
                    st.code(resp.get("email_body", "N/A"), language="markdown")
                else:
                    st.info("No email address found in the dump, so no cold email was drafted.")
