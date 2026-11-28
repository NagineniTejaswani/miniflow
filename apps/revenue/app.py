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
    per_order, total = {}, 0
    with src.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            amount = int(row["quantity"]) * int(row["price"])
            per_order[row["order_id"]] = amount
            total += amount
    (WORKSPACE / "revenue.json").write_text(
        json.dumps({"orders": per_order, "total": total}, indent=2))
    print(f"Revenue total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())