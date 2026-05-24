from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "ascii_art.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS images (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT    NOT NULL,
                filepath    TEXT    NOT NULL UNIQUE,
                file_size   INTEGER,
                width_px    INTEGER,
                height_px   INTEGER,
                added_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS conversions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id     INTEGER NOT NULL
                             REFERENCES images(id) ON DELETE CASCADE,
                ascii_width  INTEGER NOT NULL,
                ascii_height INTEGER,
                charset      TEXT    NOT NULL DEFAULT 'standard',
                inverted     INTEGER NOT NULL DEFAULT 0,
                colored      INTEGER NOT NULL DEFAULT 0,
                result_text  TEXT    DEFAULT '',
                converted_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS exports (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                conversion_id  INTEGER NOT NULL
                               REFERENCES conversions(id) ON DELETE CASCADE,
                export_path    TEXT    NOT NULL,
                export_format  TEXT    NOT NULL DEFAULT 'txt',
                exported_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)


def add_image(
    filename: str,
    filepath: str,
    file_size: int | None = None,
    width_px: int | None = None,
    height_px: int | None = None,
) -> int:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO images "
            "(filename, filepath, file_size, width_px, height_px) VALUES (?,?,?,?,?)",
            (filename, filepath, file_size, width_px, height_px),
        )
        row = conn.execute(
            "SELECT id FROM images WHERE filepath = ?", (filepath,)
        ).fetchone()
        return int(row["id"])


def add_conversion(
    image_id: int,
    ascii_width: int,
    ascii_height: int | None,
    charset: str,
    inverted: bool,
    colored: bool,
    result_text: str = "",
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO conversions "
            "(image_id, ascii_width, ascii_height, charset, inverted, colored, result_text) "
            "VALUES (?,?,?,?,?,?,?)",
            (image_id, ascii_width, ascii_height, charset,
             int(inverted), int(colored), result_text),
        )
        return int(cur.lastrowid)


def add_export(conversion_id: int, export_path: str, export_format: str = "txt") -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO exports (conversion_id, export_path, export_format) VALUES (?,?,?)",
            (conversion_id, export_path, export_format),
        )
        return int(cur.lastrowid)


def q1_conversions_for_image(image_id: int) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT c.id, c.ascii_width, c.ascii_height, c.charset, "
            "       c.inverted, c.colored, c.converted_at "
            "FROM   conversions c "
            "WHERE  c.image_id = ? "
            "ORDER  BY c.converted_at DESC",
            (image_id,),
        ).fetchall()


def q2_recent_history(limit: int = 20) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT i.filename, c.ascii_width, c.ascii_height, "
            "       c.charset, c.inverted, c.colored, c.converted_at "
            "FROM   conversions c "
            "JOIN   images i ON c.image_id = i.id "
            "ORDER  BY c.converted_at DESC "
            "LIMIT  ?",
            (limit,),
        ).fetchall()


def q3_charset_statistics() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT charset, COUNT(*) AS total "
            "FROM   conversions "
            "GROUP  BY charset "
            "ORDER  BY total DESC"
        ).fetchall()


def q4_exports_with_details() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT e.id, i.filename, c.charset, c.ascii_width, "
            "       e.export_path, e.export_format, e.exported_at "
            "FROM   exports e "
            "JOIN   conversions c ON e.conversion_id = c.id "
            "JOIN   images      i ON c.image_id      = i.id "
            "ORDER  BY e.exported_at DESC"
        ).fetchall()


def q5_top_converted_images(limit: int = 5) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT i.filename, COUNT(c.id) AS conv_count "
            "FROM   images i "
            "LEFT JOIN conversions c ON i.id = c.image_id "
            "GROUP  BY i.id "
            "ORDER  BY conv_count DESC "
            "LIMIT  ?",
            (limit,),
        ).fetchall()
