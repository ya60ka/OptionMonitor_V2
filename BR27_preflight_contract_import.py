
# BR27 - Preflight Contract Import (READ ONLY)
# Version: 2.1
# Purpose: Validate BR23 contract records against OptionMarketDB_V2.
# Safety: SELECT-only. No database data or schema is modified.

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, date
from pathlib import Path

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
API_TEST_DIR = PROJECT_DIR / "data" / "api_tests"

EXPECTED_DATABASE = "OptionMarketDB_V2"
UNDERLYING_CODE = "17914401175772326"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    f"DATABASE={EXPECTED_DATABASE};"
    "Trusted_Connection=yes;"
    "ApplicationIntent=ReadOnly;"
)


def print_header():
    print("=" * 72)
    print("BR27 - Preflight Contract Import (READ ONLY)")
    print("=" * 72)
    print(f"Project directory : {PROJECT_DIR}")
    print(f"Input directory   : {API_TEST_DIR}")
    print(f"Database          : {EXPECTED_DATABASE}")
    print("Database writes   : DISABLED")
    print()


def find_latest_br23() -> Path:
    files = list(API_TEST_DIR.glob("BR23_contracts_*.json"))

    if not files:
        raise FileNotFoundError(
            f"No BR23_contracts_*.json found in {API_TEST_DIR}"
        )

    return max(files, key=lambda p: p.stat().st_mtime)


