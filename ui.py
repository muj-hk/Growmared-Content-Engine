"""
Shared UI: brand, theme, and the small set of components both tools use.

Design direction is "Data-Dense Dashboard" (via the ui-ux-pro-max design system) mapped onto
Growmated's own tokens from growmated-site/styles.css rather than the generic blue palette the
skill suggested. The brand wins; the density and mechanics come from the skill.

Rules being followed deliberately, because breaking them is what made this look basic:
  - No emoji as structural icons. Inline SVG only, one stroke weight, one family.
  - Dense spacing scale (8/12/16/24/32), not Streamlit's roomy defaults.
  - Tabular numerals everywhere a number sits in a column, so figures do not jitter.
  - Every interactive element gets a visible focus ring and a hover state.
  - Motion is subtle (150-220ms) and disabled under prefers-reduced-motion.
  - Status is never colour-only: each state carries an icon or a word too.
"""

import re
from itertools import count
from pathlib import Path

import streamlit as st

from quality import find_fabrications, find_violations, repairable_fields

ASSETS = Path(__file__).parent / "assets"

# Growmated tokens, lifted from growmated-site/styles.css :root.
BRAND = {
    "indigo": "#5254CC",
    "indigo_lift": "#6366F1",
    "indigo_soft": "#EEF0FF",
    "ink": "#111827",
    "gray": "#4B5563",
    "gray_mid": "#6B7280",
    "gray_dim": "#9CA3AF",
    "bg": "#FFFFFF",
    "bg_2": "#F7F8FC",
    "card_2": "#F0F2F8",
    "border": "rgba(0,0,0,0.08)",
    "border_2": "rgba(0,0,0,0.14)",
    "void": "#08080A",
    "green": "#10B981",
    "amber": "#F59E0B",
    "red": "#DC2626",
}

# ------------------------------------------------------------------------------------------
# Icons. Lucide-style 24px grid, 1.75 stroke, currentColor so they inherit state colour.
# ------------------------------------------------------------------------------------------
_ICON_PATHS = {
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "alert": '<path d="M12 9v4"/><path d="M12 17h.01"/><circle cx="12" cy="12" r="9"/>',
    "ban": '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "send": '<path d="M4 12l16-8-6 16-3-6-7-2z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
    "doc": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><polyline points="14 3 14 8 19 8"/>',
    "chart": '<line x1="5" y1="20" x2="5" y2="11"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="19" y1="20" x2="19" y2="14"/>',
    "inbox": '<polyline points="3 12 7 12 9 15 15 15 17 12 21 12"/><path d="M4.5 12L6 5h12l1.5 7v6a2 2 0 0 1-2 2H6.5a2 2 0 0 1-2-2z"/>',
}


def icon(name: str, size: int = 16, color: str = "currentColor") -> str:
    """Inline SVG icon markup. Never an emoji: emoji are font-dependent and untokenizable."""
    paths = _ICON_PATHS.get(name, _ICON_PATHS["info"])
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        f'style="vertical-align:-2px;flex-shrink:0" aria-hidden="true">{paths}</svg>'
    )


BASE_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600&display=swap');

:root {{
    --gm-indigo: {BRAND['indigo']};
    --gm-indigo-lift: {BRAND['indigo_lift']};
    --gm-indigo-soft: {BRAND['indigo_soft']};
    --gm-ink: {BRAND['ink']};
    --gm-gray: {BRAND['gray']};
    --gm-gray-mid: {BRAND['gray_mid']};
    --gm-bg2: {BRAND['bg_2']};
    --gm-border: {BRAND['border']};
    --gm-green: {BRAND['green']};
    --gm-amber: {BRAND['amber']};
    --gm-red: {BRAND['red']};
    /* Dense scale: dashboards earn their keep by fitting more on screen. */
    --gm-s1: 8px; --gm-s2: 12px; --gm-s3: 16px; --gm-s4: 24px; --gm-s5: 32px;
    --gm-radius: 10px;
    --gm-t: 180ms cubic-bezier(0.4, 0, 0.2, 1);
}}

html, body, [class*="css"], .stMarkdown, input, textarea, button, select {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}

h1, h2, h3, h4 {{
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 800 !important;
    letter-spacing: -0.022em;
    color: var(--gm-ink);
}}
h1 {{ font-size: 1.6rem !important; }}
h2 {{ font-size: 1.15rem !important; }}
h3 {{ font-size: 1rem !important; }}

/* Tighter than Streamlit's default, per the data-dense direction. */
/* Top padding must clear Streamlit's floating toolbar (~3.5rem), or the page title and the
   first content rows render underneath it: that was the "content overlapping" bug. */
