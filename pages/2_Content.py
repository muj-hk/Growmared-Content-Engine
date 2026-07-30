"""
Content tool — the team's posting queue.

This tool generates nothing. The scheduled Cowork chat writes each day's post into
public.content_calendar (image + per-platform copy + tags); this page presents it so a team
member can open the right tab, hit copy, and post it on LinkedIn, Facebook or Instagram.

No manual engagement entry. Nobody fills in view counts by hand, so we do not ask.
"""

import streamlit as st

import db
from auth import require_login
from ui import inject_base_css, page_header, render_brand

st.set_page_config(page_title="Content | Growmated Engine", page_icon="📝", layout="wide")
inject_base_css()
render_brand()
require_login()

page_header(
    "Content",
    "Today's posts from the scheduled chat. Pick a platform, copy, post.",
    "inbox",
)

if not db.is_configured():
    st.error("Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY in .env.")
    st.stop()

with st.sidebar:
    st.markdown('<div class="gm-section" style="margin-top:4px">View</div>', unsafe_allow_html=True)
    show_posted = st.toggle("Show posted", value=False)
    show_archived = st.toggle("Show archived", value=False)
    if st.button("Refresh", use_container_width=True):
        st.rerun()

try:
    posts = db.list_content(limit=100, include_archived=show_archived)
except Exception as exc:
    st.error(f"Could not load content: {type(exc).__name__}: {str(exc)[:300]}")
    st.stop()

queue = [p for p in posts if p.get("status") != "Posted"]
posted = [p for p in posts if p.get("status") == "Posted"]
visible = posts if show_posted else queue

c1, c2 = st.columns(2)
c1.metric("Waiting to post", len(queue))
c2.metric("Posted", len(posted))

if not visible:
    st.info(
        "Nothing waiting. The scheduled chat writes each day's post here automatically — "
        "see CONTENT_ENGINE_HANDOFF.md if posts are not arriving."
    )

st.divider()

for post in visible:
    status = post.get("status") or "Draft"
    marker = {"Draft": "Draft", "Scheduled": "Scheduled", "Posted": "Posted", "Archived": "Archived"}.get(status, status)
    when = post.get("scheduled_date") or (post.get("created_at") or "")[:10]
    variants = db.get_variants(post)

    with st.expander(f"{post.get('title') or '(untitled)'}  ·  {when}  ·  {marker}", expanded=(post is visible[0])):
        if post.get("target_audience"):
            st.caption(f"Audience: {post['target_audience']}")

        available = [p for p in db.CONTENT_PLATFORMS if p in variants] or list(variants)
        if not available:
            st.warning("No copy on this row yet.")
        else:
            tabs = st.tabs(available)
            for tab, platform in zip(tabs, available):
                with tab:
                    variant = variants.get(platform) or {}
                    body = (variant.get("copy") or "").strip()
                    tags = (variant.get("tags") or "").strip()
                    # Per-platform image first, falling back to a post-wide one.
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
                            key=f"upload_{post['id']}_{platform}",
                            label_visibility="collapsed",
                        )
                        if uploaded is not None:
                            try:
                                with st.spinner("Uploading..."):
                                    url = db.upload_content_image(
                                        post["id"], uploaded.name, uploaded.getvalue(),
                                        uploaded.type, platform=platform,
                                    )
                                    db.set_variant_image(post["id"], platform, url)
                                st.success("Attached.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Upload failed: {type(exc).__name__}: {str(exc)[:200]}")

                    with copy_col:
                        # One block, so a single copy click grabs everything the platform needs.
                        full = f"{body}\n\n{tags}".strip() if tags else body
                        st.caption(f"Copy and paste straight into {platform}:")
                        st.code(full, language="markdown")
                        if tags:
                            st.caption(f"Tags: {tags}")
                        st.caption(f"{len(full)} characters")

        st.divider()
        action_col, archive_col = st.columns([2, 1])
        if action_col.button("Mark posted", key=f"posted_{post['id']}", use_container_width=True):
            try:
                db.mark_posted(post["id"])
                st.rerun()
            except Exception as exc:
                st.error(f"Failed: {str(exc)[:200]}")
        if archive_col.button("Archive", key=f"arch_{post['id']}", use_container_width=True):
            try:
                db.update_content(post["id"], status="Archived")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed: {str(exc)[:200]}")
