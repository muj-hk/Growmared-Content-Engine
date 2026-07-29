"""
Supabase persistence for the engine.

Project: "Growmated Engine" (ref rkhcbvssmfxoajqvsqma).

Table ownership is deliberately split so the two tools never collide:
  Prospecting -> public.pipeline (the prospect) + public.outreach_log (each generated message)
  Content     -> public.content_calendar (posts from the scheduled Claude chat)

Every function degrades gracefully: if Supabase is unreachable or unconfigured, the caller gets
an explicit failure it can surface, and the tool keeps working in session-only mode.
"""

from datetime import date
from pathlib import Path

from config import get_secret


# Read lazily rather than at import time: on Streamlit Cloud the secrets store is not
# guaranteed to be populated the moment this module is first imported.
def supabase_url() -> str:
    return get_secret("SUPABASE_URL")


def supabase_key() -> str:
    return get_secret("SUPABASE_KEY")


class DBUnavailable(RuntimeError):
    """Supabase is not configured or not reachable."""


# Vocabularies taken from the values already present in the live tables, so the tool writes
# data consistent with the 134 prospects that are already there rather than inventing new labels.
OUTREACH_STATUSES = [
    "Not Contacted",
    "Comment + DM sent",
    "Messaged",
    "Email sent",
    "Proposal sent",
    "Loom sent — awaiting reply",
    "Call completed",
    "Negotiating",
    "Not Interested",
    "Bounced",
]

SOURCES = [
    "Facebook Post",
    "Facebook Group",
    "LinkedIn",
    "Upwork",
    "Google Maps",
    "Cold Email",
    "Cold Outreach",
]

# outreach_log.channel values already in use, plus Upwork for the new proposal mode.
CHANNEL_LABELS = {
    "comment": "Facebook Comment",
    "dm": "Facebook DM",
    "email": "Email",
    "proposal": "Upwork Proposal",
}


def is_configured() -> bool:
    return bool(supabase_url() and supabase_key())


def get_client():
    if not is_configured():
        raise DBUnavailable(
            "SUPABASE_URL / SUPABASE_KEY are not set. Add them to .env locally, "
            "or to the app's secrets when deployed."
        )
    from supabase import create_client

    return create_client(supabase_url(), supabase_key())


# --------------------------------------------------------------------------------------
# Prospecting
# --------------------------------------------------------------------------------------

_PLACEHOLDER_NAMES = {"", "unknown", "n/a", "na", "none", "null", "prospect", "not specified"}


def _label_for(extracted: dict, raw_input: str) -> str:
    """A row nobody can identify is useless in a 134-row pipeline.

    Upwork postings often name no client, so fall back to what the job is actually about
    rather than writing another "Unknown".
    """
    for candidate in (extracted.get("company"), extracted.get("name")):
        if candidate and str(candidate).strip().lower() not in _PLACEHOLDER_NAMES:
            return str(candidate).strip()[:120]

    fallback = (extracted.get("intent") or raw_input or "").strip()
    return (fallback[:100] or "Unknown")


def save_prospect(extracted: dict, responses: dict, raw_input: str, mode: str, source: str = "manual") -> str:
    """Insert one pipeline row plus one outreach_log row per generated message. Returns pipeline id."""
    client = get_client()

    pipeline_row = {
        "business_name": _label_for(extracted, raw_input),
        "owner_name": extracted.get("name"),
        "email": extracted.get("email"),
        "industry": extracted.get("industry"),
        "source": source,
        # Nothing has actually been sent yet - these are drafts until the team marks them sent.
        "outreach_status": "Not Contacted",
        "notes": extracted.get("intent"),
    }
    inserted = client.table("pipeline").insert(pipeline_row).execute()
    pipeline_id = inserted.data[0]["id"]

    # One row per channel actually produced, so the log mirrors what the team can send.
    if mode == "upwork":
        channels = [("proposal", responses.get("proposal"))]
    else:
        channels = [
            ("comment", responses.get("comment")),
            ("dm", responses.get("dm")),
            ("email", responses.get("email_body")),
        ]

    # Learning-log fields, captured at draft time per the OUTREACH LEARNING LOG spec.
    # word_count is computed here, never trusted from the model.
    log_rows = [
        {
            "contact_name": extracted.get("name") or "Unknown",
            "channel": CHANNEL_LABELS.get(key, key),
            "direction": "draft",
            "content": content,
            "next_step": responses.get("opening_question") or None,
            "pipeline_id": pipeline_id,
            "opener_type": responses.get("opener_type") or None,
            "angle": responses.get("angle") or None,
            "cta_type": responses.get("cta_type") or None,
            "proof_used": responses.get("proof_used") or None,
            "word_count": len(str(content).split()),
            "touch_number": 1,
        }
        for key, content in channels
        if content and str(content).strip()
    ]
    if log_rows:
        client.table("outreach_log").insert(log_rows).execute()

    return pipeline_id


