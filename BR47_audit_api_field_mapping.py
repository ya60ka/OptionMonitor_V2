
# BR47 - Audit Raw TSETMC Option API Field Mapping
# Read-only audit. No database writes.

import json
from pathlib import Path
from collections import Counter


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
OUTPUT_DIR = DATA_DIR

UNDERLYING_CODE = "17914401175772326"

PRICE_FIELDS = (
    "pDrCotVal",
    "pClosing",
    "priceYesterday",
    "priceFirst",
    "priceMin",
    "priceMax",
)

TRADE_FIELDS = (
    "zTotTran",
    "qTotTran5J",
    "qTotCap",
    "pMeDem",
    "qTitMeDem",
    "pMeOf",
    "qTitMeOf",
    "oP",
    "yesterdayOP",
    "notionalValue",
)

UNDERLYING_FIELDS = (
    "lval30_UA",
    "pDrCotVal_UA",
    "pClosing_UA",
    "priceYesterday_UA",
)


def latest_br44_file():
    files = sorted(
        DATA_DIR.glob("BR44_live_response_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(
            f"No BR44_live_response_*.json file found in {DATA_DIR}"
        )
    return files[0]


def display_value(value, limit=180):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def main():
    source_file = latest_br44_file()

    print("=" * 78)
    print("BR47 - Raw API Field Mapping Audit")
    print("=" * 78)
    print(f"Source file : {source_file}")
    print("Mode        : READ ONLY")
    print("Database    : NOT CONNECTED")

    with source_file.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object at the root.")

    print("\nRoot keys:")
    for key, value in payload.items():
        if isinstance(value, list):
            print(f"  {key}: list, {len(value)} items")
        elif isinstance(value, dict):
            print(f"  {key}: object, {len(value)} keys")
        else:
            print(f"  {key}: {type(value).__name__}")

    api_rows = payload.get("instrumentOptMarketWatch")
    if not isinstance(api_rows, list):
        raise ValueError(
            "Expected list payload['instrumentOptMarketWatch']; "
            f"found keys: {list(payload.keys())}"
        )

    print(f"\nTotal API records: {len(api_rows)}")

    if not api_rows:
        raise ValueError("API record list is empty.")

    matching_rows = [
        row for row in api_rows
        if isinstance(row, dict)
        and str(row.get("insCode", "")) == UNDERLYING_CODE
    ]

    print(f"Matching underlying rows: {len(matching_rows)}")

    # Field inventory across all matching option records.
    field_counts = Counter()
    for row in matching_rows:
        field_counts.update(row.keys())

    print("\n" + "=" * 78)
    print("1. FIELD INVENTORY FOR MATCHING OPTION RECORDS")
    print("=" * 78)

    for field in sorted(field_counts):
        print(
            f"{field:<32} "
            f"present={field_counts[field]:>3}/{len(matching_rows)}"
        )

    print("\n" + "=" * 78)
    print("2. PRICE FIELD CANDIDATES")
    print("=" * 78)

    for field in PRICE_FIELDS:
        count = sum(field in row for row in matching_rows)
        non_null = sum(
            field in row and row[field] is not None
            for row in matching_rows
        )
        positive = sum(
            isinstance(row.get(field), (int, float))
            and not isinstance(row.get(field), bool)
            and row[field] > 0
            for row in matching_rows
        )
        samples = [
            row[field]
            for row in matching_rows
            if field in row and row[field] is not None
        ][:5]

        print(f"\nField: {field}")
        print(f"  Present       : {count}/{len(matching_rows)}")
        print(f"  Non-null      : {non_null}")
        print(f"  Positive nums : {positive}")
        print(f"  Samples       : {display_value(samples)}")

    print("\n" + "=" * 78)
    print("3. TRADE, VOLUME, ORDER BOOK AND OI CANDIDATES")
    print("=" * 78)

    for field in TRADE_FIELDS:
        count = sum(field in row for row in matching_rows)
        non_null_values = [
            row[field]
            for row in matching_rows
            if field in row and row[field] is not None
        ]
        positive = sum(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
            for value in non_null_values
        )
        zero = sum(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value == 0
            for value in non_null_values
        )

        print(f"\nField: {field}")
        print(f"  Present       : {count}/{len(matching_rows)}")
        print(f"  Non-null      : {len(non_null_values)}")
        print(f"  Positive nums : {positive}")
        print(f"  Zero nums     : {zero}")
        print(
            "  Samples       : "
            + display_value(non_null_values[:5])
        )

    print("\n" + "=" * 78)
    print("4. UNDERLYING FIELD CANDIDATES")
    print("=" * 78)

    for field in UNDERLYING_FIELDS:
        values = [
            row[field]
            for row in matching_rows
            if field in row
        ]
        print(
            f"{field:<28} "
            f"present={len(values):>3}/{len(matching_rows)} "
            f"samples={display_value(values[:5])}"
        )

    print("\n" + "=" * 78)
    print("5. FIRST RAW RECORD")
    print("=" * 78)

    print(json.dumps(
        matching_rows[0] if matching_rows else api_rows[0],
        ensure_ascii=False,
        indent=2,
    ))

    print("\n" + "=" * 78)
    print("6. POSSIBLE EXTREMA / OPEN INTEREST FIELD NAMES")
    print("=" * 78)

    keywords = (
        "first", "min", "max", "low", "high",
        "openinterest", "open_interest", "interest",
        "yesterdayop", "op",
    )

    candidate_fields = sorted({
        key
        for row in matching_rows
        for key in row
        if any(word in key.lower() for word in keywords)
    })

    if candidate_fields:
        for field in candidate_fields:
            samples = [
                row[field]
                for row in matching_rows
                if field in row and row[field] is not None
            ][:5]
            print(f"{field:<32} samples={display_value(samples)}")
    else:
        print("No candidate field names found.")

    report_file = OUTPUT_DIR / "BR47_field_mapping_audit.txt"

    # Capture a reproducible report alongside console output.
    # The source JSON remains unchanged.
    print(f"\nReport path: {report_file}")
    print(
        "\nAudit completed. No database connection or database writes performed."
    )


if __name__ == "__main__":
    main()
