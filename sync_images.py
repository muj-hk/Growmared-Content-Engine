"""
Push a folder of post images into the Content tool.

The scheduled chat writes the post text straight into Supabase but cannot host an image, so
the pictures land in a folder instead. This uploads them to Supabase Storage and attaches
each one to the right post, so the team never has to do it by hand.

Usage:
    python sync_images.py "C:\\path\\to\\images"          # dry run, shows the plan
    python sync_images.py "C:\\path\\to\\images" --apply  # actually upload

Matching, in order:
  1. A date in the filename (2026-07-29, 20260729, 29-07-2026) matches the post with that
     scheduled_date.
  2. Anything left over is paired oldest-file to oldest-post, for posts still missing an
     image.

Posts that already have an image are never touched, so re-running is safe.
"""

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

import db

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

DATE_PATTERNS = [
    (re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})"), (0, 1, 2)),  # 2026-07-29
    (re.compile(r"(20\d{2})(\d{2})(\d{2})"), (0, 1, 2)),          # 20260729
    (re.compile(r"(\d{2})[-_](\d{2})[-_](20\d{2})"), (2, 1, 0)),  # 29-07-2026
]


def date_from_name(name: str) -> date | None:
    for pattern, (y, m, d) in DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        parts = match.groups()
        try:
            return datetime(int(parts[y]), int(parts[m]), int(parts[d])).date()
        except ValueError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach a folder of images to Content posts.")
    parser.add_argument("folder", help="Folder containing the post images")
    parser.add_argument("--apply", action="store_true", help="Actually upload (default is a dry run)")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Not a folder: {folder}")
        return 1

    if not db.is_configured():
        print("Supabase is not configured. Check SUPABASE_URL / SUPABASE_KEY in .env.")
        return 1

    images = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda p: p.stat().st_mtime,
    )
    if not images:
        print(f"No images found in {folder}")
        return 0

    posts = db.list_content(limit=200, include_archived=False)
    needy = [p for p in posts if not (p.get("image_url") or "").strip()]
    needy.sort(key=lambda p: p.get("scheduled_date") or p.get("created_at") or "")

    print(f"{len(images)} image(s) in folder, {len(needy)} post(s) missing an image.\n")
    if not needy:
        print("Every post already has an image. Nothing to do.")
        return 0

    by_date = {}
    for post in needy:
        if post.get("scheduled_date"):
            by_date.setdefault(post["scheduled_date"], post)

    plan: list[tuple[Path, dict, str]] = []
    claimed_posts: set[str] = set()
    leftovers: list[Path] = []

    for image in images:
        found = date_from_name(image.name)
        post = by_date.get(found.isoformat()) if found else None
        if post and post["id"] not in claimed_posts:
            claimed_posts.add(post["id"])
            plan.append((image, post, "date in filename"))
        else:
            leftovers.append(image)

    remaining = [p for p in needy if p["id"] not in claimed_posts]
    for image, post in zip(leftovers, remaining):
        claimed_posts.add(post["id"])
        plan.append((image, post, "oldest-first pairing"))

    unmatched = leftovers[len(remaining):] if len(leftovers) > len(remaining) else []

    for image, post, why in plan:
        print(f"  {image.name}")
        print(f"    -> {post.get('title') or '(untitled)'}  [{post.get('scheduled_date')}]  ({why})")
    for image in unmatched:
        print(f"  {image.name}\n    -> SKIPPED, no post left needing an image")

    if not args.apply:
        print(f"\nDry run. Re-run with --apply to upload {len(plan)} image(s).")
        return 0

    print()
    failures = 0
    for image, post, _ in plan:
        try:
            url = db.upload_content_image(
                post["id"], image.name, image.read_bytes(),
                MIME.get(image.suffix.lower(), "image/png"),
            )
            db.update_content(post["id"], image_url=url)
            print(f"  attached {image.name} -> {post.get('title')}")
        except Exception as exc:
            failures += 1
            print(f"  FAILED {image.name}: {type(exc).__name__}: {str(exc)[:160]}")

    print(f"\n{len(plan) - failures} attached, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
