from __future__ import annotations

import platform
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, ZipInfo

from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.parser_identity import module_fingerprint

_EPUB_MIMETYPE = "application/epub+zip"
_CONTAINER_PATH = "META-INF/container.xml"
_MAX_TOTAL_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
_MAX_CONTENT_ITEM_BYTES = 25 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_CONTENT_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
_BLOCK_TAGS = {
    "p": "text",
    "li": "text",
    "blockquote": "text",
    "pre": "code",
    "dt": "text",
    "dd": "text",
    "figcaption": "text",
    "table": "table",
}
_IGNORED_TAGS = {"script", "style", "head", "nav", "noscript"}
_SPACE = re.compile(r"\s+")


class EpubDocumentParseError(RuntimeError):
    """Raised when an EPUB archive is unsafe, malformed, or has no readable spine."""


class EpubDocumentParser:
    """Parse EPUB 2/3 archives in package spine order without external dependencies."""

    name = "epub"

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension == ".epub" and not inspection.encrypted

    def identity(self) -> dict[str, str] | None:
        impl = module_fingerprint(sys.modules[__name__])
        if impl is None:
            return None
        return {
            "parser": "epub",
            "version": "1",
            "python": platform.python_version(),
            "impl": impl,
        }

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        resolved = path.expanduser().resolve()
        if resolved != inspection.path.expanduser().resolve():
            raise ValueError("The inspected path and parsed path must refer to the same file.")
        if not self.supports(inspection):
            raise EpubDocumentParseError("EPUB parser only accepts unencrypted .epub files.")

        try:
            with ZipFile(resolved) as archive:
                _validate_archive(archive)
                package_path = _package_document_path(archive)
                package = _read_xml(archive, package_path, "EPUB package document")
                manifest = _manifest(package)
                spine = _spine(package)
                if not spine:
                    raise EpubDocumentParseError("EPUB package has no readable spine items.")
                blocks, warnings = _parse_spine(
                    archive,
                    package_path=package_path,
                    manifest=manifest,
                    spine=spine,
                    toc_titles=_toc_titles(
                        archive,
                        package=package,
                        package_path=package_path,
                        manifest=manifest,
                    ),
                )
        except BadZipFile as exc:
            raise EpubDocumentParseError("EPUB is not a valid ZIP archive.") from exc
        except OSError as exc:
            raise EpubDocumentParseError(f"EPUB could not be read: {type(exc).__name__}") from exc

        if not blocks:
            raise EpubDocumentParseError("EPUB spine produced no usable text blocks.")
        return ParsedDocument(
            parser_name=self.name,
            parser_version="1",
            blocks=blocks,
            warnings=warnings,
        )


def _validate_archive(archive: ZipFile) -> None:
    infos = archive.infolist()
    if not infos:
        raise EpubDocumentParseError("EPUB archive is empty.")
    total_size = 0
    for info in infos:
        _safe_member_name(info.filename)
        if info.flag_bits & 0x1:
            raise EpubDocumentParseError("Encrypted EPUB entries are not supported.")
        total_size += info.file_size
        if total_size > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise EpubDocumentParseError("EPUB expands beyond the safe uncompressed-size limit.")
        if (
            info.file_size > 1024 * 1024
            and info.compress_size > 0
            and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO
        ):
            raise EpubDocumentParseError("EPUB contains a suspiciously compressed archive entry.")

    try:
        declared = archive.read("mimetype").decode("ascii").strip()
    except KeyError:
        declared = None
    except UnicodeDecodeError as exc:
        raise EpubDocumentParseError("EPUB mimetype entry is not valid ASCII.") from exc
    if declared is not None and declared != _EPUB_MIMETYPE:
        raise EpubDocumentParseError("Archive mimetype entry is not application/epub+zip.")


def _package_document_path(archive: ZipFile) -> str:
    root = _read_xml(archive, _CONTAINER_PATH, "EPUB container")
    rootfiles = root.findall(".//{*}rootfile")
    for rootfile in rootfiles:
        full_path = rootfile.get("full-path")
        if full_path:
            return _safe_member_name(unquote(full_path))
    raise EpubDocumentParseError("EPUB container does not declare a package document.")


