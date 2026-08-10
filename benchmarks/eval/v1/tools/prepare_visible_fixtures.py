from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader, PdfWriter

from thesisound.services.semantic_fixture_validation import (
    canonicalize_semantic_text,
    validate_semantic_fixture,
)


class _ProofreadPageText(HTMLParser):
    _BLOCKS = frozenset({"br", "div", "h1", "h2", "h3", "h4", "li", "p", "section"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capture_depth: int | None = None
        self.depth = 0
        self.skip_depth: int | None = None
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div" and "prp-pages-output" in classes:
            self.capture_depth = self.depth
        if self.capture_depth is not None and self.skip_depth is None:
            if tag in {"style", "script"} or classes & {"ws-noexport", "pagenum", "mw-editsection"}:
                self.skip_depth = self.depth
            elif tag in self._BLOCKS:
                self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.capture_depth is not None and self.skip_depth is None and tag in self._BLOCKS:
            self.parts.append("\n")
        if self.skip_depth == self.depth:
            self.skip_depth = None
        if self.capture_depth == self.depth:
            self.capture_depth = None
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capture_depth is not None and self.skip_depth is None:
            self.parts.append(data)

    def text(self) -> str:
        return _clean_text("".join(self.parts))


class _HtmlText(HTMLParser):
    """Extract substantive HTML text without navigation/style metadata."""

    _BLOCKS = frozenset({"br", "dd", "div", "dt", "h1", "h2", "h3", "h4", "li", "p", "section"})

    def __init__(
        self,
        *,
        neutralize_headings: bool = False,
        excluded_tags: frozenset[str] = frozenset(),
        excluded_classes: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip_depth: int | None = None
        self.parts: list[str] = []
        self.neutralize_headings = neutralize_headings
        self.heading_depth: int | None = None
        self.heading_count = 0
        self.excluded_tags = excluded_tags
        self.excluded_classes = excluded_classes

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self.skip_depth is None and (
            tag in {"style", "script", "nav"} | self.excluded_tags
            or classes
            & {
                "ws-noexport",
                "mw-editsection",
                "navbox",
                "noprint",
                *self.excluded_classes,
            }
        ):
            self.skip_depth = self.depth
        elif self.skip_depth is None and tag in self._BLOCKS:
            self.parts.append("\n")
        is_semantic_heading = tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or (
            tag == "span" and "section_title" in classes
        )
        if self.skip_depth is None and self.neutralize_headings and is_semantic_heading:
            self.heading_count += 1
            self.heading_depth = self.depth
            self.parts.append(f"Section {self.heading_count:02d}")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth is None and tag in self._BLOCKS:
            self.parts.append("\n")
        if self.skip_depth == self.depth:
            self.skip_depth = None
        if self.heading_depth == self.depth:
            self.heading_depth = None
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth is None and self.heading_depth is None:
            self.parts.append(data)

    def text(self) -> str:
        return _clean_text("".join(self.parts))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare scoped visible-case fixtures from pinned raw acquisitions."
    )
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--review-root",
        type=Path,
        default=None,
        help="Optional private output directory for artifact-bound human-review packets",
    )
    args = parser.parse_args()
    raw = args.raw_root.resolve()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)

    c02_text, c02_transform = _prepare_putnam(raw)
    c02_path = output / "C02-putnam-canonical.md"
    _write_text(c02_path, c02_text)
    if args.review_root is not None:
        review_root = args.review_root.resolve()
        review_root.mkdir(parents=True, exist_ok=True)
        _write_c02_review_packet(
            raw / "c02-putnam.pdf",
            c02_path,
            review_root,
            transformation=c02_transform,
        )

    _write_text(output / "C01-james-will-to-believe.txt", _prepare_james(raw))
    _write_text(output / "C03-woolf-room-complete.md", _prepare_woolf(raw))
    _write_text(output / "C04-dubois-primary.md", _prepare_dubois(raw))
    _write_text(output / "C04-dubois-strivings-1897.md", _prepare_atlantic_strivings(raw))
    _write_text(output / "C04-sep-sections-2.3-and-3.md", _prepare_sep(raw))
    _write_text(output / "C08-douglass-speech-neutralized.md", _prepare_wiki_article(
        raw / "c08-douglass-wikisource.json",
        title="Source A",
        neutralize_headings=True,
    ))
    _write_text(output / "C08-nps-decoy-neutralized.md", _prepare_nps_decoy(raw))
    _write_text(output / "C08-loc-context-neutralized.md", _prepare_loc_decoy(raw))
    _write_text(
        output / "C08-nara-declaration-neutralized.md",
        _prepare_nara_declaration_decoy(raw),
    )
    _write_text(output / "C07-bloom-rct.md", _prepare_bloom(raw))
    _write_text(output / "C09-darwin-scoped.md", _prepare_darwin(raw))

    _copy_scoped_pdf(
        raw / "c06-cmepsp.pdf",
        output / "C06-cmepsp-focused.pdf",
        selector=_commission_pages,
    )
    _write_text(
        output / "C06-oecd-hows-life-2020-focused.md",
        _prepare_oecd_2020(raw),
    )
    return 0


