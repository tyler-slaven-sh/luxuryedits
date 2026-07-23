#!/usr/bin/env bash

set -euo pipefail

input_file="${1:-data/odds.csv}"
output_file="${2:-data/odds.json}"

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
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

input_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
required_headers = ("tier", "edit", "price_range", "odds")
valid_edits = {"london", "new-york", "milan", "paris"}


def normalize_header(value):
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def fail(message):
    print(f"Odds CSV validation failed: {message}", file=sys.stderr)
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
    seen_pairs = set()
    totals = defaultdict(Decimal)

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

        edit = normalize_key(row["edit"]).removesuffix("-edit")
        if edit not in valid_edits:
            fail(f"row {row_number} edit must be london, new-york, milan, or paris")

        tier_key = normalize_key(row["tier"])
        pair = (edit, tier_key)
        if pair in seen_pairs:
            fail(f"row {row_number} repeats tier '{row['tier']}' for edit '{edit}'")
        seen_pairs.add(pair)

        if not re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?|\+)", row["price_range"]):
            fail(f"row {row_number} price_range must look like 1500-4999 or 5000+")

        try:
            odds = Decimal(row["odds"])
        except InvalidOperation:
            fail(f"row {row_number} odds '{row['odds']}' is not a decimal number")
        if not odds.is_finite() or odds < 0 or odds > 1:
            fail(f"row {row_number} odds must be between 0 and 1")

        totals[edit] += odds
        records.append({
            "tier": row["tier"],
            "edit": edit,
            "price_range": row["price_range"],
            "odds": float(odds),
        })

for edit in valid_edits:
    if totals[edit] != Decimal("1.00"):
        fail(f"odds for {edit} total {totals[edit]} instead of 1.00")

temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
with temporary_path.open("w", encoding="utf-8", newline="\n") as json_file:
    json.dump(records, json_file, ensure_ascii=False, indent=2)
    json_file.write("\n")

temporary_path.replace(output_path)
print(f"Generated {output_path} with {len(records)} odds row(s).")
PY
