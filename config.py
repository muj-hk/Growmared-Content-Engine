"""
One place that knows how to find a secret.

Locally secrets come from .env; on Streamlit Cloud there is no .env and they come from
st.secrets. Every module needs both paths, and having each one reimplement the lookup is how
the Supabase config silently went missing on the first deploy while auth and the LLM worked.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


def get_secret(name: str, default: str = "") -> str:
    """Environment first (local .env, container env vars), then Streamlit secrets.

    Streamlit is imported lazily so this module stays usable from plain scripts and tests.
    """
    value = os.getenv(name)
    if not value:
        try:
            import streamlit as st

            value = st.secrets[name]
        except Exception:
            value = None
    return (str(value) if value else default).strip()