def _manifest(package: ElementTree.Element) -> dict[str, tuple[str, str, str]]:
    output: dict[str, tuple[str, str, str]] = {}
    for item in package.findall(".//{*}manifest/{*}item"):
        item_id = (item.get("id") or "").strip()
        href = (item.get("href") or "").strip()
        media_type = (item.get("media-type") or "").strip().lower()
        properties = (item.get("properties") or "").strip().lower()
        if item_id and href:
            output[item_id] = (href, media_type, properties)
    return output


def _spine(package: ElementTree.Element) -> list[str]:
    return [
        itemref.get("idref", "").strip()
        for itemref in package.findall(".//{*}spine/{*}itemref")
        if itemref.get("idref") and itemref.get("linear", "yes").lower() != "no"
    ]


def _toc_titles(
    archive: ZipFile,
    *,
    package: ElementTree.Element,
    package_path: str,
    manifest: dict[str, tuple[str, str, str]],
) -> dict[str, str]:
    """Map each spine member to the title the book's own contents page gives it.

    A spine item whose XHTML carries no h1-h6 has no heading to name it, and the
    file name is not a name: real books ship members like `9780226924571_16_not
    .xhtml`, which becomes the chapter title, the block heading_path, and thus the
    only label a reader or a downstream filter ever sees. The table of contents is
    where the book states those names, so read it.

    Both EPUB generations are handled: the EPUB 3 navigation document and the
    EPUB 2 NCX. Failure is never fatal -- a missing or malformed contents page
    just leaves the caller with its previous fallback.
    """

    package_dir = posixpath.dirname(package_path)
    candidates: list[str] = []
    for _item_id, (href, media_type, properties) in manifest.items():
        if "nav" in properties.split() or media_type == "application/x-dtbncx+xml":
            candidates.append(href)
    spine_node = package.find(".//{*}spine")
    if spine_node is not None:
        ncx_id = (spine_node.get("toc") or "").strip()
        if ncx_id in manifest:
            candidates.insert(0, manifest[ncx_id][0])

    titles: dict[str, str] = {}
    for href in candidates:
        try:
            member = _resolve_member(package_dir, href)
            root = _read_xml(archive, member, "EPUB table of contents")
        except (EpubDocumentParseError, ValueError, KeyError):
            continue
        base = posixpath.dirname(member)
        for target, text in _toc_entries(root):
            try:
                resolved = _resolve_member(base, target)
            except (EpubDocumentParseError, ValueError):
                continue
            # First mention wins: a contents page may point several entries at one
            # file, and the earliest is the one that names it.
            titles.setdefault(resolved, text)
    return titles


def _toc_entries(root: ElementTree.Element) -> list[tuple[str, str]]:
    """(href, label) pairs from an EPUB 3 nav document or an EPUB 2 NCX."""

    entries: list[tuple[str, str]] = []
    for point in root.iter():
        name = _local_name(point.tag)
        # `_local_name` folds case, as everywhere else in this module.
        if name == "navpoint":
            label = point.find(".//{*}navLabel/{*}text")
            content = point.find("./{*}content")
            if label is None or content is None:
                continue
            text = _SPACE.sub(" ", (label.text or "")).strip()
            src = (content.get("src") or "").strip()
            if text and src:
                entries.append((src, text))
        elif name == "a":
            href = (point.get("href") or "").strip()
            text = _element_text(point)
            if href and text:
                entries.append((href, text))
    return entries


def _toc_member_title(titles: dict[str, str], member: str) -> str | None:
    return titles.get(member)


def _parse_spine(
    archive: ZipFile,
    *,
    package_path: str,
    manifest: dict[str, tuple[str, str, str]],
    spine: list[str],
    toc_titles: dict[str, str] | None = None,
) -> tuple[list[ParsedBlock], list[str]]:
    blocks: list[ParsedBlock] = []
    warnings: list[str] = []
    package_dir = posixpath.dirname(package_path)

    for spine_index, idref in enumerate(spine, start=1):
        item = manifest.get(idref)
        if item is None:
            warnings.append(f"Spine item {idref!r} is absent from the manifest.")
            continue
        href, media_type, _properties = item
        if media_type not in _CONTENT_MEDIA_TYPES:
            warnings.append(
                f"Spine item {idref!r} uses unsupported media type {media_type or 'unknown'}."
            )
            continue
        member = _resolve_member(package_dir, href)
        try:
            info = archive.getinfo(member)
        except KeyError:
            warnings.append(f"Spine content is missing: {member}")
            continue
        _validate_content_entry(info)
        payload = archive.read(info)
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            warnings.append(f"Malformed XHTML skipped at {member}: {exc}")
            continue
        item_blocks = _xhtml_blocks(
            root,
            member=member,
            idref=idref,
            spine_index=spine_index,
            toc_title=(toc_titles or {}).get(member),
        )
        if not item_blocks:
            warnings.append(f"No readable text found in spine item: {member}")
            continue
        blocks.extend(item_blocks)

    return blocks, warnings


