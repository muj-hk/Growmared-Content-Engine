# Connecting "Growmated x Prospecting" to the Emails tool

The scheduled chat keeps doing everything it does now — find businesses, spot the gap, write
the opener and three follow-ups. Only the destination changes: instead of Gmail drafts (which
only Muj can see), it writes into the Growmated Engine database. The whole team then works
the queue in the **Emails** page: send today's due messages from Gmail, click *Mark sent*,
log replies and bounces. Follow-up timing (day +3 / +7 / +12) and stop-on-reply are enforced
by the tool, not remembered by anyone.

Destination project: **Growmated Engine**, ref `rkhcbvssmfxoajqvsqma`, via the Supabase MCP
tool `execute_sql`. One statement per business inserts the prospect and all four touches
atomically.

---

## Paste this into the "Growmated x Prospecting" chat

```
CHANGE TO YOUR DELIVERY STEP — write drafts to the team database instead of Gmail drafts.

Everything about your research, angle selection and copy stays the same. Replace the
"create Gmail drafts" step with this: for EVERY business that has a real email, run one
insert via the Supabase MCP tool `execute_sql` with project_id `rkhcbvssmfxoajqvsqma`.

Use exactly this template. Keep the $$ ... $$ quoting: it makes apostrophes and line
breaks safe with no escaping. One statement per business.

with p as (
  insert into public.pipeline
    (business_name, owner_name, email, industry, source, outreach_status, notes)
  values
    ($$<business name>$$, $$<owner first name or empty>$$, $$<their real email>$$,
     $$<industry>$$, 'Cold Email', 'Not Contacted',
     $$<one line: the observed gap and the angle you led with>$$)
  returning id
)
insert into public.outreach_log
  (pipeline_id, contact_name, channel, direction, touch_number, subject, content,
   opener_type, angle, cta_type, proof_used, word_count)
select p.id, $$<owner or business name>$$, 'Email', 'draft', t.touch, t.subj, t.body,
       'observation', $$<angle as a kebab-case slug, e.g. form-only-no-calendar>$$,
       'situational-question', 'photobooth',
       array_length(regexp_split_to_array(trim(t.body), '\s+'), 1)
from p, (values
  (1, $$<subject: under 8 words, names the business>$$, $$<opening email body>$$),
  (2, null, $$<follow-up 1 body>$$),
  (3, null, $$<follow-up 2 body>$$),
  (4, null, $$<follow-up 3 body>$$)
) as t(touch, subj, body);

RULES
- touch 1 is the opener; 2, 3, 4 are FU1 (day +3), FU2 (day +7), FU3 (day +12). The tool
  computes the due dates and stops the sequence on any reply or bounce. Do not add your
  own scheduling notes to the copy.
- Your existing copy rules still apply exactly: opener and FU1 carry ZERO links and zero
  web addresses; only FU2 and FU3 may contain the cal.com link; subject under 8 words
  naming the business; opener under 110 words; the two-line sign-off; the P.S. line.
- Only businesses with a REAL public email get inserted. No email, no row.
- Never update or delete existing rows. Insert only.
- Still produce your daily GROWMATED_<date>.md summary, and end it with one line:
  "Inserted N prospects into the engine." If an insert fails, report the exact Postgres
  error for that business and continue with the rest.
```

---

## What the team sees

**Emails** page, three sections computed live:
- **Send today** — unsent openers plus follow-ups whose day has arrived. Copy subject and
  body into Gmail, send, click *Mark sent*. *Bounced* kills the sequence.
- **Awaiting reply** — sent, no outcome yet. When something lands in the inbox, paste the
  reply verbatim; that stops the remaining follow-ups automatically.
- **Scheduled** — follow-ups not yet due. Nothing to do; just visibility.

## Migrating the current backlog

The chat's existing tracked prospects (its CSVs) can be backfilled with the same template —
ask it to replay its open, un-replied prospects as inserts, setting `outreach_status` to
match ('Email sent' for ones already contacted) and marking already-sent touches by asking
Muj. Simpler alternative: start fresh from today's run and let the old CSV thread die out
naturally as its sequences finish.

## Known constraint

Scheduled cloud runs have the Supabase connector available (the content engine already uses
it daily). Gmail is NOT available in scheduled runs, which is exactly why drafts never could
be auto-created there — this handoff removes that dependency entirely.
