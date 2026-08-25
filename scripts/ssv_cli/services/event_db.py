"""SQLite EventLedger runtime-state administration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

_RUNTIME_TABLES = (
    "events",
    "detections",
    "evidence",
    "reviews",
    "review_results",
    "durable_jobs",
)
_REQUIRED_COLUMNS = {
    "events": {
        "event_id",
        "source",
        "timestamp_ms",
        "frame_id",
        "status",
        "created_ms",
    },
    "detections": {
        "id",
        "event_id",
        "class_name",
        "class_id",
        "confidence",
        "bbox_json",
        "track_id",
    },
    "evidence": {"id", "event_id", "kind", "path"},
    "reviews": {
        "review_id",
        "event_id",
        "revision",
        "verdict",
        "confidence",
        "evidence_status",
        "explanation",
        "evidence_ids_json",
        "claims_json",
        "created_ms",
    },
    "review_results": {
        "event_id",
        "verdict",
        "confidence",
        "evidence_status",
        "explanation",
        "parsed_at_ms",
    },
    "durable_jobs": {
        "job_id",
        "kind",
        "entity_id",
        "entity_revision",
        "state",
        "attempts",
        "available_at_ms",
        "created_ms",
        "updated_ms",
    },
}
_DELETE_ORDER = (
    "review_results",
    "reviews",
    "detections",
    "evidence",
    "durable_jobs",
    "events",
)


class EventDbError(RuntimeError):
    """The configured EventLedger database cannot be inspected or cleared."""


@dataclass(frozen=True)
class EventDbStatus:
    path: Path
    exists: bool
    events: int = 0
    detections: int = 0
    evidence: int = 0
    reviews: int = 0
    review_results: int = 0
    durable_jobs: int = 0

    @property
    def total_rows(self) -> int:
        return sum(
            (
                self.events,
                self.detections,
                self.evidence,
                self.reviews,
                self.review_results,
                self.durable_jobs,
            )
        )


@dataclass(frozen=True)
class EventDbCleanupResult:
    status_before: EventDbStatus
    deleted_rows: int
    dry_run: bool


def _readonly_uri(path: Path) -> str:
    return f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _validate_schema(connection: sqlite3.Connection) -> set[str]:
    table_names = _table_names(connection)
    missing = sorted(set(_RUNTIME_TABLES) - table_names)
    if missing:
        missing_tables = ", ".join(missing)
        raise EventDbError(f"不是受支持的 SSV EventLedger 数据库，缺少表: {missing_tables}")
    invalid = {
        table: sorted(required - _column_names(connection, table))
        for table, required in _REQUIRED_COLUMNS.items()
    }
    invalid = {table: columns for table, columns in invalid.items() if columns}
    if invalid:
        details = "; ".join(
            f"{table} 缺少列 {', '.join(columns)}" for table, columns in invalid.items()
        )
        raise EventDbError(f"不是受支持的 SSV EventLedger 数据库: {details}")
    return table_names


def _status_from_connection(
    path: Path,
    connection: sqlite3.Connection,
    *,
    validate: bool = True,
) -> EventDbStatus:
    if validate:
        _validate_schema(connection)
    counts = {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in _RUNTIME_TABLES
    }
    return EventDbStatus(path=path, exists=True, **counts)


class EventDbAdmin:
    """Read and clear only the runtime tables owned by EventLedger."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def status(self) -> EventDbStatus:
        if not self.path.is_file():
            return EventDbStatus(path=self.path, exists=False)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(_readonly_uri(self.path), uri=True, timeout=5.0)
            return _status_from_connection(self.path, connection)
        except (EventDbError, OSError, sqlite3.Error) as exc:
            raise EventDbError(f"无法读取 SQLite EventLedger: {self.path}: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def clear(self, *, dry_run: bool = False) -> EventDbCleanupResult:
        before = self.status()
        if dry_run or not before.exists:
            return EventDbCleanupResult(
                status_before=before,
                deleted_rows=0,
                dry_run=dry_run,
            )

        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.execute("BEGIN IMMEDIATE")
            table_names = _validate_schema(connection)
            for table in _DELETE_ORDER:
                connection.execute(f"DELETE FROM {table}")
            if "sqlite_sequence" in table_names:
                connection.execute(
                    "DELETE FROM sqlite_sequence WHERE name IN (?, ?, ?, ?, ?, ?)",
                    _RUNTIME_TABLES,
                )
            connection.commit()
        except (EventDbError, OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.rollback()
            raise EventDbError(f"无法清理 SQLite EventLedger: {self.path}: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

        return EventDbCleanupResult(
            status_before=before,
            deleted_rows=before.total_rows,
            dry_run=False,
        )
