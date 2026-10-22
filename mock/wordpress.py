"""LOCAL MOCK publishing target — stands in for the production WordPress REST API.

This is a MOCK service running locally. It executes the same request/response
round-trip as production (JSON payload over HTTP -> stored content -> returned
URL) but has no real-world publishing effect; articles are kept in memory and
the returned URL is fake (e.g. http://127.0.0.1:8001/blog/solar-sense-update).

Production integration (one-for-one):
    POST https://your-site.org/wp-json/wp/v2/posts
    headers: Authorization: Basic <application-password credentials>
    body:    {"title": ..., "content": ..., "status": "draft"}
    -> 201 with {"id": ..., "link": "https://your-site.org/article-slug/"}
The mock mirrors that request/response shape, so swapping production in later
means changing the base URL, credentials and the re-published routes only.

Run via:  python scripts/run_mock_api.py   (mounted at prefix /wordpress)
"""
from __future__ import annotations

import itertools
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

_articles: dict[int, dict] = {}
_next_id = itertools.count(1)
_BASE = f"http://127.0.0.1:{os.getenv('MOCK_API_PORT', '8001')}"


class PostIn(BaseModel):
    """Mirrors a WordPress wp/v2/posts request body."""
    title: str = Field(default="", max_length=300, description="Post title (optional)")
    content: str = Field(min_length=1, description="Full article body (markdown/html text)")
    status: str = Field(default="publish", description="WordPress status word (mock ignores real states)")


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:60]
    return slug


@router.post("/posts")
def create_post(post: PostIn) -> dict:
    """Accepts a JSON article, stores it in memory, returns a fake article URL."""
    post_id = next(_next_id)
    slug = _slugify(post.title) or f"post-{post_id}"
    url = f"{_BASE}/blog/{slug}"
    _articles[post_id] = {
        "id": post_id,
        "slug": slug,
        "title": post.title or f"Post {post_id}",
        "content": post.content,
        "status": post.status,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
    }
    # Response mirrors production WordPress (id/link/status).
    return {"id": post_id, "url": url, "link": url, "status": "published"}


@router.get("/posts")
def list_posts() -> list[dict]:
    return list(_articles.values())


@router.get("/posts/{post_id}")
def get_post(post_id: int) -> dict:
    article = _articles.get(post_id)
    if article is None:
        raise HTTPException(status_code=404, detail=f"No stored post id={post_id}")
    return article


def get_article_by_slug(slug: str) -> dict | None:
    """Used by the /blog/{slug} demo viewer in scripts/run_mock_api.py."""
    for article in _articles.values():
        if article["slug"] == slug:
            return article
    return None
