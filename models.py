"""
models.py — Pydantic models for JK BMS data.
"""

from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class PackData(BaseModel):
    voltage: float
    current: float
    power: float
    soc: int
    remain_ah: float
    nominal_ah: float
    cycles: int
    temp_mosfet: float
    temp1: float
    temp2: float
    charge_mos: bool
    disch_mos: bool
    balancer: bool
    avg_cell_v: float
    min_cell_v: float
    max_cell_v: float
    delta_mv: int
    alarm_ov: bool
    alarm_uv: bool
    alarm_oc: bool
    alarm_ot: bool
    uptime_sec: int


class CellData(BaseModel):
    c01: Optional[float] = None
    c02: Optional[float] = None
    c03: Optional[float] = None
    c04: Optional[float] = None
    c05: Optional[float] = None
    c06: Optional[float] = None
    c07: Optional[float] = None
    c08: Optional[float] = None
    c09: Optional[float] = None
    c10: Optional[float] = None
    c11: Optional[float] = None
    c12: Optional[float] = None
    c13: Optional[float] = None
    c14: Optional[float] = None
    c15: Optional[float] = None
    c16: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class LatestResponse(BaseModel):
    ts: str
    voltage: float
    current: float
    power: float
    soc: int
    remain_ah: float
    nominal_ah: float
    cycles: int
    temp_mosfet: float
    temp1: float
    temp2: float
    charge_mos: bool
    disch_mos: bool
    balancer: bool
    avg_cell_v: float
    min_cell_v: float
    max_cell_v: float
    delta_mv: int
    alarm_ov: bool
    alarm_uv: bool
    alarm_oc: bool
    alarm_ot: bool
    uptime_sec: int
    cells: dict[str, float]


class StatusResponse(BaseModel):
    mqtt_connected: bool
    last_seen: Optional[str]
    db_size_mb: float
