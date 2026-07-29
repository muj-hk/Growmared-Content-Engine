"""Shared UI helpers so both tools look and behave the same."""

import re

import streamlit as st

from quality import find_fabrications, find_violations, repairable_fields

# Design tokens lifted from growmated.com (styles.css :root) so the tool looks like the
# brand rather than like default Streamlit.
BRAND = {
    "indigo": "#5254CC",
    "indigo_lift": "#6366F1",
    "indigo_soft": "#EEF0FF",
    "ink": "#111827",
    "gray": "#4B5563",
    "gray_mid": "#6B7280",
    "bg_2": "#F7F8FC",
    "card_2": "#F0F2F8",
    "border": "rgba(0,0,0,0.08)",
    "void": "#08080A",
    "green": "#10B981",
    "amber": "#F59E0B",
}

BASE_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600&display=swap');

:root {{
    --gm-indigo: {BRAND['indigo']};
    --gm-indigo-lift: {BRAND['indigo_lift']};
    --gm-ink: {BRAND['ink']};
    --gm-gray: {BRAND['gray']};
    --gm-bg2: {BRAND['bg_2']};
    --gm-border: {BRAND['border']};
}}

html, body, [class*="css"], .stMarkdown, .stTextInput input, .stTextArea textarea {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}}

h1, h2, h3, h4 {{
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 800 !important;
    letter-spacing: -0.02em;
    color: var(--gm-ink);
}}

/* Keep long generated copy readable instead of stretching across an ultrawide monitor. */
.block-container {{ max-width: 1140px; padding-top: 2rem; }}

/* st.code is the copy-to-clipboard surface for every draft. Wrap instead of scrolling
   sideways, which is what made drafts painful to read on a laptop or phone. */
.stCode > div, .stCode pre, .stCode code {{
    white-space: pre-wrap !important;
    word-break: break-word !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.94rem;
    line-height: 1.62;
    background: var(--gm-bg2) !important;
    border: 1px solid var(--gm-border);
    border-radius: 10px;
    color: var(--gm-ink) !important;
}}

/* Buttons follow the site's pill/indigo language. */
.stButton > button {{
    border-radius: 10px;
    font-weight: 600;
    border: 1px solid var(--gm-border);
    transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
}}
.stButton > button:hover {{
    border-color: var(--gm-indigo);
    color: var(--gm-indigo);
}}

/* Tabs get cramped on narrow screens; let them wrap rather than clip. */
.stTabs [data-baseweb="tab-list"] {{ flex-wrap: wrap; gap: 0.25rem; }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; }}
.stTabs [aria-selected="true"] {{ color: var(--gm-indigo) !important; }}

/* Expanders read as cards, matching the site's surface treatment. */
[data-testid="stExpander"] {{
    border: 1px solid var(--gm-border);
    border-radius: 16px;
    background: #FFFFFF;
}}

[data-testid="stSidebar"] {{
    background: var(--gm-bg2);
    border-right: 1px solid var(--gm-border);
}}

[data-testid="stMetricValue"] {{
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-weight: 800;
    color: var(--gm-ink);
}}

/* The gm mark, inlined so it needs no hosted asset. */
.gm-brand {{
    display: flex; align-items: center; gap: 10px;
    padding: 2px 0 14px 0; margin-bottom: 10px;
    border-bottom: 1px solid var(--gm-border);
}}
.gm-brand__mark {{
    width: 32px; height: 32px; border-radius: 6px;
    background: {BRAND['void']}; position: relative; flex-shrink: 0;
    font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 19px;
    line-height: 32px; text-align: center; letter-spacing: -0.5px;
}}
.gm-brand__mark i {{ font-style: normal; color: var(--gm-indigo-lift); }}
.gm-brand__mark b {{ font-weight: 800; color: #F2F2FA; }}
.gm-brand__mark::after {{
    content: ""; position: absolute; top: 4px; right: 3px;
    width: 6px; height: 6px; border-radius: 50%; background: var(--gm-indigo-lift);
}}
.gm-brand__text {{ line-height: 1.15; }}
.gm-brand__name {{
    font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800;
    font-size: 0.95rem; color: var(--gm-ink); letter-spacing: -0.02em;
}}
.gm-brand__tag {{ font-size: 0.72rem; color: {BRAND['gray_mid']}; }}

@media (max-width: 640px) {{
    .block-container {{ padding-left: 0.8rem; padding-right: 0.8rem; padding-top: 1.2rem; }}
    .stCode > div, .stCode pre, .stCode code {{ font-size: 0.9rem; }}
}}
</style>
"""

BRAND_HEADER = """
<div class="gm-brand">
  <div class="gm-brand__mark"><i>g</i><b>m</b></div>
  <div class="gm-brand__text">
    <div class="gm-brand__name">Growmated</div>
    <div class="gm-brand__tag">Your Business, Running Itself.</div>
  </div>
</div>
"""


def inject_base_css() -> None:
    st.markdown(BASE_CSS, unsafe_allow_html=True)


def render_brand(sidebar: bool = True) -> None:
    """The gm mark and tagline, matching growmated.com's header."""
    target = st.sidebar if sidebar else st
    target.markdown(BRAND_HEADER, unsafe_allow_html=True)


def sanitize_text(text: str) -> str:
    """Strip scraper noise and cap payload size before it reaches the model."""
    cleaned = re.sub(r"(Facebook\s*)+", "Facebook ", text)
    cleaned = re.sub(r"\n\s*\n", "\n", cleaned)
    return cleaned[:2500].strip()


def render_quality_warnings(responses: dict, proof_used: str | None = None) -> None:
    """Flag anything that survived the repair pass, so nobody sends generic or broken copy."""
    fields = repairable_fields(responses)

    # Fabricated clients and invented numbers are a different class of problem from a
    # clumsy phrase: they are the one thing that must never reach a prospect.
    fabrications = find_fabrications(fields, proof_used)
    if fabrications:
        st.error(
            "🚨 **Do not send.** This copy invents something: "
            + "; ".join(fabrications)
            + ". Delete the invented claim or regenerate."
        )

    problems = find_violations(fields)
    if problems:
        st.warning("✏️ Worth editing before sending: " + "; ".join(problems))


def render_proof_banner(proof_used: str, valid_ids: set[str]) -> None:
    """Show whether the copy is grounded in a real case study. Red means do not send."""
    proof = proof_used or "unknown"
    if proof in valid_ids:
        st.success(f"✅ Grounded in real proof: `{proof}`")
    elif proof in ("none", "market_math"):
        st.info(f"ℹ️ No case study cited (`{proof}`). Fine when nothing in the bank fits.")
    else:
        st.error(
            f"🚨 Cited `{proof}`, which is not in the proof bank. "
            "Treat this as invented and do not send it."
        )
