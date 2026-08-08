from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from statistics import fmean
from typing import Callable

from datasets import load_dataset
from huggingface_hub import hf_hub_download, snapshot_download
from PIL import Image

from scoring import normalize_persian, score_text

_PERSIAN_EXCLUSIVE = set("پچژگ")
_PERSIAN_FORMS = set("کیکیگچپژ")
_ARABIC_FORMS = set("كيى")


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_tesseract() -> Callable[[Path], str]:
    def predict(path: Path) -> str:
        completed = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "fas", "--psm", "7"],
            check=True,
            text=True,
            capture_output=True,
            timeout=120,
        )
        return completed.stdout.strip()

    return predict


def build_weightedai() -> Callable[[Path], str]:
    repo = "WeightedAI/Persian_OCR"
    vocab_path = hf_hub_download(repo, "vocab.json")
    model_path = hf_hub_download(repo, "model.py")
    utils_path = hf_hub_download(repo, "utils.py")
    weights_path = hf_hub_download(repo, "pytorch_model.bin")

    import torch

    model_module = _load_module("weightedai_model", model_path)
    sys.modules["model"] = model_module
    utils_module = _load_module("weightedai_utils", utils_path)
    with open(vocab_path, encoding="utf-8") as handle:
        vocab = json.load(handle)
    idx_to_char = {int(key): value for key, value in vocab["idx_to_char"].items()}
    model = model_module.CNN_Transformer_OCR(num_classes=len(idx_to_char) + 1)
    model.load_state_dict(torch.load(weights_path, map_location="cpu"))
    model.eval()

    def predict(path: Path) -> str:
        return str(utils_module.ocr_page(str(path), model, idx_to_char)).strip()

    return predict


def build_bina02() -> Callable[[Path], str]:
    root = snapshot_download("Reza2kn/Bina-0.2-RizehPizeh")
    module = _load_module("bina_text_recognition", str(Path(root) / "bina_text_recognition.py"))
    recognizer = module.BinaTextRecognition(str(Path(root) / "inference"), device="cpu")

    def predict(path: Path) -> str:
        values = list(recognizer.predict(str(path)))
        if not values:
            return ""
        return " ".join(str(item.get("text", "")).strip() for item in values).strip()

    return predict


def _is_identifiably_persian(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    script_ratio = sum("\u0600" <= char <= "\u06ff" for char in letters) / len(letters)
    if script_ratio < 0.8:
        return False
    has_exclusive_letter = any(char in _PERSIAN_EXCLUSIVE for char in text)
    uses_persian_forms = any(char in _PERSIAN_FORMS for char in text)
    uses_arabic_forms = any(char in _ARABIC_FORMS for char in text)
    return has_exclusive_letter or (uses_persian_forms and not uses_arabic_forms)


def load_samples(limit: int, offset: int) -> list[dict[str, object]]:
    dataset = load_dataset(
        "mohajesmaeili/Persian_Arabic_TextLine_Image_Ocr_Small",
        split="Test",
        streaming=True,
    )
    selected: list[dict[str, object]] = []
    accepted = 0
    for row in dataset:
        text = str(row["Text"])
        if not _is_identifiably_persian(text):
            continue
        if accepted < offset:
            accepted += 1
            continue
        selected.append({"image": row["Image"], "text": text})
        if len(selected) >= limit:
            break
    if len(selected) != limit:
        raise RuntimeError(f"Requested {limit} identifiable Persian samples; found {len(selected)}")
    return selected


def run_system(name: str, predictor: Callable[[Path], str], samples: list[dict[str, object]]):
    rows = []
    with tempfile.TemporaryDirectory(prefix=f"persian-ocr-{name}-") as directory:
        root = Path(directory)
        for index, sample in enumerate(samples):
            image = sample["image"]
            if not isinstance(image, Image.Image):
                image = Image.open(image)
            path = root / f"sample-{index:04d}.png"
            image.convert("RGB").save(path)
            reference = str(sample["text"])
            started = time.perf_counter()
            error = None
            try:
                prediction = predictor(path)
            except Exception as exc:
                prediction = ""
                error = f"{type(exc).__name__}: {exc}"[:500]
            duration = time.perf_counter() - started
            metrics = score_text(reference, prediction)
            rows.append({
                "index": index,
                "reference": reference,
                "prediction": prediction,
                "reference_normalized": normalize_persian(reference),
                "prediction_normalized": normalize_persian(prediction),
                "cer": metrics.cer,
                "wer": metrics.wer,
                "exact": metrics.exact,
                "duration_seconds": duration,
                "error": error,
            })
    successes = [row for row in rows if row["error"] is None]
    return {
        "system": name,
        "sample_count": len(rows),
        "success_count": len(successes),
        "mean_cer": fmean(float(row["cer"]) for row in rows),
        "mean_wer": fmean(float(row["wer"]) for row in rows),
        "exact_line_accuracy": sum(bool(row["exact"]) for row in rows) / len(rows),
        "mean_latency_seconds": fmean(float(row["duration_seconds"]) for row in rows),
        "total_duration_seconds": sum(float(row["duration_seconds"]) for row in rows),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--systems", default="tesseract,weightedai,bina02")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    builders = {"tesseract": build_tesseract, "weightedai": build_weightedai, "bina02": build_bina02}
    samples = load_samples(args.limit, args.offset)
    payload = {
        "dataset": "mohajesmaeili/Persian_Arabic_TextLine_Image_Ocr_Small",
        "split": "Test",
        "selection": {
            "limit": args.limit,
            "offset": args.offset,
            "policy": "Arabic-script ratio >= 0.8 and either Persian-exclusive letters or Persian glyph forms without Arabic glyph forms",
            "known_bias": "This raises Persian precision but favors lines containing identifiable Persian orthography; use a Persian-only corpus for the final benchmark.",
        },
        "normalization": "NFKC, Arabic-to-Persian glyph mapping, digit unification, diacritic removal, whitespace normalization; ZWNJ preserved",
        "systems": [],
    }
    for name in [item.strip() for item in args.systems.split(",") if item.strip()]:
        if name not in builders:
            raise SystemExit(f"Unknown system: {name}")
        started = time.perf_counter()
        try:
            predictor = builders[name]()
            result = run_system(name, predictor, samples)
            result["initialization_seconds"] = time.perf_counter() - started - result["total_duration_seconds"]
        except Exception as exc:
            result = {"system": name, "status": "initialization_error", "error": f"{type(exc).__name__}: {exc}"[:1000]}
        payload["systems"].append(result)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{key: value for key, value in item.items() if key != "rows"} for item in payload["systems"]], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    main()
