"""Shared UI helpers so both tools look and behave the same."""

import re

import streamlit as st

from quality import find_fabrications, find_violations, repairable_fields

BASE_CSS = """
<style>
/* Keep long generated copy readable instead of stretching across an ultrawide monitor. */
.block-container { max-width: 1100px; padding-top: 2.2rem; }

/* st.code is the copy-to-clipboard surface for every draft. Wrap instead of scrolling
   sideways, which is what made drafts painful to read on a laptop or phone. */
.stCode > div, .stCode pre, .stCode code {
    white-space: pre-wrap !important;
    word-break: break-word !important;
    font-size: 0.95rem;
    line-height: 1.55;
}

/* Tabs get cramped on narrow screens; let them wrap rather than clip. */
.stTabs [data-baseweb="tab-list"] { flex-wrap: wrap; gap: 0.25rem; }

@media (max-width: 640px) {
    .block-container { padding-left: 0.8rem; padding-right: 0.8rem; padding-top: 1.2rem; }
    .stCode > div, .stCode pre, .stCode code { font-size: 0.9rem; }
}
</style>
"""


def inject_base_css() -> None:
    st.markdown(BASE_CSS, unsafe_allow_html=True)


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
