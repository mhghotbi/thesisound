from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from thesisound.ports import ParsedBlock, ParsedDocument
from thesisound.services.ocr_contracts import OcrWorkerRequest
from thesisound.services.ocr_model_registry import VLM_MODEL_NAME
from thesisound.services.ocr_planner import detect_script, plan_page


class OcrRuntimeError(RuntimeError):
    """Raised when the isolated local OCR runtime cannot process a document."""


class PaddleRuntime:
    def __init__(self, request: OcrWorkerRequest) -> None:
        self.request = request
        self._detector: Any | None = None
        self._latin: Any | None = None
        self._bina: Any | None = None
        self._layout: Any | None = None
        self._vlm: Any | None = None

    def parse(self) -> ParsedDocument:
        source = self.request.source_path.expanduser().resolve()
        blocks: list[ParsedBlock] = []
        warnings: list[str] = []
        with tempfile.TemporaryDirectory(prefix="thesisound-ocr-pages-") as tmp:
            for page_number, image, native_text in self._pages(source):
                plan = plan_page(
                    page_number,
                    native_text=native_text,
                    is_image=source.suffix.lower() != ".pdf",
                    explicit_complex_layout=(
                        self.request.inspection.likely_complex_layout and not native_text.strip()
                    ),
                )
                if plan.route == "native":
                    blocks.extend(_native_blocks(native_text, page_number))
                    continue
                page_path = Path(tmp) / f"page-{page_number:04d}.png"
                image.save(page_path)
                lines = self._recognize_page(page_path, layout=plan.route == "layout_ocr")
                if self.request.enable_vlm and _needs_vlm(lines):
                    vlm = self._vlm_page(page_path)
                    if vlm.strip():
                        blocks.append(_block(page_number, "vlm", 1, vlm.strip(), "text"))
                        warnings.append(
                            f"Page {page_number} used PaddleOCR-VL structural fallback."
                        )
                        continue
                for index, line in enumerate(lines, start=1):
                    blocks.append(_block(page_number, "line", index, line["text"], line["kind"]))
                if not lines:
                    warnings.append(f"Page {page_number} produced no OCR lines.")
        return ParsedDocument(
            parser_name="local-ocr",
            parser_version="1",
            blocks=blocks,
            warnings=warnings,
        )

    def _pages(self, source: Path) -> list[tuple[int, Any, str]]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise OcrRuntimeError("Pillow is required in the isolated OCR environment.") from exc
        if source.suffix.lower() != ".pdf":
            return [(1, Image.open(source).convert("RGB"), "")]
        try:
            import fitz
            from pypdf import PdfReader
        except ImportError as exc:
            raise OcrRuntimeError("PyMuPDF and pypdf are required for PDF OCR.") from exc
        reader = PdfReader(source, strict=False)
        document = fitz.open(source)
        scale = self.request.render_dpi / 72
        matrix = fitz.Matrix(scale, scale)
        pages: list[tuple[int, Any, str]] = []
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            try:
                native = reader.pages[index].extract_text() or ""
            except Exception:
                native = ""
            pages.append((index + 1, image, native))
        document.close()
        return pages

    def _recognize_page(self, page_path: Path, *, layout: bool) -> list[dict[str, Any]]:
        polygons = self._detect(page_path)
        regions = self._layout_regions(page_path) if layout else []
        from PIL import Image

        image = Image.open(page_path).convert("RGB")
        rows: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="thesisound-ocr-lines-") as tmp:
            for index, polygon in enumerate(polygons):
                x1, y1, x2, y2 = _bbox(polygon, image.width, image.height)
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                crop_path = Path(tmp) / f"line-{index:05d}.png"
                image.crop((x1, y1, x2, y2)).save(crop_path)
                candidates = [self._bina_line(crop_path), self._latin_line(crop_path)]
                best = max(candidates, key=_candidate_rank)
                if not best["text"].strip():
                    continue
                order, kind = _region_for(polygon, regions)
                rows.append(
                    {
                        "text": best["text"].strip(),
                        "score": best["score"],
                        "script": detect_script(best["text"]),
                        "polygon": polygon,
                        "order": order,
                        "kind": kind,
                    }
                )
        rows.sort(key=lambda row: (row["order"], _line_y(row), _line_x(row)))
        return rows

    def _detect(self, page_path: Path) -> list[list[tuple[float, float]]]:
        if self._detector is None:
            try:
                from paddleocr import TextDetection
            except ImportError as exc:
                raise OcrRuntimeError(
                    "paddleocr is required in the isolated OCR environment."
                ) from exc
            self._detector = TextDetection(
                model_name="PP-OCRv6_medium_det",
                model_dir=str(self.request.model_dirs["pp-ocrv6-medium-det"]),
                device=self.request.device,
            )
        values = list(self._detector.predict(input=str(page_path), batch_size=1))
        payload = _payload(values[0]) if values else {}
        raw = _find(payload, ("dt_polys", "polys", "boxes")) or []
        return [_polygon(item) for item in raw if _polygon(item)]

    def _latin_line(self, path: Path) -> dict[str, Any]:
        if self._latin is None:
            from paddleocr import TextRecognition

            self._latin = TextRecognition(
                model_name="PP-OCRv6_small_rec",
                model_dir=str(self.request.model_dirs["pp-ocrv6-small-rec"]),
                device=self.request.device,
            )
        values = list(self._latin.predict(input=str(path), batch_size=1))
        payload = _payload(values[0]) if values else {}
        return {
            "text": str(_find(payload, ("rec_text", "text")) or ""),
            "score": float(_find(payload, ("rec_score", "score")) or 0),
            "engine": "latin",
        }

    def _bina_line(self, path: Path) -> dict[str, Any]:
        if self._bina is None:
            root = self.request.model_dirs["bina-0.2-rizehpizeh"]
            module_path = root / "bina_text_recognition.py"
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "thesisound_bina", module_path
            )
            if spec is None or spec.loader is None:
                raise OcrRuntimeError(f"Cannot load Bina wrapper from {module_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._bina = module.BinaTextRecognition(
                str(root / "inference"), device=self.request.device
            )
        values = list(self._bina.predict(str(path)))
        value = values[0] if values else {}
        return {
            "text": str(value.get("text", "")),
            "score": float(value.get("score", value.get("confidence", 0)) or 0),
            "engine": "bina",
        }

    def _layout_regions(self, page_path: Path) -> list[dict[str, Any]]:
        if self._layout is None:
            from paddleocr import LayoutDetection

            self._layout = LayoutDetection(
                model_name="PP-DocLayoutV3",
                model_dir=str(self.request.model_dirs["pp-doclayout-v3"]),
                device=self.request.device,
            )
        values = list(self._layout.predict(input=str(page_path), batch_size=1, layout_nms=True))
        payload = _payload(values[0]) if values else {}
        raw = _find(payload, ("boxes", "layout_det_res")) or []
        if isinstance(raw, dict):
            raw = raw.get("boxes", [])
        result = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            poly = _polygon(item.get("coordinate") or item.get("bbox") or item.get("points"))
            if poly:
                result.append(
                    {
                        "polygon": poly,
                        "kind": str(item.get("label") or item.get("type") or "text").lower(),
                        "order": int(item.get("order") or item.get("reading_order") or index),
                    }
                )
        return result

    def _vlm_page(self, page_path: Path) -> str:
        if VLM_MODEL_NAME not in self.request.model_dirs:
            return ""
        if self._vlm is None:
            try:
                from paddleocr import PaddleOCRVL
            except ImportError as exc:
                raise OcrRuntimeError(
                    "Install paddleocr[doc-parser] for PaddleOCR-VL fallback."
                ) from exc
            self._vlm = PaddleOCRVL(
                pipeline_version="v1.6",
                layout_detection_model_name="PP-DocLayoutV3",
                layout_detection_model_dir=str(self.request.model_dirs["pp-doclayout-v3"]),
                vl_rec_model_name="PaddleOCR-VL-1.6",
                vl_rec_model_dir=str(self.request.model_dirs[VLM_MODEL_NAME]),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                device=self.request.device,
            )
        values = list(self._vlm.predict(str(page_path)))
        payload = _payload(values[0]) if values else {}
        value = _find(payload, ("markdown", "markdown_text", "text")) or ""
        if isinstance(value, dict):
            value = value.get("text", "")
        return str(value)


