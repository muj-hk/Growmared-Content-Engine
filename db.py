"""
Supabase persistence for the engine.

Project: "Growmated Engine" (ref rkhcbvssmfxoajqvsqma).

Table ownership is deliberately split so the two tools never collide:
  Prospecting -> public.pipeline (the prospect) + public.outreach_log (each generated message)
  Content     -> public.content_calendar (posts from the scheduled Claude chat)

Every function degrades gracefully: if Supabase is unreachable or unconfigured, the caller gets
an explicit failure it can surface, and the tool keeps working in session-only mode.
"""

from datetime import date, timedelta
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
    "answer": "Public Answer",
    "reply": "Thread Reply",
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

_PLACEHOLDER_NAMES = {
    "", "unknown", "n/a", "na", "none", "null", "prospect", "not specified",
    # Group posts are often anonymised; "Anonymous member" is not a name anyone can search.
    "anonymous", "anonymous member", "anonymous participant", "a member", "member",
    "facebook user", "linkedin member", "group member",
}


def _label_for(extracted: dict, raw_input: str) -> str:
    """A row nobody can identify is useless in a 139-row pipeline.

    Falls back through company -> person -> a SHORT description of what they want. Earlier
    this pasted the whole intent sentence in, producing names like "Wants to know how to wire
    GoHighLevel and Housecall Pro together without duplicate records, and whic" — truncated
    mid-word and impossible to scan.
    """
    for candidate in (extracted.get("company"), extracted.get("name")):
        text = str(candidate or "").strip()
        if text and text.lower() not in _PLACEHOLDER_NAMES:
            return text[:120]

    # No usable name: build a short topic label instead of a truncated sentence.
    topic = str(extracted.get("intent") or "").strip() or str(raw_input or "").strip()
    topic = " ".join(topic.split())
    if not topic:
        return "Unknown"

    if len(topic) > 58:
        # Cut at the last word boundary so it never ends mid-word.
        topic = topic[:58].rsplit(" ", 1)[0].rstrip(",.;:") + "…"

    industry = str(extracted.get("industry") or "").strip()
    return f"{industry}: {topic}" if industry and industry.lower() not in _PLACEHOLDER_NAMES else topic


def _find_existing(client, row: dict) -> str | None:
    """The id of an existing prospect this one is a repeat of, or None."""
    from datetime import datetime, timedelta, timezone

    email = (row.get("email") or "").strip()
    if email:
        hit = client.table("pipeline").select("id").eq("email", email).limit(1).execute()
        if hit.data:
            return hit.data[0]["id"]

    name = (row.get("business_name") or "").strip()
    if not name or name == "Unknown":
        return None

    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    hit = (
        client.table("pipeline").select("id")
        .eq("business_name", name).eq("source", row.get("source"))
        .gte("created_at", cutoff).limit(1).execute()
    )
    return hit.data[0]["id"] if hit.data else None


