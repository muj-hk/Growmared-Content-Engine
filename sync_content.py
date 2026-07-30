"""
Import the daily social posts the Cowork chat writes to disk.

The chat reliably writes `Social Posts/posts/<date>.json` plus the images every morning, but
its Supabase insert has not been landing, so the Content tab stayed empty while the work sat
finished on disk. This reads those files directly, which removes the chat's database access
from the critical path entirely: if the file exists, the post reaches the team.

Usage:
    python sync_content.py                      # dry run, last 7 days
    python sync_content.py --apply              # import them
    python sync_content.py --apply --days 30    # backfill further
    python sync_content.py --apply --date 2026-07-30

Safe to re-run: a date already in the calendar is skipped, and images already attached are
left alone.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import db

POSTS_DIR = Path(
    r"C:\Users\hp\OneDrive\Documents\Claude\Projects\Growmated\Social Posts"
)
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif"}

# The chat writes lowercase platform keys; the tool stores canonical names.
PLATFORM_KEYS = {"linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram"}


def load_day(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! {path.name}: unreadable ({type(exc).__name__})")
        return None


def build_variants(payload: dict) -> dict:
    """Turn the chat's per-platform blocks into the tool's variants shape."""
    variants: dict[str, dict] = {}
    for raw_key, canonical in PLATFORM_KEYS.items():
        block = payload.get(raw_key)
        if not isinstance(block, dict):
            continue
        body = (block.get("body") or "").strip()
        if not body:
            continue
        tags = block.get("hashtags") or []
        if isinstance(tags, list):
            tags = " ".join(tags)
        # The chat sometimes leaves hashtags inline in the body; the tool joins them at copy
        # time, so strip a trailing hashtag line to avoid printing them twice.
        lines = body.split("\n")
        if lines and lines[-1].strip().startswith("#"):
            if not tags:
                tags = lines[-1].strip()
            body = "\n".join(lines[:-1]).rstrip()
        variants[canonical] = {"copy": body, "tags": (tags or "").strip()}
    return variants


def title_for(payload: dict) -> str:
    topic = (payload.get("topic") or "").strip()
    if topic:
        return topic[:70].rsplit(" ", 1)[0] if len(topic) > 70 else topic
    return f"Post {payload.get('date') or ''}".strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually import (default: dry run)")
    parser.add_argument("--days", type=int, default=7, help="How many days back to consider")
    parser.add_argument("--date", help="Import one specific YYYY-MM-DD")
    args = parser.parse_args()

    if not db.is_configured():
        print("Supabase is not configured. Check SUPABASE_URL / SUPABASE_KEY in .env.")
        return 1

    posts_dir = POSTS_DIR / "posts"
    if not posts_dir.is_dir():
        print(f"No posts folder at {posts_dir}")
        return 1

    if args.date:
        wanted = [args.date]
    else:
        today = date.today()
        wanted = [(today - timedelta(days=n)).isoformat() for n in range(args.days)]

    existing = {
        p.get("scheduled_date") for p in db.list_content(limit=500, include_archived=True)
    }

    plan = []
    for day in sorted(wanted):
        path = posts_dir / f"{day}.json"
        if not path.exists():
            continue
        if day in existing:
            print(f"  = {day} already in the calendar, skipping")
            continue
        payload = load_day(path)
        if not payload:
            continue
        variants = build_variants(payload)
        if not variants:
            print(f"  ! {day} has no usable platform copy, skipping")
            continue
        plan.append((day, payload, variants))

    if not plan:
        print("\nNothing new to import.")
        return 0

    print(f"\n{len(plan)} post(s) to import:")
    for day, payload, variants in plan:
        counts = ", ".join(f"{k} {len(v['copy'])}ch" for k, v in variants.items())
        print(f"  {day}  {title_for(payload)}")
        print(f"      {counts}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to import.")
        return 0

    print()
    failures = 0
    for day, payload, variants in plan:
        try:
            platforms = " + ".join(variants)
            content_id = db.save_content(
                title=title_for(payload),
                content=(variants.get("LinkedIn") or next(iter(variants.values())))["copy"],
                platform=platforms,
                status="Draft",
                scheduled_date=day,
                target_audience=(payload.get("research_signal") or "")[:200] or None,
                notes=" · ".join(filter(None, [
                    payload.get("pillar_name"), payload.get("hook_type")])) or None,
                variants=variants,
            )

            # Attach each platform's image from the paths in the same file.
            for raw_key, canonical in PLATFORM_KEYS.items():
                rel = (payload.get("images") or {}).get(raw_key)
                if not rel or canonical not in variants:
                    continue
                img = POSTS_DIR / rel
                if not img.exists():
                    print(f"      ! image missing for {canonical}: {rel}")
                    continue
                url = db.upload_content_image(
                    content_id, img.name, img.read_bytes(),
                    MIME.get(img.suffix.lower(), "image/png"), platform=canonical)
                db.set_variant_image(content_id, canonical, url)

            print(f"  imported {day}  {title_for(payload)}")
        except Exception as exc:
            failures += 1
            print(f"  FAILED {day}: {type(exc).__name__}: {str(exc)[:200]}")

    print(f"\n{len(plan) - failures} imported, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
