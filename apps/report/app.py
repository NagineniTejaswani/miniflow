import json
import os
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))


def main() -> int:
    try:
        revenue = json.loads((WORKSPACE / "revenue.json").read_text())
        quantity = json.loads((WORKSPACE / "quantity.json").read_text())
    except FileNotFoundError as e:
        print(f"ERROR: missing input {e.filename}", file=sys.stderr)
        return 1

    lines = [
        "Daily Orders Report",
        f"Orders        : {len(revenue['orders'])}",
        f"Total revenue : {revenue['total']:,}",
        f"Total units   : {quantity['total_units']}",
        "Units by product:",
    ]
    for product, units in sorted(quantity["products"].items()):
        lines.append(f"  {product:<10} {units}")
    report = "\n".join(lines)

    (WORKSPACE / "report.txt").write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())