"""The Part 2 agent — plain Python functions, no agent framework.

Pipeline:  generate (ONE LLM call) -> save (DRAFT) -> human review/edit in the
Streamlit app -> explicit approval -> automated publish (real HTTP calls to the
local mock API) -> per-channel log rows.

THE APPROVAL GATE (fail closed):
  * `publish()` refuses to run unless the row is APPROVED (or PUBLISHED with an
    unchanged approved content hash) — publication can NEVER happen first.
  * Human edits AFTER approval reset the status to OUTDATED (see `save_edits`)
    and the row must be re-approved before it can publish again.
  * The gate is enforced twice: by status AND by a SHA-256 content hash — even
    a row whose stored status was tampered back to APPROVED is blocked if the
    drafts differ from the approved ones.
"""
from __future__ import annotations

import hashlib
import json
import os

import requests

from services import db_content as db
from services import llm
from services.llm import LLMError

CONTENT_KEYS = ("linkedin_post", "newsletter_summary", "website_announcement")

# Draft key -> channel label shown in the UI.
CHANNEL_LABELS = {
    "linkedin_post": "LinkedIn post",
    "newsletter_summary": "Newsletter (stakeholders)",
    "website_announcement": "Website announcement",
}

MOCK_API_BASE = os.getenv("MOCK_API_BASE", "http://127.0.0.1:8001").rstrip("/")

# Draft version -> (kind, mock endpoint, production integration it stands in for).
# The three drafts are the three channels; each has exactly one publishing target.
PUBLISH_TARGETS = {
    "website_announcement": ("wordpress", "/wordpress/posts",
        "WordPress REST API: POST /wp-json/wp/v2/posts (application-password auth)"),
    "linkedin_post": ("linkedin", "/social/linkedin",
        "LinkedIn API v2: POST /v2/ugcPosts (OAuth2)"),
    "newsletter_summary": ("x", "/social/x",
        "X API v2: POST /2/tweets (OAuth2) — mock reuse so every channel has a "
        "round-trip target; a real newsletter would use an email service (e.g. Mailchimp)"),
}


class ContentError(Exception):
    """User-facing generation / validation failure."""


class ApprovalError(Exception):
    """Approval-gate violation or an invalid approval request."""


# --------------------------------------------------------------------------- #
# 1. Generation — ONE LLM call, structured JSON                                 #
# --------------------------------------------------------------------------- #

CONTENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "linkedin_post": {"type": "STRING",
            "description": "Professional engaging LinkedIn post, <= ~1500 chars, 0-2 hashtags."},
        "newsletter_summary": {"type": "STRING",
            "description": "Concise informative update for organizational stakeholders, 2-3 short paragraphs."},
        "website_announcement": {
            "type": "OBJECT",
            "properties": {
                "headline": {"type": "STRING", "description": "News-page headline."},
                "paragraphs": {"type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "2-4 article paragraphs."},
                "bullets": {"type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Optional bullet list (only if it genuinely helps)."},
            },
            "required": ["headline", "paragraphs"],
        },
    },
    "required": ["linkedin_post", "newsletter_summary", "website_announcement"],
}

GENERATE_SYSTEM_PROMPT = """You are the communications assistant of a research \
organization. Turn the raw input into tailored versions for three different channels.

Return JSON with exactly this shape:
- "linkedin_post": string, professional & engaging LinkedIn post, at most ~1500 \
characters, 0-2 relevant hashtags at the end. Call out significance and concrete \
outcomes. No first-person phrasing ("I am excited…") — use the organization's voice.
- "newsletter_summary": string, concise informative update for organizational \
stakeholders, 2-3 short paragraphs, neutral-professional tone.
- "website_announcement": object for the organization's news page — \
{"headline": a clear informative headline, "paragraphs": 2-4 article paragraphs, \
"bullets": an optional short bullet list (results or agenda items only if helpful)}.

Rules:
- ADAPT tone, length and structure per channel — the three versions must feel \
genuinely different (a punchy post, a sober summary, a full news article).
- Use ONLY facts present in the input. Never invent numbers, dates, results, \
quotes, names or partners; phrase unknowns neutrally (e.g. "a date has not yet \
been announced").
- Copy every number, date and name EXACTLY as given — do not round, reformat or \
reinterpret them.
- Plain text; do not add markdown syntax except inside the website bullet list.
"""


