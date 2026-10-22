"""Create 4 FICTIONAL research inputs in sample_content/.

These are demo inputs of the four accepted kinds: project description, project
update, findings summary, event announcement. One sample deliberately contains
numbers/dates (47%, 2.1→2.8 percent, 12 plots, 214 observations, dates) that the
LLM must copy EXACTLY without altering.

All content is fictional. No confidential or personal data is used.

Run:  python scripts/generate_samples_content.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "sample_content"

SAMPLES: dict[str, str] = {
    "01_project_update_solarsense_pilot.md": """\
Update: SolarSense smart-irrigation pilot

Work on the SolarSense pilot continued this month. The team finished assembling
the second sensor enclosure and installed it at the Ashfield community garden,
so both now run the same watering-schedule logic fully on the local controller
without the cloud shortcut used during early testing.

Volunteer feedback has been positive, mostly about the simple daybreak schedule
that waters early in the morning and leaves afternoons dry. Next month the team
will review the logs from both gardens and decide whether to extend the pilot
to a nearby school garden. No blockers to report.
""",
    "02_findings_summary_soil_fungus_numbers.md": """\
Findings summary: beneficial soil fungus field trial

Across 12 monitoring plots, wheat seedlings treated with the beneficial soil
fungus R. irregularis showed a 47 percent higher germination rate than the
untreated control plots by day 14. Soil organic carbon in the treated plots
rose from 2.1 percent to 2.8 percent over the 90-day trial that ran from
March 3 to June 15, 2025.

The team logged 214 field observations in total. Dr. Lena Farid will present
the interim results in a 20-minute talk at the regional agronomy meeting.
The full report and cleaned dataset will be shared internally once quality
checks finish in early October.
""",
    "03_event_announcement_open_data_workshop.md": """\
Event announcement: Open Research Data Walkthrough

The research office will host Open Research Data Walkthrough, a one-day,
hands-on workshop on Saturday, April 18, 2026, in Novida Hall on the east
campus. Sessions cover planning research data management, choosing licenses
for research outputs, and publishing datasets with DOIs.

Attendance is free for member organizations and registration closes on
April 10, 2026. Bring your own laptop; coffee and lunch are provided.
The detailed program and room plan will be distributed two weeks before
the event.
""",
    "04_project_description_songbirdnet.md": """\
Project description: SongbirdNet — low-cost bioacoustic monitoring

SongbirdNet is a research project building an open, low-cost toolkit for
long-term bioacoustic monitoring of farmland bird communities. It designs
weatherproof recorder units from off-the-shelf parts, ships an open-source
pipeline that turns raw audio recordings into species-presence tables, and
publishes its hardware schematics and detection models under permissive
licenses.

A small volunteer network of farms and schoolyards hosts the recorders.
The team is currently looking for collaborations with ornithology groups
interested in expanding long-term monitoring coverage.
""",
}


def main() -> None:
    DEST.mkdir(exist_ok=True)
    for name, text in SAMPLES.items():
        (DEST / name).write_text(text, encoding="utf-8")
        print(f"  wrote sample_content/{name}")
    print(f"\nDone — {len(SAMPLES)} fictional samples in {DEST.name}/.")


if __name__ == "__main__":
    main()
