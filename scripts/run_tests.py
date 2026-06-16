from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from coolshift.db import CoolShiftDB, default_db_path
from coolshift.optimizer import OptimizerSettings, optimize_from_payload, optimize_scenario


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def edge_payload(grid_available=1, battery_capacity=0, initial_soc=0, tariff_type="OFF_PEAK", baseline_ac=0, vulnerable=1):
    return {
        "profile": {
            "scenario_id": "EDGE",
            "name": "Edge case",
            "timezone": "Asia/Karachi",
            "building_type": "Test",
            "area_m2": 45,
            "room_count": 1,
            "max_occupancy": 4,
            "insulation_level": "Low",
            "sun_exposure": "High",
            "comfort_min_c": 24,
            "comfort_max_c": 28,
            "vulnerable_occupants": vulnerable,
            "budget_pkr_per_day": 1000,
            "maximum_grid_demand_kw": 3,
            "evaluation_focus": "Edge testing",
        },
        "appliances": [
            {
                "scenario_id": "EDGE",
                "appliance_id": "EDGE-AC",
                "zone_id": "Z1",
                "appliance_type": "Inverter AC",
                "quantity": 1,
                "rated_power_kw": 1.2,
                "cooling_capacity_kw": 5,
                "efficiency_label": "A",
                "min_runtime_minutes": 30,
                "min_setpoint_c": 23,
                "max_setpoint_c": 30,
            },
            {
                "scenario_id": "EDGE",
                "appliance_id": "EDGE-FAN",
                "zone_id": "Z1",
                "appliance_type": "Ceiling fan",
                "quantity": 2,
                "rated_power_kw": 0.07,
                "cooling_capacity_kw": 0,
                "efficiency_label": "N/A",
                "min_runtime_minutes": 15,
                "min_setpoint_c": 0,
                "max_setpoint_c": 0,
            },
        ],
        "asset": {
            "scenario_id": "EDGE",
            "solar_capacity_kw": 0,
            "solar_conversion_efficiency": 0,
            "battery_capacity_kwh": battery_capacity,
            "initial_soc_kwh": initial_soc,
            "minimum_reserve_kwh": 0,
            "max_charge_kw": 0,
            "max_discharge_kw": 0,
            "charge_efficiency": 1,
            "discharge_efficiency": 1,
        },
        "intervals": [
            {
                "scenario_id": "EDGE",
                "timestamp_local": "2026-05-01T12:00:00",
                "interval_minutes": 15,
                "temperature_c": 38,
                "relative_humidity_pct": 70,
                "heat_index_c": 36,
                "solar_irradiance_w_m2": 0,
                "solar_available_kw": 0,
                "occupancy_count": 3,
                "grid_available": grid_available,
                "tariff_type": tariff_type,
                "tariff_pkr_per_kwh": 60,
                "grid_carbon_kgco2_per_kwh": 0.46,
                "non_cooling_load_kw": 0.5,
                "source_missing_flag": 0,
            }
        ],
        "baseline": [
            {
                "scenario_id": "EDGE",
                "timestamp_local": "2026-05-01T12:00:00",
                "baseline_ac_units_on": baseline_ac,
                "baseline_ac_setpoint_c": 26 if baseline_ac else None,
                "baseline_fan_units_on": 2,
                "baseline_other_cooling_kw": 0,
                "baseline_rule": "edge",
            }
        ],
    }


def main() -> None:
    with CoolShiftDB(default_db_path()) as db:
        scenarios = db.list_scenarios()
        counts = {s["scenario_id"]: s["interval_count"] for s in scenarios}
        starts = {s["scenario_id"]: db.available_dates(s["scenario_id"])[0] for s in scenarios}

    expect(counts["PUB-A"] == 2880, "PUB-A must have 2,880 rows")
    expect(counts["PUB-B"] == 2880, "PUB-B must have 2,880 rows")
    expect(counts["PUB-C"] == 2880, "PUB-C must have 2,880 rows")
    expect(counts["TEAM-CUSTOM"] == 672, "TEAM-CUSTOM must have 672 rows")

    for scenario_id in ("PUB-A", "PUB-B", "PUB-C", "TEAM-CUSTOM"):
        result = optimize_scenario(default_db_path(), scenario_id, starts[scenario_id], 1)
        expect(len(result["schedule"]) == 96, f"{scenario_id} must produce 96 rows for one day")
        failures = [c for c in result["checks"] if c["result"] != "PASS"]
        expect(failures == [], f"{scenario_id} acceptance failures: {failures}")
        print(f"{scenario_id}: PASS ({result['elapsed_ms']} ms)")

    outage = optimize_from_payload(edge_payload(grid_available=0, battery_capacity=0, baseline_ac=1))
    outage_row = outage["schedule"][0]
    expect(outage_row["grid_energy_kwh"] == 0, "Outage case must not draw grid energy")
    expect(outage_row["constraint_violation_count"] > 0, "Outage/no-battery case must report infeasibility")
    print("EDGE outage/no-battery: PASS")

    vulnerable = optimize_from_payload(edge_payload(baseline_ac=0, vulnerable=1), OptimizerSettings(comfort_weight=0.75))
    expect(vulnerable["schedule"][0]["recommended_ac_units_on"] == 1, "Vulnerable severe heat should allow AC above baseline")
    print("EDGE vulnerable override: PASS")

    peak = optimize_from_payload(
        edge_payload(tariff_type="PEAK", baseline_ac=1, vulnerable=1),
        OptimizerSettings(comfort_weight=0.8, cost_weight=0.1, peak_weight=0.1),
    )
    expect(peak["schedule"][0]["recommended_ac_units_on"] == 1, "Comfort-dominant severe heat should not be peak-trimmed")
    print("EDGE peak comfort conflict: PASS")

    print("All tests passed")


if __name__ == "__main__":
    main()
