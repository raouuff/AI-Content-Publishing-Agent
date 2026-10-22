"""Part 2 approval-gate & publishing tests.

Run from the repo root:  pytest -q  (or: .venv/bin/pytest -q)

Covers the hard constraints:
  1. Publication is IMPOSSIBLE before explicit approval (fail closed, no HTTP call).
  2. Human edits after approval reset the row to OUTDATED and block publishing
     until the row is re-approved.
  3. The stored approved content hash is re-verified at publish time (a row whose
     drafts differ from the approved snapshot cannot publish even if its status
     still says APPROVED).
  4. Re-publishing unchanged approved content is a no-op (no HTTP call, no
     duplicate publication rows).
  5. A live round-trip against the mock API (auto-skipped when the mock is not
     running; start it with:  python scripts/run_mock_api.py).

Tests use a temporary database and a monkeypatched HTTP function, so they need
no network and no LLM/API keys.
"""
from __future__ import annotations

import pytest
import requests

import agents.content as agent
from agents.content import ApprovalError
from services import db_content as db

DRAFTS = {
    "linkedin_post": "LinkedIn: Our SolarSense pilot passed its first field test.",
    "newsletter_summary": "Newsletter para one.\n\nNewsletter para two.",
    "website_announcement": "# SolarSense update\n\nFull article body for the news page.",
}


