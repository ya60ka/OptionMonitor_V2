
# BR48 - Audit Paired Call/Put API Records
# Read-only. No database connection or writes.

import json
from pathlib import Path
from collections import Counter


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

UNDERLYING_CODE = "17914401175772326"

COMMON_FIELDS = (
    "uaInsCode",
    "lval30_UA",
    "pDrCotVal_UA",
    "pClosing_UA",
    "priceYesterday_UA",
    "beginDate",
    "endDate",
    "strikePrice",
    "contractSize",
    "remainedDay",
)

CONTRACT_FIELDS = (
    "insCode",
    "lVal18AFC",
    "lVal30",
    "pDrCotVal",
    "pClosing",
    "priceYesterday",
    "pMeDem",
    "qTitMeDem",
    "pMeOf",
    "qTitMeOf",
    "zTotTran",
    "qTotTran5J",
    "qTotCap",
    "notionalValue",
    "oP",
    "yesterdayOP",
    "priceFirst",
    "priceMin",
    "priceMax",
)

def latest_source():
    files = sorted(
        DATA_DIR.glob("BR44_live_response_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError("BR44 JSON file not found.")
    return files[0]


def positive_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    )


def sample_text(values, limit=5):
    return repr(values[:limit])


def main():
    source = latest_source()

    print("=" * 78)
    print("BR48 - Paired Call/Put API Field Audit")
    print("=" * 78)
    print(f"Source file: {source}")
    print("Mode       : READ ONLY")
    print("Database   : NOT CONNECTED")

    with source.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    rows = payload.get("instrumentOptMarketWatch")
    if not isinstance(rows, list):
        raise ValueError("instrumentOptMarketWatch is not a list.")

    print(f"\nTotal raw records: {len(rows)}")

    # The API returns paired Call/Put records.
    # Filter using the underlying's own instrument code.
    matching = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("uaInsCode", "")) == UNDERLYING_CODE
    ]

    print(f"Matching underlying records: {len(matching)}")

    if not matching:
        codes = Counter(str(row.get("uaInsCode", "")) for row in rows
                        if isinstance(row, dict))
        print("\nMost common uaInsCode values:")
        for code, count in codes.most_common(15):
            print(f"  {code}: {count}")

        print("\nNo matching rows found. Check the underlying code.")
        return

    print("\n" + "=" * 78)
    print("1. COMMON UNDERLYING AND CONTRACT METADATA")
    print("=" * 78)

    for field in COMMON_FIELDS:
        values = [
            row[field] for row in matching
            if field in row and row[field] is not None
        ]
        print(
            f"{field:<24} present={len(values):>3}/{len(matching)} "
            f"samples={sample_text(values)}"
        )

    print("\n" + "=" * 78)
    print("2. CALL AND PUT CONTRACT INVENTORY")
    print("=" * 78)

    contracts = {"C": [], "P": []}

    for row in matching:
        for side in ("C", "P"):
            ins_code = row.get(f"insCode_{side}")
            if ins_code not in (None, "", 0, "0"):
                contracts[side].append((row, side))

    for side in ("C", "P"):
        unique_codes = {
            str(row.get(f"insCode_{side}"))
            for row, _ in contracts[side]
        }
        print(
            f"{side}: records={len(contracts[side])}, "
            f"unique IDs={len(unique_codes)}"
        )

    print("\n" + "=" * 78)
    print("3. FIELD AUDIT BY CONTRACT SIDE")
    print("=" * 78)

    for side in ("C", "P"):
        print(f"\n--- {side} CONTRACTS ---")
        side_records = contracts[side]

        for base_field in CONTRACT_FIELDS:
            field = f"{base_field}_{side}"
            present = [
                row[field] for row, _ in side_records
                if field in row
            ]
            non_null = [v for v in present if v is not None]
            positive = [v for v in non_null if positive_number(v)]
            zeros = [
                v for v in non_null
                if isinstance(v, (int, float))
                and not isinstance(v, bool)
                and v == 0
            ]

            print(
                f"{field:<28} "
                f"present={len(present):>3}/{len(side_records)} "
                f"non-null={len(non_null):>3} "
                f"positive={len(positive):>3} "
                f"zero={len(zeros):>3} "
                f"samples={sample_text(non_null)}"
            )

    print("\n" + "=" * 78)
    print("4. ALL RAW FIELD NAMES")
    print("=" * 78)

    all_fields = sorted({
        field
        for row, _ in contracts["C"] + contracts["P"]
        for field in row
    })

    for field in all_fields:
        print(field)

    print("\n" + "=" * 78)
    print("5. CANDIDATE FIELDS FOR PRICE EXTREMA AND OPEN INTEREST")
    print("=" * 78)

    keywords = (
        "first", "min", "max", "low", "high",
        "openinterest", "interest", "yesterdayop",
        "op_", "pdr", "closing", "yesterday",
    )

    candidates = [
        field for field in all_fields
        if any(word in field.lower() for word in keywords)
    ]

    for field in candidates:
        values = [
            row[field] for row, _ in contracts["C"] + contracts["P"]
            if field in row and row[field] is not None
        ]
        print(f"{field:<28} samples={sample_text(values)}")

    print("\n" + "=" * 78)
    print("6. SAMPLE RAW RECORD")
    print("=" * 78)
    print(json.dumps(matching[0], ensure_ascii=False, indent=2))

    print("\n" + "=" * 78)
    print("BR48 AUDIT COMPLETE")
    print("Database writes: NONE")
    print("Source JSON modified: NO")


if __name__ == "__main__":
    main()
