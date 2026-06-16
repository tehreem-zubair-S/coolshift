from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from coolshift.db import CoolShiftDB, default_db_path
from coolshift.optimizer import optimize_scenario


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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

    print("All tests passed")


if __name__ == "__main__":
    main()

