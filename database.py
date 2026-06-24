"""
database.py — SQLite setup and queries for JK BMS monitor.
Uses stdlib sqlite3 with a per-call connection pattern.
"""

from __future__ import annotations

import sqlite3
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "./bms.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          DATETIME DEFAULT (datetime('now')),
                voltage     REAL,
                current     REAL,
                power       REAL,
                soc         INTEGER,
                remain_ah   REAL,
                nominal_ah  REAL,
                cycles      INTEGER,
                temp_mosfet REAL,
                temp1       REAL,
                temp2       REAL,
                charge_mos  INTEGER,
                disch_mos   INTEGER,
                balancer    INTEGER,
                avg_cell_v  REAL,
                min_cell_v  REAL,
                max_cell_v  REAL,
                delta_mv    INTEGER,
                alarm_ov    INTEGER,
                alarm_uv    INTEGER,
                alarm_oc    INTEGER,
                alarm_ot    INTEGER,
                uptime_sec  INTEGER
            );

            CREATE TABLE IF NOT EXISTS cell_readings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                reading_id INTEGER REFERENCES readings(id),
                ts         DATETIME DEFAULT (datetime('now')),
                cell_num   INTEGER,
                voltage    REAL
            );

            CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);
            CREATE INDEX IF NOT EXISTS idx_cell_readings_ts ON cell_readings(ts);
            CREATE INDEX IF NOT EXISTS idx_cell_readings_rid ON cell_readings(reading_id);
        """)
    logger.info("Database initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def insert_reading(data: dict) -> int:
    """Insert a pack reading. Returns the new row id."""
    sql = """
        INSERT INTO readings (
            voltage, current, power, soc, remain_ah, nominal_ah, cycles,
            temp_mosfet, temp1, temp2,
            charge_mos, disch_mos, balancer,
            avg_cell_v, min_cell_v, max_cell_v, delta_mv,
            alarm_ov, alarm_uv, alarm_oc, alarm_ot,
            uptime_sec
        ) VALUES (
            :voltage, :current, :power, :soc, :remain_ah, :nominal_ah, :cycles,
            :temp_mosfet, :temp1, :temp2,
            :charge_mos, :disch_mos, :balancer,
            :avg_cell_v, :min_cell_v, :max_cell_v, :delta_mv,
            :alarm_ov, :alarm_uv, :alarm_oc, :alarm_ot,
            :uptime_sec
        )
    """
    # Normalise booleans → integers for SQLite
    row = {k: (int(v) if isinstance(v, bool) else v) for k, v in data.items()}
    with _connect() as conn:
        cur = conn.execute(sql, row)
        return cur.lastrowid


def insert_cells(reading_id: int, cells: dict) -> None:
    """Insert per-cell voltages linked to a reading."""
    rows = []
    for key, voltage in cells.items():
        try:
            cell_num = int(key.lstrip("c").lstrip("0") or "0")
        except ValueError:
            continue
        rows.append((reading_id, cell_num, voltage))

    with _connect() as conn:
        conn.executemany(
            "INSERT INTO cell_readings (reading_id, cell_num, voltage) VALUES (?, ?, ?)",
            rows,
        )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_latest() -> dict | None:
    """Return the most recent reading with its cell voltages, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM readings ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None

        result = dict(row)
        cells_rows = conn.execute(
            "SELECT cell_num, voltage FROM cell_readings WHERE reading_id = ? ORDER BY cell_num",
            (result["id"],),
        ).fetchall()

    result["cells"] = {f"c{r['cell_num']:02d}": r["voltage"] for r in cells_rows}
    return result


