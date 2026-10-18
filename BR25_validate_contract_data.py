
#!/usr/bin/env python3
# BR25 - Validate BR23 normalized option contracts against TSETMC raw data.
# Read-only: no API calls, no database access, no input JSON modifications.

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
UNDERLYING_CODE = "17914401175772326"

# Normalized market field -> source API base key.
EXPECTED_MAPPINGS = {
    "last_price": "pDrCotVal",
    "closing_price": "pClosing",
    "yesterday_price": "priceYesterday",
    "trade_count": "zTotTran",
    "volume": "qTotTran5J",
    "traded_value": "qTotCap",
    "notional_value": "notionalValue",
    "yesterday_open_interest": "yesterdayOP",
    "open_interest": "oP",
}

RAW_FIELDS_TO_CHECK = (
    "insCode", "lVal18AFC", "lVal30", "pDrCotVal", "pClosing",
    "priceYesterday", "oP", "zTotTran", "qTotTran5J", "qTotCap",
    "notionalValue", "yesterdayOP", "pMeDem", "qTitMeDem", "pMeOf",
    "qTitMeOf",
)


def newest_file(pattern: str) -> Path:
    matches = list(DATA_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No file found for pattern: {DATA_DIR / pattern}"
        )
    return max(matches, key=lambda p: p.stat().st_mtime)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def as_text(value: Any) -> str | None:
    return None if value is None else str(value)


def find_raw_records(raw_data: Any) -> list[dict]:
    if isinstance(raw_data, list):
        return [item for item in raw_data if isinstance(item, dict)]

    if isinstance(raw_data, dict):
        for key in (
            "instrumentOptMarketWatch",
            "instrumentOptMarketWatchList",
            "data",
            "items",
            "result",
        ):
            value = raw_data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        for value in raw_data.values():
            if isinstance(value, dict):
                try:
                    return find_raw_records(value)
                except ValueError:
                    pass

    raise ValueError("Could not find the raw API records array.")


