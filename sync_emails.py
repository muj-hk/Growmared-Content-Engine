"""
Import the cold-email CSV the "Growmated x Prospecting" chat already produces.

That chat runs in the cloud and delivers `GROWMATED_<date>.csv` as a file rather than writing
to disk or the database, so nothing has been reaching the Emails queue. Its CSV columns are
already fixed by its own instructions, so no change to that chat is required: download the
file, drop it in the inbox folder, run this.

Usage:
    python sync_emails.py                     # dry run on the inbox folder
    python sync_emails.py --apply
    python sync_emails.py path\\to\\file.csv --apply

Expected columns (extras ignored, missing ones tolerated):
    business_name, city, website, phone, email, angle, gap_summary,
    opening_subject, opening_body, followup_1, followup_2, followup_3, notes

Each row becomes one prospect plus up to four touches (opener + FU1/2/3) with the cadence the
Emails tab enforces. Re-running is safe: a prospect that already has email drafts is skipped.
"""

import argparse
import csv
import sys
from pathlib import Path

import db

INBOX = Path(
    r"C:\Users\hp\OneDrive\Documents\Claude\Projects\Growmated\Social Posts\email-inbox"
)


def clean(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def read_rows(path: Path) -> list[dict]:
    # utf-8-sig: exported CSVs routinely carry a BOM, which otherwise corrupts the first header.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle)]


def import_row(row: dict, source: str, dry: bool) -> str:
    email = clean(row.get("email"))
    business = clean(row.get("business_name")) or clean(row.get("company")) or "Unknown"
    if not email:
        return f"skip (no email): {business}"

    client = db.get_client()
    existing = client.table("pipeline").select("id").eq("email", email).limit(1).execute()
    pipeline_id = existing.data[0]["id"] if existing.data else None

    if pipeline_id:
        already = (
            client.table("outreach_log").select("id")
            .eq("pipeline_id", pipeline_id).eq("channel", "Email").limit(1).execute()
        )
        if already.data:
            return f"skip (already queued): {business}"

    touches = [
        (1, clean(row.get("opening_subject")), (row.get("opening_body") or "").strip()),
        (2, None, (row.get("followup_1") or "").strip()),
        (3, None, (row.get("followup_2") or "").strip()),
        (4, None, (row.get("followup_3") or "").strip()),
    ]
    touches = [t for t in touches if t[2]]
    if not touches:
        return f"skip (no copy): {business}"

    if dry:
        return f"would import {business} <{email}> with {len(touches)} touch(es)"

    if not pipeline_id:
        inserted = client.table("pipeline").insert({
            "business_name": business,
            "email": email,
            "country_city": clean(row.get("city")) or None,
            "source": source,
            "outreach_status": "Not Contacted",
            "notes": clean(row.get("gap_summary")) or None,
            "intent_type": "cold_email",
        }).execute()
        pipeline_id = inserted.data[0]["id"]

    client.table("outreach_log").insert([
        {
            "pipeline_id": pipeline_id,
            "contact_name": business,
            "channel": "Email",
            "direction": "draft",
            "touch_number": touch,
            "subject": subject,
            "content": body,
            "angle": clean(row.get("angle")) or None,
            "opener_type": "observation",
            "cta_type": "situational-question" if touch == 1 else "other",
            "word_count": len(body.split()),
        }
        for touch, subject, body in touches
    ]).execute()

    return f"imported {business} <{email}> with {len(touches)} touch(es)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", help="A CSV file, or omit to scan the inbox folder")
    parser.add_argument("--apply", action="store_true", help="Actually import (default: dry run)")
    parser.add_argument("--source", default="Cold Email", help="pipeline.source value")
    args = parser.parse_args()

    if not db.is_configured():
        print("Supabase is not configured. Check SUPABASE_URL / SUPABASE_KEY in .env.")
        return 1

    if args.path:
        files = [Path(args.path)]
    else:
        INBOX.mkdir(parents=True, exist_ok=True)
        files = sorted(INBOX.glob("*.csv"))
        if not files:
            print(f"No CSVs in {INBOX}")
            print("Download GROWMATED_<date>.csv from the prospecting chat, drop it there, "
                  "and run this again.")
            return 0

    total = 0
    for path in files:
        if not path.exists():
            print(f"Not found: {path}")
            return 1
        rows = read_rows(path)
        print(f"\n{path.name}: {len(rows)} row(s)")
        for row in rows:
            try:
                print("  " + import_row(row, args.source, dry=not args.apply))
                total += 1
            except Exception as exc:
                print(f"  FAILED {clean(row.get('business_name'))}: "
                      f"{type(exc).__name__}: {str(exc)[:160]}")

    if not args.apply:
        print(f"\nDry run over {total} row(s). Re-run with --apply to import.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
