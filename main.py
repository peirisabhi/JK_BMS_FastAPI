"""
main.py — FastAPI app + MQTT subscriber + startup/shutdown for JK BMS monitor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import database as db
from models import StatusResponse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "esp32")
MQTT_PASS = os.getenv("MQTT_PASS", "")
KEEP_DAYS = int(os.getenv("KEEP_DAYS", "30"))

TOPIC_PACK  = "bms/jk/pack"
TOPIC_CELLS = "bms/jk/cells"

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bms")

# ---------------------------------------------------------------------------
# Shared state (written by MQTT thread, read by API)
# ---------------------------------------------------------------------------

_state = {
    "mqtt_connected": False,
    "last_seen": None,        # datetime (UTC)
    "last_reading_id": None,  # int
    "last_reading_ts": None,  # float (time.monotonic)
}
_state_lock = threading.Lock()

CELLS_PAIRING_WINDOW = 10  # seconds: max lag between pack and cells messages


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def _on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("MQTT connected to %s:%s", MQTT_HOST, MQTT_PORT)
        client.subscribe([(TOPIC_PACK, 0), (TOPIC_CELLS, 0)])
        with _state_lock:
            _state["mqtt_connected"] = True
    else:
        logger.error("MQTT connect failed, rc=%s", rc)
        with _state_lock:
            _state["mqtt_connected"] = False


def _on_disconnect(client, userdata, rc, properties=None, reasoncode=None):
    logger.warning("MQTT disconnected, rc=%s — will auto-reconnect", rc)
    with _state_lock:
        _state["mqtt_connected"] = False


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Bad payload on %s: %s", msg.topic, exc)
        return

    if msg.topic == TOPIC_PACK:
        _handle_pack(payload)
    elif msg.topic == TOPIC_CELLS:
        _handle_cells(payload)


def _handle_pack(data: dict):
    try:
        reading_id = db.insert_reading(data)
    except Exception as exc:
        logger.error("insert_reading failed: %s", exc)
        return

    now = time.monotonic()
    with _state_lock:
        _state["last_reading_id"] = reading_id
        _state["last_reading_ts"] = now
        _state["last_seen"] = datetime.now(timezone.utc)

    logger.debug("Pack reading stored, id=%s", reading_id)


def _handle_cells(data: dict):
    now = time.monotonic()
    with _state_lock:
        reading_id = _state["last_reading_id"]
        last_ts    = _state["last_reading_ts"]

    if reading_id is None or last_ts is None:
        logger.debug("Cells received but no recent pack reading — skipping")
        return

    if (now - last_ts) > CELLS_PAIRING_WINDOW:
        logger.debug("Cells received but pack reading too old (%ss) — skipping", now - last_ts)
        return

    try:
        db.insert_cells(reading_id, data)
    except Exception as exc:
        logger.error("insert_cells failed: %s", exc)
        return

    logger.debug("Cell reading stored for reading_id=%s", reading_id)


# ---------------------------------------------------------------------------
# MQTT thread
# ---------------------------------------------------------------------------

def _mqtt_thread():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message    = _on_message

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            logger.error("MQTT error: %s — retrying in 10s", exc)
            with _state_lock:
                _state["mqtt_connected"] = False
            time.sleep(10)


# ---------------------------------------------------------------------------
# Cleanup background task
# ---------------------------------------------------------------------------

async def _daily_cleanup():
    """Run cleanup once at startup (to handle missed days) then every 24h."""
    while True:
        now = datetime.now()
        # Sleep until 03:00 local time
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run.replace(day=now.day + 1)
        sleep_sec = (next_run - now).total_seconds()
        logger.info("Next DB cleanup scheduled in %.0f seconds", sleep_sec)
        await asyncio.sleep(sleep_sec)
        try:
            deleted = db.cleanup_old_data(keep_days=KEEP_DAYS)
            logger.info("Daily cleanup done: %d readings removed", deleted)
        except Exception as exc:
            logger.error("Daily cleanup failed: %s", exc)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.init_db()

    thread = threading.Thread(target=_mqtt_thread, daemon=True, name="mqtt")
    thread.start()
    logger.info("MQTT thread started")

    cleanup_task = asyncio.create_task(_daily_cleanup())

    yield

    # Shutdown
    cleanup_task.cancel()
    logger.info("Shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="JK BMS Monitor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_dashboard():
    if not DASHBOARD_PATH.exists():
        raise HTTPException(status_code=404, detail="dashboard.html not found")
    return FileResponse(DASHBOARD_PATH)


@app.get("/api/latest")
async def api_latest():
    row = db.get_latest()
    if row is None:
        raise HTTPException(status_code=503, detail="No data received yet")

    # Convert integer booleans back to bool for JSON
    bool_fields = {"charge_mos", "disch_mos", "balancer",
                   "alarm_ov", "alarm_uv", "alarm_oc", "alarm_ot"}
    for f in bool_fields:
        if f in row:
            row[f] = bool(row[f])

    # Remove internal DB id
    row.pop("id", None)
    return JSONResponse(content=row)


@app.get("/api/history")
async def api_history(hours: int = 24, interval: int = 1):
    if hours < 1 or hours > 8760:
        raise HTTPException(status_code=400, detail="hours must be 1–8760")
    if interval < 1 or interval > 60:
        raise HTTPException(status_code=400, detail="interval must be 1–60 minutes")
    rows = db.get_history(hours=hours, interval_minutes=interval)
    return JSONResponse(content=rows)


@app.get("/api/cells/history")
async def api_cell_history(cell: int = 1, hours: int = 6):
    if cell < 1 or cell > 24:
        raise HTTPException(status_code=400, detail="cell must be 1–24")
    if hours < 1 or hours > 8760:
        raise HTTPException(status_code=400, detail="hours must be 1–8760")
    rows = db.get_cell_history(cell_num=cell, hours=hours)
    return JSONResponse(content=rows)


@app.get("/api/stats")
async def api_stats(hours: int = 24):
    if hours < 1 or hours > 8760:
        raise HTTPException(status_code=400, detail="hours must be 1–8760")
    stats = db.get_stats(hours=hours)
    if not stats or stats.get("sample_count") == 0:
        raise HTTPException(status_code=503, detail="No data in requested window")
    return JSONResponse(content=stats)


@app.get("/api/alarms")
async def api_alarms(limit: int = 50):
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be 1–1000")
    rows = db.get_alarm_events(limit=limit)
    bool_fields = {"charge_mos", "disch_mos", "balancer",
                   "alarm_ov", "alarm_uv", "alarm_oc", "alarm_ot"}
    for row in rows:
        for f in bool_fields:
            if f in row:
                row[f] = bool(row[f])
        row.pop("id", None)
    return JSONResponse(content=rows)


@app.get("/api/status", response_model=StatusResponse)
async def api_status():
    with _state_lock:
        connected = _state["mqtt_connected"]
        last_seen = _state["last_seen"]

    return StatusResponse(
        mqtt_connected=connected,
        last_seen=last_seen.isoformat() if last_seen else None,
        db_size_mb=db.get_db_size_mb(),
    )
