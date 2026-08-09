from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from uuid import UUID

from thesisound import tracing
from thesisound.episode import RetrievalHit
from thesisound.source_analysis import SourceDocumentBlock

_TOKEN = re.compile(r"\w+", re.UNICODE)


class SQLiteBlockRetriever:
    """Small local FTS5 index for retrieving context from normalized source blocks."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def rebuild(self, blocks: list[SourceDocumentBlock]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM block_fts")
            connection.executemany(
                "INSERT INTO block_fts(block_id, source_id, heading, text) VALUES (?, ?, ?, ?)",
                [
                    (
                        block.block_id,
                        str(block.source_id),
                        " / ".join(block.heading_path),
                        block.text,
                    )
                    for block in blocks
                ],
            )

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        source_ids: set[UUID] | None = None,
    ) -> list[RetrievalHit]:
        with tracing.span(
            "episode.retrieve", component="episode", kind="db", detail="verbose"
        ) as span:
            expression = _fts_expression(query)
            if not expression:
                span.measure(result_count=0)
                return []
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT block_id, source_id, bm25(block_fts) AS rank
                    FROM block_fts
                    WHERE block_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (expression, max(1, limit * 3)),
                ).fetchall()
            allowed = {str(item) for item in source_ids} if source_ids else None
            hits: list[RetrievalHit] = []
            for block_id, source_id, rank in rows:
                if allowed is not None and source_id not in allowed:
                    continue
                hits.append(
                    RetrievalHit(
                        block_id=block_id,
                        source_id=UUID(source_id),
                        score=round(1 / (1 + abs(float(rank))), 6),
                        query=query,
                    )
                )
                if len(hits) >= limit:
                    break
            span.measure(result_count=len(hits), top_score=hits[0].score if hits else 0)
            return hits

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS block_fts USING fts5(
                    block_id UNINDEXED,
                    source_id UNINDEXED,
                    heading,
                    text,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)


def _fts_expression(query: str) -> str:
    terms = [token.casefold() for token in _TOKEN.findall(query) if len(token) > 2]
    unique = list(dict.fromkeys(terms))[:16]
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in unique)
