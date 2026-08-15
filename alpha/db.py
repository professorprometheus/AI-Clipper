from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4


def now() -> str:
    return datetime.now(UTC).isoformat()


def uid() -> str:
    return str(uuid4())


def dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def load(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


class CursorLike(Protocol):
    rowcount: int

    def fetchone(self) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class PostgresConnection:
    """Expose the small sqlite-style execute surface used by the domain layer."""

    def __init__(self, connection: Any):
        self.connection = connection

    @staticmethod
    def _sql(sql: str) -> str:
        # Project SQL does not use question marks inside literals.
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> CursorLike:
        return self.connection.execute(self._sql(sql), params)


class Database:
    """SQLite/Postgres gateway with explicit transactions and additive migrations."""

    def __init__(self, target: str | Path, migrations_path: Path):
        raw_target = str(target)
        self.is_postgres = raw_target.startswith(("postgres://", "postgresql://"))
        self.url = raw_target if self.is_postgres else ""
        self.path = Path(raw_target) if not self.is_postgres else None
        self.migrations_path = Path(migrations_path)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migration_lock = threading.Lock()
        self.migrate()

    @property
    def acquire_lock_clause(self) -> str:
        return " FOR UPDATE SKIP LOCKED" if self.is_postgres else ""

    def connect(self) -> Any:
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - dependency is installed in production
                raise RuntimeError("Postgres requires the psycopg dependency") from exc
            return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migrate(self) -> None:
        with self._migration_lock:
            with self.connect() as connection:
                gateway = PostgresConnection(connection) if self.is_postgres else connection
                if self.is_postgres:
                    gateway.execute("SELECT pg_advisory_lock(71941002)")
                gateway.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                applied = {
                    row["version"]
                    for row in gateway.execute("SELECT version FROM schema_migrations").fetchall()
                }
                try:
                    for migration in sorted(self.migrations_path.glob("*.sql")):
                        if migration.name in applied:
                            continue
                        script = migration.read_text(encoding="utf-8")
                        if self.is_postgres:
                            script = "\n".join(
                                line
                                for line in script.splitlines()
                                if not line.startswith("PRAGMA ")
                            )
                            with connection.transaction():
                                connection.execute(script)
                                gateway.execute(
                                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                                    (migration.name, now()),
                                )
                        else:
                            connection.executescript(script)
                            gateway.execute(
                                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                                (migration.name, now()),
                            )
                finally:
                    if self.is_postgres:
                        gateway.execute("SELECT pg_advisory_unlock(71941002)")

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[Any]:
        connection = self.connect()
        try:
            if self.is_postgres:
                with connection.transaction():
                    yield PostgresConnection(connection)
            else:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                connection.execute("COMMIT")
        except Exception:
            if not self.is_postgres:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(sql, params)
            return cursor.rowcount

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            gateway = PostgresConnection(connection) if self.is_postgres else connection
            row = gateway.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            gateway = PostgresConnection(connection) if self.is_postgres else connection
            return [dict(row) for row in gateway.execute(sql, params).fetchall()]

    def audit(self, entity_type: str, entity_id: str, action: str, details: Any) -> None:
        self.execute(
            "INSERT INTO audit_log(id,entity_type,entity_id,action,details_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (uid(), entity_type, entity_id, action, dump(details), now()),
        )
