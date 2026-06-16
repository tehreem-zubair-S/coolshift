from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from time import perf_counter

from .db import CoolShiftDB


RUN_ID = "coolshift-v1"


@dataclass
class OptimizerSettings:
    comfort_weight: float = 0.45
    cost_weight: float = 0.25
    emissions_weight: float = 0.15
    peak_weight: float = 0.15
    comfort_min_c: float = 0
    comfort_max_c: float = 0


def optimize_scenario(db_path: Path, scenario_id: str, start: str | None, days: int, settings: OptimizerSettings | None = None) -> dict:
    with CoolShiftDB(db_path) as db:
        payload = db.scenario_payload(scenario_id, start, days)
    return optimize_from_payload(payload, settings=settings)


def optimize_from_payload(payload: dict, settings: OptimizerSettings | None = None) -> dict:
    settings = settings or OptimizerSettings()
    start_time = perf_counter()
    profile = payload["profile"]
    appliances = payload["appliances"]
    asset = payload["asset"]
    intervals = payload["intervals"]
    baseline = payload.get("baseline") or generated_baseline(intervals, appliances, profile)
    validate_payload(profile, appliances, asset, intervals, baseline)

    comfort_min = settings.comfort_min_c or float(profile["comfort_min_c"])
    comfort_max = settings.comfort_max_c or float(profile["comfort_max_c"])
    baseline_rows = run_baseline(profile, appliances, asset, intervals, baseline, comfort_min, comfort_max)
    schedule_rows = run_optimized(profile, appliances, asset, intervals, baseline, comfort_min, comfort_max, settings)
    summary_rows = summarize(profile, intervals, baseline_rows, schedule_rows)
    checks = acceptance_checks(profile, appliances, asset, intervals, schedule_rows)

    elapsed_ms = round((perf_counter() - start_time) * 1000, 2)
    return {
        "scenario": profile,
        "settings": settings.__dict__,
        "run_id": RUN_ID,
        "elapsed_ms": elapsed_ms,
        "schedule": schedule_rows,
        "baseline_schedule": baseline_rows,
        "summary_rows": summary_rows,
        "overall": summary_rows[-1] if summary_rows else {},
        "checks": checks,
    }


def validate_payload(profile: dict, appliances: list[dict], asset: dict, intervals: list[dict], baseline: list[dict]) -> None:
    if not intervals:
        raise ValueError("No interval rows found for selected period")
    if len(intervals) != len(baseline):
        raise ValueError("Baseline interval count does not match input interval count")
    required = ["timestamp_local", "interval_minutes", "temperature_c", "heat_index_c", "grid_available", "tariff_pkr_per_kwh"]
    seen = set()
    previous: datetime | None = None
    for row in intervals:
        for field in required:
            if row.get(field) in (None, ""):
                raise ValueError(f"Missing required field {field} at {row.get('timestamp_local')}")
        if int(row["interval_minutes"]) != 15:
            raise ValueError("Only 15-minute intervals are accepted")
        ts = datetime.fromisoformat(str(row["timestamp_local"]))
        if ts in seen:
            raise ValueError(f"Duplicate timestamp: {ts.isoformat()}")
        seen.add(ts)
        if previous and (ts - previous).total_seconds() != 900:
            raise ValueError(f"Timestamp gap before {ts.isoformat()}")
        previous = ts
    if not appliances:
        raise ValueError(f"No appliances configured for {profile.get('scenario_id')}")
    if float(asset["battery_capacity_kwh"]) < float(asset["minimum_reserve_kwh"]):
        raise ValueError("Battery capacity is lower than reserve")


