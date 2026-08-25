from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.ssv_cli.services.event_db import EventDbAdmin, EventDbError

_TABLES = (
    "events",
    "detections",
    "evidence",
    "reviews",
    "review_results",
    "durable_jobs",
)


def _create_event_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                frame_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_ms INTEGER NOT NULL
            );
            CREATE TABLE detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                class_name TEXT NOT NULL,
                class_id INTEGER NOT NULL,
                confidence REAL NOT NULL,
                bbox_json TEXT NOT NULL,
                track_id INTEGER NOT NULL
            );
            CREATE TABLE evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL
            );
            CREATE TABLE reviews (
                review_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                confidence REAL NOT NULL,
                evidence_status TEXT NOT NULL,
                explanation TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL,
                claims_json TEXT NOT NULL,
                created_ms INTEGER NOT NULL
            );
            CREATE TABLE review_results (
                event_id TEXT PRIMARY KEY,
                verdict TEXT,
                confidence REAL,
                evidence_status TEXT,
                explanation TEXT,
                parsed_at_ms INTEGER NOT NULL
            );
            CREATE TABLE durable_jobs (
                job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_revision INTEGER NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                available_at_ms INTEGER NOT NULL,
                created_ms INTEGER NOT NULL,
                updated_ms INTEGER NOT NULL
            );
            CREATE TABLE unrelated (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                value TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO events VALUES ('event-1', 'camera-1', 1000, 1, 'pending', 1000)"
        )
        connection.execute(
            "INSERT INTO detections VALUES (NULL, 'event-1', 'person', 0, 0.9, '[]', 1)"
        )
        connection.execute(
            "INSERT INTO evidence VALUES (NULL, 'event-1', 'frame', '/tmp/frame.jpg')"
        )
        connection.execute(
            "INSERT INTO reviews VALUES "
            "('review-1', 'event-1', 0, 'allow', 0.9, 'available', 'ok', '[]', '[]', 1000)"
        )
        connection.execute(
            "INSERT INTO review_results VALUES ('event-1', 'allow', 0.9, 'available', 'ok', 1000)"
        )
        connection.execute(
            "INSERT INTO durable_jobs VALUES "
            "(NULL, 'review', 'event-1', 0, 'pending', 0, 1000, 1000, 1000)"
        )
        connection.execute("INSERT INTO unrelated (value) VALUES ('keep me')")
        connection.commit()
    finally:
        connection.close()


class EventDbAdminTest(unittest.TestCase):
    def test_status_reports_runtime_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.db"
            _create_event_db(path)

            status = EventDbAdmin(path).status()

        self.assertTrue(status.exists)
        self.assertEqual(status.events, 1)
        self.assertEqual(status.detections, 1)
        self.assertEqual(status.durable_jobs, 1)
        self.assertEqual(status.total_rows, 6)

    def test_dry_run_does_not_delete_runtime_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.db"
            _create_event_db(path)

            result = EventDbAdmin(path).clear(dry_run=True)
            status = EventDbAdmin(path).status()

        self.assertTrue(result.dry_run)
        self.assertEqual(result.deleted_rows, 0)
        self.assertEqual(result.status_before.total_rows, 6)
        self.assertEqual(status.total_rows, 6)

    def test_clear_deletes_runtime_tables_and_resets_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.db"
            _create_event_db(path)

            result = EventDbAdmin(path).clear()
            status = EventDbAdmin(path).status()
            connection = sqlite3.connect(path)
            try:
                sequences = connection.execute("SELECT name, seq FROM sqlite_sequence").fetchall()
                unrelated = connection.execute("SELECT value FROM unrelated").fetchall()
            finally:
                connection.close()

        self.assertFalse(result.dry_run)
        self.assertEqual(result.deleted_rows, 6)
        self.assertEqual(status.total_rows, 0)
        self.assertEqual(sequences, [("unrelated", 1)])
        self.assertEqual(unrelated, [("keep me",)])

    def test_missing_database_is_an_empty_runtime_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"

            admin = EventDbAdmin(path)
            status = admin.status()
            result = admin.clear()

        self.assertFalse(status.exists)
        self.assertEqual(status.total_rows, 0)
        self.assertEqual(result.deleted_rows, 0)
        self.assertFalse(path.exists())

    def test_rejects_a_non_event_ledger_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "other.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE unrelated (id INTEGER)")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(EventDbError):
                EventDbAdmin(path).status()

    def test_rejects_same_named_database_with_incompatible_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lookalike.db"
            connection = sqlite3.connect(path)
            try:
                for table in _TABLES:
                    connection.execute(f"CREATE TABLE {table} (id INTEGER)")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(EventDbError):
                EventDbAdmin(path).status()


if __name__ == "__main__":
    unittest.main()