def parse_with_local_models(request: OcrWorkerRequest) -> ParsedDocument:
    return PaddleRuntime(request).parse()


def _native_blocks(text: str, page: int) -> list[ParsedBlock]:
    parts = [
        "\n".join(line.strip() for line in part.splitlines() if line.strip())
        for part in text.split("\n\n")
    ]
    return [
        _block(page, "native", index, part, "text")
        for index, part in enumerate(parts, 1)
        if part
    ]


def _block(page: int, source: str, index: int, text: str, kind: str) -> ParsedBlock:
    return ParsedBlock(
        source_block_key=f"page-{page}-{source}-{index}",
        text=text,
        page_start=page,
        page_end=page,
        kind=kind,
    )


def _needs_vlm(lines: list[dict[str, Any]]) -> bool:
    if not lines:
        return True
    mean = sum(float(line["score"]) for line in lines) / len(lines)
    return mean < 0.42 or sum(len(line["text"]) for line in lines) < 40 or any(
        line["kind"] in {"table", "formula", "chart"} for line in lines
    )


def _candidate_rank(value: dict[str, Any]) -> tuple[float, int]:
    script = detect_script(value["text"])
    bonus = 0.08 if (value["engine"] == "bina" and script in {"persian", "mixed"}) or (
        value["engine"] == "latin" and script == "latin"
    ) else 0
    return float(value["score"]) + bonus, len(value["text"])


