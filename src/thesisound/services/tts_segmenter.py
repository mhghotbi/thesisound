from __future__ import annotations

import re

from thesisound.audio import AudioChunk, content_hash
from thesisound.domain import Script

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!؟؛])\s+")


class TtsSegmenter:
    def __init__(self, *, max_characters: int = 900, words_per_minute: int = 135) -> None:
        if max_characters < 120:
            raise ValueError("TTS chunk size must be at least 120 characters.")
        self.max_characters = max_characters
        self.words_per_minute = words_per_minute

    def segment(
        self,
        script: Script,
        *,
        script_hash: str,
        model: str,
        voices: dict[str, str],
        style_prompt: str,
    ) -> list[AudioChunk]:
        chunks: list[AudioChunk] = []
        sequence = 0
        for turn in script.turns:
            voice = voices.get(turn.speaker)
            if not voice:
                raise ValueError(f"No TTS voice configured for speaker {turn.speaker}.")
            pieces = self._split(turn.spoken_text_fa)
            for piece_index, text in enumerate(pieces, start=1):
                chunk_id = f"audio-{sequence + 1:04d}"
                digest = content_hash(
                    script_hash,
                    turn.segment_id,
                    turn.turn_id,
                    str(piece_index),
                    turn.speaker,
                    voice,
                    model,
                    style_prompt,
                    text,
                )
                word_count = max(1, len(text.split()))
                expected = max(1.0, word_count / self.words_per_minute * 60)
                chunks.append(
                    AudioChunk(
                        chunk_id=chunk_id,
                        segment_id=turn.segment_id,
                        speaker=turn.speaker,
                        source_turn_ids=[turn.turn_id],
                        text=text,
                        sequence=sequence,
                        voice_name=voice,
                        content_hash=digest,
                        expected_duration_seconds=expected,
                    )
                )
                sequence += 1
        if not chunks:
            raise ValueError("Verified script contains no spoken turns.")
        return chunks

    def _split(self, text: str) -> list[str]:
        normalized = " ".join(text.split()).strip()
        if not normalized:
            raise ValueError("TTS cannot synthesize an empty turn.")
        sentences = [
            item.strip()
            for item in _SENTENCE_BOUNDARY.split(normalized)
            if item.strip()
        ]
        output: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > self.max_characters:
                if current:
                    output.append(current)
                    current = ""
                output.extend(self._split_long(sentence))
                continue
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > self.max_characters:
                output.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            output.append(current)
        return output

    def _split_long(self, text: str) -> list[str]:
        words = text.split()
        parts: list[str] = []
        current: list[str] = []
        for word in words:
            candidate = " ".join([*current, word])
            if current and len(candidate) > self.max_characters:
                parts.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            parts.append(" ".join(current))
        return parts
