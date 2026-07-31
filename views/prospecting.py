"""
Prospecting — paste anything a prospect wrote, get only what fits.

An intent router classifies the input first (hiring, problem, question, offer, live thread,
profile, Upwork job, or skip) and produces only the channels that intent calls for. Refusing
to write is a first-class output: a tool that always produces copy trains the team to send
copy that should not be sent.
"""

import json

import streamlit as st

import data as data_mod
import db
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
from llm import (
    PROVIDER,
    SPEED_MODES,
    MissingDependencyError,
    MissingKeyError,
    build_client,
    generate_json,
    repair_copy,
    repair_until_clean,
)
from quality import (
    find_duplicate_input,
    find_repetition,
    normalize_responses,
    repairable_fields,
)
from ui import copy_block, pill, render_proof_banner, render_quality_warnings, sanitize_text

VALID_PROOF_IDS = {entry["id"] for entry in PROOF_BANK}

MODES = {
    "Social post / profile": {
        "key": "social", "prompt": build_outreach_system_prompt,
        "schema": OUTREACH_SCHEMA, "repair_schema": OUTREACH_RESPONSES_SCHEMA,
        "placeholder": "Paste a post, profile, question, or a whole thread...",
        "default_source": "Facebook Post",
    },
    "Upwork job post": {
        "key": "upwork", "prompt": build_upwork_system_prompt,
        "schema": UPWORK_SCHEMA, "repair_schema": UPWORK_RESPONSES_SCHEMA,
        "placeholder": "Paste the full Upwork job posting, with budget and skills if shown...",
        "default_source": "Upwork",
    },
}


def _generate(text: str, mode: dict, effort: str, source: str) -> None:
    with st.spinner("Reading it, then writing only what fits..."):
        try:
            client = build_client()
            # The prompt is built per input so only the domain knowledge this paste touches
            # gets injected (ghl_knowledge.relevant_knowledge).
            payload, elapsed = generate_json(
                client, mode["prompt"](text), f"RAW TEXT:\n{text}", mode["schema"], effort=effort)

            responses = normalize_responses(payload.get("responses", {}) or {})
            # The gate: check the copy against their actual post, revise, check again.
            # Nothing reaches the team until it passes or revision stops helping.
            responses = repair_until_clean(client, responses, mode["repair_schema"],
                                           source_text=text)

            # Then check it against what we have already sent other people. Copy can be
            # specific to this prospect and still be a sentence someone else received.
            snap_now = data_mod.load()
            names = {p["id"]: p.get("business_name") for p in snap_now.prospects}
            recent = [{"content": m.get("content"), "business": names.get(m.get("pipeline_id"))}
                      for m in snap_now.messages[:150] if m.get("content")]
            repeats = find_repetition(repairable_fields(responses), recent)
            if repeats:
                responses = normalize_responses(
                    repair_copy(client, responses, repeats, mode["repair_schema"]))
                repeats = find_repetition(repairable_fields(responses), recent)

            item = {
                "extracted": payload.get("extracted", {}) or {},
                "routing": payload.get("routing", {}) or {},
                "responses": responses, "mode": mode["key"], "raw": text,
                "saved_id": None, "save_error": None, "repeats": repeats,
            }
            st.session_state.last_latency = elapsed

            engage = item["routing"].get("should_engage", "yes") != "no"
            if st.session_state.get("save_to_db", True) and db.is_configured() and engage:
                try:
                    item["saved_id"] = db.save_prospect(
                        item["extracted"], item["responses"], text, mode["key"], source,
                        intent=item["routing"].get("intent"))
                    # Team sends what it generates, so log it as sent unless toggled off.
                    if st.session_state.get("auto_sent", True):
                        db.mark_bundle_sent(item["saved_id"])
                    data_mod.refresh()
                except Exception as exc:
                    item["save_error"] = str(exc)[:300]

            st.session_state.prospect_history.append(item)
            st.rerun()

        except (MissingKeyError, MissingDependencyError) as exc:
            st.error(f"**Setup needed.** {exc}")
        except json.JSONDecodeError:
            st.error("**The model returned invalid JSON.** Usually transient — try again.")
        except Exception as exc:
            name = type(exc).__name__
            status = getattr(exc, "status_code", None)
            if "InternalServer" in name or (status or 0) >= 500:
                st.error(f"**The {PROVIDER} endpoint is returning server errors.** Nothing is "
                         "wrong with your input. Wait a moment and retry.")
            elif "RateLimit" in name:
                st.error("**Rate limited by the provider.** Wait a moment and try again.")
            elif "Timeout" in name:
                st.error("**The request timed out.** Try again, or switch to Fast.")
            elif "Authentication" in name or "PermissionDenied" in name:
                st.error("**The API key was rejected.** Check the provider key in secrets.")
            else:
                st.error(f"**Generation failed.** {name}: {str(exc)[:300]}")