def get_history(hours: int = 24, interval_minutes: int = 1) -> list[dict]:
    """
    Return downsampled pack history.
    Uses SQLite strftime bucketing to keep one row per interval bucket.
    """
    interval_sec = interval_minutes * 60
    sql = """
        SELECT
            datetime(CAST(strftime('%s', ts) / :iv AS INTEGER) * :iv, 'unixepoch') AS ts,
            AVG(voltage)  AS voltage,
            AVG(current)  AS current,
            AVG(power)    AS power,
            AVG(soc)      AS soc,
            AVG(remain_ah) AS remain_ah,
            AVG(temp1)    AS temp1,
            AVG(temp2)    AS temp2,
            AVG(avg_cell_v) AS avg_cell_v,
            AVG(min_cell_v) AS min_cell_v,
            AVG(max_cell_v) AS max_cell_v,
            AVG(delta_mv) AS delta_mv
        FROM readings
        WHERE ts >= datetime('now', :window)
        GROUP BY CAST(strftime('%s', ts) / :iv AS INTEGER)
        ORDER BY ts ASC
    """
    window = f"-{hours} hours"
    with _connect() as conn:
        rows = conn.execute(sql, {"iv": interval_sec, "window": window}).fetchall()
    return [dict(r) for r in rows]


def get_cell_history(cell_num: int, hours: int = 6) -> list[dict]:
    """Return voltage history for a single cell."""
    sql = """
        SELECT ts, voltage
        FROM cell_readings
        WHERE cell_num = ?
          AND ts >= datetime('now', ?)
        ORDER BY ts ASC
    """
    window = f"-{hours} hours"
    with _connect() as conn:
        rows = conn.execute(sql, (cell_num, window)).fetchall()
    return [dict(r) for r in rows]


def get_stats(hours: int = 24) -> dict:
    """Return min/max/avg for key fields over the requested window."""
    sql = """
        SELECT
            MIN(voltage)   AS voltage_min,  MAX(voltage)   AS voltage_max,  AVG(voltage)   AS voltage_avg,
            MIN(current)   AS current_min,  MAX(current)   AS current_max,  AVG(current)   AS current_avg,
            MIN(power)     AS power_min,    MAX(power)     AS power_max,    AVG(power)     AS power_avg,
            MIN(soc)       AS soc_min,      MAX(soc)       AS soc_max,      AVG(soc)       AS soc_avg,
            MIN(temp1)     AS temp1_min,    MAX(temp1)     AS temp1_max,    AVG(temp1)     AS temp1_avg,
            MIN(delta_mv)  AS delta_mv_min, MAX(delta_mv)  AS delta_mv_max, AVG(delta_mv)  AS delta_mv_avg,
            COUNT(*)       AS sample_count
        FROM readings
        WHERE ts >= datetime('now', ?)
    """
    window = f"-{hours} hours"
    with _connect() as conn:
        row = conn.execute(sql, (window,)).fetchone()
    return dict(row) if row else {}


def get_alarm_events(limit: int = 50) -> list[dict]:
    """Return readings where any alarm was active."""
    sql = """
        SELECT *
        FROM readings
        WHERE alarm_ov = 1 OR alarm_uv = 1 OR alarm_oc = 1 OR alarm_ot = 1
        ORDER BY ts DESC
        LIMIT ?
    """
    with _connect() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]


def cleanup_old_data(keep_days: int = 30) -> int:
    """Delete readings older than keep_days. Returns number of rows deleted."""
    window = f"-{keep_days} days"
    with _connect() as conn:
        # Delete orphaned cell_readings first (no CASCADE in SQLite by default)
        conn.execute(
            """
            DELETE FROM cell_readings
            WHERE reading_id IN (
                SELECT id FROM readings WHERE ts < datetime('now', ?)
            )
            """,
            (window,),
        )
        cur = conn.execute(
            "DELETE FROM readings WHERE ts < datetime('now', ?)",
            (window,),
        )
        deleted = cur.rowcount
    if deleted:
        logger.info("Cleanup: removed %d old readings", deleted)
    return deleted


def get_db_size_mb() -> float:
    """Return SQLite file size in MB."""
    try:
        return os.path.getsize(DB_PATH) / (1024 * 1024)
    except OSError:
        return 0.0
