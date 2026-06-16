from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from coolshift.db import CoolShiftDB, default_db_path
from coolshift.optimizer import OptimizerSettings, optimize_from_payload, optimize_scenario


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def json_bytes(payload: object, status: int = 200) -> tuple[int, bytes, str]:
    return status, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8"


def csv_bytes(rows: list[dict], status: int = 200) -> tuple[int, bytes, str]:
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return status, buffer.getvalue().encode("utf-8"), "text/csv; charset=utf-8"


def parse_settings(params: dict[str, list[str]]) -> OptimizerSettings:
    def num(name: str, default: float) -> float:
        try:
            return float(params.get(name, [default])[0])
        except (TypeError, ValueError):
            return default

    return OptimizerSettings(
        comfort_weight=num("comfort_weight", 0.45),
        cost_weight=num("cost_weight", 0.25),
        emissions_weight=num("emissions_weight", 0.15),
        peak_weight=num("peak_weight", 0.15),
        comfort_min_c=num("comfort_min_c", 0),
        comfort_max_c=num("comfort_max_c", 0),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "CoolShift/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                self.respond(*json_bytes({"ok": True, "service": "CoolShift"}))
            elif parsed.path == "/api/scenarios":
                with CoolShiftDB(default_db_path()) as db:
                    self.respond(*json_bytes(db.list_scenarios()))
            elif parsed.path == "/api/dates":
                with CoolShiftDB(default_db_path()) as db:
                    scenario_id = params.get("scenario_id", ["PUB-A"])[0]
                    self.respond(*json_bytes(db.available_dates(scenario_id)))
            elif parsed.path == "/api/run":
                scenario_id = params.get("scenario_id", ["PUB-A"])[0]
                start = params.get("start", [None])[0]
                days = int(params.get("days", ["1"])[0])
                result = optimize_scenario(default_db_path(), scenario_id, start, days, parse_settings(params))
                self.respond(*json_bytes(result))
            elif parsed.path == "/api/export/schedule.csv":
                scenario_id = params.get("scenario_id", ["PUB-A"])[0]
                start = params.get("start", [None])[0]
                days = int(params.get("days", ["7"])[0])
                result = optimize_scenario(default_db_path(), scenario_id, start, days, parse_settings(params))
                self.respond(*csv_bytes(result["schedule"]))
            elif parsed.path == "/api/export/summary.csv":
                scenario_id = params.get("scenario_id", ["PUB-A"])[0]
                start = params.get("start", [None])[0]
                days = int(params.get("days", ["7"])[0])
                result = optimize_scenario(default_db_path(), scenario_id, start, days, parse_settings(params))
                self.respond(*csv_bytes(result["summary_rows"]))
            else:
                self.serve_static(parsed.path)
        except Exception as exc:
            self.respond(*json_bytes({"error": str(exc)}, 500))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body)
            if parsed.path == "/api/run-payload":
                result = optimize_from_payload(payload)
                self.respond(*json_bytes(result))
            else:
                self.respond(*json_bytes({"error": "Unknown endpoint"}, 404))
        except Exception as exc:
            self.respond(*json_bytes({"error": str(exc)}, 500))

    def serve_static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (FRONTEND / rel).resolve()
        if not str(target).startswith(str(FRONTEND.resolve())) or not target.exists() or target.is_dir():
            self.respond(*json_bytes({"error": "Not found"}, 404))
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.respond(200, target.read_bytes(), content_type)

    def respond(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> None:
    db_path = default_db_path()
    if not db_path.exists():
        raise SystemExit("Database not found. Run: python scripts\\import_workbook.py")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    if os.environ.get("PORT"):
        host = "0.0.0.0"
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"CoolShift running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
