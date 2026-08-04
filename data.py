"""
One load of everything, shared by every tab.

Streamlit renders ALL tabs on every rerun, so six tabs each querying Supabase would mean six
round trips per click. This fetches once, caches briefly, and hands the same snapshot to each
view. Any write calls `refresh()` so the next render sees the change immediately.
"""

from dataclasses import dataclass, field

import streamlit as st

import db

CACHE_SECONDS = 20


@dataclass
class Snapshot:
    prospects: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    posts: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def messages_for(self, pipeline_id: str) -> list[dict]:
        return sorted(
            (m for m in self.messages if m.get("pipeline_id") == pipeline_id),
            key=lambda m: (m.get("touch_number") or 1, m.get("created_at") or ""),
        )

    @property
    def unsent(self) -> list[dict]:
        # Inbound replies (direction="received", written by the Netlify app into this shared
        # table) have no sent_at. Without this filter they count as drafts waiting to go out.
        return [m for m in self.messages
                if not m.get("sent_at") and m.get("direction") != "received"]

    @property
    def awaiting(self) -> list[dict]:
        return [m for m in self.messages if m.get("sent_at") and m.get("replied") is None]

    @property
    def replied(self) -> list[dict]:
        return [m for m in self.messages if m.get("replied")]


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _fetch() -> dict:
    client = db.get_client()
    return {
        "prospects": client.table("pipeline").select("*")
        .order("created_at", desc=True).execute().data or [],
        "messages": client.table("outreach_log").select("*").execute().data or [],
        "posts": client.table("content_calendar").select("*")
        .order("created_at", desc=True).execute().data or [],
    }


def load() -> Snapshot:
    if not db.is_configured():
        return Snapshot(error="Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY.")
    try:
        raw = _fetch()
    except Exception as exc:
        return Snapshot(error=f"{type(exc).__name__}: {str(exc)[:200]}")
    return Snapshot(prospects=raw["prospects"], messages=raw["messages"], posts=raw["posts"])


def refresh() -> None:
    """Call after any write so the next render reflects it rather than serving stale cache."""
    _fetch.clear()
