"""
Growmated Engine — home.

Two separate tools, sharing only the brand knowledge in growmated_knowledge.py:
  🎯 Prospecting -> pages/1_Prospecting.py -> writes public.pipeline + public.outreach_log
  📝 Content     -> pages/2_Content.py     -> reads/writes public.content_calendar

Run: streamlit run app.py
"""

import streamlit as st

import db
from auth import render_sign_out, require_login
from growmated_knowledge import BRAND, PROOF_BANK
from llm import MODEL, PROVIDER, check_dependencies, load_api_key
from ui import inject_base_css

st.set_page_config(page_title="Growmated Engine", page_icon="⚡", layout="wide")
inject_base_css()
require_login()

st.title("⚡ Growmated Engine")
st.caption(BRAND["tagline"])

col_prospect, col_content = st.columns(2)

with col_prospect:
    st.subheader("🎯 Prospecting")
    st.write(
        "Paste a Facebook post, LinkedIn profile or Upwork job. Get a comment, DM and cold email "
        "(or a tailored Upwork proposal), grounded in real Growmated case studies."
    )
    st.page_link("pages/1_Prospecting.py", label="Open Prospecting", icon="🎯")

with col_content:
    st.subheader("📝 Content")
    st.write(
        "The posting queue. Each day's post from the scheduled Cowork chat, with the image and "
        "separate copy and tags per platform. Open a tab, copy, post, mark it done."
    )
    st.page_link("pages/2_Content.py", label="Open Content", icon="📝")

st.divider()

# ------------------------------------------------------------------------------------------
# Health check, so setup problems are obvious here instead of failing mid-generation.
# ------------------------------------------------------------------------------------------
st.subheader("Status")

KEY_NAME = "ANTHROPIC_API_KEY" if PROVIDER == "claude" else "NVIDIA_API_KEY"
key_ok = bool(load_api_key(KEY_NAME))
db_ok = db.is_configured()

c1, c2, c3 = st.columns(3)
c1.metric(f"{PROVIDER.title()} key", "✅ set" if key_ok else "❌ missing")
c2.metric("Database", "✅ connected" if db_ok else "❌ not configured")
c3.metric("Proof entries", len(PROOF_BANK))

if not key_ok:
    st.error(f"{KEY_NAME} is missing. Add it to .env or the app's secrets.")

# A missing SDK should surface here on load, not as a traceback mid-generation.
dependency_problem = check_dependencies()
if dependency_problem:
    st.error(f"**Dependency missing.** {dependency_problem}")

if db_ok:
    try:
        prospects = db.list_prospects(limit=1000)
        queue = [p for p in db.list_content(limit=1000) if p.get("status") != "Posted"]
        d1, d2 = st.columns(2)
        d1.metric("Prospects in pipeline", len(prospects))
        d2.metric("Posts waiting", len(queue))
    except Exception as exc:
        st.warning(f"Database configured but unreachable: {type(exc).__name__}: {str(exc)[:200]}")

st.caption(f"Model: `{MODEL}`")

with st.sidebar:
    render_sign_out()
