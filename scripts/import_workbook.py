from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from coolshift.db import default_db_path
from coolshift.importer import import_zip_to_db


def main() -> None:
    zip_path = Path(r"C:\Users\Hp\Downloads\skillverseeee.zip")
    if len(sys.argv) > 1:
        zip_path = Path(sys.argv[1])
    result = import_zip_to_db(zip_path, default_db_path())
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()