def save_prospect(extracted: dict, responses: dict, raw_input: str, mode: str,
                  source: str = "manual", intent: str | None = None) -> str:
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
        # Keep the evidence. Without the original text nobody can check whether a draft is
        # fair, re-run it, or answer "what did they actually say?" a week later.
        "raw_input": (raw_input or "").strip() or None,
        "intent_type": intent,
        # These columns existed but were never populated, so every date field stayed empty.
        "country_city": (extracted.get("location") or "").strip() or None,
        "found_in": (extracted.get("found_in") or "").strip() or None,
        "post_url": (extracted.get("post_url") or "").strip() or None,
    }
    # Same lead pasted twice should not become two rows. Match on email when we have one
    # (the strongest signal), otherwise on the same name from the same source in the last
    # 14 days. Reusing the row keeps every draft for that prospect in one place.
    existing_id = _find_existing(client, pipeline_row)
    if existing_id:
        pipeline_id = existing_id
        # Fill in anything we now know that was blank before, without clobbering good data
        # or resetting a status the team has already moved on.
        patch = {
            key: value for key, value in pipeline_row.items()
            if value and key in ("email", "industry", "owner_name", "notes", "raw_input",
                                 "intent_type", "country_city", "found_in", "post_url")
        }
        if patch:
            client.table("pipeline").update(patch).eq("id", pipeline_id).execute()
    else:
        inserted = client.table("pipeline").insert(pipeline_row).execute()
        pipeline_id = inserted.data[0]["id"]

    # One row per channel actually produced, so the log mirrors what the team can send.
    # Intent routing means some of these are legitimately empty and get filtered below.
    if mode == "upwork":
        channels = [("proposal", responses.get("proposal"))]
    else:
        channels = [
            ("comment", responses.get("comment")),
            ("dm", responses.get("dm")),
            ("email", responses.get("email_body")),
            ("answer", responses.get("answer")),
            ("reply", responses.get("reply")),
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
            "subject": (responses.get("email_subject") or None) if key == "email" else None,
            "template_id": intent or None,  # what the input was classified as
            "objection_category": (
                responses.get("objection_category")
                if responses.get("objection_category") not in (None, "", "none") else None
            ),
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
        # An explicit column list silently drops anything added later: raw_input, found_in
        # and post_url were all invisible to every caller of this function, which made the
        # stored posts look like they had never been saved at all.
        .select("*")
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


# Follow-up cadence from the cold-outreach doc: FU1 day +3, FU2 day +7, FU3 day +12,
# all relative to the OPENING send. touch_number 1 is the opener.
FOLLOWUP_OFFSETS = {2: 3, 3: 7, 4: 12}

# A sequence stops the moment any of these is true. Sending FU3 to someone who already
# replied or bounced is how you burn a domain and look like a robot.
STOP_STATUSES = {"Bounced", "Not Interested", "Call completed", "Negotiating"}


def email_queue(prospects_rows: list[dict] | None = None,
                log_rows: list[dict] | None = None) -> dict:
    """Everything the team needs to work the cold-email queue, computed fresh.

    Returns {"send_now": [...], "scheduled": [...], "awaiting": [...], "stopped": int}.
    Each entry is {prospect, message, due_note}. An item lands in send_now when it is an
    unsent opener, or an unsent follow-up whose offset has elapsed since the opener went out
    and nobody has replied.
    """
    from datetime import datetime, timezone

    if prospects_rows is None or log_rows is None:
        client = get_client()
        prospects_rows = client.table("pipeline").select("*").execute().data or []
        log_rows = (
            client.table("outreach_log").select("*")
            .eq("channel", "Email").order("created_at").execute().data or []
        )
    prospects = {p["id"]: p for p in prospects_rows}
    rows = [r for r in log_rows if r.get("channel") == "Email"]

    by_prospect: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("pipeline_id"):
            by_prospect.setdefault(row["pipeline_id"], []).append(row)

    now = datetime.now(timezone.utc)
    send_now, scheduled, awaiting = [], [], []
    stopped = 0

    for pid, msgs in by_prospect.items():
        prospect = prospects.get(pid)
        if not prospect:
            continue
        if (prospect.get("outreach_status") or "") in STOP_STATUSES or any(m.get("replied") for m in msgs):
            stopped += 1
            continue

        msgs.sort(key=lambda m: m.get("touch_number") or 1)
        opener = next((m for m in msgs if (m.get("touch_number") or 1) == 1), None)

        for msg in msgs:
            touch = msg.get("touch_number") or 1
            if msg.get("sent_at"):
                if msg.get("replied") is None:
                    awaiting.append({"prospect": prospect, "message": msg,
                                     "due_note": f"touch {touch} sent {msg['sent_at'][:10]}"})
                continue

            if touch == 1:
                send_now.append({"prospect": prospect, "message": msg, "due_note": "opener, ready"})
                continue

            # A follow-up only exists relative to a sent opener.
            if not (opener and opener.get("sent_at")):
                scheduled.append({"prospect": prospect, "message": msg,
                                  "due_note": f"waits for the opener (day +{FOLLOWUP_OFFSETS.get(touch, '?')})"})
                continue

            opened = datetime.fromisoformat(opener["sent_at"].replace("Z", "+00:00"))
            days_since = (now - opened).days
            offset = FOLLOWUP_OFFSETS.get(touch, 99)
            if days_since >= offset:
                send_now.append({"prospect": prospect, "message": msg,
                                 "due_note": f"FU{touch - 1} due (day +{offset}, opener {days_since}d ago)"})
            else:
                scheduled.append({"prospect": prospect, "message": msg,
                                  "due_note": f"FU{touch - 1} due in {offset - days_since}d"})

    return {"send_now": send_now, "scheduled": scheduled, "awaiting": awaiting, "stopped": stopped}


def mark_bundle_sent(pipeline_id: str) -> None:
    """The team sends social copy the moment it is generated, so generated == sent for
    comment/DM/answer/reply/proposal rows. Cold Email rows stay drafts: their sequence is
    timed and worked from the Emails queue."""
    client = get_client()
    rows = (client.table("outreach_log").select("id")
            .eq("pipeline_id", pipeline_id).eq("direction", "draft")
            .neq("channel", "Email").execute().data or [])
    for row in rows:
        mark_message_sent(row["id"])


def revise_message(pipeline_id: str, channel_label: str, new_content: str) -> None:
    """Team-requested revision UPDATES the existing row in place - never a duplicate."""
    client = get_client()
    row = (client.table("outreach_log").select("id")
           .eq("pipeline_id", pipeline_id).eq("channel", channel_label)
           .order("created_at", desc=True).limit(1).execute().data)
    if row:
        client.table("outreach_log").update(
            {"content": new_content, "word_count": len(new_content.split())}
        ).eq("id", row[0]["id"]).execute()


def mark_bounced(pipeline_id: str) -> None:
    """Bounce kills the whole sequence, not just one message."""
    update_prospect_status(pipeline_id, "Bounced")


# Marking a message sent should move the prospect's status without anyone remembering to.
# Nothing here ever downgrades a status the team has already advanced past.
CHANNEL_STATUS = {
    "Facebook Comment": "Comment + DM sent",
    "Facebook DM": "Messaged",
    "LinkedIn": "Messaged",
    "Email": "Email sent",
    "Upwork Proposal": "Proposal sent",
    "Public Answer": "Messaged",
    "Thread Reply": "Messaged",
}
# Ordered weakest to strongest; a later status is never replaced by an earlier one.
_STATUS_RANK = {name: i for i, name in enumerate(OUTREACH_STATUSES)}


def mark_message_sent(log_id: str, auto_status: bool = True) -> None:
    """The draft actually went out. Stamps sent_at, which starts the days_to_reply clock,
    and advances the prospect's status so the pipeline reflects reality on its own."""
    from datetime import datetime, timezone

    client = get_client()
    client.table("outreach_log").update(
        {"direction": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", log_id).execute()

    if not auto_status:
        return

    row = (
        client.table("outreach_log")
        .select("pipeline_id, channel, touch_number").eq("id", log_id).execute()
    )
    if not row.data or not row.data[0].get("pipeline_id"):
        return
    msg_row = row.data[0]
    pipeline_id = msg_row["pipeline_id"]
    target = CHANNEL_STATUS.get(msg_row.get("channel") or "")
    if not target:
        return

    current = (
        client.table("pipeline")
        .select("outreach_status, date_first_contacted")
        .eq("id", pipeline_id).execute()
    )
    row_now = current.data[0] if current.data else {}
    now_status = row_now.get("outreach_status") or "Not Contacted"

    # Keep the date columns current without anyone typing a date. touch_number tells us
    # whether this was the first contact or a follow-up.
    touch = msg_row.get("touch_number") or 1
    today = date.today().isoformat()
    patch: dict = {}
    if _STATUS_RANK.get(target, 0) > _STATUS_RANK.get(now_status, 0):
        patch["outreach_status"] = target
    if not row_now.get("date_first_contacted"):
        patch["date_first_contacted"] = today
    if touch > 1:
        patch["last_follow_up_date"] = today
    # Next follow-up is scheduled from the cadence, so the pipeline shows what is coming.
    next_offset = FOLLOWUP_OFFSETS.get(touch + 1)
    if next_offset:
        first = row_now.get("date_first_contacted") or today
        patch["next_follow_up_date"] = (
            date.fromisoformat(first) + timedelta(days=next_offset)
        ).isoformat()

    if patch:
        client.table("pipeline").update(patch).eq("id", pipeline_id).execute()


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