def _xhtml_blocks(
    root: ElementTree.Element,
    *,
    member: str,
    idref: str,
    spine_index: int,
    toc_title: str | None = None,
) -> list[ParsedBlock]:
    body = next((node for node in root.iter() if _local_name(node.tag) == "body"), root)
    output: list[ParsedBlock] = []
    heading_path: list[str] = []
    # The book's own contents page names this section; the archive member name
    # only identifies a file. Fall back to the file name when there is no entry.
    fallback_chapter = toc_title or _humanize_member(member)

    def visit(node: ElementTree.Element, ignored: bool = False) -> None:
        nonlocal heading_path
        tag = _local_name(node.tag)
        ignored = ignored or tag in _IGNORED_TAGS
        if ignored:
            return
        if tag in {f"h{level}" for level in range(1, 7)}:
            text = _element_text(node)
            if text:
                level = int(tag[1])
                heading_path = heading_path[: level - 1]
                heading_path.append(text)
                output.append(
                    _epub_block(
                        text=text,
                        kind="heading",
                        heading_path=heading_path,
                        member=member,
                        idref=idref,
                        spine_index=spine_index,
                        block_index=len(output) + 1,
                    )
                )
            return
        if tag in _BLOCK_TAGS:
            text = _element_text(node)
            if text:
                path = heading_path or [fallback_chapter]
                output.append(
                    _epub_block(
                        text=text,
                        kind=_BLOCK_TAGS[tag],
                        heading_path=path,
                        member=member,
                        idref=idref,
                        spine_index=spine_index,
                        block_index=len(output) + 1,
                    )
                )
            return
        for child in list(node):
            visit(child, ignored)

    visit(body)
    if output:
        return output

    text = _element_text(body)
    if not text:
        return []
    return [
        _epub_block(
            text=text,
            kind="text",
            heading_path=[fallback_chapter],
            member=member,
            idref=idref,
            spine_index=spine_index,
            block_index=1,
        )
    ]


def _epub_block(
    *,
    text: str,
    kind: str,
    heading_path: list[str],
    member: str,
    idref: str,
    spine_index: int,
    block_index: int,
) -> ParsedBlock:
    spine_step = spine_index * 2
    block_step = block_index * 2
    cfi = f"epubcfi(/6/{spine_step}[{idref}]!/4/{block_step})"
    return ParsedBlock(
        source_block_key=f"{member}#{cfi}",
        text=text,
        heading_path=list(heading_path),
        kind=kind,
    )


def _read_xml(archive: ZipFile, member: str, label: str) -> ElementTree.Element:
    safe_member = _safe_member_name(member)
    try:
        info = archive.getinfo(safe_member)
    except KeyError as exc:
        raise EpubDocumentParseError(f"{label} is missing: {safe_member}") from exc
    _validate_content_entry(info)
    try:
        return ElementTree.fromstring(archive.read(info))
    except ElementTree.ParseError as exc:
        raise EpubDocumentParseError(f"{label} XML is malformed.") from exc


def _validate_content_entry(info: ZipInfo) -> None:
    if info.file_size > _MAX_CONTENT_ITEM_BYTES:
        raise EpubDocumentParseError(
            f"EPUB content item exceeds the safe size limit: {info.filename}"
        )


def _resolve_member(package_dir: str, href: str) -> str:
    path = unquote(href.split("#", 1)[0])
    return _safe_member_name(posixpath.normpath(posixpath.join(package_dir, path)))


def _safe_member_name(value: str) -> str:
    if "\\" in value:
        raise EpubDocumentParseError("EPUB archive paths must use POSIX separators.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise EpubDocumentParseError(f"Unsafe EPUB archive path: {value!r}")
    return path.as_posix()


def _element_text(node: ElementTree.Element) -> str:
    return _SPACE.sub(" ", " ".join(part for part in node.itertext())).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _humanize_member(member: str) -> str:
    stem = PurePosixPath(member).stem.replace("_", " ").replace("-", " ").strip()
    return stem or "EPUB section"
