# Connecting the scheduled Cowork chat to the Content tool

The Content tool **generates nothing**. It is the team's posting queue: it shows what your
scheduled Cowork chat already produces (image + per-platform copy + tags) so someone can open
the right tab, copy, and post.

## How the two are connected

There is no pairing step and no chat ID. The link is one-way through the database:

```
Scheduled Cowork chat  ──insert──▶  public.content_calendar  ──read──▶  Content tool
```

Any chat that can run the insert will work. The tool does not know or care which chat wrote the
row. Nothing needs to be configured on the tool side.

Destination project: **Growmated Engine**, ref `rkhcbvssmfxoajqvsqma`.

---

## Add this to the scheduled chat's instructions

```
STEP: Save today's post to the Growmated Content tool.

After you finish writing the post and generating the image, save it to Supabase so the team
sees it in the Content tool. Use the Supabase MCP tool `execute_sql` with
project_id `rkhcbvssmfxoajqvsqma`.

Run exactly one insert per day, using this template. Keep the $$ $$ quoting exactly as shown:
it lets you write apostrophes and line breaks with no escaping at all.

insert into public.content_calendar
  (title, content, platform, status, scheduled_date, target_audience, image_url, variants)
values (
  $$<short title, max 60 chars>$$,
  $$<the LinkedIn copy again, as a plain-text fallback>$$,
  'LinkedIn + Facebook + Instagram',
  'Draft',
  current_date,
  $$<who this post is aimed at>$$,
  <public image URL in single quotes, or the word NULL if you do not have one>,
  jsonb_build_object(
    'LinkedIn', jsonb_build_object(
      'copy', $$<full LinkedIn post, line breaks are fine>$$,
      'tags', $$#tag1 #tag2$$),
    'Facebook', jsonb_build_object(
      'copy', $$<full Facebook post>$$,
      'tags', $$#tag1 #tag2$$),
    'Instagram', jsonb_build_object(
      'copy', $$<full Instagram post>$$,
      'tags', $$#tag1 #tag2$$)
  )
);

RULES
- Write DIFFERENT copy for each platform. LinkedIn runs longer and more considered. Facebook is
  conversational, written to be dropped into groups. Instagram is short and punchy. Never paste
  the same body into all three.
- Put hashtags ONLY in 'tags', never inside 'copy'. The tool joins them at copy time.
- Do NOT use \' or '' escaping. The $$ $$ quoting handles every character. Just write naturally.
- Do not put a set-returning function in a RETURNING clause; it will error.
- status is always 'Draft'. A human clicks "Mark posted" in the tool.
- One row per day. Never update or delete existing rows.
- After the insert succeeds, reply with the title and the scheduled_date you used. If it fails,
  report the exact Postgres error rather than silently skipping it.
```

---

## The image

`image_url` must be a **publicly reachable URL** for the tool to display it. If the chat cannot
produce a hosted URL, insert `NULL` and the team can attach one later with the **🖼️ Set image
URL** button. Everything else works without it.

## What the team sees

One card per day: image on the left, a tab per platform on the right. Each tab has the copy and
tags already joined into one block with a copy button, plus a character count. Two buttons:
**✅ Mark posted** (timestamps it) and **📦 Archive**.

No manual engagement entry, by design.

## If posts stop arriving

The most likely cause is that the scheduled run does not have the Supabase connector available.
Scheduled/headless runs do not always inherit interactively-authorised MCP connectors. Ask the
chat to confirm it can see the Supabase tool before assuming the SQL is wrong.

Check by opening Content and hitting **🔄 Refresh**. New posts appear at the top with 📄 Draft.
