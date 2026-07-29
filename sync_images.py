"""
Push a folder of post images into the Content tool.

The scheduled chat writes the post text straight into Supabase but cannot host an image, so
the pictures land in a folder instead. This uploads them to Supabase Storage and attaches
each one to the right post, so the team never has to do it by hand.

Usage:
    python sync_images.py "C:\\path\\to\\images"          # dry run, shows the plan
    python sync_images.py "C:\\path\\to\\images" --apply  # actually upload

Filenames carry both the date and the platform, which is exactly what the tool needs:

    2026-07-29-linkedin.png   -> the LinkedIn variant of the 2026-07-29 post
    2026-07-29-facebook.png   -> the Facebook variant of the same post
    2026-07-29.png            -> used for every platform that has no specific image

The image is stored against that platform's variant, next to its copy and tags, because the
team posts one platform at a time.

Images whose date has no matching post are reported and skipped. Variants that already have
an image are left alone, so re-running is safe.
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


# Canonical platform names as stored in variants, keyed by what appears in filenames.
PLATFORM_ALIASES = {
    "linkedin": "LinkedIn",
    "li": "LinkedIn",
    "facebook": "Facebook",
    "fb": "Facebook",
    "instagram": "Instagram",
    "ig": "Instagram",
    "insta": "Instagram",
}


def platform_from_name(name: str) -> str | None:
    """Pull the platform out of e.g. 2026-07-29-b-linkedin.png. None means 'all platforms'."""
    stem = Path(name).stem.lower()
    for alias, canonical in PLATFORM_ALIASES.items():
        if re.search(rf"(^|[-_]){re.escape(alias)}([-_]|$)", stem):
            return canonical
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
    by_date = {p["scheduled_date"]: p for p in posts if p.get("scheduled_date")}

    print(f"{len(images)} image(s) in folder, {len(posts)} post(s) in the calendar.\n")

    plan: list[tuple[Path, dict, list[str]]] = []
    no_post: list[Path] = []
    already: list[str] = []

    for image in images:
        found = date_from_name(image.name)
        post = by_date.get(found.isoformat()) if found else None
        if not post:
            no_post.append(image)
            continue

        variants = db.get_variants(post)
        platform = platform_from_name(image.name)
        # A file with no platform in its name applies to every platform on that post.
        targets = [platform] if platform else list(variants)
        targets = [t for t in targets if t]

        pending = [t for t in targets if not ((variants.get(t) or {}).get("image") or "").strip()]
        for skipped in [t for t in targets if t not in pending]:
            already.append(f"{image.name} -> {skipped} (already has an image)")

        if pending:
            plan.append((image, post, pending))

    for image, post, targets in plan:
        print(f"  {image.name}")
        print(f"    -> {post.get('title') or '(untitled)'} [{post.get('scheduled_date')}] :: {', '.join(targets)}")
    for line in already:
        print(f"  {line}")
    if no_post:
        print(f"\n  {len(no_post)} image(s) skipped, no post in the calendar for that date:")
        for image in no_post[:10]:
            print(f"    {image.name}")
        if len(no_post) > 10:
            print(f"    ... and {len(no_post) - 10} more")

    if not plan:
        print("\nNothing to attach.")
        return 0

    if not args.apply:
        print(f"\nDry run. Re-run with --apply to upload {len(plan)} image(s).")
        return 0

    print()
    failures = 0
    for image, post, targets in plan:
        for platform in targets:
            try:
                url = db.upload_content_image(
                    post["id"], image.name, image.read_bytes(),
                    MIME.get(image.suffix.lower(), "image/png"), platform=platform,
                )
                db.set_variant_image(post["id"], platform, url)
                print(f"  attached {image.name} -> {post.get('title')} :: {platform}")
            except Exception as exc:
                failures += 1
                print(f"  FAILED {image.name} ({platform}): {type(exc).__name__}: {str(exc)[:160]}")

    print(f"\nDone. {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
