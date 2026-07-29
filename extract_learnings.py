"""
Monthly extraction per the OUTREACH LEARNING LOG spec. Run on the 1st:

    python extract_learnings.py            # report only
    python extract_learnings.py --apply    # also mark 30-day-silent messages dead

Re-answers the 8 hardening questions (voice, winners, losers, openers, length, CTA,
angles, objections) USING ONLY THE LOG. Deterministic stats are computed in code; the
model only narrates on top of them and is instructed that "No data yet" is a valid answer.
Patterns need 3+ occurrences to count. scam-probe replies are never counted as wins.
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone

import db
from context_builder import _obj, _STR  # reuse the schema helpers
from llm import MODEL, build_client, generate_json

MIN_PATTERN = 3  # per the spec: flag any pattern with 3+ occurrences
DEAD_AFTER_DAYS = 30

WIN_QUALITIES = {"interested", "question"}  # scam-probe/hostile/brush-off are not wins


def fetch_sent_messages() -> list[dict]:
    client = db.get_client()
    result = (
        client.table("outreach_log")
        .select("*")
        .not_.is_("sent_at", "null")
        .order("sent_at")
        .execute()
    )
    return result.data or []


def rate_by(messages: list[dict], key: str) -> list[str]:
    """Reply rate per attribute value, only for groups with MIN_PATTERN+ sends."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in messages:
        value = m.get(key)
        if value:
            groups[str(value)].append(m)

    lines = []
    for value, group in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(group) < MIN_PATTERN:
            continue
        wins = sum(1 for m in group if m.get("replied") and (m.get("reply_quality") in WIN_QUALITIES or not m.get("reply_quality")))
        scams = sum(1 for m in group if m.get("reply_quality") == "scam-probe")
        line = f"  {key}={value}: {len(group)} sent, {wins} real replies ({wins/len(group):.0%})"
        if scams:
            line += f", {scams} scam-probe (flagged, not wins)"
        lines.append(line)
    return lines or ["  No pattern with 3+ occurrences yet."]


def silent_thirty_days(messages: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    out = []
    for m in messages:
        if m.get("replied") is not None or m.get("final_outcome"):
            continue
        sent = datetime.fromisoformat(m["sent_at"].replace("Z", "+00:00"))
        if (now - sent).days >= DEAD_AFTER_DAYS:
            out.append(m)
    return out


REPORT_SCHEMA = _obj({q: _STR for q in [
    "voice", "winners", "losers", "openers", "length", "cta", "angles", "objections",
]})

NARRATIVE_SYSTEM = """You are analysing an outreach log for Growmated. Answer the 8 hardening
questions USING ONLY the log rows provided. Hard rules:
- Never invent an example, a number, or a pattern. Quote reply_text and message content
  verbatim when citing them.
- "No data yet" is the correct answer wherever the log is too thin. Do not pad.
- A pattern needs 3 or more occurrences to be a pattern.
- scam-probe replies are negative signal: copy that attracts them should be flagged for the
  ban list, never praised.
Each answer is a short markdown section. Cite counts."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Mark 30-day-silent messages dead")
    args = parser.parse_args()

    messages = fetch_sent_messages()
    print(f"# Outreach extraction — {datetime.now(timezone.utc).date()}")
    print(f"\n{len(messages)} sent message(s) in the log.")
    if not messages:
        print("\nNo data yet. Send messages and record outcomes first; nothing to extract.")
        return 0

    replied = [m for m in messages if m.get("replied")]
    print(f"{len(replied)} replied. Reply rate: {len(replied)/len(messages):.0%}\n")

    print("## Deterministic patterns (3+ occurrences only)")
    for key in ("channel", "opener_type", "angle", "cta_type", "proof_used"):
        print(f"\nBy {key}:")
        for line in rate_by(messages, key):
            print(line)

    silent = silent_thirty_days(messages)
    print(f"\n## 30-day silence autopsy: {len(silent)} message(s)")
    for m in silent[:15]:
        print(f"  {m['sent_at'][:10]}  {m.get('channel')}  {m.get('contact_name')}  angle={m.get('angle')}")
    if silent and args.apply:
        client = db.get_client()
        for m in silent:
            client.table("outreach_log").update(
                {"replied": False, "final_outcome": "dead"}
            ).eq("id", m["id"]).execute()
        print(f"  -> marked {len(silent)} dead (autopsy them quarterly).")
    elif silent:
        print("  -> re-run with --apply to mark these dead.")

    # LLM narrative over the raw rows. Compact digest keeps the context sane.
    digest = "\n---\n".join(
        "\n".join(
            f"{k}: {m.get(k)}" for k in (
                "channel", "opener_type", "angle", "cta_type", "proof_used", "word_count",
                "replied", "days_to_reply", "reply_quality", "objection_category",
                "final_outcome", "content", "reply_text",
            ) if m.get(k) is not None
        )
        for m in messages[-120:]  # most recent 120 keeps the prompt bounded
    )

    print("\n## The 8 hardening questions, answered from the log only\n")
    try:
        client = build_client()
        report, elapsed = generate_json(
            client, NARRATIVE_SYSTEM,
            f"LOG ROWS:\n{digest}", REPORT_SCHEMA, effort="high",
        )
        for question in ("voice", "winners", "losers", "openers", "length", "cta", "angles", "objections"):
            print(f"### {question.upper()}\n{report.get(question, 'No data yet.')}\n")
        print(f"(model: {MODEL}, {elapsed:.1f}s)")
    except Exception as exc:
        print(f"Narrative pass failed ({type(exc).__name__}: {str(exc)[:200]}).")
        print("The deterministic stats above still stand.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