@pytest.fixture()
def db_(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_content.db")
    db.init_db()
    return db


def _stub_http_ok(monkeypatch, store: list):
    def fake_post_json(url, payload, timeout=10.0):
        store.append((url, payload))
        return True, "http://mock/fake-url?ref=" + str(len(store)), None
    monkeypatch.setattr(agent, "_post_json", fake_post_json)


# -------------------------------------------------------------------------- #
# 1. Nothing is published before approval                                     #
# -------------------------------------------------------------------------- #

def test_publish_is_blocked_before_approval(db_, monkeypatch):
    calls: list = []
    _stub_http_ok(monkeypatch, calls)
    cid = agent.save_new_draft("Sample title", "Source text", DRAFTS)

    with pytest.raises(ApprovalError, match="APPROVAL GATE"):
        agent.publish(cid)

    assert calls == []  # not a single HTTP call was attempted
    assert db.list_publications() == []  # no log rows either


def test_publish_is_blocked_for_pending_and_rejected_rows(db_, monkeypatch):
    calls: list = []
    _stub_http_ok(monkeypatch, calls)
    cid = agent.save_new_draft("Sample title", "Source text", DRAFTS)

    agent.submit_for_review(cid)
    with pytest.raises(ApprovalError, match="APPROVAL GATE"):
        agent.publish(cid)

    agent.reject(cid)
    with pytest.raises(ApprovalError, match="APPROVAL GATE"):
        agent.publish(cid)

    assert calls == []


def test_approve_requires_channels(db_):
    cid = agent.save_new_draft("Sample title", "Source text", DRAFTS)
    with pytest.raises(ApprovalError, match="at least one channel"):
        agent.approve(cid, [])


# -------------------------------------------------------------------------- #
# 2. Approval -> publish works, and records everything                         #
# -------------------------------------------------------------------------- #

def test_approved_row_publishes_and_logs(db_, monkeypatch):
    calls: list = []
    _stub_http_ok(monkeypatch, calls)
    cid = agent.save_new_draft("Sample title", "Source text", DRAFTS)

    agent.approve(cid, ["website_announcement", "linkedin_post"])
    results = agent.publish(cid)

    assert [r["status"] for r in results] == ["SUCCEEDED", "SUCCEEDED"]
    assert len(db.list_publications()) == 2
    assert all(r["status"] == "SUCCEEDED" for r in db.list_publications())
    assert all(r["published_url"] for r in db.list_publications())
    assert db.get_content(cid)["status"] == "PUBLISHED"


# -------------------------------------------------------------------------- #
# 3. Edits after approval -> OUTDATED -> must re-approve                       #
# -------------------------------------------------------------------------- #

def test_edit_after_approval_requires_reapproval(db_, monkeypatch):
    calls: list = []
    _stub_http_ok(monkeypatch, calls)
    cid = agent.save_new_draft("Sample title", "Source text", DRAFTS)

    agent.approve(cid, ["website_announcement"])
    results = agent.publish(cid)
    assert all(r["status"] == "SUCCEEDED" for r in results)
    calls.clear()

    edited = dict(DRAFTS)
    edited["website_announcement"] = "# Edited headline\n\nChanged body."
    status = agent.save_edits(cid, edited)
    assert status == "OUTDATED"

    with pytest.raises(ApprovalError, match="APPROVAL GATE"):
        agent.publish(cid)
    assert calls == []  # blocked end-to-end, no HTTP attempt

    # Re-approval of the edited content -> publish works and is a NEW version
    agent.approve(cid, ["website_announcement"])
    results = agent.publish(cid)
    assert [r["status"] for r in results] == ["SUCCEEDED"]
    assert len(calls) == 1  # the edited content really went out again

    # Two publications for the same channel, different hashes -> two versions
    pubs = [r for r in db.list_publications(content_id=cid)
            if r["channel"] == "website_announcement"]
    assert len(pubs) == 2 and pubs[0]["content_hash"] != pubs[1]["content_hash"]


# -------------------------------------------------------------------------- #
# 4. Hash check: status tampering cannot bypass the gate                       #
# -------------------------------------------------------------------------- #

def test_hash_mismatch_blocks_publish_even_if_status_says_approved(db_, monkeypatch):
    calls: list = []
    _stub_http_ok(monkeypatch, calls)
    cid = agent.save_new_draft("Sample title", "Source text", DRAFTS)

    # Simulate corrupt state: someone flips the status back to APPROVED without
    # re-approving, after the drafts were secretly changed.
    db.update_drafts(cid, {**DRAFTS, "linkedin_post": "Tampered LinkedIn text."})
    db.set_status(cid, "APPROVED", approved_at="2026-01-01T00:00:00+00:00",
                  approved_content_hash=agent.content_hash(DRAFTS),  # hash of ORIGINAL drafts
                  selected_channels=["website_announcement"])

    with pytest.raises(ApprovalError, match="changed after approval"):
        agent.publish(cid)
    assert calls == []


# -------------------------------------------------------------------------- #
# 5. Re-publishing unchanged approved content is a no-op                       #
# -------------------------------------------------------------------------- #

def test_republish_unchanged_content_is_a_noop(db_, monkeypatch):
    calls: list = []
    _stub_http_ok(monkeypatch, calls)
    cid = agent.save_new_draft("Sample title", "Source text", DRAFTS)

    agent.approve(cid, ["website_announcement", "linkedin_post", "newsletter_summary"])
    agent.publish(cid)
    assert len(calls) == 3
    assert len(db.list_publications()) == 3

    results = agent.publish(cid)  # second run with identical content
    assert [r["status"] for r in results] == ["ALREADY_PUBLISHED"] * 3
    assert len(calls) == 3                      # no new HTTP calls at all
    assert len(db.list_publications()) == 3     # and no duplicate log rows
    assert db.get_content(cid)["status"] == "PUBLISHED"


# -------------------------------------------------------------------------- #
# 6. LIVE round-trip against the real mock API (skips if it is not running)    #
# -------------------------------------------------------------------------- #

def test_mock_api_live_roundtrip():
    base = agent.MOCK_API_BASE
    try:
        assert requests.get(f"{base}/health", timeout=1).status_code == 200
    except requests.RequestException:
        pytest.skip("mock API not running — start it with: python scripts/run_mock_api.py")

    r = requests.post(f"{base}/wordpress/posts",
                      json={"title": "Publish-gate test article", "content": "Fictional body."},
                      timeout=5)
    assert r.status_code == 200
    link = r.json()["url"]
    assert link.startswith("http://")
    assert requests.get(link, timeout=5).status_code == 200  # the fake URL actually serves

    r2 = requests.post(f"{base}/social/linkedin",
                       json={"text": "Publish-gate test: pilot passed its first field check."},
                       timeout=5)
    assert r2.status_code == 200 and "linkedin.com" in r2.json()["url"]
