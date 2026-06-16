from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from coolshift.db import CoolShiftDB, default_db_path
from coolshift.optimizer import optimize_scenario


def test_public_scenarios_have_required_rows():
    with CoolShiftDB(default_db_path()) as db:
        scenarios = db.list_scenarios()
    counts = {s["scenario_id"]: s["interval_count"] for s in scenarios}
    assert counts["PUB-A"] == 2880
    assert counts["PUB-B"] == 2880
    assert counts["PUB-C"] == 2880
    assert counts["TEAM-CUSTOM"] == 672


def test_single_day_acceptance_checks_pass_for_public_cases():
    with CoolShiftDB(default_db_path()) as db:
        starts = {s["scenario_id"]: db.available_dates(s["scenario_id"])[0] for s in db.list_scenarios()}
    for scenario_id in ("PUB-A", "PUB-B", "PUB-C", "TEAM-CUSTOM"):
        result = optimize_scenario(default_db_path(), scenario_id, starts[scenario_id], 1)
        assert len(result["schedule"]) == 96
        failures = [c for c in result["checks"] if c["result"] != "PASS"]
        assert failures == []