def _prepare_james(raw: Path) -> str:
    text = (raw / "james-pg26659.txt").read_text(encoding="utf-8-sig")
    start = _after(text, "\nTHE WILL TO BELIEVE.[1]\n")
    end = text.index("\nIS LIFE WORTH LIVING?[1]\n", start)
    return "THE WILL TO BELIEVE\n\n" + _clean_text(text[start:end]) + "\n"


def _prepare_woolf(raw: Path) -> str:
    chapters: list[str] = ["# A Room of One's Own\n"]
    for number in range(1, 7):
        payload = json.loads(
            (raw / f"c03-woolf-chapter-{number}.json").read_text(encoding="utf-8")
        )
        page = _ProofreadPageText()
        page.feed(payload["parse"]["text"])
        text = page.text()
        if len(text) < 2_000:
            raise ValueError(f"Wikisource chapter {number} did not yield substantive text")
        chapters.extend((f"## Chapter {number}\n", text, ""))
    return "\n\n".join(chapters).strip() + "\n"


def _prepare_putnam(raw: Path) -> tuple[str, dict[str, object]]:
    """Build an auditable canonical text derivative from the publisher PDF.

    This is structural, source-independent PDF preprocessing: top-margin running
    furniture is removed after coordinate confirmation, page-bottom note apparatus
    is collected at the end so it cannot interrupt a paragraph crossing a page, and
    the shared R13 canonicalizer removes only isolated no-identity marks. No word is
    substituted and no OCR is used.
    """

    reader = PdfReader(raw / "c02-putnam.pdf", strict=False)
    if len(reader.pages) != 31:
        raise ValueError("Unexpected Putnam PDF page count; review before preparing")
    body_pages: list[str] = []
    notes: list[str] = []
    body_texts: list[str] = []
    note_texts: list[str] = []
    removed_running_heads: list[dict[str, int]] = []
    note_pages: list[int] = []
    extracted_parts: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if len(page_text.strip()) < 100:
            raise ValueError(f"Putnam source page {page_number} has no substantive text")
        lines = page_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        top_margin_line_count = _top_margin_line_count(page) if page_number > 1 else 0
        if top_margin_line_count:
            lines = lines[top_margin_line_count:]
            removed_running_heads.append(
                {"page": page_number, "line_count": top_margin_line_count}
            )
        split = next(
            (
                index
                for index, line in enumerate(lines)
                if not line.strip() and len(line) >= 40
            ),
            None,
        )
        if split is None:
            body_lines = lines
            note_lines: list[str] = []
        else:
            body_lines = lines[:split]
            note_lines = lines[split + 1 :]
        body = _clean_text("\n".join(body_lines))
        if body:
            body_pages.extend((f"## Source PDF page {page_number}", body, ""))
            body_texts.append(body)
            extracted_parts.append(body)
        note_text = _clean_text("\n".join(note_lines))
        if note_text:
            note_pages.append(page_number)
            notes.extend((f"### Source PDF page {page_number} notes", note_text, ""))
            note_texts.append(note_text)
            extracted_parts.append(note_text)

    assembled = "\n".join(
        [
            "# Putnam article — canonical text derivative",
            "",
            *body_pages,
            "## Collected page notes",
            "",
            *notes,
        ]
    ).strip()
    canonical, canonicalization = canonicalize_semantic_text(assembled)
    if canonicalization["residual_code_points"]:
        raise ValueError("Putnam derivative has non-canonicalizable code-point residue")
    source_text = "\n\n".join(extracted_parts)
    source_canonical, source_canonicalization = canonicalize_semantic_text(source_text)
    source_words = re.findall(r"\S+", source_canonical)
    prepared_substantive, _ = canonicalize_semantic_text(
        "\n\n".join([*body_texts, *note_texts])
    )
    prepared_words = re.findall(r"\S+", prepared_substantive)
    # Moving apparatus changes order, but must not add, remove, or rewrite a word.
    # Counter equality is auditable and stronger than comparing two approximate
    # counts that could conceal offsetting losses and additions.
    if not source_words:
        raise ValueError("Putnam derivative unexpectedly has no source words")
    if Counter(source_words) != Counter(prepared_words):
        raise ValueError("Putnam structural preprocessing changed substantive words")
    return canonical.strip() + "\n", {
        "method": "native pypdf text extraction; no OCR",
        "removed_running_head_pages": removed_running_heads,
        "collected_page_note_pages": note_pages,
        "canonicalization": source_canonicalization,
        "source_word_count": len(source_words),
        "prepared_non_locator_word_count": len(prepared_words),
    }


