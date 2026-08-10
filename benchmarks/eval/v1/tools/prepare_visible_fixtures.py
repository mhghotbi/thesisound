from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader, PdfWriter


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

    def __init__(self, *, neutralize_headings: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip_depth: int | None = None
        self.parts: list[str] = []
        self.neutralize_headings = neutralize_headings
        self.heading_depth: int | None = None
        self.heading_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self.skip_depth is None and (
            tag in {"style", "script", "nav"}
            or classes & {"ws-noexport", "mw-editsection", "navbox", "noprint"}
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
    args = parser.parse_args()
    raw = args.raw_root.resolve()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)

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
    _write_text(output / "C07-bloom-rct.md", _prepare_bloom(raw))
    _write_text(output / "C09-darwin-scoped.md", _prepare_darwin(raw))

    _copy_scoped_pdf(
        raw / "c06-cmepsp.pdf",
        output / "C06-cmepsp-focused.pdf",
        selector=_commission_pages,
    )
    _copy_scoped_pdf(
        raw / "c06-oecd.pdf",
        output / "C06-oecd-focused.pdf",
        selector=_oecd_pages,
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


def _prepare_dubois(raw: Path) -> str:
    text = (raw / "dubois-pg408.txt").read_text(encoding="utf-8-sig")
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
    parser = _HtmlText(neutralize_headings=True)
    parser.feed(html[start:end])
    text = parser.text()
    if len(text) < 8_000:
        raise ValueError("The pinned NPS decoy extraction was unexpectedly short")
    return "# Source B\n\n" + text + "\n"


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
    text = (raw / "darwin-pg1228.txt").read_text(encoding="utf-8-sig")
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


def _oecd_pages(reader: PdfReader) -> list[int]:
    # Physical PDF pages 16-34 contain the complete overview/framework chapter
    # (printed pages 14-32), including its notes and references.
    if len(reader.pages) != 286:
        raise ValueError("Unexpected OECD page count; review the pinned edition before slicing")
    _require_page_text(reader, 15, "OVERVIEW")
    return list(range(15, 34))


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
