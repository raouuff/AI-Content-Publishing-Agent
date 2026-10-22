# AI Content Generation & Automated Publishing Agent — Part 2

Prototype for the internship assessment (Part 2 of 2). Turns research project
updates — a project description, project update, findings summary, or event
announcement — into **three channel-tailored drafts**, runs them through a
**mandatory human approval gate**, and — **only after explicit approval** —
publishes them automatically via **real HTTP calls** to a local mock publishing
API (WordPress / LinkedIn / X), logging every attempt with status, URL,
timestamp and version.

> **Repo choice:** this is a **sibling folder** to the Part 1 repository
> (`ai-financial-assistant/`, located at `../AI-Powered Financial Management/`
> in this workspace). Both keep their own database (`content.db` vs
> `expenses.db`/`app.db`), their own UI, and share only the *contract* of the
> `services/llm.py` provider wrapper (Gemini default, OpenAI swappable via
> `.env`), so the two agents stay fully independent.

**No real social/WordPress credentials are used anywhere. All sample data is
fictional. Only `.env.example` is committed; the real `.env` is git-ignored.**

---

## Features

- **Content input:** title (optional) + raw research text in Streamlit (with
  4 fictional samples built in via `sample_content/`).
- **AI generation — ONE LLM call, structured JSON:**
  - `linkedin_post` — professional/engaging, ≤ ~1500 chars, 0–2 hashtags,
    outcomes-focused, no first-person filler;
  - `newsletter_summary` — 2–3 short stakeholder paragraphs;
  - `website_announcement` — structured article (headline, 2–4 paragraphs,
    optional bullets).
  Numbers, dates and names must be copied verbatim — no hallucination.
- **Content library:** SQLite `content.db` (auto-created), one row per input,
  full status lifecycle `DRAFT → PENDING_APPROVAL → APPROVED → PUBLISHED`,
  plus `REJECTED` / `OUTDATED`, with status + date filters.
- **Human approval gate (mandatory, code-enforced):** side-by-side review,
  inline editing of each version, per-channel checkboxes, *Approve & Publish /
  Save edits only / Submit for review / Reject*. **Any edit after approval
  resets the status to OUTDATED and the row cannot publish again until
  re-approved** — enforced by both workflow status and a SHA-256 content-hash
  comparison against the approved snapshot (fail closed).
- **Automated publishing (approval-triggered):** real `HTTP POST`s with JSON
  payloads + timeouts + try/except to the local mock API; returned URLs saved
  per channel; idempotent (unchanged re-publishes are no-ops, changed content
  publishes as a new version); per-channel success/failure shown immediately.
- **Publication log:** every attempt with status, returned URL, timestamp,
  version (content-hash prefix) and error message; **Export CSV**.
- **Tests:** `tests/test_publish_gate.py` — 8 tests proving the gate fails
  closed (nothing publishes before approval), edit-after-approval requires
  re-approval, hash-tampering is blocked, republish is a no-op, plus a live
  round-trip against the mock API.

## Repository layout

```
ai-content-publishing/
├── app_content.py                  # Streamlit app (3 tabs)
├── agents/content.py               # generate / approve / publish / log — plain functions
├── services/
│   ├── db_content.py               # ALL SQL (content.db, auto-created)
│   └── llm.py                      # LLM wrapper: Gemini default, OpenAI via .env
├── mock/
│   ├── wordpress.py                # LOCAL MOCK — WordPress REST API stand-in (POST /posts)
│   └── social.py                   # LOCAL MOCK — LinkedIn (/linkedin) + X (/x) stand-ins
├── scripts/
│   ├── run_mock_api.py             # starts the real HTTP mock service (:8001)
│   ├── generate_samples_content.py # writes the 4 fictional inputs to sample_content/
│   └── export_outputs_content.py   # writes outputs/: publication_log.csv + 3 samples
├── tests/test_publish_gate.py      # approval-gate tests (+ live mock round-trip)
├── sample_content/                 # fictional research inputs (generated)
├── outputs/                        # deliverable exports (generated)
├── docs/architecture_content.md    # architecture + Mermaid + evaluation mapping
└── requirements.txt · requirements-dev.txt · .env.example · .gitignore · README.md
```

## Setup

```bash
cd ai-content-publishing
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
#  edit .env: add a Gemini API key (free: https://aistudio.google.com/apikey)
```

`.env` keys: `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.8-flash`), optional
`LLM_PROVIDER=openai` + `OPENAI_API_KEY`, `MOCK_API_BASE`, `MOCK_API_PORT`,
`CONTENT_DB_PATH`. *(The default model is the one currently served by the Gemini
API — `gemini-2.5-flash` was retired for new users; any valid model name can be
entered.)*

## Run (two commands)

```bash
python scripts/run_mock_api.py     # terminal 1 — real mock HTTP service on :8001
streamlit run app_content.py       # terminal 2 — the agent UI
```