def _payload(value: Any) -> Any:
    for attr in ("json", "res"):
        result = getattr(value, attr, None)
        if callable(result):
            result = result()
        if result is not None:
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return {"text": result}
            return result
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {"text": str(value)}


def _find(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for nested in value.values():
            found = _find(nested, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find(nested, keys)
            if found is not None:
                return found
    return None


def _polygon(value: Any) -> list[tuple[float, float]]:
    if isinstance(value, dict):
        value = value.get("coordinate") or value.get("bbox") or value.get("points")
    if not isinstance(value, (list, tuple)):
        return []
    if len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
        x1, y1, x2, y2 = map(float, value)
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return [
        (float(point[0]), float(point[1]))
        for point in value
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]


def _bbox(poly: list[tuple[float, float]], width: int, height: int) -> tuple[int, int, int, int]:
    xs = [point[0] for point in poly]
    ys = [point[1] for point in poly]
    return (
        max(0, int(min(xs))),
        max(0, int(min(ys))),
        min(width, int(max(xs) + 1)),
        min(height, int(max(ys) + 1)),
    )


def _region_for(poly: list[tuple[float, float]], regions: list[dict[str, Any]]) -> tuple[int, str]:
    xs = [point[0] for point in poly]
    ys = [point[1] for point in poly]
    center = (sum(xs) / len(xs), sum(ys) / len(ys))
    for region in sorted(regions, key=lambda item: item["order"]):
        x1, y1, x2, y2 = _bbox(region["polygon"], 10**9, 10**9)
        if x1 <= center[0] <= x2 and y1 <= center[1] <= y2:
            kind = (
                "heading"
                if "title" in region["kind"] or "heading" in region["kind"]
                else region["kind"]
            )
            return region["order"], kind
    return len(regions), "text"


def _line_y(row: dict[str, Any]) -> float:
    return min(point[1] for point in row["polygon"])


def _line_x(row: dict[str, Any]) -> float:
    x = min(point[0] for point in row["polygon"])
    return -x if row["script"] in {"persian", "mixed"} else x
