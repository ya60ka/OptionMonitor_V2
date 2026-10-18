
# BR39 - Inspect Raw TSETMC Market Fields
# Read-only API field discovery. No database access or writes.

import json
from pathlib import Path
from collections import Counter

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
UNDERLYING_CODE = "17914401175772326"

WATCH_TERMS = (
    "inscode", "pmedem", "pmeof", "qtitmedem", "qtitmeof",
    "ztottran", "qtottran", "qtotcap", "pclosing",
    "pdr cot", "pdr cot", "priceyesterday", "best",
    "volume", "value", "trade", "bid", "ask", "offer",
    "dem", "of_", "price", "quantity", "count",
)


def latest_br37_file():
    files = list(DATA_DIR.glob("BR37_live_response_*.json"))
    if not files:
        raise FileNotFoundError(
            f"No BR37_live_response_*.json found in {DATA_DIR}"
        )
    return max(files, key=lambda p: p.stat().st_mtime)


def extract_records(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        records = payload.get("instrumentOptMarketWatch")
        if isinstance(records, list):
            return records

        for value in payload.values():
            if isinstance(value, dict):
                records = value.get("instrumentOptMarketWatch")
                if isinstance(records, list):
                    return records

    raise ValueError("API array 'instrumentOptMarketWatch' not found.")


def matches_underlying(record):
    for key in ("uaInsCode", "UAInsCode", "ua_ins_code"):
        value = record.get(key)
        if value is not None and str(value) == UNDERLYING_CODE:
            return True

    return False


def short_value(value, limit=180):
    text = repr(value)
    if len(text) > limit:
        return text[:limit - 3] + "..."
    return text


def main():
    print("=" * 78)
    print("BR39 - RAW TSETMC MARKET FIELD INSPECTION")
    print("=" * 78)

    source = latest_br37_file()
    print(f"Source file: {source}")

    with source.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    records = extract_records(payload)
    matched = [
        (index, row)
        for index, row in enumerate(records)
        if isinstance(row, dict) and matches_underlying(row)
    ]

    print(f"Total API records: {len(records)}")
    print(f"Matching underlying records: {len(matched)}")

    if not matched:
        print("\nERROR: No records matched the underlying code.")
        print("Root object keys:")
        if isinstance(payload, dict):
            for key in payload:
                print(f"  {key}")
        return

    # Collect every key seen in matching records.
    key_counts = Counter()
    for _, row in matched:
        key_counts.update(row.keys())

    all_keys = sorted(key_counts)

    print("\n" + "=" * 78)
    print("1. ALL KEYS IN MATCHING RAW RECORDS")
    print("=" * 78)
    for key in all_keys:
        print(f"{key:<36} present in {key_counts[key]:>3}/{len(matched)} records")

    print("\n" + "=" * 78)
    print("2. MARKET-RELATED FIELD NAMES")
    print("=" * 78)

    selected_keys = [
        key for key in all_keys
        if any(term in key.lower() for term in WATCH_TERMS)
    ]

    for key in selected_keys:
        print(f"\n{key}")
        value_counts = Counter(
            repr(row.get(key, "<KEY ABSENT>"))
            for _, row in matched
        )
        for value, count in value_counts.most_common(8):
            print(f"  {count:>3} records | {value[:150]}")

    print("\n" + "=" * 78)
    print("3. RAW MATCHING RECORDS — FIRST 3")
    print("=" * 78)

    for index, row in matched[:3]:
        print(f"\n--- API record index: {index} ---")
        print(json.dumps(row, ensure_ascii=False, indent=2, default=str))

    print("\n" + "=" * 78)
    print("4. CALL / PUT FIELD COMPARISON")
    print("=" * 78)

    for side in ("C", "P"):
        print(f"\n[{side}]")

        side_keys = [
            key for key in all_keys
            if key.endswith(f"_{side}")
        ]

        for key in side_keys:
            values = Counter(
                repr(row.get(key, "<KEY ABSENT>"))
                for _, row in matched
            )
            common = "; ".join(
                f"{value[:70]} ({count})"
                for value, count in values.most_common(4)
            )
            print(f"{key:<30} {common}")

    # Save the diagnostic output as text and JSON for reproducibility.
    output = {
        "source_file": str(source),
        "underlying_code": UNDERLYING_CODE,
        "total_api_records": len(records),
        "matching_records": len(matched),
        "keys": [
            {"name": key, "record_count": key_counts[key]}
            for key in all_keys
        ],
        "raw_matching_samples": [
            {"source_record_index": index, "record": row}
            for index, row in matched[:3]
        ],
    }

    stamp = source.stem.replace("BR37_live_response_", "")
    json_path = DATA_DIR / f"BR39_raw_field_inspection_{stamp}.json"
    txt_path = DATA_DIR / f"BR39_raw_field_inspection_{stamp}.txt"

    json_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    summary = [
        f"Source file: {source}",
        f"Total API records: {len(records)}",
        f"Matching records: {len(matched)}",
        "",
        "ALL KEYS:",
        *[
            f"{key}: {key_counts[key]}/{len(matched)}"
            for key in all_keys
        ],
        "",
        "RAW SAMPLES:",
        *[
            f"Record index {index}:\n"
            + json.dumps(row, ensure_ascii=False, indent=2, default=str)
            for index, row in matched[:3]
        ],
    ]
    txt_path.write_text("\n".join(summary), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"JSON diagnostic: {json_path}")
    print(f"Text diagnostic: {txt_path}")
    print("Database access: NONE")
    print("Database writes: NONE")
    print("BR39 completed.")
    print("=" * 78)


if __name__ == "__main__":
    main()