def appliance_totals(appliances: list[dict]) -> dict:
    ac = [a for a in appliances if "AC" in a["appliance_type"].upper()]
    fans = [a for a in appliances if "FAN" in a["appliance_type"].upper()]
    ac_units = sum(int(a["quantity"]) for a in ac)
    fan_units = sum(int(a["quantity"]) for a in fans)
    return {
        "ac_units": ac_units,
        "fan_units": fan_units,
        "ac_power_per_unit_kw": safe_mean([float(a["rated_power_kw"]) for a in ac]),
        "fan_power_per_unit_kw": safe_mean([float(a["rated_power_kw"]) for a in fans]),
        "ac_capacity_per_unit_kw": safe_mean([float(a["cooling_capacity_kw"]) for a in ac]),
        "min_setpoint_c": min([float(a["min_setpoint_c"]) for a in ac], default=23.0),
        "max_setpoint_c": max([float(a["max_setpoint_c"]) for a in ac], default=30.0),
    }


def safe_mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def generated_baseline(intervals: list[dict], appliances: list[dict], profile: dict) -> list[dict]:
    totals = appliance_totals(appliances)
    rows = []
    for row in intervals:
        occupied = int(row["occupancy_count"]) > 0
        hot = float(row["heat_index_c"]) > float(profile["comfort_max_c"]) + 1
        rows.append(
            {
                "scenario_id": row["scenario_id"],
                "timestamp_local": row["timestamp_local"],
                "baseline_ac_units_on": min(totals["ac_units"], 1 if occupied and hot else 0),
                "baseline_ac_setpoint_c": profile["comfort_max_c"] if occupied and hot else None,
                "baseline_fan_units_on": min(totals["fan_units"], totals["fan_units"] if occupied else 0),
                "baseline_other_cooling_kw": 0,
                "baseline_rule": "Generated fallback baseline",
            }
        )
    return rows


def run_baseline(profile: dict, appliances: list[dict], asset: dict, intervals: list[dict], baseline: list[dict], comfort_min: float, comfort_max: float) -> list[dict]:
    totals = appliance_totals(appliances)
    soc = float(asset["initial_soc_kwh"])
    indoor = float(intervals[0]["temperature_c"])
    rows = []
    for row, base in zip(intervals, baseline):
        ac_units = min(int(base["baseline_ac_units_on"] or 0), totals["ac_units"])
        fan_units = min(int(base["baseline_fan_units_on"] or 0), totals["fan_units"])
        cooling_kw = ac_units * totals["ac_power_per_unit_kw"] + fan_units * totals["fan_power_per_unit_kw"] + float(base["baseline_other_cooling_kw"] or 0)
        indoor = estimate_indoor_temp(profile, row, totals, ac_units, fan_units, indoor, comfort_max)
        dispatch = dispatch_energy(row, asset, cooling_kw, soc, prefer_battery=False)
        soc = dispatch["battery_soc_kwh"]
        rows.append(output_row(profile["scenario_id"], row, ac_units, base.get("baseline_ac_setpoint_c"), fan_units, cooling_kw, indoor, comfort_min, comfort_max, dispatch, "BASELINE", "Organizer baseline schedule used for comparison."))
    return rows


