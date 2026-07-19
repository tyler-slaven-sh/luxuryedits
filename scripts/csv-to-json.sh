#!/usr/bin/env bash

set -euo pipefail

input_file="${1:-data/bags.csv}"
output_file="${2:-data/bags.json}"

if [[ ! -f "$input_file" ]]; then
  echo "CSV file not found: $input_file" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_file")"

python3 - "$input_file" "$output_file" <<'PY'
import csv
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

input_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
required_headers = ("id", "name", "price", "brand", "edit", "tier", "image_name")


def normalize_header(value):
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def fail(message):
    print(f"CSV validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


with input_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
    reader = csv.DictReader(csv_file)
    if not reader.fieldnames:
        fail("the file does not contain a header row")

    normalized_headers = [normalize_header(header) for header in reader.fieldnames]
    if len(set(normalized_headers)) != len(normalized_headers):
        fail("two or more column names normalize to the same value")

    source_headers = dict(zip(normalized_headers, reader.fieldnames))
    missing_headers = [header for header in required_headers if header not in source_headers]
    if missing_headers:
        fail(f"missing required column(s): {', '.join(missing_headers)}")

    records = []
    seen_ids = set()

    for row_number, source_row in enumerate(reader, start=2):
        row = {
            header: (source_row.get(source_headers[header]) or "").strip()
            for header in required_headers
        }

        if not any(row.values()):
            continue

        empty_fields = [header for header, value in row.items() if not value]
        if empty_fields:
            fail(f"row {row_number} has empty field(s): {', '.join(empty_fields)}")

        bag_id = row["id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", bag_id):
            fail(f"row {row_number} id must use only letters, numbers, hyphens, or underscores")
        if bag_id.casefold() in seen_ids:
            fail(f"row {row_number} repeats id '{bag_id}'")
        seen_ids.add(bag_id.casefold())

        try:
            price_dollars = Decimal(row["price"])
        except InvalidOperation:
            fail(f"row {row_number} price '{row['price']}' is not a number")

        price_cents = price_dollars * 100
        if not price_dollars.is_finite() or price_dollars < 0:
            fail(f"row {row_number} price must be a non-negative number")
        if price_cents != price_cents.to_integral_value():
            fail(f"row {row_number} price cannot have more than two decimal places")

        image_name = row["image_name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", image_name):
            fail(f"row {row_number} image_name must be a filename without spaces or folders")
        if Path(image_name).suffix.lower() not in {".avif", ".jpeg", ".jpg", ".png", ".webp"}:
            fail(f"row {row_number} image_name must end in avif, jpeg, jpg, png, or webp")

        records.append({
            "id": bag_id,
            "name": row["name"],
            "price": int(price_cents),
            "brand": row["brand"],
            "edit": row["edit"],
            "tier": row["tier"],
            "imageName": image_name,
            "image": f"./images/{image_name}",
        })

temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
with temporary_path.open("w", encoding="utf-8", newline="\n") as json_file:
    json.dump(records, json_file, ensure_ascii=False, indent=2)
    json_file.write("\n")

temporary_path.replace(output_path)
print(f"Generated {output_path} with {len(records)} bag record(s).")
PY
