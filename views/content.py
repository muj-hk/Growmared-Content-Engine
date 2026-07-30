"""
Content — the posting queue fed by the scheduled Cowork chat.

Generates nothing. Shows each day's post with its per-platform copy, tags and image so the
team can open a tab, copy, and post.

Posts used to vanish the moment someone clicked "Mark posted": the default view filtered them
out entirely, so the team saw today's post appear and then disappear with no trace. Anything
posted today now stays visible in its own section, and the count is always on screen.
"""

from datetime import date, datetime, timezone

import streamlit as st

import data as data_mod
import db
from data import Snapshot
from ui import copy_block, pill, section


def _posted_today(post: dict) -> bool:
    stamp = post.get("posted_at")
    if not stamp:
        return False
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).date() == date.today()
    except ValueError:
        return False


def _render_post(post: dict, done: bool = False) -> None:
    when = post.get("scheduled_date") or (post.get("created_at") or "")[:10]
    status = post.get("status") or "Draft"
    variants = db.get_variants(post)

    with st.expander(f"{post.get('title') or '(untitled)'}  ·  {when}  ·  {status}",
                     expanded=not done):
        if post.get("target_audience"):
            st.caption(f"Audience: {post['target_audience']}")

        available = [p for p in db.CONTENT_PLATFORMS if p in variants] or list(variants)
        if not available:
            st.warning("No copy on this row yet.")
        else:
            for tab, platform in zip(st.tabs(available), available):
                with tab:
                    variant = variants.get(platform) or {}
                    body = (variant.get("copy") or "").strip()
                    tags = (variant.get("tags") or "").strip()
                    image = (variant.get("image") or post.get("image_url") or "").strip()

                    image_col, copy_col = st.columns([1, 2])
                    with image_col:
                        if image:
                            st.image(image, use_container_width=True)
                            st.caption(f"[Download for {platform}]({image})")
                        else:
                            st.info(f"No {platform} image.")
                        uploaded = st.file_uploader(
                            f"Upload {platform} image",
                            type=["png", "jpg", "jpeg", "webp", "gif"],
                            key=f"up_{post['id']}_{platform}",
                            label_visibility="collapsed",
                        )
                        if uploaded is not None:
                            try:
                                with st.spinner("Uploading..."):
                                    url = db.upload_content_image(
                                        post["id"], uploaded.name, uploaded.getvalue(),
                                        uploaded.type, platform=platform)
                                    db.set_variant_image(post["id"], platform, url)
                                data_mod.refresh()
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Upload failed: {type(exc).__name__}: {str(exc)[:200]}")

                    with copy_col:
                        full = f"{body}\n\n{tags}".strip() if tags else body
                        st.caption(f"Copy and paste straight into {platform}:")
                        copy_block(full, key=f"copy_{post['id']}_{platform}")
                        if tags:
                            st.caption(f"Tags: {tags}")
                        st.caption(f"{len(full)} characters")

        st.divider()
        left, right = st.columns([2, 1])
        if done:
            # Undo matters: one stray click used to make a post disappear for good.
            if left.button("Move back to queue", key=f"unpost_{post['id']}",
                           use_container_width=True):
                try:
                    db.update_content(post["id"], status="Draft")
                    data_mod.refresh()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {str(exc)[:200]}")
        else:
            if left.button("Mark posted", key=f"posted_{post['id']}", use_container_width=True):
                try:
                    db.mark_posted(post["id"])
                    data_mod.refresh()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {str(exc)[:200]}")
        if right.button("Archive", key=f"arch_{post['id']}", use_container_width=True):
            try:
                db.update_content(post["id"], status="Archived")
                data_mod.refresh()
                st.rerun()
            except Exception as exc:
                st.error(f"Failed: {str(exc)[:200]}")


def render(snap: Snapshot) -> None:
    posts = snap.posts
    queue = [p for p in posts if (p.get("status") or "") not in ("Posted", "Archived")]
    done_today = [p for p in posts if _posted_today(p)]
    older_posted = [p for p in posts if (p.get("status") == "Posted") and not _posted_today(p)]
    archived = [p for p in posts if p.get("status") == "Archived"]

    st.markdown(
        pill(f"{len(queue)} to post", "warn" if queue else "good", "inbox")
        + " " + pill(f"{len(done_today)} posted today", "good", "check")
        + " " + pill(f"{len(older_posted)} posted earlier", "mute")
        + " " + pill(f"{len(archived)} archived", "mute"),
        unsafe_allow_html=True,
    )

    if queue:
        section("To post", "inbox")
        for post in queue:
            _render_post(post)
    else:
        section("To post", "inbox")
        st.info(
            "Nothing waiting. The scheduled chat writes each day's post here automatically. "
            "If today's post is missing, ask that chat whether its Supabase insert ran and "
            "what error it got (see CONTENT_ENGINE_HANDOFF.md)."
        )

    # Posted today stays on screen, so nothing appears to vanish after one click.
    if done_today:
        section("Posted today", "check")
        for post in done_today:
            _render_post(post, done=True)

    if older_posted or archived:
        with st.expander(f"History ({len(older_posted) + len(archived)})", expanded=False):
            for post in older_posted + archived:
                when = post.get("scheduled_date") or (post.get("created_at") or "")[:10]
                st.markdown(
                    pill(f"{post.get('title') or '(untitled)'} · {when} · {post.get('status')}",
                         "mute", "doc"),
                    unsafe_allow_html=True,
                )
