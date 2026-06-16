from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .db import CoolShiftDB
from .sample_data import custom_rows


WORKBOOK_NAME = "04_CoolShift_Public_Dataset_and_Templates.xlsx"


def read_sheet(ws, header_row: int = 1) -> list[dict]:
    rows = list(ws.iter_rows(values_only=True))
    header_index = None
    for idx, row in enumerate(rows):
        values = [str(v).strip() if v is not None else "" for v in row]
        if any(v in ("scenario_id", "case_id", "reason_code", "field", "Metric") for v in values):
            header_index = idx
            break
    if header_index is None:
        return []
    headers = [str(v).strip() if v is not None else "" for v in rows[header_index]]
    output = []
    for row in rows[header_index + 1 :]:
        item = {}
        for col, value in zip(headers, row):
            if col:
                item[col] = clean_value(value)
        if any(v not in (None, "") for v in item.values()):
            output.append(item)
    return output


def clean_value(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def import_zip_to_db(zip_path: Path, db_path: Path) -> dict:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for workbook import. Install it or use the bundled Codex Python.") from exc

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(WORKBOOK_NAME) as fh:
            workbook_bytes = io.BytesIO(fh.read())
    wb = openpyxl.load_workbook(workbook_bytes, data_only=True)

    scenario_profiles = read_sheet(wb["Scenario_Profiles"])
    appliances = read_sheet(wb["Appliances"])
    energy_assets = read_sheet(wb["Energy_Assets"])
    intervals = read_sheet(wb["Interval_Inputs"])
    baseline = read_sheet(wb["Baseline_Schedule"])

    custom = custom_rows()
    scenario_profiles.append(custom["profile"])
    appliances.extend(custom["appliances"])
    energy_assets.append(custom["asset"])
    intervals.extend(custom["intervals"])
    baseline.extend(custom["baseline"])

    normalize(scenario_profiles, appliances, energy_assets, intervals, baseline)

    with CoolShiftDB(db_path) as db:
        db.initialize()
        db.clear()
        db.insert_many("scenario_profiles", scenario_profiles)
        db.insert_many("appliances", appliances)
        db.insert_many("energy_assets", energy_assets)
        db.insert_many("interval_inputs", intervals)
        db.insert_many("baseline_schedule", baseline)

    return {
        "scenario_profiles": len(scenario_profiles),
        "appliances": len(appliances),
        "energy_assets": len(energy_assets),
        "interval_inputs": len(intervals),
        "baseline_schedule": len(baseline),
        "db_path": str(db_path),
    }


def normalize(profiles, appliances, assets, intervals, baseline) -> None:
    for row in profiles:
        row.setdefault("evaluation_focus", row.get("data_source_or_generation_note", ""))
        for key in ("area_m2", "comfort_min_c", "comfort_max_c", "budget_pkr_per_day", "maximum_grid_demand_kw"):
            row[key] = float(row[key])
        for key in ("room_count", "max_occupancy", "vulnerable_occupants"):
            row[key] = int(row[key])

    for row in appliances:
        row["quantity"] = int(row["quantity"])
        row["rated_power_kw"] = float(row["rated_power_kw"])
        row["cooling_capacity_kw"] = float(row["cooling_capacity_kw"])
        row["min_runtime_minutes"] = int(row["min_runtime_minutes"])
        row["min_setpoint_c"] = float(row["min_setpoint_c"] or 0)
        row["max_setpoint_c"] = float(row["max_setpoint_c"] or 0)

    for row in assets:
        for key in (
            "solar_capacity_kw",
            "solar_conversion_efficiency",
            "battery_capacity_kwh",
            "initial_soc_kwh",
            "minimum_reserve_kwh",
            "max_charge_kw",
            "max_discharge_kw",
            "charge_efficiency",
            "discharge_efficiency",
        ):
            row[key] = float(row[key])

    for row in intervals:
        row["timestamp_local"] = str(row["timestamp_local"]).replace(" ", "T")
        row["interval_minutes"] = int(row["interval_minutes"])
        for key in (
            "temperature_c",
            "relative_humidity_pct",
            "heat_index_c",
            "solar_irradiance_w_m2",
            "solar_available_kw",
            "tariff_pkr_per_kwh",
            "grid_carbon_kgco2_per_kwh",
            "non_cooling_load_kw",
        ):
            row[key] = float(row[key])
        row["occupancy_count"] = int(row["occupancy_count"])
        row["grid_available"] = int(row["grid_available"])
        row["source_missing_flag"] = int(row.get("source_missing_flag") or 0)

    for row in baseline:
        row["timestamp_local"] = str(row["timestamp_local"]).replace(" ", "T")
        row["baseline_ac_units_on"] = int(row["baseline_ac_units_on"] or 0)
        row["baseline_ac_setpoint_c"] = None if row.get("baseline_ac_setpoint_c") in ("", None) else float(row["baseline_ac_setpoint_c"])
        row["baseline_fan_units_on"] = int(row["baseline_fan_units_on"] or 0)
        row["baseline_other_cooling_kw"] = float(row.get("baseline_other_cooling_kw") or 0)