def render_website_announcement(ann: dict) -> str:
    """Render the structured website object as a markdown article for storage/editing."""
    headline = str(ann.get("headline", "")).strip()
    paragraphs = [str(p).strip() for p in (ann.get("paragraphs") or []) if str(p).strip()]
    bullets = [str(b).strip() for b in (ann.get("bullets") or []) if str(b).strip()]
    parts = [f"# {headline}", ""] if headline else []
    parts += paragraphs
    if bullets:
        parts += ["", "\n".join(f"- {b}" for b in bullets)]
    return "\n".join(parts).strip()


def generate_drafts(title: str, body: str) -> dict[str, str]:
    """Raw input -> three tailored drafts (single LLM call, validated).

    Raises ContentError for empty input/incomplete LLM output; LLMError from the
    provider wrapper bubbles up with its user-friendly message.
    """
    body = (body or "").strip()
    if not body:
        raise ContentError(
            "The source text is empty — paste a research project description, "
            "project update, findings summary or event announcement first."
        )
    user = f"TITLE (optional): {title.strip() or '(none)'}\n\nSOURCE TEXT:\n{body}"
    data = llm.chat_json(GENERATE_SYSTEM_PROMPT, user, CONTENT_SCHEMA, temperature=0.3)

    linkedin = str(data.get("linkedin_post") or "").strip()
    newsletter = str(data.get("newsletter_summary") or "").strip()
    website = data.get("website_announcement")
    missing = []
    if not linkedin:
        missing.append("linkedin_post")
    if not newsletter:
        missing.append("newsletter_summary")
    if not isinstance(website, dict) or not str(website.get("headline", "")).strip():
        missing.append("website_announcement.headline")
    if missing:
        raise ContentError(
            "The LLM response was incomplete (missing: " + ", ".join(missing) +
            "). No fantasy fill-ins allowed — please try generating again."
        )
    return {
        "linkedin_post": linkedin,
        "newsletter_summary": newsletter,
        "website_announcement": render_website_announcement(website),
    }


# --------------------------------------------------------------------------- #
# 2. Content management (thin wrappers over services/db_content.py)             #
# --------------------------------------------------------------------------- #

def save_new_draft(title: str, source_text: str, drafts: dict) -> int:
    """Insert one content row with the three drafts, status DRAFT. Returns the id."""
    missing = [k for k in CONTENT_KEYS if not (drafts.get(k) or "").strip()]
    if missing:
        raise ContentError(f"Cannot save: draft(s) empty: {', '.join(missing)}")
    return db.insert_content(title, source_text,
                             drafts["linkedin_post"], drafts["newsletter_summary"],
                             drafts["website_announcement"])


def drafts_from_row(row: dict) -> dict:
    return {key: (row.get(key) or "") for key in CONTENT_KEYS}


