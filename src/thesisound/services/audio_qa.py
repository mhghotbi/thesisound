from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from thesisound import tracing
from thesisound.audio import AsrTranscript, AudioChunk, AudioSegmentQa
from thesisound.services.lineage_events import emit_quality_label, emit_review_decision
from thesisound.services.semantic_identity import AUDIO_QA_VERSION, audio_qa_identity

_PERSIAN_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")
_PERSIAN_PUNCTUATION = re.compile(r"[،؛؟٪٫٬«»]")
_NON_WORD = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)
_SENTENCES = re.compile(r"(?<=[.!؟؛])\s+")

# TTS input and ASR output disagree on precomposed hamza carriers: the script
# writes تأثیر / اشیاء, the transcript comes back تاثیر / اشیا. Fold the family so
# the exact-containment fast path in _sentence_similarity still fires.
# (_PERSIAN_DIACRITICS already covers the *combining* hamza marks U+0654/U+0655.)
_HAMZA_FOLD = str.maketrans(
    {
        "آ": "ا",  # آ -> ا
        "أ": "ا",  # أ -> ا
        "إ": "ا",  # إ -> ا
        "ؤ": "و",  # ؤ -> و
        "ئ": "ی",  # ئ -> ی
        "ء": "",  # ء -> dropped
    }
)

# A sentence is scored against the best-matching window of the transcript rather
# than the whole transcript: SequenceMatcher.ratio() divides by the summed length
# of both inputs, so a short sentence inside a long transcript is capped at
# 2L/(L+H) < 1 even when it was read perfectly. On the 2026-08-09 production run
# every flagged sentence had a ceiling below the old 0.6 threshold.
_WINDOW_SCALES = (0.8, 1.0, 1.2)
_MISSING_SENTENCE_THRESHOLD = 0.85


class AudioQaService:
    def __init__(
        self,
        *,
        pass_threshold: float = 0.9,
        review_threshold: float = 0.78,
        missing_sentence_threshold: float = _MISSING_SENTENCE_THRESHOLD,
    ) -> None:
        if not 0 <= review_threshold < pass_threshold <= 1:
            raise ValueError("Audio QA thresholds must satisfy 0 <= review < pass <= 1.")
        if not 0 < missing_sentence_threshold <= 1:
            raise ValueError("Missing-sentence threshold must satisfy 0 < threshold <= 1.")
        self.pass_threshold = pass_threshold
        self.review_threshold = review_threshold
        self.missing_sentence_threshold = missing_sentence_threshold

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
            missing = _missing_sentences(
                _sentences(chunk.text),
                transcript.text,
                threshold=self.missing_sentence_threshold,
            )
            repeated = _repeated_phrases(transcript.text)
            truncated = _is_truncated(expected, actual)
            speaker_error = transcript.speaker is not None and transcript.speaker != chunk.speaker

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
            emit_quality_label(
                label_source="audio_qa",
                subject_type="audio_chunk",
                subject_id=chunk.chunk_id,
                verdict=verdict,
                score=round(ratio, 4),
            )
            if verdict == "manual_review":
                emit_review_decision(
                    disposition="manual_review",
                    subject_type="audio_chunk",
                    subject_id=chunk.chunk_id,
                    reason_code="audio_qa_threshold",
                    component="audio",
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
                **audio_qa_identity(
                    pass_threshold=self.pass_threshold,
                    review_threshold=self.review_threshold,
                    missing_sentence_threshold=self.missing_sentence_threshold,
                    qa_version=AUDIO_QA_VERSION,
                ),
            )


def _normalize(text: str) -> str:
    value = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    value = value.translate(_HAMZA_FOLD)
    # Drop ZWNJ/ZWJ so TTS/ASR spelling variants like زحمت‌کش vs زحمتکش match.
    value = value.replace("\u200c", "").replace("\u200d", "")
    value = _PERSIAN_DIACRITICS.sub("", value)
    # Arabic-block punctuation stays inside \u0600-\u06ff; strip it explicitly.
    value = _PERSIAN_PUNCTUATION.sub(" ", value)
    value = _NON_WORD.sub(" ", value.casefold())
    return " ".join(value.split())


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in _SENTENCES.split(text) if len(item.split()) >= 4]


def _best_window_similarity(needle: str, haystack: str) -> float:
    """Best ratio between `needle` and any comparable-length word window of `haystack`.

    Comparing against the whole haystack length-penalises short sentences; see
    _WINDOW_SCALES above.
    """
    score, _ = _best_available_window_match(needle, haystack.split(), consumed_words=set())
    return score


def _best_available_window_match(
    needle: str,
    haystack_words: list[str],
    *,
    consumed_words: set[int],
) -> tuple[float, tuple[int, int] | None]:
    """Return the best non-consumed transcript window and its word span."""
    needle_words = needle.split()
    if not needle_words:
        return 1.0, None
    if len(haystack_words) <= len(needle_words):
        if consumed_words:
            return 0.0, None
        return (
            SequenceMatcher(None, needle, " ".join(haystack_words), autojunk=False).ratio(),
            (0, len(haystack_words)),
        )

    best = 0.0
    best_window: tuple[int, int] | None = None
    # difflib indexes seq2 and caches it across set_seq1 calls, so the needle
    # must be seq2 and the sliding window seq1 -- not the other way round.
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(needle)
    widths = sorted({max(1, round(len(needle_words) * scale)) for scale in _WINDOW_SCALES})
    for width in widths:
        if width > len(haystack_words):
            continue
        for start in range(len(haystack_words) - width + 1):
            end = start + width
            if any(index in consumed_words for index in range(start, end)):
                continue
            matcher.set_seq1(" ".join(haystack_words[start : start + width]))
            # Cheap upper bounds first; skip windows that cannot beat `best`.
            if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
                continue
            score = matcher.ratio()
            if score > best:
                best = score
                best_window = (start, end)
    return best, best_window


def _missing_sentences(sentences: list[str], transcript: str, *, threshold: float) -> list[str]:
    """Find missing sentences without allowing one ASR span to match two inputs."""
    haystack_words = _normalize(transcript).split()
    consumed_words: set[int] = set()
    missing: list[str] = []
    for sentence in sentences:
        score, window = _best_available_window_match(
            _normalize(sentence),
            haystack_words,
            consumed_words=consumed_words,
        )
        if score < threshold:
            missing.append(sentence)
            continue
        if window is not None:
            consumed_words.update(range(*window))
    return missing


def _sentence_similarity(sentence: str, transcript: str) -> float:
    needle = _normalize(sentence)
    haystack = _normalize(transcript)
    if not needle:
        return 1
    if needle in haystack:
        return 1
    return _best_window_similarity(needle, haystack)


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
