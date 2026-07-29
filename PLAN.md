# Growmated Engine — where this goes next

Written 2026-07-29. Current state: Streamlit app live at growmatedengine.streamlit.app with
Prospecting, Content and Pipeline, backed by Supabase `rkhcbvssmfxoajqvsqma`.

---

## 0. One decision needed first: the proof bank

`growmated_knowledge.py` currently allows **one** case study (photo booth). I quarantined the
other three because the handoff doc says *"The one proof story (use only this, do not
embellish)"*.

But `Growmated-Capabilities-and-Case-Studies.pdf` **publishes all four**, with numbers, plus
three named testimonials. That is a client-facing document, so those claims are clearly
approved for external use.

The contradiction resolves cleanly if the single-story rule was about **cold email**, where
brevity and deliverability matter, not about every channel. Proposed split:

| Context | Proof available |
|---|---|
| Cold email, first-touch DM, public comment | photo booth only (unchanged) |
| Upwork proposals, warm replies, anything with the PDF attached | all four |

That unlocks the consulting-firm story for consulting prospects, the chauffeur story for
transport, and the agency story for agencies — which is the single biggest quality win
available, because right now a transport prospect gets a photo booth case study.

**Needs a yes/no from Muj.** Nothing else in this plan depends on it, but proposal quality does.

---

## 1. The platform question, answered

ORTUS (`ORTUS SYSTEM/ortus`) is a **Next.js 16 + Tailwind 4 + Supabase + Netlify** app with
Sentry, Playwright, `@react-pdf/renderer`, and `recharts`. It deploys to Netlify natively via
`@netlify/plugin-nextjs`.

That is the answer to three separate complaints at once:

- **"Deploy to Netlify"** — Next.js on Netlify works. Streamlit never could.
- **"It looks too basic"** — Tailwind plus a real component library has no Streamlit ceiling.
- **"Case study PDFs"** — `@react-pdf/renderer` is already proven in this org, in
  `ortus/lib/pdf` and `ortus/components/pdf`.

Plus `recharts` for the scoring dashboards, and the `supabase.ts` / `supabase-server.ts`
browser/server split and `AuthGuard`/`RoleContext` patterns to copy rather than reinvent.

**Reuse the stack and the patterns, not the domain code.** ORTUS is a property-management app;
none of its bookings/guests logic is relevant. What transfers is the skeleton: project config,
Netlify setup, Supabase client split, auth guard, PDF renderer, chart components.

The Streamlit app stays live and useful the whole time. It is the reference implementation and
the fallback; nothing gets switched off until the replacement is better.

---

## 2. Prospecting: the input is not always a post

Today the tool assumes one shape (a post or profile) and always produces comment + DM + email.
The team actually pastes questions, complaints, hiring posts, service offers, and live client
conversations. Those need different outputs, and some need *no* output at all.

**Add an intent router as step one.** Classify the dump, then route:

| Intent | What the team pastes | Right output |
|---|---|---|
| `hiring` | "Looking for a GHL expert" | Proposal-shaped DM + qualifying questions |
| `problem` | "My follow-up is a mess, help" | Genuinely useful answer first, soft DM second |
| `question` | "Does anyone know if X works?" | Helpful answer, no pitch, credibility play |
| `offer` | Someone selling *to* us | Partnership angle, or skip |
| `conversation` | A live thread with a prospect/client | Next reply, in context, with the objection named |
| `profile` | LinkedIn/FB profile | Cold intro |
| `upwork` | Job posting | Full proposal (see §3) |
| `skip` | Not a prospect at all | Say so, and why. Save the effort. |

Two things this must get right:

1. **`skip` is a real answer.** A tool that always produces copy trains the team to send copy
   that shouldn't be sent. The honest Upwork decline already works this way and it was the
   biggest single quality improvement so far.
2. **`conversation` needs history.** Pasting one reply is not enough context; the input box
   should accept a whole thread and the output should name the objection category (the same
   vocabulary the learning log already uses: price / timing / have-someone / distrust).

---

## 3. Upwork: win rate, not proposal count

Two halves, and the first is worth more than the second.

**Bid gate.** Before writing anything, score the job and recommend bid or skip, because
connects are finite and a bad bid costs more than a missed one. Inputs: budget floor, client
spend and hire rate, payment verified, proposal count, red-flag wording, and fit against what
Growmated actually does. This is a real gate with a verdict banner, not a soft hint.

**Then the proposal**, with the assets that actually close:

- **Tailored PDF** — generate per prospect with `@react-pdf/renderer`, leading with the
  matching case study rather than sending the same four-pager to everyone.
- **Loom** — needs a decision: a reusable library mapped by service/industry, or record per
  prospect. Library means the tool auto-attaches; per-prospect means it prompts.
- **Suggestions alongside the proposal** — what to ask before quoting, which risk the client
  is silently worried about, and a rate range based on comparable past jobs.

---

## 4. The autonomous part

"Learns, understands, tracks, identifies gaps, points us in the right direction" is four
different mechanisms. Three exist; one is missing.

- **Tracks** — done. `outreach_log` records every message and outcome, reply text verbatim.
- **Learns** — partly done. `extract_learnings.py` computes reply rates per opener, angle, CTA
  and channel, at 3+ occurrences, and narrates the 8 hardening questions from the log only.
  Next: feed those findings *back* into the prompt automatically instead of by hand.
- **Understands** — the guard layers (fabrication, house style, proof integrity) are the
  understanding. They keep improving as real failures surface.
- **Identifies gaps and points direction** — **missing.** This is the piece to build: a weekly
  Director report that answers "what should we do differently this week", from the data:
  which angle is dying, which industry never replies, which CTA is quietly winning, how many
  prospects are sitting untouched, which drafts were generated and never sent.

That last point matters most. The gap between *generated* and *sent* is the most honest signal
in the system: if the team isn't sending what the tool writes, the tool is wrong.

---

## 5. Phasing

Each phase ships something usable. Nothing is a big-bang rewrite.

**Phase 1 — quality, on Streamlit (days)**
Intent router. Proof-bank split once decided. Upwork bid gate. Conversation mode.
Rationale: highest value per hour, no platform risk, team feels it immediately.

**Phase 2 — the loop closes (days)**
Weekly Director report. Learnings feed back into prompts. Generated-vs-sent tracking.

**Phase 3 — Next.js on the ORTUS stack (1-2 weeks)**
Scaffold from ORTUS's config. Port the Python guards to TypeScript (`quality.py` is the
critical one — it is pure logic and ports cleanly). Real UI. Deploy to Netlify.
PDF generation per prospect. Scoring dashboards.

**Phase 4 — assets and polish**
Tailored PDFs. Loom mapping. Case-study matching by industry.

Reordering note: Phase 3 is what Muj asked for first, but doing it before Phase 1 means
porting logic that is still changing shape. Quality work is cheap on Streamlit and expensive
to redo mid-port.

---

## 6. Blocked on Muj

1. **Proof bank split** — yes or no to §0.
2. **Loom** — reusable library, or per prospect?
3. **The three extraction prompts** — the answers become voice rules and scoring thresholds.
   Without them the scoring is my guesswork rather than his data.
4. **Command center** — ORTUS is the Maqam property app. If there is a separate Growmated
   command center, point me at it; otherwise ORTUS is the stack template.

## 7. Still open from earlier

- App sharing is public (password-gated only) — restrict to the team.
- RLS is disabled on all 11 tables; needs the service_role key swap first, then
  `supabase_rls.sql`.
- Rotate the Anthropic key (unused, but exposed in a chat transcript).
