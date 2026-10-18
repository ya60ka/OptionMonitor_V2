
# BR22 - Inspect TSETMC option market watch response
# Purpose:
# 1. Read the previously saved raw API response.
# 2. Inspect underlying instrument codes.
# 3. Find records matching the exact underlying code of اهرم.
# 4. Save a diagnostic report and matching records.
# 5. Do not call the API or access any database.

import json
from collections import Counter
from pathlib import Path
from datetime import datetime


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")

RAW_FILE = (
    PROJECT_DIR
    / "data"
    / "api_tests"
    / "BR21_response_20261011_080053.raw"
)

UNDERLYING_CODE = "17914401175772326"

OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def write_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_path = OUTPUT_DIR / f"BR22_report_{timestamp}.txt"
    matches_path = OUTPUT_DIR / f"BR22_matches_{timestamp}.json"

    print("=" * 70)
    print("BR22 - Inspect Existing TSETMC API Response")
    print("=" * 70)
    print(f"Input file     : {RAW_FILE}")
    print(f"Underlying code: {UNDERLYING_CODE}")
    print("API request    : NO")
    print("Database       : NOT USED")
    print("-" * 70)

    if not RAW_FILE.is_file():
        print("ERROR: Raw response file does not exist.")
        print("Check the RAW_FILE path in this script.")
        return

    # Read the previously saved response.
    raw_bytes = RAW_FILE.read_bytes()

    try:
        payload = json.loads(raw_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"ERROR: Cannot parse the raw response: {exc}")
        return

    if not isinstance(payload, dict):
        print(f"ERROR: Unexpected JSON root type: {type(payload).__name__}")
        return

    records = payload.get("instrumentOptMarketWatch")

    if not isinstance(records, list):
        print("ERROR: instrumentOptMarketWatch is not a JSON array.")
        print(f"Root keys: {list(payload.keys())}")
        return

    # Count underlying codes without changing the source data.
    code_counts = Counter()

    for record in records:
        if not isinstance(record, dict):
            continue

        code = record.get("uaInsCode")

        if code is not None:
            code_counts[str(code)] += 1

    # Match only the exact underlying code.
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and str(record.get("uaInsCode", "")) == UNDERLYING_CODE
    ]

    lines = []

    def log(message=""):
        print(message)
        lines.append(str(message))

    log("BR22 INSPECTION REPORT")
    log("=" * 70)
    log(f"Source file: {RAW_FILE}")
    log(f"Total array items: {len(records)}")
    log(f"Items with uaInsCode: {sum(code_counts.values())}")
    log(f"Distinct underlying codes: {len(code_counts)}")
    log(f"Target underlying code: {UNDERLYING_CODE}")
    log(f"Exact matching records: {len(matches)}")
    log()

    log("MOST FREQUENT UNDERLYING CODES")
    log("-" * 70)

    for code, count in code_counts.most_common(20):
        log(f"{code}: {count} record(s)")

    log()
    log("EXACT MATCH DETAILS")
    log("-" * 70)

    if not matches:
        log("No exact matches were found.")
        log("No assumption was made about alternative code formats.")
    else:
        for index, record in enumerate(matches, start=1):
            log()
            log(f"MATCH #{index}")
            log(f"Field count: {len(record)}")

            for key, value in record.items():
                log(f"  {key} = {value!r}")

    # Save the matching records separately.
    # An empty array is saved if no exact matches exist.
    write_json(matches_path, matches)

    report_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("-" * 70)
    print(f"Report         : {report_path}")
    print(f"Matching JSON  : {matches_path}")
    print("Source raw file: unchanged")
    print("Database       : not accessed")
    print("=" * 70)


if __name__ == "__main__":
    main()
