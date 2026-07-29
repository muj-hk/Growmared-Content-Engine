"""
One place that knows how to find a secret.

Locally secrets come from this project's .env; on Streamlit Cloud there is no .env and they
come from st.secrets. Every module needs both paths, and having each one reimplement the
lookup is how the Supabase config silently went missing on the first deploy.

Precedence is deliberate and load-bearing:

  1. This project's .env, captured into a dict AT IMPORT TIME.
  2. Real process environment.
  3. st.secrets.

Step 1 exists because Streamlit merges the machine-wide ~/.streamlit/secrets.toml into every
app and injects its values into os.environ the first time st.secrets is read. A stale global
file was overwriting SUPABASE_KEY with a dead project's JWT, producing "Invalid API key" 401s
that appeared only after `import llm`. Reading .env into our own dict makes this project
immune to anything that mutates os.environ later.
"""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

_ENV_FILE = Path(__file__).with_name(".env")

# Snapshot taken before anything else can touch the environment.
_PROJECT_ENV = {key: value for key, value in dotenv_values(_ENV_FILE).items() if value}

# Still populate os.environ, since third-party libraries read it directly.
load_dotenv(_ENV_FILE)


def get_secret(name: str, default: str = "") -> str:
    """Project .env first, then the real environment, then Streamlit secrets."""
    local = _PROJECT_ENV.get(name)
    if local:
        return local.strip()

    value = os.getenv(name)
    if value:
        return value.strip()

    try:
        import streamlit as st

        value = st.secrets[name]
    except Exception:
        value = None
    return (str(value) if value else default).strip()
