from __future__ import annotations

import math
from datetime import datetime, timedelta


def custom_rows() -> dict:
    scenario_id = "TEAM-CUSTOM"
    profile = {
        "scenario_id": scenario_id,
        "name": "Karachi community cooling clinic",
        "timezone": "Asia/Karachi",
        "building_type": "Clinic",
        "area_m2": 120,
        "room_count": 5,
        "max_occupancy": 55,
        "insulation_level": "Medium",
        "sun_exposure": "High",
        "comfort_min_c": 24,
        "comfort_max_c": 28,
        "vulnerable_occupants": 1,
        "budget_pkr_per_day": 3200,
        "maximum_grid_demand_kw": 8,
        "evaluation_focus": "Synthetic fixed-seed clinic scenario with solar, battery, evening peak tariff and planned outages.",
    }
    appliances = [
        {
            "scenario_id": scenario_id,
            "appliance_id": "TC-AC-01",
            "zone_id": "CLINIC",
            "appliance_type": "Inverter AC",
            "quantity": 3,
            "rated_power_kw": 1.25,
            "cooling_capacity_kw": 4.8,
            "efficiency_label": "A",
            "min_runtime_minutes": 30,
            "min_setpoint_c": 23,
            "max_setpoint_c": 30,
        },
        {
            "scenario_id": scenario_id,
            "appliance_id": "TC-FAN-01",
            "zone_id": "CLINIC",
            "appliance_type": "Ceiling fan",
            "quantity": 8,
            "rated_power_kw": 0.065,
            "cooling_capacity_kw": 0,
            "efficiency_label": "N/A",
            "min_runtime_minutes": 15,
            "min_setpoint_c": 0,
            "max_setpoint_c": 0,
        },
    ]
    asset = {
        "scenario_id": scenario_id,
        "solar_capacity_kw": 6,
        "solar_conversion_efficiency": 0.82,
        "battery_capacity_kwh": 12,
        "initial_soc_kwh": 7,
        "minimum_reserve_kwh": 2.5,
        "max_charge_kw": 3.5,
        "max_discharge_kw": 3.5,
        "charge_efficiency": 0.94,
        "discharge_efficiency": 0.94,
    }
    start = datetime(2026, 5, 1)
    intervals = []
    baseline = []
    for i in range(7 * 96):
        ts = start + timedelta(minutes=15 * i)
        hour = ts.hour + ts.minute / 60
        day_wave = math.sin((hour - 6) / 24 * math.tau)
        temp = 31 + 6.5 * max(0, day_wave) + 1.6 * math.sin(i / 41)
        humidity = 62 + 9 * math.sin((hour + 3) / 24 * math.tau)
        heat_index = temp + max(0, humidity - 50) * 0.06
        solar_kw = max(0, math.sin((hour - 6) / 12 * math.pi)) * asset["solar_capacity_kw"] * asset["solar_conversion_efficiency"]
        occupied = 7 <= hour <= 20
        occupancy = int((18 + 30 * max(0, math.sin((hour - 7) / 13 * math.pi))) if occupied else 4)
        grid_available = 0 if (13 <= hour < 14 or 19 <= hour < 19.5) else 1
        tariff_type = "PEAK" if 18 <= hour < 23 else "OFF_PEAK"
        tariff = 58 if tariff_type == "PEAK" else 41
        non_cooling = 0.55 + (0.35 if occupied else 0.05)
        intervals.append(
            {
                "scenario_id": scenario_id,
                "timestamp_local": ts.isoformat(timespec="seconds"),
                "interval_minutes": 15,
                "temperature_c": round(temp, 2),
                "relative_humidity_pct": round(humidity, 2),
                "heat_index_c": round(heat_index, 2),
                "solar_irradiance_w_m2": round((solar_kw / max(asset["solar_capacity_kw"], 1)) * 1000, 2),
                "solar_available_kw": round(solar_kw, 3),
                "occupancy_count": occupancy,
                "grid_available": grid_available,
                "tariff_type": tariff_type,
                "tariff_pkr_per_kwh": tariff,
                "grid_carbon_kgco2_per_kwh": 0.46,
                "non_cooling_load_kw": round(non_cooling, 3),
                "source_missing_flag": 0,
            }
        )
        hot = heat_index > profile["comfort_max_c"] + 1 and occupied
        baseline.append(
            {
                "scenario_id": scenario_id,
                "timestamp_local": ts.isoformat(timespec="seconds"),
                "baseline_ac_units_on": 2 if hot else 0,
                "baseline_ac_setpoint_c": 26 if hot else None,
                "baseline_fan_units_on": 8 if occupied else 2,
                "baseline_other_cooling_kw": 0,
                "baseline_rule": "Deterministic synthetic clinic baseline",
            }
        )
    return {"profile": profile, "appliances": appliances, "asset": asset, "intervals": intervals, "baseline": baseline}