def content_hash(drafts: dict) -> str:
    """SHA-256 over the canonical JSON of the three drafts — the approval fingerprint."""
    canonical = json.dumps({key: drafts.get(key, "") for key in CONTENT_KEYS},
                           sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_edits(content_id: int, drafts: dict) -> str:
    """Persist human edits. Enforces: any edit AFTER approval -> status OUTDATED."""
    row = db.get_content(content_id)
    if row is None:
        raise ContentError(f"Content #{content_id} not found.")
    if any(key not in drafts for key in CONTENT_KEYS):
        raise ContentError("Edit payload must contain all three channel drafts.")
    db.update_drafts(content_id, drafts)
    if row["status"] in ("APPROVED", "PUBLISHED"):
        db.set_status(content_id, "OUTDATED")
        return "OUTDATED"
    return row["status"]


def submit_for_review(content_id: int) -> str:
    """DRAFT/OUTDATED/REJECTED -> PENDING_APPROVAL (signals a reviewer is needed)."""
    row = db.get_content(content_id)
    if row is None:
        raise ContentError(f"Content #{content_id} not found.")
    if row["status"] in ("DRAFT", "OUTDATED", "REJECTED"):
        db.set_status(content_id, "PENDING_APPROVAL")
        return "PENDING_APPROVAL"
    return row["status"]  # APPROVED/PUBLISHED/PENDING stay as they are


def reject(content_id: int) -> str:
    """Reviewer decision: REJECTED. Published rows cannot be rejected (make a new update)."""
    row = db.get_content(content_id)
    if row is None:
        raise ContentError(f"Content #{content_id} not found.")
    if row["status"] == "PUBLISHED":
        raise ApprovalError("A published row cannot be rejected — create a fresh update instead.")
    db.set_status(content_id, "REJECTED")
    return "REJECTED"


# --------------------------------------------------------------------------- #
# 3. Approval — the MANDATORY human gate                                        #
# --------------------------------------------------------------------------- #

def approve(content_id: int, channels: list[str]) -> str:
    """Explicit human approval. Locks the current drafts via content hash.

    Returns the approved content hash. Publishing afterwards is only possible
    through `publish()`, which re-verifies this hash.
    """
    if not channels:
        raise ApprovalError("Select at least one channel before approving.")
    bad = [c for c in channels if c not in CONTENT_KEYS]
    if bad:
        raise ApprovalError(f"Unknown channel(s): {', '.join(bad)}")
    row = db.get_content(content_id)
    if row is None:
        raise ContentError(f"Content #{content_id} not found.")
    digest = content_hash(drafts_from_row(row))
    db.set_status(content_id, "APPROVED", approved_at=db.now_iso(),
                  approved_content_hash=digest, selected_channels=list(channels))
    return digest


def assert_approval_gate(row: dict) -> None:
    """Fail-closed publication precondition — raises unless EXPLICITLY approved:
      1. workflow status must be APPROVED or PUBLISHED, and
      2. an approval record (approved_at + approved_content_hash) must exist, and
      3. the SHA-256 of the CURRENT drafts must equal the approved hash, and
      4. an approval timestamp must be set.
    Any edit after approval invalidates (1) or (3), so publishing is blocked
    until the row is re-approved. This is the heart of test_publish_gate.py.
    """
    status = row["status"]
    if status not in ("APPROVED", "PUBLISHED"):
        raise ApprovalError(
            f"APPROVAL GATE: cannot publish — status is {status}. Content must be "
            "explicitly approved (edited rows become OUTDATED and need re-approval)."
        )
    approved_at, approved_hash = row.get("approved_at"), row.get("approved_content_hash")
    if not approved_at or not approved_hash:
        raise ApprovalError("APPROVAL GATE: cannot publish — no approval record found.")
    current_hash = content_hash(drafts_from_row(row))
    if current_hash != approved_hash:
        raise ApprovalError(
            "APPROVAL GATE: cannot publish — content changed after approval "
            "(stored hash does not match the current drafts). Re-approve first."
        )


# --------------------------------------------------------------------------- #
# 4. Automated publishing — real HTTP calls, ONLY after the gate passes         #
# --------------------------------------------------------------------------- #

def publish(content_id: int, channels: list[str] | None = None) -> list[dict]:
    """Publish the approved drafts to the local mock API, one attempt per channel.

    * Fails closed: assert_approval_gate() runs FIRST.
    * Idempotent: a channel already SUCCEEDED with the same approved hash is a
      no-op (no HTTP call, no duplicate log row). After re-approval of edited
      content (new hash) it publishes again — a new version.
    * Every attempt is recorded in `publications` with status, URL, timestamp
      and the content hash used as the version marker.
    * Errors are captured per channel (HTTP status, non-JSON, unreachable API);
      the UI shows success/failure per channel immediately.
    """
    row = db.get_content(content_id)
    if row is None:
        raise ContentError(f"Content #{content_id} not found.")
    assert_approval_gate(row)  # <-- MANDATORY gate; publication never happens without it

    try:
        stored = json.loads(row.get("selected_channels") or "[]")
    except json.JSONDecodeError:
        stored = []
    selected = [c.strip() for c in stored]
    channels = list(channels) if channels is not None else selected
    if not channels:
        raise ApprovalError("This approved row has no channels selected — re-approve with channels.")
    approved_hash = row["approved_content_hash"]
    drafts = drafts_from_row(row)
    results: list[dict] = []

    for channel in channels:
        if channel not in PUBLISH_TARGETS:
            msg = f"Unknown channel '{channel}' (valid: {', '.join(CONTENT_KEYS)})."
            db.record_publication(content_id, channel, "FAILED",
                                  error_message=msg, content_hash=approved_hash)
            results.append({"channel": channel, "label": channel, "status": "FAILED",
                            "published_url": None, "error": msg})
            continue
        _kind, endpoint, _production = PUBLISH_TARGETS[channel]
        text = (drafts.get(channel) or "").strip()
        previous = db.get_published(content_id, channel)
        if previous and previous.get("content_hash") == approved_hash:
            # No-op: already published with the SAME approved content — never duplicate.
            results.append({"channel": channel, "label": CHANNEL_LABELS[channel],
                            "status": "ALREADY_PUBLISHED",
                            "published_url": previous["published_url"], "error": None})
            continue
        if not text:
            msg = "Cannot publish an empty draft for this channel."
            db.record_publication(content_id, channel, "FAILED",
                                  error_message=msg, content_hash=approved_hash)
            results.append({"channel": channel, "label": CHANNEL_LABELS[channel],
                            "status": "FAILED", "published_url": None, "error": msg})
            continue
        if channel == "website_announcement":
            payload = {"title": row.get("title") or f"Research update #{content_id}",
                       "content": text, "status": "publish"}
        else:
            payload = {"text": text}
        ok, url, err = _post_json(f"{MOCK_API_BASE}{endpoint}", payload)
        if ok:
            db.record_publication(content_id, channel, "SUCCEEDED",
                                  published_url=url, content_hash=approved_hash)
            results.append({"channel": channel, "label": CHANNEL_LABELS[channel],
                            "status": "SUCCEEDED", "published_url": url, "error": None})
        else:
            db.record_publication(content_id, channel, "FAILED",
                                  error_message=err, content_hash=approved_hash)
            results.append({"channel": channel, "label": CHANNEL_LABELS[channel],
                            "status": "FAILED", "published_url": None, "error": err})

    if any(r["status"] == "SUCCEEDED" for r in results):
        db.set_status(content_id, "PUBLISHED")
    return results


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> tuple[bool, str | None, str | None]:
    """Real HTTP POST with JSON body, timeout and error capture.

    Returns (ok, returned_url, error_message).
    """
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            return False, None, f"HTTP {resp.status_code} from publishing API: {resp.text[:200]}"
        data = resp.json()
    except requests.exceptions.RequestException as exc:
        return False, None, f"Could not reach the publishing API at {url}: {exc}"
    except ValueError as exc:
        return False, None, f"Publishing API returned a non-JSON response: {exc}"
    link = data.get("url") if isinstance(data, dict) else None
    if not link:
        return False, None, f"Publishing API returned no URL: {str(data)[:200]}"
    return True, link, None


def publication_log(status: str | None = None, created_since: str | None = None,
                    content_id: int | None = None) -> list[dict]:
    """Publication attempts for the log tab / CSV export (adds a `version` column)."""
    rows = db.list_publications(status=status, created_since=created_since,
                                content_id=content_id)
    for r in rows:
        r["version"] = (r.get("content_hash") or "")[:8]
    return rows
