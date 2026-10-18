
# BR23 - Normalize اهرم option contracts from saved TSETMC response
# Purpose:
# 1. Read the saved BR21 API response without calling the API.
# 2. Select records matching the exact underlying code of اهرم.
# 3. Normalize C-side contracts as CALL and P-side contracts as PUT.
# 4. Preserve all available expiries and original side-specific fields.
# 5. Save normalized JSON and a diagnostic report.
# 6. Do not connect to or modify any database.

import json
from collections import Counter
from datetime import datetime
from pathlib import Path


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")

RAW_FILE = (
    PROJECT_DIR
    / "data"
    / "api_tests"
    / "BR21_response_20261014_064945.raw"
)

OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"

UNDERLYING_CODE = "17914401175772326"


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def save_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_contract_type(side):
    """
    Determine contract type from the documented API side suffix.
    C = CALL
    P = PUT
    """
    if side == "C":
        return "CALL"

    if side == "P":
        return "PUT"

    return "UNKNOWN"


def normalize_contract(record, side, source_index):
    """
    Convert one side of a combined API record into a contract record.
    Preserve original side-specific fields for validation.
    """
    suffix = f"_{side}"

    full_name = record.get(f"lVal30{suffix}")
    short_name = record.get(f"lVal18AFC{suffix}")

    source_fields = {
        key: value
        for key, value in record.items()
        if key.endswith(suffix)
    }

    return {
        "source_record_index": source_index,

        "underlying": {
            "ins_code": record.get("uaInsCode"),
            "name": record.get("lval30_UA"),
            "last_price": record.get("pDrCotVal_UA"),
            "closing_price": record.get("pClosing_UA"),
            "yesterday_price": record.get("priceYesterday_UA"),
        },

        "contract": {
            "ins_code": record.get(f"insCode{suffix}"),
            "short_name": short_name,
            "full_name": full_name,
            "type": get_contract_type(side),
            "contract_size": record.get("contractSize"),
            "strike_price": record.get("strikePrice"),
            "begin_date": record.get("beginDate"),
            "end_date": record.get("endDate"),
            "remaining_days": record.get("remainedDay"),
        },

        "market": {
            "last_price": record.get(f"pDrCotVal{suffix}"),
            "closing_price": record.get(f"pClosing{suffix}"),
            "yesterday_price": record.get(f"priceYesterday{suffix}"),

            # The API field oP represents open interest, not opening price.
            "open_price": None,
            "open_interest": record.get(f"oP{suffix}"),
            "yesterday_open_interest": record.get(
                f"yesterdayOP{suffix}"
            ),

            "trade_count": record.get(f"zTotTran{suffix}"),
            "volume": record.get(f"qTotTran5J{suffix}"),
            "traded_value": record.get(f"qTotCap{suffix}"),
            "notional_value": record.get(f"notionalValue{suffix}"),
        },

        "order_book": {
            "bid_price": record.get(f"pMeDem{suffix}"),
            "bid_quantity": record.get(f"qTitMeDem{suffix}"),
            "ask_price": record.get(f"pMeOf{suffix}"),
            "ask_quantity": record.get(f"qTitMeOf{suffix}"),
        },

        # Preserve the original side-specific API fields.
        "source_fields": source_fields,
    }


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    contracts_path = (
        OUTPUT_DIR / f"BR23_contracts_{timestamp}.json"
    )

    report_path = (
        OUTPUT_DIR / f"BR23_report_{timestamp}.txt"
    )

    print("=" * 70)
    print("BR23 - Normalize اهرم Option Contracts")
    print("=" * 70)
    print(f"Input file      : {RAW_FILE}")
    print(f"Underlying code : {UNDERLYING_CODE}")
    print("API request     : NO")
    print("Database        : NOT USED")
    print("-" * 70)

    if not RAW_FILE.is_file():
        print("ERROR: Input raw response file was not found.")
        print("Check RAW_FILE. No files were modified.")
        return

    try:
        payload = json.loads(RAW_FILE.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: Cannot read or parse input JSON: {exc}")
        return

    if not isinstance(payload, dict):
        print("ERROR: Unexpected JSON root type.")
        return

    records = payload.get("instrumentOptMarketWatch")

    if not isinstance(records, list):
        print("ERROR: instrumentOptMarketWatch is not an array.")
        return

    matching_records = [
        (index, record)
        for index, record in enumerate(records)
        if isinstance(record, dict)
        and str(record.get("uaInsCode", "")) == UNDERLYING_CODE
    ]

    contracts = []

    for source_index, record in matching_records:
        # The API provides both sides in each combined record.
        for side in ("P", "C"):
            contract = normalize_contract(
                record=record,
                side=side,
                source_index=source_index,
            )
            contracts.append(contract)

    # --------------------------------------------------
    # Diagnostics
    # --------------------------------------------------

    type_counts = Counter(
        item["contract"]["type"]
        for item in contracts
    )

    expiry_counts = Counter(
        item["contract"]["end_date"] or "UNKNOWN"
        for item in contracts
    )

    missing_id_count = sum(
        1
        for item in contracts
        if not item["contract"]["ins_code"]
    )

    unique_ids = [
        item["contract"]["ins_code"]
        for item in contracts
        if item["contract"]["ins_code"]
    ]

    duplicate_id_count = len(unique_ids) - len(set(unique_ids))

    missing_name_count = sum(
        1
        for item in contracts
        if not item["contract"]["full_name"]
    )

    unknown_type_count = type_counts.get("UNKNOWN", 0)

    # Save all normalized records without filtering by expiry.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_json(contracts_path, contracts)

    lines = [
        "BR23 NORMALIZATION REPORT",
        "=" * 70,
        f"Source file: {RAW_FILE}",
        f"Total API array items: {len(records)}",
        f"Matching underlying records: {len(matching_records)}",
        f"Normalized contract records: {len(contracts)}",
        f"CALL records: {type_counts.get('CALL', 0)}",
        f"PUT records: {type_counts.get('PUT', 0)}",
        f"UNKNOWN type records: {unknown_type_count}",
        f"Records missing contract ID: {missing_id_count}",
        f"Records missing contract name: {missing_name_count}",
        f"Duplicate non-empty contract IDs: {duplicate_id_count}",
        "",
        "CONTRACT COUNTS BY EXPIRY",
        "-" * 70,
    ]

    for expiry, count in sorted(expiry_counts.items()):
        lines.append(f"{expiry}: {count}")

    lines.extend([
        "",
        "OUTPUT",
        "-" * 70,
        f"Contracts JSON: {contracts_path}",
        f"Report: {report_path}",
        "API requested: NO",
        "Database accessed: NO",
        "Source raw file modified: NO",
    ])

    report_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(f"Matching records : {len(matching_records)}")
    print(f"Normalized items : {len(contracts)}")
    print(f"CALL records     : {type_counts.get('CALL', 0)}")
    print(f"PUT records      : {type_counts.get('PUT', 0)}")
    print(f"UNKNOWN types    : {unknown_type_count}")
    print(f"Missing IDs      : {missing_id_count}")
    print(f"Missing names    : {missing_name_count}")
    print(f"Duplicate IDs    : {duplicate_id_count}")
    print()
    print("Expiry counts:")

    for expiry, count in sorted(expiry_counts.items()):
        print(f"  {expiry}: {count}")

    print("-" * 70)
    print(f"Contracts JSON  : {contracts_path}")
    print(f"Report          : {report_path}")

    if unknown_type_count == 0 and missing_id_count == 0:
        print("RESULT          : SUCCESS")
    else:
        print("RESULT          : REVIEW REQUIRED")

    print("Database        : NOT USED")
    print("=" * 70)


if __name__ == "__main__":
    main()