(The app's sidebar can also **auto-start** the mock API for a one-command demo.)

Optional scripts:

```bash
python scripts/generate_samples_content.py   # (re)create the fictional samples
pytest -q                                    # 8 tests — gate + live mock round-trip
python scripts/export_outputs_content.py     # refresh outputs/ deliverables
```

## Demo walkthrough (~3 min, Part 2 share of the single combined video)

1. **Tab 1** – *Load a fictional sample* → the findings summary that contains
   numbers **Generate three drafts** → show the three genuinely different
   versions; check `47 %, 2.1→2.8, 214, dates` copied exactly → **Save to
   content library**.
2. **Tab 2** – review the row side by side, edit a version, tick channels
   (or un-tick) → **✅ Approve & Publish** → three per-channel results with
   mock URLs; open the returned `http://127.0.0.1:8001/blog/<slug>` URL — the
   mock "site" really serves it.
3. **Gate in action** – edit an approved/published row → status flips to
   🔄 **OUTDATED** → try **Re-publish** → blocked by the approval gate →
   re-approve with the corrected text → publishes as a **new version**.
4. **Tab 3** – publication log: SUCCEEDED/FAILED rows, versions, timestamps,
   error messages (e.g. a real "mock API unreachable" failure row) →
   **Export CSV** → note `outputs/publication_log.csv` is created.

## Data model

- `content(id, title, source_text, linkedin_post, newsletter_summary,
  website_announcement, status, approved_at, approved_content_hash,
  selected_channels, created_at)`
- `publications(id, content_id, channel, status, published_url, published_at,
  error_message, content_hash)` — `content_hash` = the approved-content
  fingerprint used as the **version** marker in the log.

## Delivered sample outputs (`outputs/`)

- `publication_log.csv` – real log of publish attempts per channel
  (includes a genuine `FAILED` round captured when the mock API was briefly
  offline, plus the successful retry — real error handling, not staged).
- `linkedin_sample.md`, `newsletter_sample.md`, `website_sample.md` – the three
  channel-tailored drafts from a real Gemini run against the fictional
  "numbers must not be altered" sample (all numbers preserved verbatim).

## Limitations

See `docs/architecture_content.md` §10 — main ones: the mocks have no real
social reach (fake URLs, in-memory storage), text-only (no image uploads),
single approver, no scheduling; the newsletter channel reuses the mock `/x`
endpoint as its real HTTP round-trip target.

---

## Combined deliverables checklist (Parts 1 + 2)

| Deliverable | Where |
|---|---|
| One working prototype, both agents runnable | Part 1: `../AI-Powered Financial Management/` · Part 2: this repo |
| `.env.example` committed, real `.env` never committed | `.env.example` (+ `.gitignore` covers `.env`) |
| ONE combined demo video (≤5 min) | Part 1 ~2 min (upload → flags → tracker → summary), Part 2 ~3 min (see walkthrough above) |
| `expense_tracker.csv`, `financial_summary.md` | Part 1: `exports/` in the sibling repo |
| `publication_log.csv` + 3 content samples | Part 2: `outputs/` here |
| Both architecture docs | Part 1: `docs/ARCHITECTURE.md` · Part 2: `docs/architecture_content.md` |

## Requirement → file map (Part 2)

| Requirement | Implemented in |
|---|---|
| Content input (title + body, 4 kinds) | `app_content.py` (Tab 1), `sample_content/*.md` |
| ONE LLM call → 3 tailored drafts, no invented facts | `services/llm.py` + `agents/content.py` (`generate_drafts`, schema + system prompt) |
| LLM failure / malformed JSON errors | `services/llm.py` (`chat_json`, `_parse_json`), `app_content.py` error banners |
| Content rows + statuses + filters | `services/db_content.py`, `app_content.py` (Tab 2 filters) |
| Side-by-side view, inline edit, channel checkboxes | `app_content.py` (Tab 2) |
| Approve & Publish / Save edits / Reject / Submit | `app_content.py` buttons → `agents/content.py` (`approve`, `save_edits`, `reject`, `submit_for_review`) |
| Edit-after-approval → OUTDATED → re-approve | `agents/content.py` (`save_edits`, `assert_approval_gate`) + `tests/test_publish_gate.py` |
| Content-hash check, fail-closed publishing | `agents/content.py` (`content_hash`, `assert_approval_gate`) + tests |
| Real HTTP publish only on approval | `agents/content.py` (`publish`, `_post_json`), `mock/*.py`, `scripts/run_mock_api.py` |
| Publications table (status/URL/timestamp/error) | `services/db_content.py` (`record_publication`, …) |
| Republish no-op / new version after change | `agents/content.py` (`publish`) + `test_republish_unchanged_content_is_a_noop` |
| Publication log tab + CSV export | `app_content.py` (Tab 3), `scripts/export_outputs_content.py` |
| Mock API as real running HTTP service | `scripts/run_mock_api.py`, `mock/wordpress.py`, `mock/social.py` (+ live test) |
| Fictional sample data (incl. protected numbers) | `scripts/generate_samples_content.py` → `sample_content/` |
| Architecture + Mermaid + rationale + eval mapping | `docs/architecture_content.md` |