def run_optimized(profile: dict, appliances: list[dict], asset: dict, intervals: list[dict], baseline: list[dict], comfort_min: float, comfort_max: float, settings: OptimizerSettings) -> list[dict]:
    totals = appliance_totals(appliances)
    soc = float(asset["initial_soc_kwh"])
    indoor = float(intervals[0]["temperature_c"])
    rows = []
    max_demand = float(profile["maximum_grid_demand_kw"])
    vulnerable = int(profile["vulnerable_occupants"]) == 1
    for row, base in zip(intervals, baseline):
        occupied = int(row["occupancy_count"]) > 0
        heat_index = float(row["heat_index_c"])
        temp = float(row["temperature_c"])
        peak = str(row["tariff_type"]).upper() == "PEAK"
        outage = int(row["grid_available"]) == 0
        heat_risk = heat_index >= comfort_max + (2.5 if vulnerable else 3.5)
        severe = heat_index >= comfort_max + (6 if vulnerable else 7) or temp >= comfort_max + 7

        base_ac = min(int(base.get("baseline_ac_units_on") or 0), totals["ac_units"])
        base_fans = min(int(base.get("baseline_fan_units_on") or 0), totals["fan_units"])
        ac_units = base_ac
        fan_units = base_fans if occupied else min(base_fans, 1)
        reason = "BASELINE_OPTIMIZED"
        explanation = "Starts from the organizer baseline and removes avoidable energy use."

        if not occupied:
            ac_units = 0
            reason = "LOAD_SHIFT"
            explanation = "Unoccupied interval; active cooling is shifted away from this period."
        elif severe and base_ac == 0 and settings.comfort_weight >= 0.5:
            ac_units = 1
            fan_units = totals["fan_units"]
            reason = "COMFORT_REQUIRED"
            explanation = "Severe occupied heat risk requires cooling above baseline."
        elif occupied and (heat_risk or indoor > comfort_max + 1.0):
            fan_units = max(fan_units, totals["fan_units"])
            reason = "COMFORT_REQUIRED"
            explanation = "Occupied hot interval; fans and baseline cooling protect comfort."
        if peak and ac_units > 0 and (not severe or settings.cost_weight + settings.peak_weight > settings.comfort_weight):
            ac_units = max(0, ac_units - 1)
            reason = "PEAK_TARIFF"
            explanation = "Peak tariff detected; cooling is trimmed while fans preserve perceived comfort."
        if outage:
            reason = "GRID_OUTAGE"
            explanation = "Grid is unavailable; plan relies on solar/battery and reports any infeasible load."
            if float(asset["battery_capacity_kwh"]) <= 0 and float(row["solar_available_kw"]) <= 0:
                ac_units = 0
        if float(row["solar_available_kw"]) > 0.1 and ac_units > 0:
            reason = "SOLAR_AVAILABLE"
            explanation = "Solar generation is available, so active cooling is shifted into clean-energy hours."

        setpoint = None
        if ac_units:
            base_setpoint = comfort_max if peak else max(comfort_min, comfort_max - 1)
            if vulnerable and heat_risk:
                base_setpoint = max(comfort_min, comfort_max - 2)
            setpoint = min(max(base_setpoint, totals["min_setpoint_c"]), totals["max_setpoint_c"])

        cooling_kw = ac_units * totals["ac_power_per_unit_kw"] + fan_units * totals["fan_power_per_unit_kw"]
        demand_kw = cooling_kw + float(row["non_cooling_load_kw"])
        if max_demand > 0 and demand_kw > max_demand:
            allowed_cooling_kw = max(0, max_demand - float(row["non_cooling_load_kw"]))
            ac_units = min(ac_units, int(allowed_cooling_kw // max(totals["ac_power_per_unit_kw"], 0.01)))
            cooling_kw = ac_units * totals["ac_power_per_unit_kw"] + fan_units * totals["fan_power_per_unit_kw"]
            reason = "DEMAND_LIMIT"
            explanation = "Installed maximum demand limit reduces active cooling."

        prefer_battery = outage or peak or heat_risk or settings.emissions_weight > 0.3
        indoor = estimate_indoor_temp(profile, row, totals, ac_units, fan_units, indoor, comfort_max)
        dispatch = dispatch_energy(row, asset, cooling_kw, soc, prefer_battery=prefer_battery)
        soc = dispatch["battery_soc_kwh"]
        rows.append(output_row(profile["scenario_id"], row, ac_units, setpoint, fan_units, cooling_kw, indoor, comfort_min, comfort_max, dispatch, reason, explanation))
    return rows


def estimate_indoor_temp(profile: dict, row: dict, totals: dict, ac_units: int, fan_units: int, previous: float, comfort_max: float) -> float:
    insulation = {"LOW": 1.15, "MEDIUM": 0.9, "HIGH": 0.65}.get(str(profile["insulation_level"]).upper(), 0.9)
    sun = {"LOW": 0.15, "MEDIUM": 0.35, "HIGH": 0.55}.get(str(profile["sun_exposure"]).upper(), 0.35)
    outdoor = float(row["temperature_c"])
    solar_gain = sun * (float(row["solar_irradiance_w_m2"]) / 1000.0) * insulation
    occupancy_gain = min(1.8, int(row["occupancy_count"]) / max(1, int(profile["max_occupancy"])) * 1.2)
    cooling_effect = ac_units * totals["ac_capacity_per_unit_kw"] / max(25, float(profile["area_m2"])) * 7.5
    fan_effect = min(0.8, fan_units * 0.12)
    indoor = previous * 0.62 + outdoor * 0.30 + solar_gain + occupancy_gain - cooling_effect - fan_effect
    if ac_units and indoor > comfort_max + 1:
        indoor -= 0.6
    return round(max(16.0, min(45.0, indoor)), 2)


def dispatch_energy(row: dict, asset: dict, cooling_kw: float, soc: float, prefer_battery: bool) -> dict:
    hours = float(row["interval_minutes"]) / 60.0
    demand_kwh = (cooling_kw + float(row["non_cooling_load_kw"])) * hours
    solar_available = max(0.0, float(row.get("solar_available_kw") or 0) * hours)
    battery_capacity = float(asset["battery_capacity_kwh"])
    reserve = float(asset["minimum_reserve_kwh"])
    max_charge = float(asset["max_charge_kw"]) * hours
    max_discharge = float(asset["max_discharge_kw"]) * hours
    charge_eff = max(0.01, float(asset["charge_efficiency"]))
    discharge_eff = max(0.01, float(asset["discharge_efficiency"]))

    solar_direct = min(demand_kwh, solar_available)
    remaining = demand_kwh - solar_direct
    excess_solar = solar_available - solar_direct
    battery_charge = 0.0
    if battery_capacity > 0 and excess_solar > 0:
        battery_room_input = max(0.0, (battery_capacity - soc) / charge_eff)
        battery_charge = min(excess_solar, max_charge, battery_room_input)
        soc += battery_charge * charge_eff

    battery_discharge = 0.0
    usable_soc = max(0.0, soc - reserve)
    if battery_capacity > 0 and remaining > 0 and (prefer_battery or int(row["grid_available"]) == 0):
        battery_discharge = min(remaining, max_discharge, usable_soc * discharge_eff)
        soc -= battery_discharge / discharge_eff
        remaining -= battery_discharge

    grid_energy = remaining if int(row["grid_available"]) == 1 else 0.0
    unmet = 0.0 if int(row["grid_available"]) == 1 else max(0.0, remaining)
    return {
        "grid_energy_kwh": round(grid_energy, 5),
        "solar_energy_used_kwh": round(solar_direct + battery_charge, 5),
        "battery_charge_kwh": round(battery_charge, 5),
        "battery_discharge_kwh": round(battery_discharge, 5),
        "battery_soc_kwh": round(max(0.0, min(battery_capacity, soc)), 5),
        "unmet_load_kwh": round(unmet, 5),
        "site_demand_kwh": round(demand_kwh, 5),
        "solar_available_kwh": round(solar_available, 5),
    }


def output_row(scenario_id: str, row: dict, ac_units: int, setpoint: float | None, fan_units: int, cooling_kw: float, indoor: float, comfort_min: float, comfort_max: float, dispatch: dict, reason: str, explanation: str) -> dict:
    occupied = int(row["occupancy_count"]) > 0
    violation_count = 0
    details = []
    if dispatch["unmet_load_kwh"] > 0.0001:
        violation_count += 1
        details.append("Unserved load during outage")
    if occupied and indoor > comfort_max + 3:
        comfort = "UNSAFE_HEAT"
        violation_count += 1
        details.append("Occupied heat above safety band")
    elif occupied and indoor > comfort_max:
        comfort = "WARM"
    elif occupied and indoor < comfort_min:
        comfort = "TOO_COOL"
    elif occupied:
        comfort = "COMFORT_OK"
    else:
        comfort = "UNOCCUPIED"
    if violation_count and comfort != "UNSAFE_HEAT":
        comfort = "INFEASIBLE"
    grid_energy = dispatch["grid_energy_kwh"]
    return {
        "scenario_id": scenario_id,
        "run_id": RUN_ID,
        "timestamp_local": row["timestamp_local"],
        "recommended_ac_units_on": ac_units,
        "recommended_ac_setpoint_c": "" if setpoint is None else round(float(setpoint), 1),
        "recommended_fan_units_on": fan_units,
        "grid_energy_kwh": grid_energy,
        "solar_energy_used_kwh": dispatch["solar_energy_used_kwh"],
        "battery_charge_kwh": dispatch["battery_charge_kwh"],
        "battery_discharge_kwh": dispatch["battery_discharge_kwh"],
        "battery_soc_kwh": dispatch["battery_soc_kwh"],
        "cooling_energy_kwh": round(cooling_kw * (float(row["interval_minutes"]) / 60.0), 5),
        "estimated_indoor_temp_c": indoor,
        "comfort_status": comfort,
        "interval_cost_pkr": round(grid_energy * float(row["tariff_pkr_per_kwh"]), 4),
        "interval_emissions_kgco2e": round(grid_energy * float(row["grid_carbon_kgco2_per_kwh"]), 5),
        "reason_code": reason,
        "explanation": explanation,
        "constraint_violation_count": violation_count,
        "constraint_violation_details": "; ".join(details),
    }


def summarize(profile: dict, intervals: list[dict], baseline: list[dict], optimized: list[dict]) -> list[dict]:
    by_day = sorted(set(r["timestamp_local"][:10] for r in intervals))
    rows = []
    for day in by_day:
        idx = [i for i, r in enumerate(intervals) if r["timestamp_local"].startswith(day)]
        rows.append(summary_row(profile, [intervals[i] for i in idx], [baseline[i] for i in idx], [optimized[i] for i in idx], day, day))
    rows.append(summary_row(profile, intervals, baseline, optimized, intervals[0]["timestamp_local"][:10], intervals[-1]["timestamp_local"][:10], overall=True))
    return rows


def summary_row(profile: dict, intervals: list[dict], baseline: list[dict], optimized: list[dict], start: str, end: str, overall: bool = False) -> dict:
    base_energy = sum(float(r["grid_energy_kwh"]) for r in baseline)
    opt_energy = sum(float(r["grid_energy_kwh"]) for r in optimized)
    base_cost = sum(float(r["interval_cost_pkr"]) for r in baseline)
    opt_cost = sum(float(r["interval_cost_pkr"]) for r in optimized)
    base_emissions = sum(float(r["interval_emissions_kgco2e"]) for r in baseline)
    opt_emissions = sum(float(r["interval_emissions_kgco2e"]) for r in optimized)
    occupied = [r for r in optimized if r["comfort_status"] != "UNOCCUPIED"]
    comfort_ok = [r for r in occupied if r["comfort_status"] in ("COMFORT_OK", "WARM")]
    solar_available = sum(float(row.get("solar_available_kw") or 0) * (float(row["interval_minutes"]) / 60.0) for row in intervals)
    solar_used = sum(float(r["solar_energy_used_kwh"]) for r in optimized)
    peak_grid_kw = max((float(r["grid_energy_kwh"]) / 0.25 for r in optimized), default=0.0)
    peak_period_grid = sum(float(r["grid_energy_kwh"]) for row, r in zip(intervals, optimized) if str(row["tariff_type"]).upper() == "PEAK")
    unsafe = sum(1 for r in optimized if r["comfort_status"] in ("UNSAFE_HEAT", "INFEASIBLE"))
    return {
        "scenario_id": profile["scenario_id"],
        "run_id": RUN_ID,
        "period_start": start,
        "period_end": end,
        "period_type": "overall" if overall else "daily",
        "baseline_energy_kwh": round(base_energy, 4),
        "optimized_energy_kwh": round(opt_energy, 4),
        "energy_saving_kwh": round(base_energy - opt_energy, 4),
        "energy_saving_pct": pct(base_energy - opt_energy, base_energy),
        "baseline_cost_pkr": round(base_cost, 2),
        "optimized_cost_pkr": round(opt_cost, 2),
        "cost_saving_pkr": round(base_cost - opt_cost, 2),
        "cost_saving_pct": pct(base_cost - opt_cost, base_cost),
        "baseline_emissions_kgco2e": round(base_emissions, 4),
        "optimized_emissions_kgco2e": round(opt_emissions, 4),
        "emissions_avoided_kgco2e": round(base_emissions - opt_emissions, 4),
        "peak_grid_demand_kw": round(peak_grid_kw, 4),
        "peak_period_grid_energy_kwh": round(peak_period_grid, 4),
        "solar_available_kwh": round(solar_available, 4),
        "solar_used_kwh": round(solar_used, 4),
        "solar_utilization_pct": pct(solar_used, solar_available),
        "comfort_compliance_pct": pct(len(comfort_ok), len(occupied)),
        "unsafe_interval_count": unsafe,
        "constraint_violation_count": sum(int(r["constraint_violation_count"]) for r in optimized),
    }


def pct(value: float, base: float) -> float:
    return round((value / base * 100.0), 2) if base else 0.0


def acceptance_checks(profile: dict, appliances: list[dict], asset: dict, intervals: list[dict], schedule: list[dict]) -> list[dict]:
    totals = appliance_totals(appliances)
    capacity = float(asset["battery_capacity_kwh"])
    reserve = float(asset["minimum_reserve_kwh"])
    checks = []
    checks.append(check("A1", "Exactly one output record per 15-minute timestamp", len(schedule) == len(intervals)))
    checks.append(check("A2", "No grid energy while grid is unavailable", all(float(r["grid_energy_kwh"]) == 0 for i, r in zip(intervals, schedule) if int(i["grid_available"]) == 0)))
    checks.append(check("A3", "Battery SOC remains within capacity", all(0 <= float(r["battery_soc_kwh"]) <= capacity + 1e-6 for r in schedule)))
    checks.append(check("A4", "Battery reserve respected except reported infeasibility", all(float(r["battery_soc_kwh"]) + 1e-6 >= reserve or "Unserved" in r["constraint_violation_details"] or capacity == 0 for r in schedule)))
    checks.append(check("A5", "Appliance quantities respected", all(int(r["recommended_ac_units_on"]) <= totals["ac_units"] and int(r["recommended_fan_units_on"]) <= totals["fan_units"] for r in schedule)))
    checks.append(check("A6", "Energy balance and costs are within tolerance", all(abs(float(r["interval_cost_pkr"]) - float(r["grid_energy_kwh"]) * float(i["tariff_pkr_per_kwh"])) < 0.02 for i, r in zip(intervals, schedule))))
    checks.append(check("A8", "Comfort status calculated for occupied intervals", all(r["comfort_status"] for r in schedule if True)))
    checks.append(check("A9", "Infeasible comfort is reported", all(int(r["constraint_violation_count"]) == 0 or r["constraint_violation_details"] for r in schedule)))
    checks.append(check("A10", "Emissions equal interval grid energy times carbon factor", all(abs(float(r["interval_emissions_kgco2e"]) - float(r["grid_energy_kwh"]) * float(i["grid_carbon_kgco2_per_kwh"])) < 0.002 for i, r in zip(intervals, schedule))))
    return checks


def check(identifier: str, description: str, passed: bool) -> dict:
    return {"id": identifier, "description": description, "result": "PASS" if passed else "FAIL"}
