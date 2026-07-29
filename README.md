# Growmated Engine

Two internal tools behind one password:

- **🎯 Prospecting** — paste a Facebook/LinkedIn post or an Upwork job, get a comment, DM and
  cold email (or a tailored proposal), grounded in real Growmated proof. Writes to Supabase
  `pipeline` + `outreach_log`.
- **📝 Content** — the posting queue. Shows each day's post from the scheduled Cowork chat with
  the image and per-platform copy and tags. Generates nothing itself.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501 and sign in with `APP_PASSWORD`.

## Configuration

All secrets live in `.env` locally (gitignored) or in the host's secrets manager when deployed.
**Never commit them.**

| Variable | Required | What it is |
|---|---|---|
| `APP_PASSWORD` | ✅ | Team password for the app. The app refuses to start without it. |
| `SUPABASE_URL` | ✅ | `https://rkhcbvssmfxoajqvsqma.supabase.co` |
| `SUPABASE_KEY` | ✅ | Service-role key. Server-side only, never reaches the browser. |
| `NVIDIA_API_KEY` | ✅ (nvidia) | Free NVIDIA endpoint |
| `ANTHROPIC_API_KEY` | ✅ (claude) | Anthropic API, needs credits |
| `GROWMATED_PROVIDER` | — | `nvidia` (default) or `claude` |
| `GROWMATED_NVIDIA_MODEL` | — | Default `mistralai/mistral-nemotron` |

### Switching model provider

`GROWMATED_PROVIDER=claude` moves generation to `claude-opus-5` with server-enforced structured
outputs. `nvidia` is free; `claude` costs roughly $0.02 per generation and needs credits on the
Anthropic account.

## Testing

```bash
python test_outreach.py
```

Runs five fixtures through the live model and checks every house rule: the one approved proof
story, no invented clients or statistics, no links or contact details in cold emails, subject
under 8 words, body under 110 words, the two-line sign-off, and no banned phrases. Exits
non-zero on failure.

## Architecture

```
app.py                  home + health check
pages/1_Prospecting.py  -> pipeline + outreach_log
pages/2_Content.py      -> content_calendar

auth.py                 password gate (fails closed)
llm.py                  provider abstraction (nvidia | claude)
db.py                   Supabase
quality.py              house-style + fabrication guards
context_builder.py      prompts + JSON schemas
growmated_knowledge.py  SOURCE OF TRUTH: positioning, proof, voice
```

**To change what the copy says, edit `growmated_knowledge.py`** — never a prompt string. The
prompts are composed from it.

## Guardrails

Generated copy passes through four layers before a human sees it:

1. **Typography normalisation** — em dashes, smart quotes, ellipses fixed deterministically.
2. **House-style check** — banned phrases, word limits, placeholders, and the deliverability
   rules (no links, domains, email addresses or phone numbers in a cold email).
3. **Fabrication check** — invented clients ("we helped a bookshop…") and invented numbers
   ("30% lift", "triple engagement"). Shows a red **Do not send** banner.
4. **Repair pass** — a second model call that rewrites only the offending fields.

A green proof banner means the copy cites the one approved case study. Red means it invented
one: do not send it.
