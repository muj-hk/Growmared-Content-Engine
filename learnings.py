"""
The loop that closes itself: outcome data -> rules -> back into the prompt.

derive_rules() is DELIBERATELY deterministic. The model never writes rules into its own
prompt; only reply-rate math with real thresholds does. A finding needs enough volume
(MIN_N per side) and a wide enough gap (MIN_GAP) before it becomes an instruction, because
"100% on two messages" is noise dressed as a lesson.

publish_rules() replaces the previous auto batch. active_rules() is what the prompt builder
reads, cached per process so generation never adds a DB round trip per call.
"""

import sys
import time

import db

MIN_N = 5        # sends per side before a comparison means anything
MIN_GAP = 0.25   # reply-rate gap required to call a winner
WIN = {"interested", "question"}

_ATTRS = ("opener_type", "cta_type", "angle", "channel")

_cache: dict = {"rules": None, "at": 0.0}
_TTL = 600  # seconds


def _rate(group: list[dict]) -> float:
    wins = sum(1 for m in group if m.get("replied")
               and (m.get("reply_quality") in WIN or not m.get("reply_quality")))
    return wins / len(group)


def derive_rules(messages: list[dict]) -> list[tuple[str, str]]:
    """(rule, evidence) pairs from sent messages with outcomes."""
    sent = [m for m in messages if m.get("sent_at")]
    rules: list[tuple[str, str]] = []

    for attr in _ATTRS:
        groups: dict[str, list[dict]] = {}
        for m in sent:
            value = m.get(attr)
            if value:
                groups.setdefault(str(value), []).append(m)
        sized = {v: g for v, g in groups.items() if len(g) >= MIN_N}
        if len(sized) < 2:
            continue
        ranked = sorted(sized.items(), key=lambda kv: -_rate(kv[1]))
        (best, bg), (worst, wg) = ranked[0], ranked[-1]
        best_r, worst_r = _rate(bg), _rate(wg)
        if best_r - worst_r >= MIN_GAP:
            rules.append((
                f"Prefer {attr}='{best}' over '{worst}': our own sends show "
                f"{best_r:.0%} vs {worst_r:.0%} reply rate.",
                f"{attr}: {best} {len(bg)} sends/{best_r:.0%} vs {worst} {len(wg)} sends/{worst_r:.0%}",
            ))

    # Copy that attracts scam-probes is negative signal regardless of reply rate.
    for attr in ("angle", "cta_type"):
        groups = {}
        for m in sent:
            if m.get(attr):
                groups.setdefault(str(m[attr]), []).append(m)
        for value, group in groups.items():
            scams = sum(1 for m in group if m.get("reply_quality") == "scam-probe")
            if len(group) >= MIN_N and scams / len(group) >= 0.4:
                rules.append((
                    f"Avoid {attr}='{value}': it mostly attracts scam-probe replies, not buyers.",
                    f"{scams}/{len(group)} scam-probe",
                ))

    return rules


def publish_rules(rules: list[tuple[str, str]]) -> int:
    """Replace the previous auto batch. Manual rules (source != 'auto') are never touched."""
    client = db.get_client()
    client.table("learned_rules").update({"active": False}).eq("source", "auto").execute()
    if rules:
        client.table("learned_rules").insert([
            {"rule": rule, "evidence": evidence, "source": "auto", "active": True}
            for rule, evidence in rules
        ]).execute()
    _cache["rules"] = None
    return len(rules)


def active_rules() -> list[str]:
    """Active rules, cached; fails soft to [] so generation never breaks on a DB hiccup."""
    now = time.time()
    if _cache["rules"] is not None and now - _cache["at"] < _TTL:
        return _cache["rules"]
    try:
        rows = (db.get_client().table("learned_rules").select("rule")
                .eq("active", True).order("created_at", desc=True).limit(8).execute().data or [])
        _cache["rules"] = [r["rule"] for r in rows]
    except Exception:
        _cache["rules"] = []
    _cache["at"] = now
    return _cache["rules"]


def refresh_from_outcomes() -> list[tuple[str, str]]:
    """Fetch outcomes, derive, publish. Run daily by sync_all; cheap and deterministic."""
    messages = db.get_client().table("outreach_log").select("*").execute().data or []
    rules = derive_rules(messages)
    publish_rules(rules)
    return rules


def learned_block() -> str:
    rules = active_rules()
    if not rules:
        return ""
    return (
        "\nLEARNED FROM OUR OWN OUTCOMES - these come from real reply data, follow them:\n"
        + "\n".join(f"  - {rule}" for rule in rules)
    )


if __name__ == "__main__":
    found = refresh_from_outcomes()
    print(f"{len(found)} rule(s) published")
    for rule, evidence in found:
        print(f"  {rule}  [{evidence}]")
    sys.exit(0)