def _top_margin_line_count(page) -> int:
    top_line_positions: set[float] = set()

    def visit(text, _cm, tm, _font, font_size) -> None:
        y = float(tm[5])
        if text.strip() and y >= 685 and float(font_size) <= 11.5:
            top_line_positions.add(round(y, 1))

    page.extract_text(visitor_text=visit)
    return len(top_line_positions)


def _prepare_dubois(raw: Path) -> str:
    text = _strip_gutenberg_back_matter((raw / "dubois-pg408.txt").read_text(encoding="utf-8-sig"))
    markers = list(re.finditer(r"(?m)^([IVX]+)\.\s*$", text))
    chapters: dict[str, str] = {}
    for index, marker in enumerate(markers):
        roman = marker.group(1)
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        chapters[roman] = _clean_text(text[marker.start():end])
    missing = {"I", "III", "XIV"} - chapters.keys()
    if missing:
        raise ValueError(f"Du Bois chapter markers missing: {sorted(missing)}")
    return (
        "# The Souls of Black Folk — primary scope\n\n"
        + "\n\n".join(chapters[key] for key in ("I", "III", "XIV"))
        + "\n"
    )


def _prepare_wiki_article(
    path: Path,
    *,
    title: str,
    neutralize_headings: bool = False,
) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_html = payload["parse"]["text"]
    if neutralize_headings:
        source_html = _neutralize_wikisource_centered_headings(source_html)
    parser = _HtmlText(neutralize_headings=neutralize_headings)
    parser.feed(source_html)
    text = parser.text()
    if len(text) < 2_000:
        raise ValueError(f"Wikisource article {path.name} did not yield substantive text")
    return f"# {title}\n\n{text}\n"


