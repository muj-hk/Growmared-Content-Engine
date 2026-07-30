"""
Growmated Engine — one page, one set of tabs.

Everything the team does lives here: what to do today, prospecting, the email queue, the
posting queue, the lead pipeline, and what the data says. Multi-page navigation split related
work across screens and made state hard to follow; tabs keep it in one place.

Data is loaded ONCE per render (data.load) and shared by every tab, because Streamlit renders
all tabs on each rerun and six independent queries per click would be slow and inconsistent.

Run: streamlit run app.py
"""

import streamlit as st

import data as data_mod
import db
from auth import render_sign_out, require_login
from growmated_knowledge import BRAND, PROOF_BANK
from llm import MODEL, PROVIDER, check_dependencies, load_api_key
from ui import icon, inject_base_css, page_header, pill, render_brand
from views import content as content_view
from views import emails as emails_view
from views import insights as insights_view
from views import pipeline as pipeline_view
from views import prospecting as prospecting_view
from views import today as today_view

st.set_page_config(page_title="Growmated Engine", page_icon="⚡", layout="wide")
inject_base_css()
render_brand()
require_login()

# No repeated title block: the wordmark in the sidebar already carries identity, and saying
# "Growmated Engine" three times before any data is what made the top feel like filler.
# The page opens straight into the tabs and the numbers.

# ------------------------------------------------------------------------------------------
# Setup problems surface here, before any tab tries to work
# ------------------------------------------------------------------------------------------
KEY_NAME = "ANTHROPIC_API_KEY" if PROVIDER == "claude" else "NVIDIA_API_KEY"
key_ok = bool(load_api_key(KEY_NAME))
dependency_problem = check_dependencies()

if not key_ok:
    st.error(f"**{KEY_NAME} is missing.** Add it to .env locally, or to the app's secrets "
             "when deployed. Generation will fail until it is set.")
if dependency_problem:
    st.error(f"**Dependency missing.** {dependency_problem}")

snap = data_mod.load()
if not snap.ok:
    st.error(f"**Database unavailable.** {snap.error}")

with st.sidebar:
    st.markdown('<div class="gm-section" style="margin-top:4px">Switches</div>',
                unsafe_allow_html=True)
    st.toggle("Dark mode", key="dark_mode",
              help="Dark surfaces for late sessions. Preference is per browser session.")
    st.toggle("Generated = sent", key="auto_sent", value=True,
              help="The team sends social copy immediately, so new drafts log as sent. "
                   "Cold emails always stay in the timed queue.")
    st.markdown('<div class="gm-section">Session</div>', unsafe_allow_html=True)
    if st.button("Refresh data", use_container_width=True):
        data_mod.refresh()
        st.rerun()

if st.session_state.get("dark_mode"):
    st.markdown("""<style>
    .stApp, [data-testid="stHeader"] {background:#0E0E15 !important;}
    [data-testid="stSidebar"] {background:#12121B !important; border-right-color:rgba(255,255,255,0.08) !important;}
    h1,h2,h3,h4,p,li,label,.stMarkdown,[data-testid="stMetricLabel"],[data-testid="stWidgetLabel"] p {color:#ECECF1 !important;}
    .gm-kpi,.gm-action,[data-testid="stExpander"] {background:#161622 !important; border-color:rgba(255,255,255,0.09) !important;}
    .gm-kpi__value,.gm-brand__name,[data-testid="stMetricValue"] {color:#ECECF1 !important;}
    .gm-kpi__label,.gm-kpi__note,.gm-action__body,[data-testid="stCaptionContainer"] p,.gm-section {color:#A0A0AD !important;}
    .gm-action__body strong {color:#ECECF1 !important;}
    [data-testid="stTextArea"] textarea:disabled,[data-testid="stTextArea"] textarea,
    .stTextInput input,[data-baseweb="select"] > div {background:#161622 !important; color:#ECECF1 !important; -webkit-text-fill-color:#ECECF1 !important; border-color:rgba(255,255,255,0.12) !important;}
    .stButton > button {background:#161622; color:#ECECF1; border-color:rgba(255,255,255,0.14);}
    .stTabs [data-baseweb="tab"] {color:#A0A0AD;}
    .stTabs [aria-selected="true"] {color:#8B8DF0 !important;}
    .gm-pill--mute {background:#161622; color:#A0A0AD; border-color:rgba(255,255,255,0.12);}
    [data-testid="stExpander"] summary, [data-testid="stExpander"] summary p {color:#ECECF1 !important;}
    [data-testid="stSidebarHeader"] {background:#12121B !important;}
    .gm-bar {background:#22222E !important;}
    hr, [data-testid="stDivider"] {border-color:rgba(255,255,255,0.09) !important;}
    </style>""", unsafe_allow_html=True)
    render_sign_out()
    st.markdown(
        pill(f"{PROVIDER}: {MODEL}", "good" if key_ok and not dependency_problem else "bad",
             "check" if key_ok and not dependency_problem else "ban")
        + "<br><br>" + pill("Database connected" if snap.ok else "Database down",
                            "good" if snap.ok else "bad", "check" if snap.ok else "ban")
        + "<br><br>" + pill(f"{len(PROOF_BANK)} approved case studies", "info", "doc"),
        unsafe_allow_html=True)

# ------------------------------------------------------------------------------------------
# Tabs. Order follows the working day: see what needs doing, then do it.
# ------------------------------------------------------------------------------------------
tab_today, tab_prospect, tab_emails, tab_content, tab_pipeline, tab_insights = st.tabs(
    ["Today", "Prospecting", "Emails", "Content", "Pipeline", "Insights"])

with tab_today:
    today_view.render(snap)

with tab_prospect:
    prospecting_view.render(snap)

with tab_emails:
    if snap.ok:
        emails_view.render(snap)

with tab_content:
    if snap.ok:
        content_view.render(snap)

with tab_pipeline:
    if snap.ok:
        pipeline_view.render(snap)

with tab_insights:
    if snap.ok:
        insights_view.render(snap)
