"""LOCAL MOCK publishing targets — stand in for the production social APIs.

This is a MOCK service running locally. Each endpoint executes a real HTTP
request/response round-trip (JSON payload over HTTP -> stored post -> returned
URL) but has no real-world reach: posts are kept in memory and returned URLs are
fake. No credentials are ever used or required.

Production integrations (one-for-one):
  POST /linkedin  ->  LinkedIn API v2: POST https://api.linkedin.com/v2/ugcPosts
                      (OAuth2 access token; returns an activity URN, which maps
                      to a feed URL)
  POST /x         ->  X API v2: POST https://api.twitter.com/2/tweets
                      (OAuth2 user token; returns post id,…/status/{id})
The mock mirrors those request/response shapes, so swapping production in later
means adding auth + real base URLs only.

Run via:  python scripts/run_mock_api.py   (mounted at prefix /social)
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

_social_posts: list[dict] = []
_next_id = itertools.count(1)


class TextPostIn(BaseModel):
    """JSON body for both social endpoints."""
    text: str = Field(min_length=1, description="Post text (plain text)")
    # LinkedIn hard limit ~3000 chars, mirrored here so the mock FAILS like
    # production would: FastAPI answers 422 with a validation message.
    # Used by /linkedin only, see post_linkedin().
    def validated(self, max_chars: int) -> str:
        if len(self.text) > max_chars:
            raise HTTPException(
                status_code=422,
                detail=f"Text too long for this channel: {len(self.text)} > {max_chars} characters.",
            )
        return self.text


@router.post("/linkedin")
def post_linkedin(body: TextPostIn) -> dict:
    """Accepts a JSON text post, stores it in memory, returns a fake post URL."""
    body.validated(max_chars=3000)  # mirrors the real LinkedIn limit
    share_id = next(_next_id)
    url = f"https://www.linkedin.com/feed/update/urn:li:share:MOCK-{share_id}"
    _social_posts.append({
        "id": share_id, "channel": "linkedin", "text": body.text, "url": url,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return {"id": share_id, "url": url, "status": "posted"}


@router.post("/x")
def post_x(body: TextPostIn) -> dict:
    """Accepts a JSON text post, stores it in memory, returns a fake post URL."""
    share_id = next(_next_id)
    url = f"https://x.com/mock_research_org/status/MOCK-{share_id}"
    _social_posts.append({
        "id": share_id, "channel": "x", "text": body.text, "url": url,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return {"id": share_id, "url": url, "status": "posted"}


@router.get("/posts")
def list_posts() -> list[dict]:
    return _social_posts
