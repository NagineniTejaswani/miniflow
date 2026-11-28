import csv
import os
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
COLUMNS = ["order_id", "product", "quantity", "price"]


def main() -> int:
    src = WORKSPACE / "orders.csv"
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 1

    errors, rows, seen = [], [], set()
    with src.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            print(f"ERROR: expected columns {COLUMNS}, got {reader.fieldnames}",
                  file=sys.stderr)
            return 1
        for line, row in enumerate(reader, start=2):
            oid = (row["order_id"] or "").strip()
            product = (row["product"] or "").strip()
            try:
                qty = int(row["quantity"])
                price = int(row["price"])
            except (TypeError, ValueError):
                errors.append(f"line {line}: quantity and price must be whole numbers")
                continue
            if not oid:
                errors.append(f"line {line}: missing order_id")
            elif oid in seen:
                errors.append(f"line {line}: duplicate order_id {oid}")
            if not product:
                errors.append(f"line {line}: missing product")
            if qty <= 0:
                errors.append(f"line {line}: quantity must be positive")
            if price <= 0:
                errors.append(f"line {line}: price must be positive")
            seen.add(oid)
            rows.append([oid, product, qty, price])

    if not rows and not errors:
        errors.append("file has no orders")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    with (WORKSPACE / "validated.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    print(f"Validated {len(rows)} orders")
    return 0


if __name__ == "__main__":
    sys.exit(main())