def load_records(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    if isinstance(payload, list):
        records = payload

    elif isinstance(payload, dict):
        records = None

        for key in ("contracts", "records", "data", "items"):
            if isinstance(payload.get(key), list):
                records = payload[key]
                break

        if records is None:
            raise ValueError(
                "JSON root is an object, but no contract list was found."
            )

    else:
        raise ValueError(
            f"Unexpected JSON root type: {type(payload).__name__}"
        )

    if not records:
        raise ValueError("The BR23 JSON contains no records.")

    if not all(isinstance(record, dict) for record in records):
        raise ValueError("A record in the JSON list is not an object.")

    return records


def parse_gregorian_date(value) -> date | None:
    if value is None:
        return None

    value = str(value).strip()

    if not re.fullmatch(r"\d{8}", value):
        return None

    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def parse_persian_expiry(full_name) -> str | None:
    """
    Extract a Persian date only when the exact YYYY/MM/DD pattern
    is present in the contract full name.
    """
    if not full_name:
        return None

    match = re.search(
        r"(?<!\d)(1\d{3})/(\d{2})/(\d{2})(?!\d)",
        str(full_name)
    )

    if not match:
        return None

    return "/".join(match.groups())


def normalize_record(record: dict, index: int) -> dict:
    # BR23 fields are nested, not at the root level.
    underlying = record.get("underlying")
    contract = record.get("contract")

    if not isinstance(underlying, dict):
        raise ValueError(
            f"Record #{index}: 'underlying' is missing or invalid."
        )

    if not isinstance(contract, dict):
        raise ValueError(
            f"Record #{index}: 'contract' is missing or invalid."
        )

    code = str(contract.get("ins_code") or "").strip()

    if not code:
        raise ValueError(
            f"Record #{index}: contract.ins_code is empty."
        )

    underlying_code = str(
        underlying.get("ins_code") or ""
    ).strip()

    raw_type = str(
        contract.get("type") or ""
    ).strip().upper()

    if raw_type not in ("CALL", "PUT"):
        raise ValueError(
            f"Contract {code}: invalid type {raw_type!r}."
        )

    strike_raw = contract.get("strike_price")

    try:
        strike = float(strike_raw) if strike_raw is not None else None
    except (TypeError, ValueError):
        raise ValueError(
            f"Contract {code}: invalid strike_price {strike_raw!r}."
        )

    contract_size_raw = contract.get("contract_size")

    try:
        contract_size = (
            int(contract_size_raw)
            if contract_size_raw is not None
            else None
        )
    except (TypeError, ValueError):
        raise ValueError(
            f"Contract {code}: invalid contract_size "
            f"{contract_size_raw!r}."
        )

    full_name = contract.get("full_name")
    end_date_source = contract.get("end_date")

    expiry_gregorian = parse_gregorian_date(end_date_source)
    expiry_persian = parse_persian_expiry(full_name)

    return {
        "source_record_index": record.get(
            "source_record_index", index
        ),
        "underlying_code": underlying_code,
        "underlying_name": underlying.get("name"),
        "tse_code": code,
        "symbol": contract.get("short_name"),
        "name": full_name,
        "option_type": "C" if raw_type == "CALL" else "P",
        "option_type_source": raw_type,
        "strike": strike,
        "contract_size": contract_size,
        "expiry_persian": expiry_persian,
        "expiry_gregorian": expiry_gregorian,
        "end_date_source": end_date_source,
        "remaining_days": contract.get("remaining_days"),
    }


def get_columns(cursor, table_name: str) -> set[str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = ?
        """,
        table_name,
    )

    return {row[0] for row in cursor.fetchall()}


def compare_value(field, source_value, db_value):
    """
    Return a mismatch description or None.
    Missing source Persian expiry is intentionally not compared.
    """
    if field in ("ExpiryDate", "ExpiryDatePersian"):
        if source_value is None:
            return None

    if source_value is None and db_value is None:
        return None

    if source_value is None:
        return None

    if db_value is None:
        return f"{field}: source={source_value!r}, database=NULL"

    if field == "StrikePrice":
        if abs(float(source_value) - float(db_value)) < 0.0001:
            return None
        return (
            f"{field}: source={source_value!r}, "
            f"database={db_value!r}"
        )

    if field == "ExpiryDate":
        source_date = source_value
        db_date = db_value.date() if isinstance(
            db_value, datetime
        ) else db_value

        if source_date == db_date:
            return None

    elif str(source_value).strip() == str(db_value).strip():
        return None

    return f"{field}: source={source_value!r}, database={db_value!r}"


def main() -> int:
    print_header()

    try:
        source_path = find_latest_br23()
        source_records = load_records(source_path)

        normalized = [
            normalize_record(record, index)
            for index, record in enumerate(source_records)
        ]

    except Exception as exc:
        print(f"INPUT ERROR: {type(exc).__name__}: {exc}")
        return 2

    print(f"Source file       : {source_path}")
    print(f"Source records    : {len(normalized)}")

    source_codes = [item["tse_code"] for item in normalized]

    duplicate_codes = sorted({
        code
        for code in source_codes
        if source_codes.count(code) > 1
    })

    wrong_underlyings = sorted({
        item["underlying_code"]
        for item in normalized
        if item["underlying_code"] != UNDERLYING_CODE
    })

    missing_strike = sum(
        item["strike"] is None for item in normalized
    )

    missing_expiry = sum(
        item["expiry_gregorian"] is None for item in normalized
    )

    missing_persian_expiry = sum(
        item["expiry_persian"] is None for item in normalized
    )

    print(f"Unique contract IDs: {len(set(source_codes))}")
    print(f"Duplicate source IDs: {len(duplicate_codes)}")
    print(f"Unexpected underlying codes: {len(wrong_underlyings)}")
    print(f"Missing strike: {missing_strike}")
    print(f"Missing Gregorian expiry: {missing_expiry}")
    print(f"Missing Persian expiry: {missing_persian_expiry}")
    print()

    if duplicate_codes:
        print("Duplicate source contract IDs:")
        for code in duplicate_codes:
            print(f"  {code}")

    if wrong_underlyings:
        print("Unexpected underlying codes:")
        for code in wrong_underlyings:
            print(f"  {code}")

    connection = None

    try:
        connection = pyodbc.connect(
            CONNECTION_STRING,
            timeout=10,
            autocommit=True,
        )

        cursor = connection.cursor()

        cursor.execute("SELECT DB_NAME()")
        actual_database = cursor.fetchone()[0]

        print(f"Connected database: {actual_database}")

        if actual_database != EXPECTED_DATABASE:
            print("SAFETY STOP: Unexpected database.")
            return 3

        underlying_columns = get_columns(cursor, "Underlying")
        contract_columns = get_columns(cursor, "OptionContract")

        if not underlying_columns or not contract_columns:
            print(
                "SCHEMA ERROR: dbo.Underlying or "
                "dbo.OptionContract was not found."
            )
            return 4

        required_contract_columns = {
            "UnderlyingID",
            "TSEInsCode",
            "Symbol",
            "ContractName",
            "OptionType",
            "StrikePrice",
            "ExpiryDatePersian",
            "ExpiryDate",
            "ContractSize",
        }

        missing_columns = (
            required_contract_columns - contract_columns
        )

        if missing_columns:
            print(
                "SCHEMA ERROR: Required columns are missing: "
                + ", ".join(sorted(missing_columns))
            )
            return 5

        cursor.execute(
            """
            SELECT UnderlyingID, TSEInsCode, Symbol, InstrumentName
            FROM dbo.Underlying
            WHERE TSEInsCode = ?
            """,
            UNDERLYING_CODE,
        )

        underlying_rows = cursor.fetchall()

        if len(underlying_rows) != 1:
            print(
                "SAFETY STOP: Expected exactly one underlying row; "
                f"found {len(underlying_rows)}."
            )
            return 6

        underlying_id, db_code, db_symbol, db_name = underlying_rows[0]

        print(
            f"Underlying match: ID={underlying_id}, "
            f"code={db_code}, symbol={db_symbol}, name={db_name}"
        )

        cursor.execute(
            """
            SELECT TSEInsCode, Symbol, ContractName, OptionType,
                   StrikePrice, ExpiryDatePersian, ExpiryDate,
                   ContractSize
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
            """,
            underlying_id,
        )

        db_rows = cursor.fetchall()
        existing_by_code = {
            str(row.TSEInsCode): row for row in db_rows
        }

        new_candidates = []
        matching_existing = []
        conflicts = []

        for item in normalized:
            code = item["tse_code"]

            if code in duplicate_codes:
                conflicts.append(
                    (item, ["Duplicate TSEInsCode in BR23 source."])
                )
                continue

            if item["underlying_code"] != UNDERLYING_CODE:
                conflicts.append(
                    (
                        item,
                        [
                            "Underlying code does not match "
                            "the configured underlying."
                        ],
                    )
                )
                continue

            db_row = existing_by_code.get(code)

            if db_row is None:
                new_candidates.append(item)
                continue

            comparisons = [
                ("Symbol", item["symbol"], db_row.Symbol),
                ("ContractName", item["name"], db_row.ContractName),
                ("OptionType", item["option_type"], db_row.OptionType),
                ("StrikePrice", item["strike"], db_row.StrikePrice),
                (
                    "ExpiryDatePersian",
                    item["expiry_persian"],
                    db_row.ExpiryDatePersian,
                ),
                (
                    "ExpiryDate",
                    item["expiry_gregorian"],
                    db_row.ExpiryDate,
                ),
                (
                    "ContractSize",
                    item["contract_size"],
                    db_row.ContractSize,
                ),
            ]

            mismatches = []

            for field, source_value, db_value in comparisons:
                message = compare_value(
                    field, source_value, db_value
                )
                if message:
                    mismatches.append(message)

            if mismatches:
                conflicts.append((item, mismatches))
            else:
                matching_existing.append(item)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = API_TEST_DIR / (
            f"BR27_preflight_report_{timestamp}.txt"
        )

        lines = [
            "BR27 - PREFLIGHT CONTRACT IMPORT REPORT",
            "=" * 72,
            f"Timestamp: {datetime.now().isoformat(timespec='seconds')}",
            f"Source file: {source_path}",
            f"Database: {actual_database}",
            f"Underlying: {db_symbol} / {db_code} / ID={underlying_id}",
            f"Source records: {len(normalized)}",
            f"Unique source IDs: {len(set(source_codes))}",
            f"Matching existing records: {len(matching_existing)}",
            f"New candidates: {len(new_candidates)}",
            f"Records with conflicts: {len(conflicts)}",
            f"Duplicate source IDs: {len(duplicate_codes)}",
            f"Unexpected underlying codes: {len(wrong_underlyings)}",
            f"Missing strike: {missing_strike}",
            f"Missing Gregorian expiry: {missing_expiry}",
            f"Missing Persian expiry: {missing_persian_expiry}",
            "",
            "NEW CANDIDATES (not inserted):",
        ]

        for item in new_candidates:
            lines.append(
                f"{item['tse_code']} | {item['symbol']} | "
                f"{item['option_type_source']} | "
                f"strike={item['strike']} | "
                f"expiry={item['end_date_source']} | "
                f"Persian={item['expiry_persian']}"
            )

        lines.extend(["", "CONFLICTS:"])

        for item, messages in conflicts:
            lines.append(
                f"{item['tse_code']} | {item['symbol']}"
            )
            for message in messages:
                lines.append(f"  - {message}")

        lines.extend([
            "",
            "SAFETY: SELECT-only; no database data or schema was modified.",
        ])

        report_path.write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

        print()
        print("PREFLIGHT SUMMARY")
        print("-" * 72)
        print(f"Matching existing records: {len(matching_existing)}")
        print(f"New candidates: {len(new_candidates)}")
        print(f"Records with conflicts: {len(conflicts)}")
        print(f"Report: {report_path}")
        print()
        print("READ-ONLY PREFLIGHT COMPLETE. NO DATABASE DATA WAS MODIFIED.")

        return 0

    except Exception as exc:
        print(f"PRECHECK ERROR: {type(exc).__name__}: {exc}")
        return 7

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    sys.exit(main())
