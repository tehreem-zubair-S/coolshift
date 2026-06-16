from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from coolshift.db import CoolShiftDB, default_db_path
from coolshift.optimizer import optimize_scenario


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not rows:
            return
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    all_schedule = []
    all_summary = []
    with CoolShiftDB(default_db_path()) as db:
        scenarios = [row["scenario_id"] for row in db.list_scenarios()]
        starts = {sid: db.available_dates(sid)[0] for sid in scenarios}
    for scenario_id in scenarios:
        result = optimize_scenario(default_db_path(), scenario_id, starts[scenario_id], 7)
        all_schedule.extend(result["schedule"])
        all_summary.extend(result["summary_rows"])
        print(f"{scenario_id}: {len(result['schedule'])} rows, {result['overall']['cost_saving_pkr']} PKR saved")
    write_csv(ROOT / "outputs" / "public_results.csv", all_schedule)
    write_csv(ROOT / "outputs" / "summary_results.csv", all_summary)
    print(f"schedule_rows: {len(all_schedule)}")
    print(f"summary_rows: {len(all_summary)}")


if __name__ == "__main__":
    main()

