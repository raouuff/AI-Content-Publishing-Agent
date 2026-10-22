"""Start the local mock publishing API (FastAPI + uvicorn).

Usage:
    python scripts/run_mock_api.py          # http://127.0.0.1:8001
    MOCK_API_PORT=8002 python scripts/run_mock_api.py

This is the only command needed to run the mock "publishing infrastructure"
used by Part 2. It launches a REAL HTTP service executing real request/response
round-trips:

  POST /wordpress/posts      -> fake article URL  http://127.0.0.1:8001/blog/<slug>
  POST /social/linkedin      -> fake post URL   https://www.linkedin.com/feed/update/...
  POST /social/x             -> fake post URL   https://x.com/mock_research_org/status/...
  GET  /health               -> {"status": "ok"}
  GET  /blog/<slug>          -> view a mock-published article (demo nicety)
  GET  /docs                 -> interactive API docs (FastAPI auto-docs)
"""
import os
import sys
from pathlib import Path

# Allow running from any working directory (imports agents/services-style packages).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402

from mock.social import router as social_router  # noqa: E402
from mock.wordpress import router as wordpress_router, get_article_by_slug  # noqa: E402

app = FastAPI(
    title="Mock Publishing API (Part 2)",
    description=(
        "LOCAL MOCK endpoints standing in for the production WordPress REST API, "
        "LinkedIn API v2 and X API v2. Posts are stored in memory and returned URLs "
        "are fake — no real network effects. See mock/wordpress.py and mock/social.py "
        "for the exact production integrations these mocks document one-for-one."
    ),
)

app.include_router(wordpress_router, prefix="/wordpress")
app.include_router(social_router, prefix="/social")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mock-publishing-api"}


@app.get("/blog/{slug}", response_class=HTMLResponse)
def view_article(slug: str) -> HTMLResponse:
    """Demo nicety: mock-published articles are browsable at their returned URL."""
    article = get_article_by_slug(slug)
    if article is None:
        raise HTTPException(status_code=404, detail="No mock article with that slug.")
    body = article["content"].replace("\n", "<br>")
    return HTMLResponse(
        "<html><head><title>%(title)s</title></head><body>"
        "<h1>%(title)s</h1>%(body)s</body></html>"
        % {"title": article["title"], "body": body}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("MOCK_API_PORT", "8001")))