.block-container {{ max-width: 1240px; padding-top: 3.6rem; padding-bottom: var(--gm-s5); }}
[data-testid="stVerticalBlock"] {{ gap: var(--gm-s2); }}

/* Numbers must not jitter when they change. */
[data-testid="stMetricValue"], .gm-kpi__value, .gm-num {{
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
}}
[data-testid="stMetricValue"] {{
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-weight: 800;
    font-size: 1.5rem;
    color: var(--gm-ink);
}}
[data-testid="stMetricLabel"] {{ color: var(--gm-gray-mid); font-size: 0.78rem; font-weight: 500; }}

/* Copy surfaces are read-only text areas (see ui.copy_block, and the comment there about
   st.code's broken wrap_lines). Style them to read like a document, not a form field. */
[data-testid="stTextArea"] textarea:disabled {{
    background: var(--gm-bg2) !important;
    color: var(--gm-ink) !important;
    -webkit-text-fill-color: var(--gm-ink) !important;
    opacity: 1 !important;
    border: 1px solid var(--gm-border) !important;
    border-radius: var(--gm-radius);
    font-family: 'Inter', sans-serif !important;
    font-size: 0.92rem !important;
    line-height: 1.6 !important;
    cursor: text;
    resize: vertical;
}}

.stButton > button {{
    border-radius: var(--gm-radius);
    font-weight: 600;
    font-size: 0.88rem;
    border: 1px solid var(--gm-border);
    transition: background var(--gm-t), border-color var(--gm-t), color var(--gm-t);
    cursor: pointer;
}}
.stButton > button:hover {{ border-color: var(--gm-indigo); color: var(--gm-indigo); background: var(--gm-indigo-soft); }}

/* Focus must always be visible. Removing it fails WCAG and makes keyboard use guesswork. */
.stButton > button:focus-visible,
input:focus-visible, textarea:focus-visible, select:focus-visible,
[role="tab"]:focus-visible, summary:focus-visible {{
    outline: 2px solid var(--gm-indigo) !important;
    outline-offset: 2px;
}}

.stTabs [data-baseweb="tab-list"] {{ flex-wrap: wrap; gap: 2px; border-bottom: 1px solid var(--gm-border); }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; font-size: 0.86rem; padding: var(--gm-s1) var(--gm-s2); }}
.stTabs [aria-selected="true"] {{ color: var(--gm-indigo) !important; }}

/* Rows read as cards, and highlight on hover so the eye can track them. */
[data-testid="stExpander"] {{
    border: 1px solid var(--gm-border);
    border-radius: var(--gm-radius);
    background: #fff;
    transition: border-color var(--gm-t), box-shadow var(--gm-t);
}}
[data-testid="stExpander"]:hover {{
    border-color: var(--gm-border);
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 4px 12px rgba(0,0,0,0.04);
}}
[data-testid="stExpander"] summary {{ font-weight: 600; font-size: 0.92rem; }}

/* Clearance below captions. Margin, not padding: padding extends the caption's own box
   down into the following element, which reads as an overlap to any geometry check even
   though the text itself does not collide. */
[data-testid="stCaptionContainer"] {{ margin-bottom: 8px; }}
[data-testid="stCaptionContainer"] p {{ margin-bottom: 0; line-height: 1.5; }}

[data-testid="stSidebar"] {{ background: var(--gm-bg2); border-right: 1px solid var(--gm-border); }}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: var(--gm-s2); }}
/* Streamlit headings keep a tall box; without this they collide with the control below
   at dense gaps (the "Settings" / "Input type" overlap). */
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
    margin: 0 !important; padding: 0 0 var(--gm-s1) 0 !important; line-height: 1.25 !important;
    font-size: 0.95rem !important;
}}
h1, h2, h3, h4 {{ margin-top: 0 !important; }}
[data-testid="stHeading"] {{ padding-bottom: 0 !important; }}

/* KPI tile: the dense alternative to a row of st.metric calls. */
.gm-kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(148px, 1fr)); gap: var(--gm-s2); }}
.gm-kpi {{
    border: 1px solid var(--gm-border);
    border-radius: var(--gm-radius);
    padding: var(--gm-s2) var(--gm-s3);
    background: #fff;
    display: flex; flex-direction: column; gap: 2px;
}}
.gm-kpi__label {{
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em;
    text-transform: uppercase; color: var(--gm-gray-mid);
    display: flex; align-items: center; gap: 6px;
}}
.gm-kpi__value {{ font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: 1.5rem; color: var(--gm-ink); line-height: 1.1; }}
.gm-kpi__note {{ font-size: 0.72rem; color: var(--gm-gray-mid); }}
.gm-kpi--good {{ border-left: 3px solid var(--gm-green); }}
.gm-kpi--warn {{ border-left: 3px solid var(--gm-amber); }}
.gm-kpi--bad  {{ border-left: 3px solid var(--gm-red); }}

