"""Streamlit UI for the Part 2 agent — AI Content Generation & Automated Publishing.

Run:  streamlit run app_content.py

Tabs:
  1. Draft Content            — paste a research input, ONE LLM call -> three tailored drafts
  2. Approvals & Publishing   — review/edit, choose channels, Approve & Publish (human gate)
  3. Publication Log          — every attempt with status/URL/timestamp + CSV export

The sidebar can auto-start the local mock publishing API (mock/wordpress.py +
mock/social.py) so the demo works with a single command.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import streamlit as st

from agents import content as agent
from agents.content import ApprovalError, CHANNEL_LABELS
from services import db_content as db
from services.llm import LLMError

ROOT = Path(__file__).resolve().parent
MOCK_API_BASE = agent.MOCK_API_BASE

STATUS_EMOJI = {
    "DRAFT": "📝", "PENDING_APPROVAL": "⏳", "APPROVED": "👍",
    "PUBLISHED": "📣", "REJECTED": "🚫", "OUTDATED": "🔄",
}

db.init_db()
st.set_page_config(page_title="AI Content & Publishing Agent", page_icon="🚀", layout="wide")
st.title("🚀 AI Content Generation & Publishing Agent")
st.caption("Part 2 · research input → three tailored drafts → human approval gate → "
           "automated local publishing (mock WordPress / LinkedIn / X). "
           "All sample data is fictional.")

# --------------------------------------------------------------------------- #
# Sidebar: mock publishing API status + auto-start                              #
# --------------------------------------------------------------------------- #

def _mock_healthy() -> bool:
    try:
        return requests.get(f"{MOCK_API_BASE}/health", timeout=0.6).status_code == 200
    except requests.RequestException:
        return False


def auto_start_mock_api() -> bool:
    """Spawn scripts/run_mock_api.py and wait briefly for health; True when ready."""
    if _mock_healthy():
        return True
    subprocess.Popen([sys.executable, str(ROOT / "scripts" / "run_mock_api.py")],
                     cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):  # up to ~6 s
        time.sleep(0.3)
        if _mock_healthy():
            return True
    return False


with st.sidebar:
    st.header("🧪 Mock publishing API")
    auto_start = st.checkbox("Auto-start with the app", value=True)
    api_up = _mock_healthy()
    if not api_up and auto_start:
        with st.spinner("Starting mock API …"):
            api_up = auto_start_mock_api()
    if api_up:
        st.success(f"Running at {MOCK_API_BASE}  ·  [API docs]({MOCK_API_BASE}/docs)")
    else:
        st.error("Offline — publishing will fail until it is running.\n\n"
                 "```\npython scripts/run_mock_api.py\n```")
    st.caption("Real HTTP round-trips · no real credentials · in-memory mock")
    st.divider()
    st.subheader("Status legend")
    st.caption(" | ".join(f"{e} {s}" for s, e in STATUS_EMOJI.items()))


# --------------------------------------------------------------------------- #
# Tab 1 · Draft Content                                                         #
# --------------------------------------------------------------------------- #

tab1, tab2, tab3 = st.tabs(["1 · Draft Content", "2 · Approvals & Publishing", "3 · Publication Log"])

with tab1:
    st.header("Draft content")
    st.markdown("Paste a **research project description, project update, findings "
                "summary or event announcement**. One LLM call produces three "
                "*tailored* drafts (LinkedIn post, stakeholder newsletter, news-page "
                "article) — no invented facts, numbers copied verbatim.")

    samples = sorted((ROOT / "sample_content").glob("*.md"))
    if samples:
        def _load_sample(fname: str) -> None:
            st.session_state["gen_title"] = (Path(fname).stem[:-3]).replace("_", " ").title()
            st.session_state["gen_body"] = (ROOT / "sample_content" / fname).read_text(encoding="utf-8")
        with st.expander(f"📚 Load a fictional sample ({len(samples)} available)"):
            pick = st.selectbox("Sample source text", [f.name for f in samples],
                                index=None, placeholder="Choose a sample …")
            st.button("Load sample", disabled=not pick, on_click=_load_sample, args=(pick,))

    title = st.text_input("Title (optional)", key="gen_title")
    body = st.text_area("Source text", key="gen_body", height=230,
                        placeholder="e.g. Our SolarSense pilot completed its first field deployment …")

    if saved_msg := st.session_state.pop("saved_msg", None):
        st.success(saved_msg)
    if err := st.session_state.get("fresh_error"):
        st.error(f"❌ {err}")
        st.session_state.pop("fresh_error", None)

    generate = st.button("✨ Generate three drafts (one LLM call)",
                         type="primary", disabled=not bool(body.strip()))
    if generate:
        st.session_state["fresh_drafts"] = None
        try:
            st.session_state["fresh_drafts"] = agent.generate_drafts(title, body)
        except (agent.ContentError, LLMError) as exc:
            st.session_state["fresh_error"] = str(exc)

    fresh = st.session_state.get("fresh_drafts")
    if fresh:
        st.success("Drafts generated — review below, then save to the content library.")
        cols = st.columns(3)
        for col, key in zip(cols, agent.CONTENT_KEYS):
            with col:
                st.container(border=True).markdown(
                    f"### {CHANNEL_LABELS[key]}\n\n{fresh[key]}")
        if st.button("💾 Save to content library (status DRAFT)", type="primary"):
            cid = agent.save_new_draft(title, body, fresh)
            st.session_state["fresh_drafts"] = None
            st.session_state["saved_msg"] = f"Saved as draft #{cid} — review, edit and approve in tab 2."
            st.rerun()

# --------------------------------------------------------------------------- #
# Tab 2 · Approvals & Publishing                                                #
# --------------------------------------------------------------------------- #

with tab2:
    st.header("Approvals & publishing")
    st.markdown("Every row is gated: publishing is only possible after an explicit "
                "**approve**, and any edit after approval resets the row to 🔄 **OUTDATED** "
                "(enforced in code via status + a SHA-256 content hash check).")

    f_status, f_date = st.columns(2)
    status_filter = f_status.selectbox("Filter by status",
                                       ["All", *STATUS_EMOJI.keys()], index=0)
    date_from = f_date.date_input("Created from (optional)", value=None)

    rows = db.list_contents(status=None if status_filter == "All" else status_filter,
                            created_since=date_from.isoformat() if date_from else None)
    st.caption(f"{len(rows)} row(s) · newest first")

    if not rows:
        st.info("No content rows yet — generate one in tab 1 (or load a sample there).")
    else:
        labels = [f"#{r['id']}  {STATUS_EMOJI.get(r['status'], '·')} {r['status']}  ·  "
                  f"{(r['title'] or '(untitled)')[:60]}  ·  {r['created_at'][:16]}"
                  for r in rows]
        selectbox = st.selectbox("Select a row to review", options=labels, index=0)
        row = rows[labels.index(selectbox)]
        cid = row["id"]
        drafts = agent.drafts_from_row(row)

        meta1, meta2, meta3 = st.columns(3)
        meta1.markdown(f"**Status:** {STATUS_EMOJI.get(row['status'], '')} `{row['status']}`")
        meta2.markdown(f"**Approved at:** {row['approved_at'] or '—'}")
        meta3.markdown(f"**Approved hash:** `…{(row['approved_content_hash'] or '—')[:10]}`")

        editors = st.columns(3)
        for col, key in zip(editors, agent.CONTENT_KEYS):
            with col:
                st.subheader(CHANNEL_LABELS[key])
                col.text_area("Edit in place", key=f"ed_{cid}_{key}", value=drafts[key],
                              height=320, label_visibility="collapsed")

        st.markdown("**Channels to publish (checkboxes → included in the publish run)**")
        try:
            stored_channels = json.loads(row["selected_channels"] or "[]")
        except json.JSONDecodeError:
            stored_channels = []
        ch_cols = st.columns(3)
        selected = []
        for i, key in enumerate(agent.CONTENT_KEYS):
            if ch_cols[i].checkbox(CHANNEL_LABELS[key], key=f"ch_{cid}_{key}",
                                   value=key in stored_channels if stored_channels else True):
                selected.append(key)

        current = agent.content_hash(agent.drafts_from_row(row))
        matches = current == (row["approved_content_hash"] or "")
        st.caption(f"Current content hash: `{current[:10]}…` · "
                   + ("matches the approved hash" if matches else "differs from the approved hash"))

        b1, b2, b3, b4, b5 = st.columns(5)
        btn_approve = b1.button("✅ Approve & Publish", type="primary", key=f"btn_pub_{cid}",
                                help="Explicit human approval, then automated publish to the selected mock channels.")
        btn_save = b2.button("💾 Save edits only", key=f"btn_save_{cid}")
        btn_submit = b3.button("⏳ Submit for review", key=f"btn_rev_{cid}",
                               disabled=row["status"] not in ("DRAFT", "OUTDATED", "REJECTED"))
        btn_reject = b4.button("🚫 Reject", key=f"btn_rej_{cid}",
                               disabled=row["status"] == "PUBLISHED")
        btn_repub = b5.button("🔁 Re-publish", key=f"btn_repub_{cid}",
                              disabled=row["status"] not in ("APPROVED", "PUBLISHED"),
                              help="Idempotent: channels already published with the approved hash are skipped — no duplicates.")

        try:
            if btn_approve:
                edits = {key: st.session_state[f"ed_{cid}_{key}"] for key in agent.CONTENT_KEYS}
                agent.save_edits(cid, edits)      # persist what the reviewer sees
                agent.approve(cid, selected)      # explicit human approval (mandatory)
                st.session_state[f"pubres_{cid}"] = agent.publish(cid)
                st.rerun()
            if btn_save:
                edits = {key: st.session_state[f"ed_{cid}_{key}"] for key in agent.CONTENT_KEYS}
                status = agent.save_edits(cid, edits)
                st.session_state[f"pubres_{cid}"] = None
                if status == "OUTDATED":
                    st.session_state["outdated_msg"] = (
                        "Edits saved — status reset to **OUTDATED** 🔄. "
                        "This row must be re-approved before it can publish again.")
                st.rerun()
            if out_msg := st.session_state.get("outdated_msg"):
                if out_msg.startswith("Edits saved"):
                    st.warning(out_msg)
                    del st.session_state["outdated_msg"]
            if btn_submit:
                agent.submit_for_review(cid)
                st.rerun()
            if btn_reject:
                agent.reject(cid)
                st.session_state[f"pubres_{cid}"] = None
                st.rerun()
            if btn_repub:
                st.session_state[f"pubres_{cid}"] = agent.publish(cid)
                st.rerun()
        except (ApprovalError, agent.ContentError, LLMError) as exc:
            st.error(f"⚠️ {exc}")
        except requests.RequestException as exc:
            st.error(f"⚠️ Publishing API unreachable: {exc}")

        results = st.session_state.get(f"pubres_{cid}")
        if results:
            st.subheader("Publish results")
            for r in results:
                label = r["label"] or r["channel"]
                if r["status"] == "SUCCEEDED":
                    st.success(f"✅ **{label}** published → [{r['published_url']}]({r['published_url']})")
                elif r["status"] == "ALREADY_PUBLISHED":
                    st.info(f"ℹ️ **{label}** already published with this approved version "
                            f"— skipped, no duplicate ({r['published_url']})")
                else:
                    st.error(f"❌ **{label}** FAILED — {r['error']}")

        history = agent.publication_log(content_id=cid)
        if history:
            with st.expander(f"📜 Publication history for #{cid} ({len(history)})"):
                st.dataframe(history, width='stretch', hide_index=True)

# --------------------------------------------------------------------------- #
# Tab 3 · Publication Log                                                       #
# --------------------------------------------------------------------------- #

with tab3:
    st.header("Publication log")
    st.markdown("Every publish attempt (per channel): status, returned URL, timestamp, "
                "version (approved content hash prefix) and error messages.")

    l_status, l_date = st.columns(2)
    log_status = l_status.selectbox("Status", ["All", "SUCCEEDED", "FAILED", "ALREADY_PUBLISHED"], index=0)
    log_date = l_date.date_input("Published from (optional)", value=None)

    log_rows = agent.publication_log(
        status=None if log_status == "All" else log_status,
        created_since=log_date.isoformat() if log_date else None)

    if not log_rows:
        st.info("No publication attempts yet — approve & publish a row in tab 2.")
    else:
        import pandas as pd  # streamlit ships pandas; import here keeps startup light
        df = pd.DataFrame(log_rows)[[
            "id", "content_id", "channel", "version", "status",
            "published_url", "published_at", "error_message"]]
        st.dataframe(df, width='stretch', hide_index=True)
        st.download_button("⬇️ Export CSV", data=df.to_csv(index=False).encode("utf-8"),
                           file_name="publication_log.csv", mime="text/csv")