def list_prospects(limit: int = 50) -> list[dict]:
    client = get_client()
    result = (
        client.table("pipeline")
        .select("id, business_name, owner_name, email, industry, source, outreach_status, notes, created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def list_messages(pipeline_id: str) -> list[dict]:
    client = get_client()
    result = (
        client.table("outreach_log")
        .select("*")
        .eq("pipeline_id", pipeline_id)
        .order("created_at")
        .execute()
    )
    return result.data or []


# Learning-log vocabularies, verbatim from the founder's spec.
REPLY_QUALITIES = ["interested", "question", "brush-off", "hostile", "scam-probe"]
OBJECTION_CATEGORIES = ["price", "timing", "have-someone", "distrust", "other"]
FINAL_OUTCOMES = ["call_booked", "client", "dead"]


def mark_message_sent(log_id: str) -> None:
    """The draft actually went out. Stamps sent_at, which starts the days_to_reply clock."""
    from datetime import datetime, timezone

    client = get_client()
    client.table("outreach_log").update(
        {"direction": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", log_id).execute()


def record_outcome(log_id: str, replied: bool, reply_text: str = "",
                   reply_quality: str | None = None, objection_category: str | None = None,
                   final_outcome: str | None = None) -> None:
    """Log what happened, the moment it happens. reply_text is stored VERBATIM."""
    from datetime import datetime, timezone

    client = get_client()
    row = client.table("outreach_log").select("sent_at").eq("id", log_id).execute()
    sent_at = (row.data[0].get("sent_at") if row.data else None)

    days = None
    if replied and sent_at:
        sent = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        days = round((datetime.now(timezone.utc) - sent).total_seconds() / 86400, 1)

    client.table("outreach_log").update({
        "replied": replied,
        "days_to_reply": days,
        "reply_text": reply_text.strip() or None,
        "reply_quality": reply_quality,
        "objection_category": objection_category,
        "final_outcome": final_outcome,
    }).eq("id", log_id).execute()


def update_prospect_status(pipeline_id: str, status: str) -> None:
    client = get_client()
    client.table("pipeline").update({"outreach_status": status}).eq("id", pipeline_id).execute()


# --------------------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------------------

CONTENT_STATUSES = ["Draft", "Scheduled", "Posted", "Archived"]

# The platforms the scheduled Cowork chat writes copy for. Order drives tab order in the UI.
CONTENT_PLATFORMS = ["LinkedIn", "Facebook", "Instagram"]


def list_content(limit: int = 100, include_archived: bool = False) -> list[dict]:
    client = get_client()
    query = client.table("content_calendar").select("*")
    if not include_archived:
        query = query.neq("status", "Archived")
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data or []


def get_variants(post: dict) -> dict:
    """Per-platform copy/tags, falling back to the single `content` column for older rows."""
    variants = post.get("variants") or {}
    if isinstance(variants, str):
        import json

        try:
            variants = json.loads(variants)
        except ValueError:
            variants = {}

    if variants:
        return variants

    # Legacy row: one body, possibly aimed at several platforms via "Facebook + LinkedIn".
    body = post.get("content") or ""
    platform_field = post.get("platform") or ""
    targets = [p for p in CONTENT_PLATFORMS if p.lower() in platform_field.lower()] or ["Facebook"]
    return {p: {"copy": body, "tags": ""} for p in targets}


def save_content(title: str, content: str, platform: str, status: str = "Draft",
                 scheduled_date: str | None = None, target_audience: str | None = None,
                 notes: str | None = None, image_url: str | None = None,
                 variants: dict | None = None) -> str:
    client = get_client()
    row = {
        "title": title,
        "content": content,
        "platform": platform,
        "status": status,
        "scheduled_date": scheduled_date,
        "target_audience": target_audience,
        "notes": notes,
        "image_url": image_url,
        "variants": variants or {},
    }
    inserted = client.table("content_calendar").insert(row).execute()
    return inserted.data[0]["id"]


def update_content(content_id: str, **fields) -> None:
    """Update a subset of columns. None entries are ignored."""
    client = get_client()
    clean = {k: v for k, v in fields.items() if v is not None}
    if clean:
        client.table("content_calendar").update(clean).eq("id", content_id).execute()


def mark_posted(content_id: str) -> None:
    """One click for the team: published, timestamped, no manual metric entry."""
    from datetime import datetime, timezone

    client = get_client()
    client.table("content_calendar").update(
        {"status": "Posted", "posted_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", content_id).execute()


def delete_content(content_id: str) -> None:
    client = get_client()
    client.table("content_calendar").delete().eq("id", content_id).execute()


# --------------------------------------------------------------------------------------
# Image storage
# --------------------------------------------------------------------------------------

IMAGE_BUCKET = "content-images"


def set_variant_image(content_id: str, platform: str, url: str) -> None:
    """Attach an image to ONE platform's variant.

    The daily images are produced per platform (2026-07-29-linkedin.png,
    2026-07-29-facebook.png), so the image belongs next to that platform's copy rather than
    on the post as a whole. Reads-modifies-writes the jsonb so the other platforms survive.
    """
    client = get_client()
    current = client.table("content_calendar").select("variants").eq("id", content_id).execute()
    variants = (current.data[0].get("variants") if current.data else None) or {}
    if isinstance(variants, str):
        import json

        variants = json.loads(variants or "{}")

    entry = dict(variants.get(platform) or {})
    entry["image"] = url
    variants[platform] = entry

    client.table("content_calendar").update({"variants": variants}).eq("id", content_id).execute()


def upload_content_image(content_id: str, filename: str, data: bytes, content_type: str,
                         platform: str | None = None) -> str:
    """Put an image in Supabase Storage and return its public URL.

    The scheduled Cowork chat has no image host, so the picture has to get here somehow:
    either synced from the images folder or dropped in by hand. The bucket is public because
    LinkedIn, Facebook and Instagram have to fetch the image when the post goes out.
    """
    client = get_client()
    suffix = Path(filename).suffix.lower() or ".png"
    # Key by content row (and platform, when given) so re-uploading replaces rather than
    # accumulating orphans.
    key = f"{content_id}-{platform.lower()}{suffix}" if platform else f"{content_id}{suffix}"

    client.storage.from_(IMAGE_BUCKET).upload(
        path=key,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    public_url = client.storage.from_(IMAGE_BUCKET).get_public_url(key)
    # Supabase appends a trailing "?" on some client versions; it breaks nothing but is ugly.
    return public_url.rstrip("?")
