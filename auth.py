"""
Shared password gate for every page.

This app reads and writes a live database holding real prospects, clients, income and
expenses, so it must never be reachable without a password once it leaves localhost.

Fails CLOSED on purpose: if APP_PASSWORD is missing the app refuses to load rather than
serving an open door. A deploy where someone forgot to set the secret should be broken and
obvious, not silently public.
"""

import hmac

import streamlit as st

from config import get_secret

SESSION_KEY = "_growmated_authenticated"


def _expected_password() -> str:
    return get_secret("APP_PASSWORD")


def require_login() -> None:
    """Call at the top of every page, immediately after set_page_config."""
    if st.session_state.get(SESSION_KEY):
        return

    expected = _expected_password()
    if not expected:
        st.error(
            "**APP_PASSWORD is not set, so this app is refusing to start.**\n\n"
            "Add `APP_PASSWORD` to `.env` locally, or to the app's secrets when deployed. "
            "This is deliberate: the app writes to a live database and must never run "
            "without a password."
        )
        st.stop()

    from ui import render_brand

    render_brand(sidebar=False)
    st.subheader("Team access")
    st.caption("This tool reads and writes live client data. Sign in to continue.")

    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", use_container_width=True):
            # compare_digest avoids leaking length/content through timing.
            if hmac.compare_digest(entered.strip(), expected):
                st.session_state[SESSION_KEY] = True
                st.rerun()
            else:
                st.error("Incorrect password.")

    st.stop()


def render_sign_out() -> None:
    """Optional sidebar control, so a shared machine can be locked again."""
    if st.session_state.get(SESSION_KEY) and st.button("Sign out", use_container_width=True):
        st.session_state[SESSION_KEY] = False
        st.rerun()
