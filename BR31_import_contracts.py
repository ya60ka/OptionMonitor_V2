
# BR31 - Atomic Option Contract Import
# Project: OptionMonitor_V2
# Target DB: OptionMarketDB_V2
# Source: BR23_contracts_20261014_065435.json
# Atomic transaction; old database OptionMarketDB is never accessed.

import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
SOURCE_FILE = DATA_DIR / "BR23_contracts_20261014_065435.json"

UNDERLYING_CODE = "17914401175772326"
DATABASE_NAME = "OptionMarketDB_V2"
EXPECTED_RECORDS = 84

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    f"DATABASE={DATABASE_NAME};"
    "Trusted_Connection=yes;"
)

INSERT_SQL = """
INSERT INTO dbo.OptionContract
(
    UnderlyingID,
    TSEInsCode,
    Symbol,
    ContractName,
    OptionType,
    StrikePrice,
    ExpiryDatePersian,
    ExpiryDate,
    ContractSize
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


def parse_decimal(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None


def parse_date(value):
    if value is None:
        return None

    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_persian_expiry(full_name):
    match = re.search(
        r"(?<!\d)(14\d{2})[/-](\d{1,2})[/-](\d{1,2})(?!\d)",
        str(full_name or ""),
    )
    if not match:
        return None

    year, month, day = match.groups()
    return f"{year}/{int(month):02d}/{int(day):02d}"


def load_and_validate_source():
    if not SOURCE_FILE.is_file():
        raise FileNotFoundError(
            f"Approved BR23 source file not found: {SOURCE_FILE}"
        )

    with SOURCE_FILE.open("r", encoding="utf-8-sig") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError("BR23 JSON root must be a list.")

    if len(records) != EXPECTED_RECORDS:
        raise ValueError(
            f"Expected {EXPECTED_RECORDS} records, found {len(records)}. "
            "Import aborted."
        )

    normalized = []
    seen_codes = set()
    errors = []

    for index, record in enumerate(records):
        label = f"Record #{index}"

        if not isinstance(record, dict):
            errors.append(f"{label}: record is not an object")
            continue

        underlying = record.get("underlying")
        contract = record.get("contract")

        if not isinstance(underlying, dict) or not isinstance(contract, dict):
            errors.append(f"{label}: missing underlying/contract object")
            continue

        underlying_code = str(
            underlying.get("ins_code") or ""
        ).strip()

        code = str(contract.get("ins_code") or "").strip()
        option_raw = str(contract.get("type") or "").strip().upper()

        if option_raw in ("CALL", "C"):
            option_type = "C"
        elif option_raw in ("PUT", "P"):
            option_type = "P"
        else:
            option_type = None

        short_name = str(contract.get("short_name") or "").strip()
        full_name = str(contract.get("full_name") or "").strip()
        strike = parse_decimal(contract.get("strike_price"))
        expiry_date = parse_date(contract.get("end_date"))
        expiry_persian = parse_persian_expiry(full_name)

        try:
            size_raw = contract.get("contract_size")
            contract_size = (
                int(size_raw)
                if size_raw is not None and str(size_raw).strip()
                else None
            )
        except (TypeError, ValueError):
            contract_size = None

        if underlying_code != UNDERLYING_CODE:
            errors.append(f"{label}: unexpected underlying code")

        if not code:
            errors.append(f"{label}: missing TSEInsCode")
        elif len(code) > 30:
            errors.append(f"{label}: TSEInsCode exceeds 30 characters")
        elif code in seen_codes:
            errors.append(f"{label}: duplicate source TSEInsCode {code}")
        else:
            seen_codes.add(code)

        if option_type not in ("C", "P"):
            errors.append(f"{label}: invalid OptionType")

        if strike is None or strike < 0:
            errors.append(f"{label}: invalid StrikePrice")

        if expiry_date is None:
            errors.append(f"{label}: invalid Gregorian expiry")

        if expiry_persian is None:
            errors.append(f"{label}: Persian expiry not found in full_name")

        if contract_size is None or contract_size <= 0:
            errors.append(f"{label}: invalid ContractSize")

        if len(short_name) > 100:
            errors.append(f"{label}: Symbol exceeds 100 characters")

        if len(full_name) > 250:
            errors.append(f"{label}: ContractName exceeds 250 characters")

        if (
            underlying_code == UNDERLYING_CODE
            and code
            and len(code) <= 30
            and option_type in ("C", "P")
            and strike is not None
            and strike >= 0
            and expiry_date is not None
            and expiry_persian is not None
            and contract_size is not None
            and contract_size > 0
            and len(short_name) <= 100
            and len(full_name) <= 250
        ):
            normalized.append(
                (
                    code,
                    short_name or None,
                    full_name or None,
                    option_type,
                    strike,
                    expiry_persian,
                    expiry_date,
                    contract_size,
                )
            )

    if errors:
        raise ValueError(
            "Source validation failed:\n- " + "\n- ".join(errors)
        )

    if len(normalized) != EXPECTED_RECORDS:
        raise ValueError(
            f"Only {len(normalized)} records passed validation."
        )

    return normalized


def main():
    print("=" * 72)
    print("BR31 - Atomic Option Contract Import")
    print("=" * 72)
    print(f"Project: {PROJECT_DIR}")
    print(f"Target database: {DATABASE_NAME}")
    print(f"Source: {SOURCE_FILE}")
    print("Old database: NOT ACCESSED")
    print()

    connection = None
    report_lines = []
    inserted_count = 0

    try:
        # Validate the complete source before opening the transaction.
        records = load_and_validate_source()

        call_count = sum(1 for r in records if r[3] == "C")
        put_count = sum(1 for r in records if r[3] == "P")

        print(f"Source validation: PASS ({len(records)} records)")
        print(f"CALL: {call_count}")
        print(f"PUT : {put_count}")

        if call_count != 42 or put_count != 42:
            raise ValueError(
                f"Unexpected CALL/PUT distribution: {call_count}/{put_count}"
            )

        connection = pyodbc.connect(
            CONNECTION_STRING,
            timeout=15,
            autocommit=False,
        )
        connection.timeout = 15
        cursor = connection.cursor()

        # Use SERIALIZABLE and key-range locks to reduce the risk of
        # concurrent duplicate inserts. The unique index remains the
        # final database-level protection.
        cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")

        cursor.execute("SELECT DB_NAME();")
        actual_database = cursor.fetchone()[0]

        if actual_database != DATABASE_NAME:
            raise RuntimeError(
                f"Wrong database connected: {actual_database}"
            )

        print(f"Connected database: {actual_database}")

        # Confirm exactly one matching underlying and lock the row.
        cursor.execute(
            """
            SELECT UnderlyingID, TSEInsCode, Symbol, InstrumentName
            FROM dbo.Underlying WITH (UPDLOCK, HOLDLOCK)
            WHERE TSEInsCode = ?;
            """,
            UNDERLYING_CODE,
        )
        underlying_rows = cursor.fetchall()

        if len(underlying_rows) != 1:
            raise RuntimeError(
                "Expected exactly one matching Underlying row; "
                f"found {len(underlying_rows)}."
            )

        underlying_id = underlying_rows[0].UnderlyingID
        print(f"Target UnderlyingID: {underlying_id}")

        # Global duplicate check by unique TSEInsCode, not by UnderlyingID.
        existing_codes = []
        for record in records:
            code = record[0]
            cursor.execute(
                """
                SELECT TSEInsCode, UnderlyingID
                FROM dbo.OptionContract WITH (UPDLOCK, HOLDLOCK)
                WHERE TSEInsCode = ?;
                """,
                code,
            )
            row = cursor.fetchone()
            if row is not None:
                existing_codes.append(
                    f"{row.TSEInsCode} (UnderlyingID={row.UnderlyingID})"
                )

        if existing_codes:
            raise RuntimeError(
                "At least one source contract already exists globally. "
                "No records will be inserted:\n- "
                + "\n- ".join(existing_codes)
            )

        print("Global duplicate check: PASS")
        print("Starting transaction...")

        # Insert each record in the same transaction.
        for record in records:
            (
                code,
                symbol,
                full_name,
                option_type,
                strike,
                expiry_persian,
                expiry_date,
                contract_size,
            ) = record

            cursor.execute(
                INSERT_SQL,
                underlying_id,
                code,
                symbol,
                full_name,
                option_type,
                strike,
                expiry_persian,
                expiry_date,
                contract_size,
            )
            inserted_count += 1

        # Verify all source IDs are present under the intended underlying
        # before committing the transaction.
        source_codes = [record[0] for record in records]
        placeholders = ",".join("?" for _ in source_codes)

        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
              AND TSEInsCode IN ({placeholders});
            """,
            underlying_id,
            *source_codes,
        )
        verified_count = cursor.fetchone()[0]

        if verified_count != EXPECTED_RECORDS:
            raise RuntimeError(
                "Post-insert verification failed: "
                f"expected {EXPECTED_RECORDS}, found {verified_count}."
            )

        # Verify the inserted CALL/PUT distribution.
        cursor.execute(
            f"""
            SELECT OptionType, COUNT(*)
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
              AND TSEInsCode IN ({placeholders})
            GROUP BY OptionType;
            """,
            underlying_id,
            *source_codes,
        )
        distribution = {
            str(row.OptionType): int(row[1])
            for row in cursor.fetchall()
        }

        if distribution.get("C", 0) != 42 or distribution.get("P", 0) != 42:
            raise RuntimeError(
                f"Post-insert CALL/PUT verification failed: {distribution}"
            )

        connection.commit()

        report_lines = [
            "BR31 - IMPORT RESULT",
            "=" * 72,
            f"Timestamp: {datetime.now().isoformat(timespec='seconds')}",
            f"Database: {actual_database}",
            f"UnderlyingID: {underlying_id}",
            f"Source file: {SOURCE_FILE}",
            f"Source records: {len(records)}",
            f"Inserted in transaction: {inserted_count}",
            f"Verified records: {verified_count}",
            f"CALL: {distribution.get('C', 0)}",
            f"PUT: {distribution.get('P', 0)}",
            "Transaction: COMMITTED",
            "Old database OptionMarketDB: NOT ACCESSED",
        ]

        print()
        print("=" * 72)
        print("BR31 RESULT: SUCCESS")
        print("=" * 72)
        print(f"Inserted records: {inserted_count}")
        print(f"Verified records: {verified_count}")
        print(f"CALL: {distribution.get('C', 0)}")
        print(f"PUT : {distribution.get('P', 0)}")
        print("Transaction committed successfully.")

    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
                print("Transaction rolled back.")
            except Exception as rollback_exc:
                print(f"Rollback error: {rollback_exc}")

        report_lines = [
            "BR31 - IMPORT RESULT",
            "=" * 72,
            f"Timestamp: {datetime.now().isoformat(timespec='seconds')}",
            f"Source file: {SOURCE_FILE}",
            f"Error: {type(exc).__name__}: {exc}",
            "Transaction: ROLLED BACK if it had started",
            "Old database OptionMarketDB: NOT ACCESSED",
        ]

        print()
        print(f"BR31 FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)

    finally:
        if connection is not None:
            connection.close()

        try:
            report_path = DATA_DIR / (
                f"BR31_import_report_{datetime.now():%Y%m%d_%H%M%S}.txt"
            )
            report_path.write_text(
                "\n".join(report_lines),
                encoding="utf-8",
            )
            print(f"Report saved: {report_path}")
        except Exception as report_exc:
            print(f"WARNING: Could not save report: {report_exc}")


if __name__ == "__main__":
    main()
