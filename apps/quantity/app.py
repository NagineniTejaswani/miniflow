import csv
import json
import os
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))


def main() -> int:
    src = WORKSPACE / "validated.csv"
    if not src.exists():
        print("ERROR: validated.csv not found", file=sys.stderr)
        return 1
    units: dict[str, int] = {}
    with src.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            units[row["product"]] = units.get(row["product"], 0) + int(row["quantity"])
    (WORKSPACE / "quantity.json").write_text(
        json.dumps({"products": units, "total_units": sum(units.values())}, indent=2))
    print(f"Units by product: {units}")
    return 0


if __name__ == "__main__":
    sys.exit(main())