def render(snap) -> None:
    if "prospect_history" not in st.session_state:
        st.session_state.prospect_history = []

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    mode_label = c1.selectbox("Input type", list(MODES), label_visibility="collapsed")
    mode = MODES[mode_label]
    speed_label = c2.selectbox("Model", list(SPEED_MODES), label_visibility="collapsed")
    source = c3.selectbox(
        "Source", db.SOURCES, label_visibility="collapsed",
        index=db.SOURCES.index(mode["default_source"]) if mode["default_source"] in db.SOURCES else 0)
    c4.toggle("Save to pipeline", value=True, key="save_to_db")

    if st.session_state.get("last_latency"):
        st.caption(f"Last generation: {st.session_state.last_latency:.1f}s")

    effort = SPEED_MODES[speed_label]["effort"]

    raw_input = st.chat_input(mode["placeholder"])
    if raw_input:
        text = sanitize_text(raw_input)
        # Same post pasted twice is a human error, not a generation request. Catch it before
        # spending a call and before creating a second lead for one business.
        duplicate = find_duplicate_input(text, snap.prospects)
        if duplicate:
            st.session_state.dup_pending = {
                "text": text, "mode": mode_label, "effort": effort,
                "source": source, "lead": duplicate,
            }
            st.rerun()
        _generate(text, mode, effort, source)

    pending = st.session_state.get("dup_pending")
    if pending:
        lead = pending["lead"]
        when = (lead.get("created_at") or "")[:10]
        st.warning(
            f"**This looks like a post you already ran.** "
            f"{lead.get('business_name') or 'A lead'} was generated on {when or 'an earlier date'}. "
            "The drafts below are the ones you already have."
        )
        for msg in snap.messages_for(lead["id"])[:2]:
            st.caption(f"{msg.get('channel')} — already written")
            copy_block(msg.get("content") or "", key=f"dup_{msg['id']}")

        keep, regen = st.columns(2)
        if keep.button("Keep the existing drafts", use_container_width=True):
            st.session_state.pop("dup_pending", None)
            st.rerun()
        if regen.button("Write a fresh version anyway", use_container_width=True):
            saved = st.session_state.pop("dup_pending")
            _generate(saved["text"], MODES[saved["mode"]], saved["effort"], saved["source"])

    if not st.session_state.prospect_history:
        st.info("Paste anything a prospect wrote below. It works out what it is, writes only "
                "what fits, and tells you when a lead is not worth engaging.")
        return

    for idx, item in enumerate(reversed(st.session_state.prospect_history)):
        ext, resp = item["extracted"], item["responses"]
        routing = item.get("routing", {}) or {}
        detected = routing.get("intent") or "post"
        title = ext.get("name") or "Prospect"
        company = ext.get("company")
        header = f"{title} · {company}" if company else title
        label = INTENTS.get(detected, {}).get("label", detected)

        with st.expander(f"{header}  ·  {label}", expanded=(idx == 0)):
            if routing.get("should_engage") == "no" or detected == "skip":
                st.warning(f"**Skip this one.** {routing.get('skip_reason') or 'Not a fit.'}")

            left, right = st.columns([3, 2])
            with left:
                st.markdown(f"**Need:** {ext.get('intent', 'N/A')}")
                st.markdown(f"**Industry:** {ext.get('industry', 'N/A')}")
            with right:
                for field, lbl in (("email", "Email"), ("phone", "Phone"),
                                   ("location", "Location"), ("budget", "Budget"),
                                   ("stack", "Stack")):
                    if ext.get(field):
                        st.markdown(f"**{lbl}:** {ext[field]}")

            proof_id = normalize_proof_id(resp.get("proof_used"))
            render_proof_banner(proof_id, VALID_PROOF_IDS)
            render_quality_warnings(resp, proof_id, item.get("raw", ""))
            if item.get("repeats"):
                st.warning(
                    "**Repeats copy sent to someone else.** " + "; ".join(item["repeats"])
                    + ". Rewrite that line before sending."
                )

            if item.get("save_error"):
                st.warning(f"Draft generated but not saved: {item['save_error']}")
            elif item.get("saved_id"):
                st.markdown(pill("Saved to pipeline", "mute", "check"), unsafe_allow_html=True)

            st.divider()

            if item["mode"] == "upwork":
                bid = (resp.get("bid") or "").lower()
                writer = {"bid": st.success, "maybe": st.warning, "skip": st.error}.get(bid, st.info)
                writer(f"**{bid.upper() or 'UNSCORED'}** — {resp.get('bid_reason', '')}")
                st.caption(f"Fit: {resp.get('fit_score', '?')} · {resp.get('fit_reason', '')}")
                if resp.get("red_flags"):
                    st.caption(f"Red flags: {resp['red_flags']}")
                if resp.get("client_risk"):
                    st.caption(f"Client's likely worry: {resp['client_risk']}")
                st.caption("Paste into Upwork:")
                copy_block(resp.get("proposal", ""), key=f"prop_{idx}")
                if resp.get("questions_to_ask"):
                    st.caption("Ask before quoting a number:")
                    copy_block(resp["questions_to_ask"], key=f"q_{idx}")
            else:
                available = [(n, t, c) for n, t, c in (
                    ("comment", "Comment", "Drop under their post:"),
                    ("dm", "DM", "Send via Messenger / LinkedIn:"),
                    ("answer", "Answer", "Post as the answer. No pitch, by design:"),
                    ("reply", "Reply", "The next message in this thread:"),
                ) if (resp.get(n) or "").strip()]
                if (resp.get("email_body") or "").strip():
                    available.append(("email", "Email", None))

                if not available:
                    st.info("No copy generated, which is the correct output for a skip.")
                else:
                    for tab, (name, _, caption) in zip(
                            st.tabs([t for _, t, _ in available]), available):
                        with tab:
                            if name == "email":
                                st.caption(f"Send to: **{ext.get('email', 'unknown')}**")
                                st.text_input("Subject", value=resp.get("email_subject", ""),
                                              key=f"subj_{idx}")
                                copy_block(resp.get("email_body", ""), key=f"eb_{idx}")
                            else:
                                st.caption(caption)
                                copy_block(resp.get(name, ""), key=f"{name}_{idx}")

                objection = resp.get("objection_category")
                if objection and objection != "none":
                    st.caption(f"Objection detected: **{objection}**")

            # Revisions: rewrite one field in place. Updates the SAME DB row, never a new one.
            with st.popover("Revise a message"):
                fields = [f for f in ("comment", "dm", "email_body", "answer", "reply",
                                      "proposal") if (resp.get(f) or "").strip()]
                if fields:
                    target = st.selectbox("Which one?", fields, key=f"rvf_{idx}")
                    ask = st.text_input("What should change?", key=f"rvq_{idx}",
                                        placeholder="e.g. shorter, mention their timeline")
                    if st.button("Revise", key=f"rvb_{idx}") and ask.strip():
                        try:
                            client = build_client()
                            new_text = repair_until_clean(client, {
                                **resp, target:
                                f"REVISE PER TEAM NOTE ({ask.strip()}):\n{resp[target]}"},
                                mode["repair_schema"],
                                source_text=item.get("raw", "")).get(target, resp[target])
                            resp[target] = new_text
                            if item.get("saved_id"):
                                label = db.CHANNEL_LABELS.get(
                                    "email" if target == "email_body" else target, target)
                                db.revise_message(item["saved_id"], label, new_text)
                                data_mod.refresh()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Revision failed: {str(exc)[:200]}")