/* Status pill. Carries an icon as well as colour: colour alone is not accessible. */
.gm-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 100px;
    font-size: 0.76rem; font-weight: 600; line-height: 1.5;
    border: 1px solid transparent;
}}
.gm-pill--good {{ background: #ECFDF5; color: #065F46; border-color: #A7F3D0; }}
.gm-pill--warn {{ background: #FFFBEB; color: #92400E; border-color: #FDE68A; }}
.gm-pill--bad  {{ background: #FEF2F2; color: #991B1B; border-color: #FECACA; }}
.gm-pill--info {{ background: var(--gm-indigo-soft); color: #3730A3; border-color: #C7D2FE; }}
.gm-pill--mute {{ background: var(--gm-bg2); color: var(--gm-gray); border-color: var(--gm-border); }}

/* Section heading with a rule, so dense pages still have structure. */
.gm-section {{
    display: flex; align-items: center; gap: var(--gm-s1);
    font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800;
    font-size: 0.82rem; letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--gm-gray-mid);
    margin: var(--gm-s4) 0 var(--gm-s1) 0;
    padding-bottom: 6px; border-bottom: 1px solid var(--gm-border);
}}

.gm-action {{
    display: flex; gap: var(--gm-s2); align-items: flex-start;
    padding: var(--gm-s2) var(--gm-s3);
    border: 1px solid var(--gm-border); border-left-width: 3px;
    border-radius: var(--gm-radius); background: #fff;
    margin-bottom: var(--gm-s1);
}}
.gm-action--warn {{ border-left-color: var(--gm-amber); }}
.gm-action--bad {{ border-left-color: var(--gm-red); }}
.gm-action--info {{ border-left-color: var(--gm-indigo); }}
.gm-action__body {{ font-size: 0.88rem; color: var(--gm-ink); line-height: 1.5; }}
.gm-action__body strong {{ font-weight: 700; }}

.gm-bar {{ height: 6px; border-radius: 100px; background: var(--gm-card_2, #F0F2F8); overflow: hidden; }}
.gm-bar__fill {{ height: 100%; border-radius: 100px; background: var(--gm-indigo); }}

@media (max-width: 640px) {{
    .block-container {{ padding-left: var(--gm-s2); padding-right: var(--gm-s2); padding-top: var(--gm-s3); }}
    .stCode > div, .stCode pre, .stCode code {{ font-size: 0.88rem; }}
    h1 {{ font-size: 1.35rem !important; }}
    .gm-kpi-row {{ grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }}
}}

/* Motion is a nice-to-have, never a requirement. */
@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{ transition: none !important; animation: none !important; }}
}}
</style>
"""


def inject_base_css() -> None:
    st.markdown(BASE_CSS, unsafe_allow_html=True)


def render_brand() -> None:
    """Logo above the sidebar nav.

    Uses st.logo rather than markdown in the sidebar body: markdown lands BELOW Streamlit's
    auto page-nav, which pushed the mark ~290px down the sidebar and out of view on short
    screens. st.logo is the supported slot above the nav.
    """
    # The light wordmark's ink-dark text disappears against a dark sidebar, which is what
    # made the logo look broken. Pick the variant that matches the active theme.
    name = "growmated-wordmark-dark.svg" if st.session_state.get("dark_mode") \
        else "growmated-wordmark.svg"
    wordmark = ASSETS / name
    if wordmark.exists():
        st.logo(str(wordmark), size="large", icon_image=str(ASSETS / "growmated-icon.svg"))


def page_header(title: str, subtitle: str = "", icon_name: str = "") -> None:
    """Consistent page title. Icon is SVG, never emoji."""
    mark = icon(icon_name, 20, BRAND["indigo"]) if icon_name else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:2px">{mark}'
        f'<h1 style="margin:0">{title}</h1></div>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(
            f'<div style="color:{BRAND["gray_mid"]};font-size:0.88rem;margin-bottom:var(--gm-s3)">{subtitle}</div>',
            unsafe_allow_html=True,
        )


def section(label: str, icon_name: str = "") -> None:
    mark = icon(icon_name, 14, BRAND["gray_mid"]) if icon_name else ""
    st.markdown(f'<div class="gm-section">{mark}{label}</div>', unsafe_allow_html=True)


def kpi_row(items: list[dict]) -> None:
    """Dense KPI tiles. Each item: {label, value, note?, tone?, icon?}.

    tone is "good" | "warn" | "bad" | None, and only ever reinforces text that already says
    the same thing, so meaning never depends on colour.
    """
    tiles = []
    for item in items:
        tone = f" gm-kpi--{item['tone']}" if item.get("tone") else ""
        mark = icon(item["icon"], 12, BRAND["gray_mid"]) if item.get("icon") else ""
        note = f'<div class="gm-kpi__note">{item["note"]}</div>' if item.get("note") else ""
        tiles.append(
            f'<div class="gm-kpi{tone}">'
            f'<div class="gm-kpi__label">{mark}{item["label"]}</div>'
            f'<div class="gm-kpi__value">{item["value"]}</div>{note}</div>'
        )
    st.markdown(f'<div class="gm-kpi-row">{"".join(tiles)}</div>', unsafe_allow_html=True)


def pill(text: str, tone: str = "mute", icon_name: str = "") -> str:
    mark = icon(icon_name, 13) if icon_name else ""
    return f'<span class="gm-pill gm-pill--{tone}">{mark}{text}</span>'


def action_card(body: str, tone: str = "info", icon_name: str = "alert") -> None:
    """A thing the team should do, not a statistic to admire."""
    colour = {"warn": BRAND["amber"], "bad": BRAND["red"], "info": BRAND["indigo"]}.get(tone, BRAND["indigo"])
    st.markdown(
        f'<div class="gm-action gm-action--{tone}">{icon(icon_name, 16, colour)}'
        f'<div class="gm-action__body">{body}</div></div>',
        unsafe_allow_html=True,
    )


def bar(fraction: float) -> None:
    pct = max(0.0, min(1.0, fraction)) * 100
    st.markdown(
        f'<div class="gm-bar"><div class="gm-bar__fill" style="width:{pct:.0f}%"></div></div>',
        unsafe_allow_html=True,
    )


_copy_seq = count()


def copy_block(text: str, key: str | None = None) -> None:
    """Show copy-ready text.

    Deliberately NOT st.code: with wrap_lines=True Streamlit 1.60 wraps the text but does not
    recompute each line's height, so long paragraphs paint on top of each other (measured 15
    overlapping lines on one proposal). Reproduced with all custom CSS removed, so it is the
    widget, not our theme.

    A read-only text_area wraps correctly, preserves the text byte-for-byte for pasting, and
    supports select-all + copy. Height is estimated from content so there is no inner scroll
    for normal-length copy.
    """
    body = text or ""
    # Measured in-browser rather than guessed: in the narrowest place these appear (a 2/3
    # column beside the image) the textarea fits ~60 chars per row at 23.55px line-height
    # with 24px vertical padding. Using 56 chars per row keeps a margin for wider glyphs so
    # nothing clips; wider columns simply get a little slack at the bottom.
    rows = sum(max(1, -(-len(line) // 56)) for line in body.split("\n")) or 1
    height = max(90, min(1400, round(24 * rows) + 30))
    st.text_area(
        "copy",
        value=body,
        height=height,
        key=key or f"copy_{next(_copy_seq)}",
        label_visibility="collapsed",
        disabled=True,
    )


def sanitize_text(text: str) -> str:
    """Strip scraper noise and cap payload size before it reaches the model."""
    cleaned = re.sub(r"(Facebook\s*)+", "Facebook ", text)
    cleaned = re.sub(r"\n\s*\n", "\n", cleaned)
    return cleaned[:4000].strip()


def render_proof_banner(proof_used: str, valid_ids: set[str]) -> None:
    """Whether the copy is grounded in an approved case study. Red means do not send."""
    proof = proof_used or "unknown"
    if proof in valid_ids:
        st.markdown(
            pill(f"Grounded in approved proof: {proof}", "good", "check"), unsafe_allow_html=True
        )
    elif proof in ("none", "market_math"):
        st.markdown(
            pill(f"No case study cited ({proof})", "info", "info"), unsafe_allow_html=True
        )
    else:
        st.error(
            f"Cited `{proof}`, which is not an approved case study. Treat this as invented "
            "and do not send it."
        )


def render_quality_warnings(responses: dict, proof_used: str | None = None) -> None:
    """Anything that survived the repair pass, so nobody sends generic or invented copy."""
    fields = repairable_fields(responses)

    fabrications = find_fabrications(fields, proof_used)
    if fabrications:
        st.error(
            "**Do not send.** This copy invents something: "
            + "; ".join(fabrications)
            + ". Delete the invented claim or regenerate."
        )

    problems = find_violations(fields)
    if problems:
        st.warning("Worth editing before sending: " + "; ".join(problems))
