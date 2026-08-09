from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from thesisound import tracing
from thesisound.audio import AsrTranscript, AudioChunk, AudioSegmentQa

_PERSIAN_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")
_PERSIAN_PUNCTUATION = re.compile(r"[،؛؟٪٫٬«»]")
_NON_WORD = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)
_SENTENCES = re.compile(r"(?<=[.!؟؛])\s+")


class AudioQaService:
    def __init__(self, *, pass_threshold: float = 0.9, review_threshold: float = 0.78) -> None:
        if not 0 <= review_threshold < pass_threshold <= 1:
            raise ValueError("Audio QA thresholds must satisfy 0 <= review < pass <= 1.")
        self.pass_threshold = pass_threshold
        self.review_threshold = review_threshold

    def compare(self, chunk: AudioChunk, transcript: AsrTranscript) -> AudioSegmentQa:
        with tracing.span(
            "audio.qa", component="audio", subject_type="chunk", subject_id=chunk.chunk_id
        ) as span:
            expected = _normalize(chunk.text)
            actual = _normalize(transcript.text)
            # autojunk=True treats frequent Persian letters as junk and collapses
            # near-identical transcripts to ~0.02 similarity.
            ratio = (
                SequenceMatcher(None, expected, actual, autojunk=False).ratio()
                if expected and actual
                else 0
            )
            missing = [
                sentence
                for sentence in _sentences(chunk.text)
                if _sentence_similarity(sentence, transcript.text) < 0.6
            ]
            repeated = _repeated_phrases(transcript.text)
            truncated = _is_truncated(expected, actual)
            speaker_error = (
                transcript.speaker is not None and transcript.speaker != chunk.speaker
            )

            if (
                ratio >= self.pass_threshold
                and not missing
                and not repeated
                and not truncated
                and not speaker_error
            ):
                verdict = "pass"
                instruction = None
            elif ratio >= self.review_threshold and not truncated and not speaker_error:
                verdict = "manual_review"
                instruction = "رونویسی نزدیک است اما برای اطمینان نیاز به بازبینی شنیداری دارد."
            else:
                verdict = "regenerate"
                reasons: list[str] = []
                if missing:
                    reasons.append("جمله‌های افتاده را کامل بخوان")
                if repeated:
                    reasons.append("بخش‌های تکراری را حذف کن")
                if truncated:
                    reasons.append("پایان متن را کامل و بدون قطع‌شدن بخوان")
                if speaker_error:
                    reasons.append(f"فقط با صدای گوینده {chunk.speaker} اجرا کن")
                instruction = "؛ ".join(reasons) or "متن را دقیق‌تر و بدون تغییر بازتولید کن"

            span.set(verdict=verdict)
            span.measure(
                similarity_ratio=round(ratio, 4),
                missing_sentence_count=len(missing),
                repeated_phrase_count=len(repeated),
            )
            return AudioSegmentQa(
                chunk_id=chunk.chunk_id,
                chunk_hash=chunk.content_hash,
                wav_sha256=transcript.wav_sha256,
                verdict=verdict,
                similarity_ratio=ratio,
                expected_text=chunk.text,
                transcript_text=transcript.text,
                missing_sentences=missing,
                repeated_phrases=repeated,
                truncated=truncated,
                regeneration_instruction=instruction,
            )


def _normalize(text: str) -> str:
    value = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    # Drop ZWNJ/ZWJ so TTS/ASR spelling variants like زحمت‌کش vs زحمتکش match.
    value = value.replace("\u200c", "").replace("\u200d", "")
    value = _PERSIAN_DIACRITICS.sub("", value)
    # Arabic-block punctuation stays inside \u0600-\u06ff; strip it explicitly.
    value = _PERSIAN_PUNCTUATION.sub(" ", value)
    value = _NON_WORD.sub(" ", value.casefold())
    return " ".join(value.split())


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in _SENTENCES.split(text) if len(item.split()) >= 4]


def _sentence_similarity(sentence: str, transcript: str) -> float:
    needle = _normalize(sentence)
    haystack = _normalize(transcript)
    if not needle:
        return 1
    if needle in haystack:
        return 1
    return SequenceMatcher(None, needle, haystack, autojunk=False).ratio()


def _is_truncated(expected: str, actual: str) -> bool:
    expected_tail = " ".join(expected.split()[-6:])
    actual_tail = " ".join(actual.split()[-10:])
    return bool(expected_tail) and (
        SequenceMatcher(None, expected_tail, actual_tail, autojunk=False).ratio() < 0.55
    )


def _repeated_phrases(text: str) -> list[str]:
    tokens = _normalize(text).split()
    if len(tokens) < 12:
        return []
    windows = [" ".join(tokens[index : index + 6]) for index in range(len(tokens) - 5)]
    counts = Counter(windows)
    return [phrase for phrase, count in counts.items() if count >= 2][:5]
