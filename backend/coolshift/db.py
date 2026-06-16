from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]


def default_db_path() -> Path:
    return ROOT / "data" / "coolshift.sqlite"


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS scenario_profiles (
    scenario_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    building_type TEXT NOT NULL,
    area_m2 REAL NOT NULL,
    room_count INTEGER NOT NULL,
    max_occupancy INTEGER NOT NULL,
    insulation_level TEXT NOT NULL,
    sun_exposure TEXT NOT NULL,
    comfort_min_c REAL NOT NULL,
    comfort_max_c REAL NOT NULL,
    vulnerable_occupants INTEGER NOT NULL,
    budget_pkr_per_day REAL NOT NULL,
    maximum_grid_demand_kw REAL NOT NULL,
    evaluation_focus TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS appliances (
    scenario_id TEXT NOT NULL,
    appliance_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    appliance_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    rated_power_kw REAL NOT NULL,
    cooling_capacity_kw REAL NOT NULL,
    efficiency_label TEXT,
    min_runtime_minutes INTEGER NOT NULL,
    min_setpoint_c REAL NOT NULL,
    max_setpoint_c REAL NOT NULL,
    PRIMARY KEY (scenario_id, appliance_id)
);

CREATE TABLE IF NOT EXISTS energy_assets (
    scenario_id TEXT PRIMARY KEY,
    solar_capacity_kw REAL NOT NULL,
    solar_conversion_efficiency REAL NOT NULL,
    battery_capacity_kwh REAL NOT NULL,
    initial_soc_kwh REAL NOT NULL,
    minimum_reserve_kwh REAL NOT NULL,
    max_charge_kw REAL NOT NULL,
    max_discharge_kw REAL NOT NULL,
    charge_efficiency REAL NOT NULL,
    discharge_efficiency REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS interval_inputs (
    scenario_id TEXT NOT NULL,
    timestamp_local TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    temperature_c REAL NOT NULL,
    relative_humidity_pct REAL NOT NULL,
    heat_index_c REAL NOT NULL,
    solar_irradiance_w_m2 REAL NOT NULL,
    solar_available_kw REAL NOT NULL,
    occupancy_count INTEGER NOT NULL,
    grid_available INTEGER NOT NULL,
    tariff_type TEXT NOT NULL,
    tariff_pkr_per_kwh REAL NOT NULL,
    grid_carbon_kgco2_per_kwh REAL NOT NULL,
    non_cooling_load_kw REAL NOT NULL,
    source_missing_flag INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scenario_id, timestamp_local)
);

CREATE TABLE IF NOT EXISTS baseline_schedule (
    scenario_id TEXT NOT NULL,
    timestamp_local TEXT NOT NULL,
    baseline_ac_units_on INTEGER NOT NULL,
    baseline_ac_setpoint_c REAL,
    baseline_fan_units_on INTEGER NOT NULL,
    baseline_other_cooling_kw REAL NOT NULL,
    baseline_rule TEXT,
    PRIMARY KEY (scenario_id, timestamp_local)
);

CREATE INDEX IF NOT EXISTS idx_interval_scenario_time ON interval_inputs(scenario_id, timestamp_local);
"""


class CoolShiftDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> "CoolShiftDB":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.conn:
            self.conn.close()

    @property
    def db(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Database is not open")
        return self.conn

    def initialize(self) -> None:
        self.db.executescript(SCHEMA)
        self.db.commit()

    def clear(self) -> None:
        for table in ("baseline_schedule", "interval_inputs", "energy_assets", "appliances", "scenario_profiles"):
            self.db.execute(f"DELETE FROM {table}")
        self.db.commit()

    def insert_many(self, table: str, rows: Iterable[dict]) -> None:
        rows = list(rows)
        if not rows:
            return
        cols = list(rows[0].keys())
        placeholders = ",".join("?" for _ in cols)
        sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
        self.db.executemany(sql, [[row.get(col) for col in cols] for row in rows])
        self.db.commit()

    def list_scenarios(self) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT p.*, COUNT(i.timestamp_local) AS interval_count,
                   MIN(i.timestamp_local) AS first_timestamp,
                   MAX(i.timestamp_local) AS last_timestamp
            FROM scenario_profiles p
            LEFT JOIN interval_inputs i ON i.scenario_id = p.scenario_id
            GROUP BY p.scenario_id
            ORDER BY p.scenario_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def available_dates(self, scenario_id: str) -> list[str]:
        rows = self.db.execute(
            "SELECT DISTINCT substr(timestamp_local, 1, 10) AS day FROM interval_inputs WHERE scenario_id=? ORDER BY day",
            (scenario_id,),
        ).fetchall()
        return [row["day"] for row in rows]

    def scenario_payload(self, scenario_id: str, start: str | None, days: int) -> dict:
        profile = self.db.execute("SELECT * FROM scenario_profiles WHERE scenario_id=?", (scenario_id,)).fetchone()
        if not profile:
            raise ValueError(f"Unknown scenario_id: {scenario_id}")
        appliances = [dict(row) for row in self.db.execute("SELECT * FROM appliances WHERE scenario_id=? ORDER BY appliance_id", (scenario_id,))]
        asset = self.db.execute("SELECT * FROM energy_assets WHERE scenario_id=?", (scenario_id,)).fetchone()
        if not asset:
            raise ValueError(f"Missing energy assets for {scenario_id}")
        if not start:
            start = self.available_dates(scenario_id)[0]
        end_clause = "datetime(?, '+' || ? || ' days')"
        intervals = [
            dict(row)
            for row in self.db.execute(
                f"""
                SELECT * FROM interval_inputs
                WHERE scenario_id=? AND datetime(timestamp_local) >= datetime(?)
                  AND datetime(timestamp_local) < {end_clause}
                ORDER BY timestamp_local
                """,
                (scenario_id, start, start, days),
            )
        ]
        baseline = [
            dict(row)
            for row in self.db.execute(
                f"""
                SELECT * FROM baseline_schedule
                WHERE scenario_id=? AND datetime(timestamp_local) >= datetime(?)
                  AND datetime(timestamp_local) < {end_clause}
                ORDER BY timestamp_local
                """,
                (scenario_id, start, start, days),
            )
        ]
        return {
            "profile": dict(profile),
            "appliances": appliances,
            "asset": dict(asset),
            "intervals": intervals,
            "baseline": baseline,
        }