def _neutralize_wikisource_centered_headings(source_html: str) -> str:
    """Replace only short centered labels, preserving centered quotations."""
    pattern = re.compile(
        r'<div[^>]*class="[^"]*wst-center[^"]*"[^>]*>(.*?)</div>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        visible = html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))
        visible = _clean_inline(visible)
        # The first centered container is the document-form label ("Oration").
        # Other semantic headings are uppercase and short. Quoted epigraphs are
        # deliberately retained as substantive source text.
        is_heading = count == 0 or (
            len(visible) <= 80
            and any(character.isalpha() for character in visible)
            and visible == visible.upper()
            and not visible.startswith(("“", '"'))
        )
        if not is_heading:
            return match.group(0)
        count += 1
        return f"<h2>Section {count:02d}</h2>"

    return pattern.sub(replace, source_html)


def _prepare_atlantic_strivings(raw: Path) -> str:
    html = (raw / "c04-strivings-atlantic.html").read_text(encoding="utf-8")
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if match is None:
        raise ValueError("The pinned Atlantic page has no __NEXT_DATA__ payload")
    payload = json.loads(match.group(1))
    candidate_lists: list[list[dict[str, object]]] = []

    def visit(value: object) -> None:
        if isinstance(value, str) and value.startswith(("{", "[")):
            try:
                visit(json.loads(value))
            except json.JSONDecodeError:
                return
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            article_items = [
                item
                for item in value
                if isinstance(item, dict)
                and isinstance(item.get("innerHtml"), str)
                and str(item.get("__typename", "")).startswith("Article")
            ]
            if len(article_items) >= 10:
                candidate_lists.append(article_items)
            for child in value:
                visit(child)

    visit(payload)
    if not candidate_lists:
        raise ValueError("The pinned Atlantic payload has no substantive article body")
    items = max(candidate_lists, key=len)
    parts: list[str] = []
    for item in items:
        parser = _HtmlText()
        parser.feed(str(item["innerHtml"]))
        value = parser.text()
        if value:
            parts.append(value)
    result = _clean_text("\n\n".join(parts))
    if len(result) < 10_000:
        raise ValueError("The Atlantic primary extraction was unexpectedly short")
    return "# Strivings of the Negro People (1897)\n\n" + result + "\n"


def _prepare_sep(raw: Path) -> str:
    html = (raw / "c04-sep.html").read_text(encoding="utf-8")
    sections = [
        _html_between(html, '<h3 id="DeflRead">', '<h3 id="AnalPoliPhilReco">'),
        _html_between(
            html,
            '<h2 id="DoubConsSoulBlacFolkProb">',
            '<h2 id="DuBoisDoubConsAfteSoul">',
        ),
    ]
    return "# Double Consciousness — bounded SEP commentary\n\n" + "\n\n".join(sections) + "\n"


def _prepare_nps_decoy(raw: Path) -> str:
    html = (raw / "c08-nps.html").read_text(encoding="utf-8")
    start = html.index('<h1 class="page-title">')
    end = html.index('<div class="Component RelatedGrid"', start)
    parser = _HtmlText(
        neutralize_headings=True,
        excluded_tags=frozenset({"figure"}),
        excluded_classes=frozenset({"Person__Facts"}),
    )
    parser.feed(html[start:end])
    text = parser.text()
    if len(text) < 8_000:
        raise ValueError("The pinned NPS decoy extraction was unexpectedly short")
    return "# Source B\n\n" + text + "\n"


def _prepare_loc_decoy(raw: Path) -> str:
    root = ElementTree.fromstring((raw / "c08-loc-july-2020-feed.xml").read_bytes())
    content_tag = "{http://purl.org/rss/1.0/modules/content/}encoded"
    matches = []
    for item in root.findall("./channel/item"):
        link = item.findtext("link") or ""
        if "what-to-the-american-slave-is-your-4th-of-july" in link:
            matches.append(item)
    if len(matches) != 1:
        raise ValueError(f"Expected one LoC RSS item; found {len(matches)}")
    source_html = matches[0].findtext(content_tag) or ""
    parser = _HtmlText(
        neutralize_headings=True,
        excluded_tags=frozenset({"figure"}),
    )
    parser.feed(source_html)
    text = parser.text()
    if len(text) < 4_500:
        raise ValueError("The pinned LoC contextual article was unexpectedly short")
    return "# Source C\n\n" + text + "\n"


def _prepare_nara_declaration_decoy(raw: Path) -> str:
    source_html = (raw / "c08-nara-declaration.html").read_text(encoding="utf-8")
    start = source_html.index("<h1>Declaration of Independence: A Transcription</h1>")
    end = source_html.index("Back to Main Declaration Page", start)
    # Cut at the containing paragraph rather than retain a partial anchor.
    end = source_html.rfind("<p", start, end)
    parser = _HtmlText(
        neutralize_headings=True,
        excluded_tags=frozenset({"figure"}),
    )
    parser.feed(source_html[start:end])
    text = parser.text()
    if len(text) < 7_000:
        raise ValueError("The pinned National Archives transcript was unexpectedly short")
    return "# Source D\n\n" + text + "\n"


def _write_c02_review_packet(
    source_pdf: Path,
    prepared_fixture: Path,
    review_root: Path,
    *,
    transformation: dict[str, object],
) -> None:
    required_pages = (1, 3, 4, 12, 18, 31)
    reader = PdfReader(source_pdf, strict=False)
    prepared = prepared_fixture.read_text(encoding="utf-8")
    validation = validate_semantic_fixture(
        prepared_fixture,
        artifact_id="C02-putnam-canonical",
        expected_language="fa",
        intended_scope="complete Putnam article review packet binding",
    )
    fixture_hash = validation.production_text_parity[
        "production_ingested_normalized_text_sha256"
    ]
    sections = [
        "# C02 Gate E human reading-order collation packet",
        "",
        "This packet does not record approval. It binds a fluent-reader review to the "
        "exact canonical derivative that R13 and the semantic pipeline ingest.",
        "",
        "- Artifact ID: `C02-putnam-canonical`",
        f"- Fixture: `{prepared_fixture}`",
        f"- Normalized fixture SHA-256: `{fixture_hash}` (diagnostic binding, not freeze)",
        f"- Source PDF: `{source_pdf}` (private/offline; do not redistribute)",
        "- Required pages: 1, 3, 4, 12, 18, 31",
        "- Review the rendered PDF page and both text views for every page.",
        "",
        "For each required page, attest only after checking: body reading order; "
        "paragraph continuation across page breaks; footnote and running-head separation; "
        "and whether Persian remains meaning-preserving despite zero ZWNJ in extraction.",
        "",
        "## Deterministic transformation record",
        "",
        "```json",
        json.dumps(transformation, ensure_ascii=False, indent=2),
        "```",
    ]
    for page_number in required_pages:
        raw_text = reader.pages[page_number - 1].extract_text() or ""
        page_marker = f"## Source PDF page {page_number}"
        next_marker = f"## Source PDF page {page_number + 1}"
        start = prepared.find(page_marker)
        end = prepared.find(next_marker, start + 1) if start >= 0 else -1
        prepared_page = (
            prepared[start : end if end >= 0 else len(prepared)] if start >= 0 else "MISSING"
        )
        sections.extend(
            (
                "",
                f"## Review item: source PDF page {page_number}",
                "",
                f"Open physical PDF page {page_number} in `{source_pdf}`.",
                "",
                "### Native extraction before furniture separation",
                "",
                "```text",
                raw_text.strip(),
                "```",
                "",
                "### Canonical derivative view",
                "",
                "```text",
                prepared_page.strip(),
                "```",
                "",
                "Reviewer notes: ________________________________________________",
            )
        )
    packet_path = review_root / "C02-gate-e-review-packet.md"
    _write_text(packet_path, "\n".join(sections).strip() + "\n")
    packet_sha256 = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    attestation = {
        "schema_version": "thesisound.semantic-fixture-collation.v1",
        "artifact_id": "C02-putnam-canonical",
        "packet_filename": packet_path.name,
        "packet_sha256": packet_sha256,
        "fixture_normalized_text_sha256": fixture_hash,
        "reviewer": None,
        "reviewed_on": None,
        "pages_checked": [],
        "reading_order_correct": None,
        "footnote_and_margin_separation_correct": None,
        "script_rendering_correct": None,
        "zwnj_loss_meaning_preserving": None,
        "notes": None,
        "approval_status": "pending_human_review",
    }
    _write_text(
        review_root / "C02-gate-e-attestation.pending.json",
        json.dumps(attestation, ensure_ascii=False, indent=2) + "\n",
    )


def _html_between(html: str, start_marker: str, end_marker: str) -> str:
    start = html.index(start_marker)
    end = html.index(end_marker, start)
    parser = _HtmlText()
    parser.feed(html[start:end])
    result = parser.text()
    if len(result) < 1_000:
        raise ValueError(f"Bounded HTML section unexpectedly short: {start_marker}")
    return result


def _prepare_bloom(raw: Path) -> str:
    root = ElementTree.fromstring((raw / "c07-bloom.xml").read_bytes())
    body = next((element for element in root.iter() if _local(element.tag) == "body"), None)
    if body is None:
        raise ValueError("Europe PMC payload has no article body")
    parts = ["# Hybrid working from home improves retention without damaging performance", ""]
    for element in body.iter():
        tag = _local(element.tag)
        if tag not in {"title", "p"}:
            continue
        text = _clean_inline("".join(element.itertext()))
        if not text:
            continue
        if tag == "title":
            parts.extend((f"## {text}", ""))
        else:
            parts.extend((text, ""))
    result = "\n".join(parts).strip() + "\n"
    if len(result) < 10_000:
        raise ValueError("Europe PMC body extraction was unexpectedly short")
    return result


def _prepare_darwin(raw: Path) -> str:
    text = _strip_gutenberg_back_matter(
        (raw / "darwin-pg1228.txt").read_text(encoding="utf-8-sig")
    )
    index = re.search(r"(?m)^INDEX\.?\s*$", text)
    if index is not None:
        text = text[: index.start()]
    markers = [
        match
        for match in re.finditer(r"(?m)^CHAPTER ([IVX]+)\.\s*$", text)
        if match.start() > 10_000
    ]
    chapters: dict[str, str] = {}
    for index, marker in enumerate(markers):
        roman = marker.group(1)
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        chapters[roman] = _clean_text(text[marker.start():end])
    selected = ("I", "II", "III", "IV", "VI", "XIV")
    missing = set(selected) - chapters.keys()
    if missing:
        raise ValueError(f"Darwin chapter markers missing: {sorted(missing)}")
    return "# On the Origin of Species — 1859 scoped chapters\n\n" + "\n\n".join(
        chapters[key] for key in selected
    ) + "\n"


def _commission_pages(reader: PdfReader) -> list[int]:
    # Physical PDF pages 7-18 are the complete executive summary. Pages 41-60
    # are the complete short-narrative framework chapter on quality of life.
    # The fixed indices are intentional and are recorded in the acquisition manifest.
    if len(reader.pages) != 292:
        raise ValueError("Unexpected CMEPSP page count; review the pinned edition before slicing")
    _require_page_text(reader, 6, "EXECUTIVE SUMMARY")
    _require_page_text(reader, 40, "QUALITY OF LIFE")
    return [*range(6, 18), *range(40, 60)]


def _prepare_oecd_2020(raw: Path) -> str:
    """Build the C06 OECD complement without OCR or glyph-specific repair.

    Whole printed-page ranges retain the framework/current-well-being section and
    the sustainability/resources section while keeping the replacement within 10%
    of the rejected candidate's R13 token count. The shared R13 canonicalizer may
    remove only isolated no-identity page furniture; every source word is retained.
    """

    source = raw / "c06-oecd-hows-life-2020.pdf"
    reader = PdfReader(source, strict=False)
    if len(reader.pages) != 247:
        raise ValueError("Unexpected How's Life? 2020 page count; review before preparing C06")

    required_pages = {
        19: "How’s Life? in OECD countries",
        23: "How’s Life in the OECD?",
        44: "How sustainable is well-being going forward?",
        56: "References",
    }
    for index, marker in required_pages.items():
        _require_page_text(reader, index, marker)

    indices = [*range(19, 32), *range(44, 57)]
    printed_pages = [*range(18, 31), *range(43, 56)]
    output = ["# How's Life? 2020: Measuring Well-being", ""]
    dropped = Counter()

    for index, printed_page in zip(indices, printed_pages, strict=True):
        extracted = reader.pages[index].extract_text() or ""
        canonical, report = canonicalize_semantic_text(extracted)
        if report["residual_code_points"] or not report["word_sequence_preserved"]:
            raise ValueError(
                f"How's Life? 2020 source page {index + 1} needs forbidden repair"
            )
        dropped.update(
            {
                item["code_point"]: item["count"]
                for item in report["dropped_code_points"]
            }
        )
        output.extend(
            (
                f"## Printed page {printed_page} (source PDF page {index + 1})",
                "",
                canonical.strip(),
                "",
            )
        )

    expected_dropped = Counter({"U+F07C UNNAMED": 26, "U+F0B7 UNNAMED": 3})
    if dropped != expected_dropped:
        raise ValueError(f"Unexpected How's Life? 2020 page-furniture profile: {dropped}")
    return "\n".join(output).rstrip() + "\n"


def _require_page_text(reader: PdfReader, index: int, needle: str) -> None:
    text = reader.pages[index].extract_text() or ""
    if needle.casefold() not in text.casefold() or len(text) < 1_000:
        raise ValueError(f"Pinned PDF page {index + 1} no longer contains: {needle}")


def _copy_scoped_pdf(source: Path, destination: Path, *, selector) -> None:
    reader = PdfReader(source, strict=False)
    indices = selector(reader)
    if not indices:
        raise ValueError(f"No scoped pages selected from {source.name}")
    writer = PdfWriter()
    for index in indices:
        writer.add_page(reader.pages[index])
    writer.add_metadata(
        {
            "/Title": f"Scoped semantic fixture from {source.name}",
            "/ThesisoundSourcePageIndices": ",".join(str(index + 1) for index in indices),
        }
    )
    with destination.open("wb") as handle:
        writer.write(handle)


def _strip_gutenberg_back_matter(text: str) -> str:
    """Cut the Project Gutenberg licence before any chapter is sliced out.

    A chapter selector that runs "from this marker to end of file" swallows
    everything after the last chapter. That put the PG licence into the Du Bois
    primary fixture and the licence plus the book index into the Darwin fixture,
    where they inflated the coverage denominator and stood ready to be extracted
    as if they were source evidence.
    """

    end = re.search(r"(?m)^\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", text)
    if end is None:
        raise ValueError("Project Gutenberg end marker not found; check the pinned download")
    return text[: end.start()]


def _after(text: str, marker: str) -> int:
    return text.index(marker) + len(marker)


def _clean_text(text: str) -> str:
    value = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [_clean_inline(line) for line in value.splitlines()]
    output: list[str] = []
    blank = False
    for line in lines:
        if line:
            output.append(line)
            blank = False
        elif not blank and output:
            output.append("")
            blank = True
    return "\n".join(output).strip()


def _clean_inline(text: str) -> str:
    return re.sub(r"[ \t\f\v]+", " ", text).strip()


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


if __name__ == "__main__":
    raise SystemExit(main())
