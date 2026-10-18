
# BR42 - Validate Derived Fields and Ambiguous API Values
# Uses saved BR37 data only. No database connection or writes.

from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections import Counter


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
UNDERLYING_CODE = "17914401175772326"

CANDIDATE_FIELDS = [
    "oP",
    "yesterdayOP",
    "notionalValue",
    "qTotCap",
    "zTotTran",
    "qTotTran5J",
    "pDrCotVal",
    "pClosing",
    "priceYesterday",
    "pMeDem",
    "pMeOf",
    "qTitMeDem",
    "qTitMeOf",
    "pFirst",
    "pMin",
    "pMax",
    "priceFirst",
    "priceMin",
    "priceMax",
    "priceOpen",
]


def normalize_id(value):
    if value is None:
        return None

    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    return text or None


def decimal_value(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        text = str(value).strip()
        if not text:
            return None
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None


def latest_br37_file():
    files = sorted(
        DATA_DIR.glob("BR37_live_response_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise FileNotFoundError(
            f"No BR37_live_response_*.json found in {DATA_DIR}"
        )

    return files[0]


def find_api_array(payload):
    candidates = []

    def walk(value, path="$"):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")

        elif isinstance(value, list):
            if value and all(isinstance(item, dict) for item in value):
                matches = sum(
                    1 for item in value
                    if "insCode_C" in item and "insCode_P" in item
                )

                if matches:
                    candidates.append(
                        (matches, len(value), path, value)
                    )

            for index, child in enumerate(value):
                if isinstance(child, (dict, list)):
                    walk(child, f"{path}[{index}]")

    walk(payload)

    if not candidates:
        raise ValueError("API array containing option IDs was not found.")

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, path, records = candidates[0]
    return path, records


def fmt(value):
    if value is None:
        return "N/A"

    if isinstance(value, Decimal):
        return f"{value:,.6f}".rstrip("0").rstrip(".")

    return str(value)


def distribution(values):
    valid = [value for value in values if value is not None]

    if not valid:
        return "valid=0"

    zeros = sum(value == 0 for value in valid)
    positives = sum(value > 0 for value in valid)
    negatives = sum(value < 0 for value in valid)

    return (
        f"valid={len(valid)}, positive={positives}, "
        f"zero={zeros}, negative={negatives}, "
        f"min={fmt(min(valid))}, max={fmt(max(valid))}"
    )


def main():
    print("=" * 78)
    print("BR42 - Validate Derived Fields and Ambiguous API Values")
    print("=" * 78)
    print("Mode             : READ ONLY; saved JSON only")
    print(f"Underlying code  : {UNDERLYING_CODE}")
    print()

    source_path = latest_br37_file()

    with source_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)

    array_path, all_records = find_api_array(payload)

    records = [
        record for record in all_records
        if normalize_id(record.get("uaInsCode")) == UNDERLYING_CODE
    ]

    if not records:
        raise RuntimeError(
            f"No records matched uaInsCode={UNDERLYING_CODE}"
        )

    print(f"Source file      : {source_path}")
    print(f"API array path   : {array_path}")
    print(f"Total API records: {len(all_records)}")
    print(f"Underlying rows  : {len(records)}")

    report = [
        "BR42 - Derived Fields and Ambiguous API Values",
        f"Run time: {datetime.now().isoformat(timespec='seconds')}",
        f"Source file: {source_path}",
        f"API array path: {array_path}",
        f"Underlying code: {UNDERLYING_CODE}",
        f"Total API records: {len(all_records)}",
        f"Underlying rows: {len(records)}",
        "Mode: READ ONLY; no database connection or writes",
        "",
    ]

    # 1. Inspect candidate fields and actual raw key names.
    print()
    print("-" * 78)
    print("1. RAW FIELD AVAILABILITY")
    print("-" * 78)
    report.extend(["RAW FIELD AVAILABILITY"])

    all_keys = set()
    for record in records:
        all_keys.update(record.keys())

    for base in CANDIDATE_FIELDS:
        present_sides = []
        for side in ("C", "P"):
            key = f"{base}_{side}"
            if key in all_keys:
                present_sides.append(side)

        values = []
        for record in records:
            for side in ("C", "P"):
                key = f"{base}_{side}"
                if key in record:
                    values.append(decimal_value(record.get(key)))

        line = (
            f"{base:18} sides={','.join(present_sides) or 'NONE':5} "
            f"{distribution(values)}"
        )
        print(line)
        report.append(line)

    # 2. Calculate price differences for each contract.
    print()
    print("-" * 78)
    print("2. PRICE DIFFERENCE CANDIDATES")
    print("-" * 78)
    report.extend(["", "PRICE DIFFERENCE CANDIDATES"])

    calculated = []

    for record in records:
        for side in ("C", "P"):
            contract_id = normalize_id(record.get(f"insCode_{side}"))

            last = decimal_value(record.get(f"pDrCotVal_{side}"))
            close = decimal_value(record.get(f"pClosing_{side}"))
            yesterday = decimal_value(record.get(f"priceYesterday_{side}"))

            last_change = (
                last - yesterday
                if last is not None and yesterday is not None
                else None
            )
            close_change = (
                close - yesterday
                if close is not None and yesterday is not None
                else None
            )

            last_percent = None
            close_percent = None

            if yesterday is not None and yesterday != 0 and last_change is not None:
                last_percent = last_change * Decimal("100") / yesterday

            if yesterday is not None and yesterday != 0 and close_change is not None:
                close_percent = close_change * Decimal("100") / yesterday

            calculated.append({
                "side": side,
                "contract_id": contract_id,
                "last": last,
                "close": close,
                "yesterday": yesterday,
                "last_change": last_change,
                "last_percent": last_percent,
                "close_change": close_change,
                "close_percent": close_percent,
            })

    for item in calculated[:12]:
        line = (
            f"{item['side']} ID={item['contract_id']} "
            f"last={fmt(item['last'])} "
            f"close={fmt(item['close'])} "
            f"yesterday={fmt(item['yesterday'])} "
            f"last_change={fmt(item['last_change'])} "
            f"last_pct={fmt(item['last_percent'])}% "
            f"close_change={fmt(item['close_change'])} "
            f"close_pct={fmt(item['close_percent'])}%"
        )
        print(line)
        report.append(line)

    for field in (
        "last_change",
        "last_percent",
        "close_change",
        "close_percent",
    ):
        values = [item[field] for item in calculated]
        line = f"{field}: {distribution(values)}"
        print(line)
        report.append(line)

    # 3. Underlying price fields.
    print()
    print("-" * 78)
    print("3. UNDERLYING PRICE FIELDS")
    print("-" * 78)
    report.extend(["", "UNDERLYING PRICE FIELDS"])

    underlying_fields = (
        "lval30_UA",
        "pDrCotVal_UA",
        "pClosing_UA",
        "priceYesterday_UA",
    )

    for field in underlying_fields:
        values = [
            record.get(field)
            for record in records
            if record.get(field) is not None
        ]
        unique_values = list(dict.fromkeys(str(value) for value in values))
        line = (
            f"{field}: present={len(values)}/{len(records)}, "
            f"unique_values={unique_values[:10]}"
        )
        print(line)
        report.append(line)

    # 4. Underlying change candidates.
    print()
    print("-" * 78)
    print("4. UNDERLYING CHANGE CANDIDATES")
    print("-" * 78)
    report.extend(["", "UNDERLYING CHANGE CANDIDATES"])

    if records:
        first = records[0]
        ua_last = decimal_value(first.get("pDrCotVal_UA"))
        ua_close = decimal_value(first.get("pClosing_UA"))
        ua_yesterday = decimal_value(first.get("priceYesterday_UA"))

        for label, current in (
            ("last_vs_yesterday", ua_last),
            ("close_vs_yesterday", ua_close),
        ):
            difference = (
                current - ua_yesterday
                if current is not None and ua_yesterday is not None
                else None
            )

            percentage = None
            if (
                difference is not None
                and ua_yesterday is not None
                and ua_yesterday != 0
            ):
                percentage = difference * Decimal("100") / ua_yesterday

            line = (
                f"{label}: current={fmt(current)}, "
                f"yesterday={fmt(ua_yesterday)}, "
                f"difference={fmt(difference)}, "
                f"percentage={fmt(percentage)}%"
            )
            print(line)
            report.append(line)

    # 5. Conclusions are deliberately conservative.
    print()
    print("-" * 78)
    print("5. VALIDATION NOTES")
    print("-" * 78)

    notes = [
        "Calculated price differences are candidate values, not proof of the "
        "official API definition for PriceChange.",
        "Percentage change is not calculated when the previous price is zero.",
        "Fields absent from the API must not be fabricated as live values.",
        "FirstPrice, MinPrice and MaxPrice require explicit source fields or "
        "a separately approved derivation; do not infer them from last/close.",
        "oP and yesterdayOP are inspected as raw fields, but their semantics "
        "must be confirmed before production mapping.",
        "qTotCap is inspected independently from notionalValue; their units "
        "and meanings must be confirmed before mapping TradeValue.",
        "No database connection was opened and no database changes were made.",
    ]

    for note in notes:
        print(f"- {note}")
        report.append(f"- {note}")

    report_path = DATA_DIR / (
        "BR42_derived_fields_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".txt"
    )

    report_path.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8-sig",
    )

    print()
    print("=" * 78)
    print("BR42 FINISHED")
    print("=" * 78)
    print("Database writes : NONE")
    print(f"Report          : {report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("=" * 78)
        print("BR42 FAILED")
        print("=" * 78)
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)
