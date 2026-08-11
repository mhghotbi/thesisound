"""Always-on product event store. Never consults tracing_enabled."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel


class ProductEventRecord(BaseModel):
    event_id: str
    occurred_at: datetime
    name: str
    user_id: int | None = None
    anon_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    environment: str
    is_synthetic: bool
    event_version: int = 1
    properties: dict[str, Any]


class ProductEventStore:
    """Append-only product events + disposable daily rollups in the ledger DB."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def write(
        self,
        *,
        name: str,
        properties_json: str,
        environment: str,
        is_synthetic: bool,
        user_id: int | None = None,
        anon_id: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        event_version: int = 1,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
    ) -> str:
        """Append one product event. Returns the event_id."""

        eid = event_id or str(uuid4())
        when = (occurred_at or datetime.now(UTC)).astimezone(UTC)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO product_events(
                    event_id, occurred_at, name, user_id, anon_id, project_id,
                    session_id, environment, is_synthetic, event_version,
                    properties_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    when.isoformat(),
                    name,
                    user_id,
                    anon_id,
                    project_id,
                    session_id,
                    environment,
                    int(is_synthetic),
                    event_version,
                    properties_json,
                ),
            )
        return eid

    def last_event_time(
        self,
        *,
        name: str,
        project_id: UUID | str | None = None,
        gate_name: str | None = None,
    ) -> datetime | None:
        """Return the most recent occurred_at for a named event, optionally scoped."""

        clauses = ["name = ?"]
        params: list[object] = [name]
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(str(project_id))
        if gate_name is not None:
            clauses.append("json_extract(properties_json, '$.gate_name') = ?")
            params.append(gate_name)
        sql = (
            f"SELECT occurred_at FROM product_events WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC LIMIT 1"
        )
        with closing(self.connect_readonly()) as connection:
            row = connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(str(row[0]))

    def list_events(
        self,
        *,
        name: str | None = None,
        project_id: UUID | str | None = None,
        user_id: int | None = None,
        limit: int = 200,
    ) -> list[ProductEventRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if name is not None:
            clauses.append("name = ?")
            params.append(name)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(str(project_id))
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT event_id, occurred_at, name, user_id, anon_id, project_id,
                   session_id, environment, is_synthetic, event_version,
                   properties_json
              FROM product_events
              {where}
             ORDER BY occurred_at DESC
             LIMIT ?
        """
        params.append(limit)
        with closing(self.connect_readonly()) as connection:
            rows = connection.execute(sql, params).fetchall()
        import json

        return [
            ProductEventRecord(
                event_id=row[0],
                occurred_at=datetime.fromisoformat(str(row[1])),
                name=row[2],
                user_id=row[3],
                anon_id=row[4],
                project_id=row[5],
                session_id=row[6],
                environment=row[7],
                is_synthetic=bool(row[8]),
                event_version=int(row[9]),
                properties=json.loads(row[10] or "{}"),
            )
            for row in rows
        ]

    def connect_readonly(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection
