# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-06-27

### Initial Release

First public release of JK BMS Monitor - a self-hosted battery monitoring dashboard for JK BMS units via ESP32 + MQTT.

### Added

**Backend**
- FastAPI application with lifespan management (startup/shutdown hooks)
- MQTT subscriber via `paho-mqtt` with auto-reconnect
- Two-topic data pipeline: `bms/jk/pack` for pack data, `bms/jk/cells` for per-cell voltages
- 10-second pairing window to link cell readings to their parent pack reading
- SQLite database with `readings` and `cell_readings` tables
- Automatic daily cleanup task at 03:00 - configurable via `KEEP_DAYS`
- Thread-safe shared state between MQTT thread and FastAPI async loop

**API Endpoints**
- `GET /api/latest` - most recent full BMS snapshot including cell voltages
- `GET /api/history` - downsampled time-series with configurable `hours` and `interval` (minutes)
- `GET /api/cells/history` - per-cell voltage history for a single cell
- `GET /api/stats` - min/max/avg aggregates over a configurable time window
- `GET /api/alarms` - historical alarm events (OV, UV, OC, OT)
- `GET /api/status` - MQTT connection health, last seen timestamp, DB size

**Dashboard**
- Dark-theme real-time web dashboard served at `/`
- Live MQTT connection via WebSocket (browser connects directly to Mosquitto)
- KPI cards: pack voltage, current, power, SoC, cell delta, MOSFET temperature
- Charging/discharging/idle state badge with colour coding
- SoC progress bar with remaining Ah
- Per-cell voltage grid with min/max highlight and balancer indicator
- Voltage history chart and current/power dual-axis history chart
- Temperature bar gauges (MOSFET, Sensor 1, Sensor 2)
- MOS switch status, balancer status, cycle count, uptime
- Alarm panel with active alarm highlighting
- Device info panel (model, serial, hardware/firmware version)
- Offline detection banner after 15 seconds of no data
- Responsive layout for mobile and tablet

**Infrastructure**
- `bms.service` - systemd unit file for running as a background service
- `.env` / `.env.example` - environment-based configuration
- `requirements.txt` - minimal dependency list (FastAPI, uvicorn, paho-mqtt, python-dotenv)
- `.gitignore` - excludes venv, database, secrets, and OS files

**Documentation**
- Full `README.md` with step-by-step deployment guide
- Oracle Cloud Free Tier setup instructions
- Mosquitto MQTT broker configuration guide
- Nginx reverse proxy configuration
- UFW and Oracle Cloud Security List firewall setup
- ESPHome vs Home Assistant comparison (pros & cons)
- MQTT payload format reference
- REST API reference table
- `CHANGELOG.md` (this file)

---

## [Unreleased]

### Planned
- [ ] HTTPS / TLS support for MQTT (port 8883)
- [ ] Push notifications (Telegram / Pushover) on alarm trigger
- [ ] CSV export endpoint for history data
- [ ] Multi-BMS support (multiple ESP32 units)
- [ ] Configurable cell count (currently assumes up to 24S)
- [ ] Dark/light theme toggle on dashboard
- [ ] Docker Compose deployment option

---

[1.0.0]: https://github.com/peirisabhi/JK_BMS_FastAPI/releases/tag/v1.0.0
[Unreleased]: https://github.com/peirisabhi/JK_BMS_FastAPI/compare/v1.0.0...HEAD
