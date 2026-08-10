from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SELECTIONS = (
    {
        "scholar_number": 344,
        "qazvini_ghani_number": 352,
        "main_filename": "v15-wikisource-ghazal-k344-api.json",
        "page_filename": "v15-wikisource-scan-page-372-api.json",
        "section": "p242-1",
        "scan_sequence": 372,
        "printed_page": 242,
        "incipit": "روزگاری شد که در میخانه خدمت می‌کنم",
        "scholar_citations": ["Lewis Hafez viii", "de Bruijn Hafez iii"],
    },
    {
        "scholar_number": 347,
        "qazvini_ghani_number": 355,
        "main_filename": "v15-wikisource-ghazal-k347-api.json",
        "page_filename": "v15-wikisource-scan-page-374-api.json",
        "section": "p244-1",
        "scan_sequence": 374,
        "printed_page": 244,
        "incipit": "حالیا مصلحت وقت در آن می‌بینم",
        "scholar_citations": ["Lewis Hafez viii", "de Bruijn Hafez iii"],
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare the private, pending V15 verse-to-scan collation packet."
    )
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--review-root", required=True, type=Path)
    args = parser.parse_args()

    raw_root = args.raw_root.resolve()
    review_root = args.review_root.resolve()
    review_root.mkdir(parents=True, exist_ok=True)

    sections: list[str] = [
        "# V15 human verse-to-scan collation packet",
        "",
        "This packet is pending human review. It does not approve a fixture and does "
        "not authorize source freeze. The Persian fixture must not be produced until "
        "every row is reviewed and the completed attestation is accepted by R13 Gate E.",
        "",
        "## Provenance layers (do not collapse)",
        "",
        "1. Textual/editorial basis: Qazvini–Ghani critical edition, first edition "
        "1320 SH / 1941.",
        "2. Physical printing behind the pinned scan: Sina, Tehran, 1989.",
        "3. Transcription route: Persian Wikisource index revision 290057; its "
        "Progress=T status is not a claim of full validation.",
        "",
        "## Selection rule",
        "",
        "The two candidates are the overlap of examples cited by Franklin Lewis "
        "(Hafez viii) and J. T. P. de Bruijn (Hafez iii): Khanlari numbers 344 "
        "and 347. They are mapped to the Qazvini–Ghani route by incipit, not by "
        "assuming numbering equivalence.",
        "",
        "The scan's errata page is scan sequence 531 (printed غلطنامه, revision "
        "112904). It lists no correction for printed pages 242 or 244. The reviewer "
        "must still inspect notes and visible variants on each selected page.",
    ]
    packet_records: list[dict[str, Any]] = []
    for selection in SELECTIONS:
        main_record = _revision(raw_root / selection["main_filename"])
        page_record = _revision(raw_root / selection["page_filename"])
        page_text = page_record["slots"]["main"]["content"]
        section_text = _section(page_text, selection["section"])
        verses = _verses(section_text)
        if not verses:
            raise ValueError(f"no verses parsed for Khanlari {selection['scholar_number']}")

        main_title = main_record["_title"]
        page_title = page_record["_title"]
        sections.extend(
            [
                "",
                f"## Khanlari {selection['scholar_number']} → Qazvini–Ghani "
                f"{selection['qazvini_ghani_number']}",
                "",
                f"- Incipit: {selection['incipit']}",
                f"- Scholar citations: {', '.join(selection['scholar_citations'])}",
                f"- Main transcription: `{main_title}`, revision "
                f"{main_record['revid']} ({main_record['timestamp']})",
                f"- Scan-backed Page record: `{page_title}`, revision "
                f"{page_record['revid']} ({page_record['timestamp']})",
                f"- Scan sequence: {selection['scan_sequence']}; printed page: "
                f"{selection['printed_page']}; transcluded section: "
                f"`{selection['section']}`",
                f"- Rendered scan page: "
                f"https://fa.wikisource.org/wiki/{page_title.replace(' ', '_')}",
                "",
                "| Verse | Pinned transcription | Scan agrees? | Discrepancy / "
                "editorial note |",
                "|---:|---|---|---|",
            ]
        )
        for index, verse in enumerate(verses, start=1):
            sections.append(f"| {index} | {verse} | ☐ |  |")

        packet_records.append(
            {
                **selection,
                "main_title": main_title,
                "main_revision": main_record["revid"],
                "main_revision_timestamp": main_record["timestamp"],
                "page_title": page_title,
                "page_revision": page_record["revid"],
                "page_revision_timestamp": page_record["timestamp"],
                "verse_count": len(verses),
            }
        )

    sections.extend(
        [
            "",
            "## Required attestation",
            "",
            "The reviewer must record their identity/date, check every verse against "
            "the rendered scan, inspect the errata entry set, list every discrepancy, "
            "and attest that no substantive variant was silently normalized. Blank "
            "or partial fields are a failed Gate E.",
        ]
    )
    packet_path = review_root / "V15-verse-to-scan-collation-packet.md"
    packet_path.write_text("\n".join(sections) + "\n", encoding="utf-8")

    attestation = {
        "schema_version": "thesisound.semantic-fixture-collation.v1",
        "artifact_id": "V15-hafez-qazvini-ghani-selection",
        "packet_filename": packet_path.name,
        "packet_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
        "source_fixture_created": False,
        "selections": packet_records,
        "reviewer": None,
        "reviewed_on": None,
        "every_selected_verse_checked": None,
        "errata_checked": None,
        "all_discrepancies_recorded": None,
        "no_substantive_variant_silently_normalized": None,
        "notes": None,
        "approval_status": "pending_human_review",
    }
    (review_root / "V15-collation-attestation.pending.json").write_text(
        json.dumps(attestation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def _revision(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    page = payload["query"]["pages"][0]
    revision = dict(page["revisions"][0])
    revision["_title"] = page["title"]
    return revision


def _section(text: str, name: str) -> str:
    match = re.search(
        rf'<section begin="{re.escape(name)}"/>(.*?)<section end="{re.escape(name)}"/>',
        text,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"missing transcluded section {name}")
    return match.group(1)


def _verses(section: str) -> list[str]:
    without_notes = re.sub(r"<ref>.*?</ref>", "", section, flags=re.DOTALL)
    verses = [
        f"{first.strip()} / {second.strip()}"
        for first, second in re.findall(
            r"\{\{ب\|(?:ش=[^|]+\|شچ=[^|]+\|)?(.*?)\|(.*?)\}\}",
            without_notes,
            flags=re.DOTALL,
        )
    ]
    half_lines = [
        value.strip()
        for value in re.findall(r"\{\{م\|(.*?)\}\}", without_notes, flags=re.DOTALL)
    ]
    if len(half_lines) % 2:
        raise ValueError("unpaired final hemistich in selected ghazal")
    verses.extend(
        f"{half_lines[index]} / {half_lines[index + 1]}"
        for index in range(0, len(half_lines), 2)
    )
    return verses


if __name__ == "__main__":
    raise SystemExit(main())
