
# BR55 - Underlying Notional Formula Audit
# Read-only analysis of the saved BR54 API response.

import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

INPUT_FILE = DATA_DIR / "BR54_live_response_20261015_072826.json"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

CSV_FILE = DATA_DIR / f"BR55_underlying_notional_{RUN_ID}.csv"
JSON_FILE = DATA_DIR / f"BR55_report_{RUN_ID}.json"

UNDERLYING_ID = "17914401175772326"


def num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def ratio(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def rel_error(actual, expected):
    if actual is None or expected is None or expected == 0:
        return None
    return (actual - expected) / expected


def median(values):
    values = [
        value for value in values
        if value is not None and math.isfinite(value)
    ]
    return statistics.median(values) if values else None


def load_records(path):
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        records = data.get("instrumentOptMarketWatch")
        if isinstance(records, list):
            return records

    raise ValueError("Unexpected API response structure.")


def main():
    print("=" * 76)
    print("BR55 - UNDERLYING NOTIONAL FORMULA AUDIT")
    print("=" * 76)
    print(f"Input: {INPUT_FILE}")
    print("Database access: NONE")
    print("Database changes: NONE")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(str(INPUT_FILE))

    records = load_records(INPUT_FILE)
    rows = []

    for index, record in enumerate(records):
        if str(record.get("uaInsCode", "")) != UNDERLYING_ID:
            continue

        underlying_close = num(record.get("pClosing_UA"))
        underlying_last = num(record.get("pDrCotVal_UA"))
        underlying_yesterday = num(record.get("priceYesterday_UA"))
        contract_size = num(record.get("contractSize"))

        for suffix, side in (("C", "CALL"), ("P", "PUT")):
            contract_id = record.get(f"insCode_{suffix}")
            if contract_id is None:
                continue

            volume = num(record.get(f"qTotTran5J_{suffix}"))
            notional = num(record.get(f"notionalValue_{suffix}"))
            option_close = num(record.get(f"pClosing_{suffix}"))
            cap = num(record.get(f"qTotCap_{suffix}"))

            expected_close = (
                volume * underlying_close * contract_size
                if volume is not None
                and underlying_close is not None
                and contract_size is not None
                else None
            )

            expected_last = (
                volume * underlying_last * contract_size
                if volume is not None
                and underlying_last is not None
                and contract_size is not None
                else None
            )

            expected_yesterday = (
                volume * underlying_yesterday * contract_size
                if volume is not None
                and underlying_yesterday is not None
                and contract_size is not None
                else None
            )

            rows.append({
                "source_record_index": index,
                "side": side,
                "symbol": record.get(f"lVal18AFC_{suffix}"),
                "contract_id": str(contract_id),
                "volume": volume,
                "contract_size": contract_size,
                "underlying_close": underlying_close,
                "underlying_last": underlying_last,
                "underlying_yesterday": underlying_yesterday,
                "option_close": option_close,
                "qTotCap": cap,
                "notionalValue": notional,
                "notional_per_volume": ratio(notional, volume),
                "underlying_close_times_size": (
                    underlying_close * contract_size
                    if underlying_close is not None
                    and contract_size is not None
                    else None
                ),
                "expected_notional_using_underlying_close": expected_close,
                "expected_notional_using_underlying_last": expected_last,
                "expected_notional_using_underlying_yesterday":
                    expected_yesterday,
                "relative_error_underlying_close":
                    rel_error(notional, expected_close),
                "relative_error_underlying_last":
                    rel_error(notional, expected_last),
                "relative_error_underlying_yesterday":
                    rel_error(notional, expected_yesterday),
                "relative_error_option_close_formula": rel_error(
                    cap,
                    volume * option_close * 1000
                    if volume is not None and option_close is not None
                    else None,
                ),
            })

    if not rows:
        raise RuntimeError("No matching contracts found.")

    positive = [
        row for row in rows
        if row["volume"] is not None and row["volume"] > 0
    ]

    def formula_summary(field, tolerance):
        eligible = [
            row for row in positive
            if row[field] is not None
        ]
        matched = sum(
            abs(row[field]) <= tolerance
            for row in eligible
        )
        errors = [row[field] for row in eligible]

        return {
            "eligible": len(eligible),
            "matched_within_relative_error_tolerance": matched,
            "tolerance": tolerance,
            "median_relative_error": median(errors),
            "max_absolute_relative_error": (
                max(abs(value) for value in errors)
                if errors else None
            ),
        }

    underlying_close_values = sorted({
        row["underlying_close"] for row in rows
        if row["underlying_close"] is not None
    })
    underlying_last_values = sorted({
        row["underlying_last"] for row in rows
        if row["underlying_last"] is not None
    })
    underlying_yesterday_values = sorted({
        row["underlying_yesterday"] for row in rows
        if row["underlying_yesterday"] is not None
    })
    contract_sizes = sorted({
        row["contract_size"] for row in rows
        if row["contract_size"] is not None
    })

    report = {
        "input_file": str(INPUT_FILE),
        "raw_record_count": len(records),
        "contract_count": len(rows),
        "positive_volume_count": len(positive),
        "underlying_close_values": underlying_close_values,
        "underlying_last_values": underlying_last_values,
        "underlying_yesterday_values": underlying_yesterday_values,
        "contract_sizes": contract_sizes,
        "notional_formula_using_underlying_close": formula_summary(
            "relative_error_underlying_close", 1e-9
        ),
        "notional_formula_using_underlying_last": formula_summary(
            "relative_error_underlying_last", 1e-9
        ),
        "notional_formula_using_underlying_yesterday": formula_summary(
            "relative_error_underlying_yesterday", 1e-9
        ),
        "database_access": False,
        "database_changes": False,
        "contracts": rows,
    }

    with CSV_FILE.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)

    with JSON_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print(f"\nContracts: {len(rows)}")
    print(f"Positive volume: {len(positive)}")
    print(f"Underlying closing prices: {underlying_close_values}")
    print(f"Underlying last prices: {underlying_last_values}")
    print(f"Underlying yesterday prices: {underlying_yesterday_values}")
    print(f"Contract sizes: {contract_sizes}")

    print("\nFORMULA TESTS")
    print(
        "Notional = volume * underlying close * contract size:",
        report["notional_formula_using_underlying_close"],
    )
    print(
        "Notional = volume * underlying last * contract size:",
        report["notional_formula_using_underlying_last"],
    )
    print(
        "Notional = volume * underlying yesterday * contract size:",
        report["notional_formula_using_underlying_yesterday"],
    )

    print("\nSAMPLE CONTRACTS")
    for row in positive[:8]:
        print(
            f"{row['symbol']} | volume={row['volume']} | "
            f"underlying_close={row['underlying_close']} | "
            f"size={row['contract_size']} | "
            f"notional={row['notionalValue']} | "
            f"expected={row['expected_notional_using_underlying_close']} | "
            f"relative_error={row['relative_error_underlying_close']}"
        )

    print("\nOUTPUT FILES")
    print(f"CSV : {CSV_FILE}")
    print(f"JSON: {JSON_FILE}")
    print("\nBR55 completed successfully.")


if __name__ == "__main__":
    main()
