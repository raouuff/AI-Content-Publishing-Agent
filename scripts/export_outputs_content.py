"""Export Part 2 deliverables to outputs/.

Writes:
  outputs/publication_log.csv    — every recorded publication attempt
  outputs/linkedin_sample.md     — per-channel sample from the newest complete row
  outputs/newsletter_sample.md
  outputs/website_sample.md

Run after the app has generated/published at least one item:
    python scripts/export_outputs_content.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import content as agent  # noqa: E402
from services import db_content as db  # noqa: E402

OUT = ROOT / "outputs"

CHANNEL_FILES = {
    "linkedin_post": "linkedin_sample.md",
    "newsletter_summary": "newsletter_sample.md",
    "website_announcement": "website_sample.md",
}

HEADER_NOTE = (
    "<!-- Generated sample output of the Part 2 agent. All data is fictional. -->\n\n"
)


def main() -> None:
    db.init_db()
    OUT.mkdir(exist_ok=True)

    # 1) Publication log CSV
    pubs = agent.publication_log()  # newest first, includes `version` column
    with (OUT / "publication_log.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["publication_id", "content_id", "channel", "version",
                         "status", "published_url", "published_at", "error_message"])
        for row in pubs:
            writer.writerow([
                row["id"], row["content_id"], row["channel"], row.get("version", ""),
                row["status"], row["published_url"] or "", row["published_at"],
                row["error_message"] or ""])
    print(f"outputs/publication_log.csv  ({len(pubs)} attempt rows)")

    # 2) Newest content row that has all three drafts -> per-channel samples
    newest_complete = next(
        (r for r in db.list_contents()
         if all((agent.drafts_from_row(r)[k] or "").strip() for k in agent.CONTENT_KEYS)),
        None)
    if newest_complete is None:
        print("No generated content found yet — run the app once to generate drafts, "
              "then run this script again. (Channel samples skipped.)")
        return
    drafts = agent.drafts_from_row(newest_complete)
    source_title = newest_complete["title"]
    cid = newest_complete["id"]
    for key, filename in CHANNEL_FILES.items():
        (OUT / filename).write_text(
            f"{HEADER_NOTE}**Content #{cid} · title:** {source_title}\n\n---\n\n{drafts[key]}\n",
            encoding="utf-8")
        print(f"outputs/{filename}  (from content #{cid})")

    print("\nDone — deliverables in outputs/.")


if __name__ == "__main__":
    main()