def compare_values(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None

    # Compare numeric values without being sensitive to JSON int/float/string.
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def contract_suffix(contract_type: str) -> str | None:
    if contract_type == "CALL":
        return "C"
    if contract_type == "PUT":
        return "P"
    return None


def main() -> int:
    print("=" * 70)
    print("BR25 - Validate BR23 Normalized Option Contract Data")
    print("=" * 70)
    print(f"Project directory : {PROJECT_DIR}")
    print(f"Data directory    : {DATA_DIR}")
    print(f"Underlying code   : {UNDERLYING_CODE}")
    print("API request       : NO")
    print("Database          : NOT USED")
    print("-" * 70)

    # BR23 is the current normalization output; do not read an old BR24 file.
    contracts_path = newest_file("BR23_contracts_*.json")
    raw_path = newest_file("BR21_response_*.raw")

    records = load_json(contracts_path)
    raw_data = load_json(raw_path)
    raw_records = find_raw_records(raw_data)

    if not isinstance(records, list):
        raise ValueError("BR23 JSON root must be a list.")

    print(f"BR23 input        : {contracts_path}")
    print(f"BR21 raw source   : {raw_path}")
    print(f"BR23 records      : {len(records)}")
    print(f"Raw API records   : {len(raw_records)}")
    print("-" * 70)

    counts = {
        "CALL": 0,
        "PUT": 0,
        "UNKNOWN": 0,
        "source_index_missing": 0,
        "raw_record_not_found": 0,
        "underlying_mismatch": 0,
        "source_field_mismatch": 0,
        "normalized_mapping_mismatch": 0,
        "open_price_not_null": 0,
        "missing_contract_id": 0,
        "duplicate_contract_id": 0,
        "invalid_numeric_values": 0,
    }

    issues: list[str] = []
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()

    def add_issue(counter: str, message: str) -> None:
        counts[counter] += 1
        issues.append(message)

    for index, rec in enumerate(records):
        if not isinstance(rec, dict):
            issues.append(f"Record #{index}: record is not an object.")
            continue

        underlying = rec.get("underlying") or {}
        contract = rec.get("contract") or {}
        market = rec.get("market") or {}
        source = rec.get("source_fields") or {}
        name = contract.get("short_name", f"record #{index}")
        typ = contract.get("type")
        suffix = contract_suffix(typ)

        if typ in ("CALL", "PUT"):
            counts[typ] += 1
        else:
            counts["UNKNOWN"] += 1
            issues.append(f"{name}: unknown contract type {typ!r}.")

        contract_id = as_text(contract.get("ins_code"))
        if not contract_id:
            add_issue(
                "missing_contract_id",
                f"{name}: missing contract.ins_code.",
            )
        elif contract_id in seen_ids:
            duplicate_ids.add(contract_id)
        else:
            seen_ids.add(contract_id)

        if as_text(underlying.get("ins_code")) != UNDERLYING_CODE:
            add_issue(
                "underlying_mismatch",
                f"{name}: underlying code is "
                f"{underlying.get('ins_code')!r}.",
            )

        raw_index = rec.get("source_record_index")
        raw = None

        if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
            add_issue(
                "source_index_missing",
                f"{name}: invalid source_record_index {raw_index!r}.",
            )
        elif raw_index >= len(raw_records):
            add_issue(
                "raw_record_not_found",
                f"{name}: source index {raw_index} is outside raw array "
                f"(size {len(raw_records)}).",
            )
        else:
            raw = raw_records[raw_index]

        if raw is None or suffix is None:
            continue

        # Validate source_fields snapshot against the raw record at this index.
        for base in RAW_FIELDS_TO_CHECK:
            key = f"{base}_{suffix}"
            if key not in source:
                continue

            raw_value = raw.get(key)
            stored_value = source.get(key)

            if not compare_values(raw_value, stored_value):
                add_issue(
                    "source_field_mismatch",
                    f"{name}: source_fields.{key}={stored_value!r}, "
                    f"raw API value={raw_value!r}.",
                )

        # Check the option contract ID against the corresponding raw API field.
        raw_contract_id = raw.get(f"insCode_{suffix}")
        if (
            raw_contract_id is not None
            and contract_id is not None
            and str(raw_contract_id) != contract_id
        ):
            add_issue(
                "source_field_mismatch",
                f"{name}: contract ID {contract_id!r} does not match "
                f"raw insCode_{suffix}={raw_contract_id!r}.",
            )

        # Validate normalized market fields against their source snapshots.
        for market_field, base in EXPECTED_MAPPINGS.items():
            source_key = f"{base}_{suffix}"

            # Missing source or market keys must not silently pass.
            if source_key not in source:
                add_issue(
                    "normalized_mapping_mismatch",
                    f"{name}: missing source_fields.{source_key}.",
                )
                continue

            if market_field not in market:
                add_issue(
                    "normalized_mapping_mismatch",
                    f"{name}: missing market.{market_field}.",
                )
                continue

            if not compare_values(
                market.get(market_field),
                source.get(source_key),
            ):
                add_issue(
                    "normalized_mapping_mismatch",
                    f"{name}: market.{market_field}="
                    f"{market.get(market_field)!r} does not match "
                    f"source_fields.{source_key}={source.get(source_key)!r}.",
                )

        # oP is treated as open interest, never as opening trade price.
        if "open_price" not in market or market.get("open_price") is not None:
            add_issue(
                "open_price_not_null",
                f"{name}: market.open_price should be None unless a "
                "verified opening-price source is defined; current value="
                f"{market.get('open_price')!r}.",
            )

        # Basic numeric sanity checks. Negative values are flagged.
        numeric_fields = tuple(EXPECTED_MAPPINGS.keys())

        for field in numeric_fields:
            value = market.get(field)
            if value is None:
                continue

            try:
                numeric_value = float(value)
                if numeric_value < 0:
                    add_issue(
                        "invalid_numeric_values",
                        f"{name}: market.{field} is negative ({value!r}).",
                    )
            except (TypeError, ValueError):
                add_issue(
                    "invalid_numeric_values",
                    f"{name}: market.{field} is not numeric ({value!r}).",
                )

    counts["duplicate_contract_id"] = len(duplicate_ids)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = DATA_DIR / f"BR25_validation_report_{stamp}.txt"

    lines = [
        "BR25 BR23 NORMALIZED CONTRACT VALIDATION REPORT",
        "=" * 70,
        f"BR23 input: {contracts_path}",
        f"BR21 raw source: {raw_path}",
        f"Underlying code: {UNDERLYING_CODE}",
        f"Total BR23 records: {len(records)}",
        f"Raw API records: {len(raw_records)}",
        "",
        "COUNTS",
        "-" * 70,
    ]

    for key, value in counts.items():
        lines.append(f"{key}: {value}")

    lines.extend(["", "ISSUES (first 200)", "-" * 70])
    lines.extend(
        issues[:200]
        if issues
        else ["No issues detected by the implemented checks."]
    )

    if len(issues) > 200:
        lines.append(
            f"... {len(issues) - 200} additional issues omitted."
        )

    lines.extend([
        "",
        "SAFETY",
        "-" * 70,
        "API requests: none",
        "Database access: none",
        "Input JSON modified: no",
        "oP is validated as open_interest, not open_price.",
        "A passed result applies only to the checks implemented here.",
        f"Report: {report_path}",
    ])

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("VALIDATION COUNTS")
    print("-" * 70)
    for key, value in counts.items():
        print(f"{key:34}: {value}")

    print("-" * 70)
    print(f"Issues recorded   : {len(issues)}")
    print(f"Report            : {report_path}")
    print("API request       : NO")
    print("Database          : NOT USED")
    print("Input JSON modified: NO")

    blocking = (
        "UNKNOWN",
        "source_index_missing",
        "raw_record_not_found",
        "underlying_mismatch",
        "source_field_mismatch",
        "normalized_mapping_mismatch",
        "open_price_not_null",
        "missing_contract_id",
        "duplicate_contract_id",
        "invalid_numeric_values",
    )

    if any(counts[key] for key in blocking):
        print("RESULT            : REVIEW REQUIRED")
        return 2

    print("RESULT            : CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"BR25 ERROR: {type(exc).__name__}: {exc}")
        raise
