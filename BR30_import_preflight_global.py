
# BR30 - Global Contract Import Preflight (READ ONLY)
# Project: OptionMonitor_V2
# Database: OptionMarketDB_V2
# No database writes. Old database remains untouched.

import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
UNDERLYING_CODE = "17914401175772326"
DB_NAME = "OptionMarketDB_V2"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    f"DATABASE={DB_NAME};"
    "Trusted_Connection=yes;"
    "ApplicationIntent=ReadOnly;"
)

REPORT_PREFIX = "BR30_preflight_report"


def latest_source_file():
    files = sorted(
        DATA_DIR.glob("BR23_contracts_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(
            f"No BR23 source JSON found in: {DATA_DIR}"
        )
    return files[0]


def read_source(path):
    with path.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)

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
                "Could not find a contract list in the JSON root."
            )
    else:
        raise ValueError("Unexpected JSON root type.")

    return records


def parse_decimal(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None


def parse_gregorian_date(value):
    if value is None or str(value).strip() == "":
        return None

    text = str(value).strip()
    candidates = (
        "%Y-%m-%d",
        "%Y%m%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in candidates:
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            pass
    return None


def normalize_record(record, index):
    if not isinstance(record, dict):
        return {
            "index": index,
            "error": "Record is not an object",
        }

    # BR23 records are expected to have nested underlying/contract objects.
    underlying = record.get("underlying")
    contract = record.get("contract")

    if not isinstance(underlying, dict) or not isinstance(contract, dict):
        return {
            "index": index,
            "error": "Missing nested underlying or contract object",
        }

    underlying_code = str(
        underlying.get("ins_code", "") or ""
    ).strip()
    contract_code = str(
        contract.get("ins_code", "") or ""
    ).strip()

    raw_type = str(contract.get("type", "") or "").strip().upper()
    if raw_type in ("CALL", "C"):
        option_type = "C"
    elif raw_type in ("PUT", "P"):
        option_type = "P"
    else:
        option_type = None

    strike = parse_decimal(contract.get("strike_price"))
    contract_size_value = contract.get("contract_size")
    try:
        contract_size = (
            int(contract_size_value)
            if contract_size_value is not None
            and str(contract_size_value).strip() != ""
            else None
        )
    except (TypeError, ValueError):
        contract_size = None

    expiry_gregorian = parse_gregorian_date(
        contract.get("end_date")
    )

    full_name = str(
        contract.get("full_name", "") or ""
    ).strip()
    short_name = str(
        contract.get("short_name", "") or ""
    ).strip()

    # Attempt to extract a Persian expiry token from the full contract name.
    # Preserve the value only if a YYYY/MM/DD or YYYY-MM-DD token is present.
    expiry_persian = None
    match = re.search(
        r"(?<!\d)(14\d{2})[/-](\d{1,2})[/-](\d{1,2})(?!\d)",
        full_name,
    )
    if match:
        expiry_persian = (
            f"{match.group(1)}/"
            f"{int(match.group(2)):02d}/"
            f"{int(match.group(3)):02d}"
        )

    return {
        "index": index,
        "underlying_code": underlying_code,
        "contract_code": contract_code,
        "symbol": short_name or None,
        "contract_name": full_name or None,
        "option_type": option_type,
        "strike": strike,
        "contract_size": contract_size,
        "expiry_gregorian": expiry_gregorian,
        "expiry_persian": expiry_persian,
        "error": None,
    }


def main():
    print("=" * 72)
    print("BR30 - Global Contract Import Preflight (READ ONLY)")
    print("=" * 72)

    source_path = latest_source_file()
    source_records = read_source(source_path)
    normalized = [
        normalize_record(record, index)
        for index, record in enumerate(source_records)
    ]

    report_path = DATA_DIR / (
        f"{REPORT_PREFIX}_{datetime.now():%Y%m%d_%H%M%S}.txt"
    )

    errors = []
    valid_records = []

    for item in normalized:
        if item.get("error"):
            errors.append(
                f"Record #{item['index']}: {item['error']}"
            )
            continue

        if item["underlying_code"] != UNDERLYING_CODE:
            errors.append(
                f"Record #{item['index']}: unexpected underlying "
                f"code {item['underlying_code']!r}"
            )

        if not item["contract_code"]:
            errors.append(
                f"Record #{item['index']}: missing contract ID"
            )

        if item["option_type"] not in ("C", "P"):
            errors.append(
                f"Record #{item['index']}: invalid option type"
            )

        if item["strike"] is None or item["strike"] < 0:
            errors.append(
                f"Record #{item['index']}: invalid strike price"
            )

        if item["contract_size"] is None or item["contract_size"] <= 0:
            errors.append(
                f"Record #{item['index']}: invalid contract size"
            )

        if item["expiry_gregorian"] is None:
            errors.append(
                f"Record #{item['index']}: missing/invalid Gregorian expiry"
            )

        if item["expiry_persian"] is None:
            errors.append(
                f"Record #{item['index']}: missing Persian expiry in full_name"
            )

        valid_records.append(item)

    ids = [
        item["contract_code"]
        for item in valid_records
        if item.get("contract_code")
    ]
    duplicate_ids = sorted({
        code for code in ids if ids.count(code) > 1
    })

    conn = None
    db_rows = []
    underlying_rows = []

    try:
        conn = pyodbc.connect(CONNECTION_STRING, timeout=10)
        conn.timeout = 10
        cursor = conn.cursor()

        cursor.execute("SELECT DB_NAME()")
        connected_db = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT UnderlyingID, TSEInsCode, Symbol, InstrumentName
            FROM dbo.Underlying
            WHERE TSEInsCode = ?
            """,
            UNDERLYING_CODE,
        )
        underlying_rows = cursor.fetchall()

        # Critical improvement: inspect all contracts globally by TSEInsCode.
        cursor.execute(
            """
            SELECT
                OptionID,
                UnderlyingID,
                TSEInsCode,
                Symbol,
                ContractName,
                OptionType,
                StrikePrice,
                ExpiryDatePersian,
                ExpiryDate,
                ContractSize
            FROM dbo.OptionContract
            """
        )
        db_rows = cursor.fetchall()

    except Exception as exc:
        print(f"ERROR: Database inspection failed: {exc}")
        sys.exit(2)
    finally:
        if conn is not None:
            conn.close()

    existing_by_code = {
        str(row.TSEInsCode).strip(): row
        for row in db_rows
        if row.TSEInsCode is not None
    }

    if len(underlying_rows) != 1:
        errors.append(
            "Expected exactly one matching Underlying row; "
            f"found {len(underlying_rows)}"
        )

    underlying_id = (
        underlying_rows[0].UnderlyingID
        if len(underlying_rows) == 1
        else None
    )

    new_candidates = []
    matching_existing = []
    conflicts = []

    for item in valid_records:
        code = item.get("contract_code")
        if not code:
            continue

        existing = existing_by_code.get(code)

        if existing is None:
            new_candidates.append(item)
            continue

        differences = []

        if underlying_id is not None and existing.UnderlyingID != underlying_id:
            differences.append(
                f"UnderlyingID DB={existing.UnderlyingID}, "
                f"source target={underlying_id}"
            )

        if existing.OptionType and existing.OptionType != item["option_type"]:
            differences.append(
                f"OptionType DB={existing.OptionType}, "
                f"source={item['option_type']}"
            )

        if (
            existing.StrikePrice is not None
            and item["strike"] is not None
            and Decimal(str(existing.StrikePrice)) != item["strike"]
        ):
            differences.append(
                f"StrikePrice DB={existing.StrikePrice}, "
                f"source={item['strike']}"
            )

        if (
            existing.ExpiryDate is not None
            and item["expiry_gregorian"] is not None
            and existing.ExpiryDate != item["expiry_gregorian"]
        ):
            differences.append(
                f"ExpiryDate DB={existing.ExpiryDate}, "
                f"source={item['expiry_gregorian']}"
            )

        if differences:
            conflicts.append((item, differences, existing))
        else:
            matching_existing.append((item, existing))

    duplicate_report = []
    for code in duplicate_ids:
        duplicate_report.append(
            f"Duplicate source TSEInsCode: {code}"
        )

    lines = [
        "BR30 - GLOBAL CONTRACT IMPORT PREFLIGHT (READ ONLY)",
        "=" * 72,
        f"Source file: {source_path}",
        f"Source records: {len(source_records)}",
        f"Normalized records: {len(normalized)}",
        f"Connected database: {DB_NAME}",
        f"Database confirmed: {connected_db}",
        f"Database OptionContract rows: {len(db_rows)}",
        f"Matching Underlying rows: {len(underlying_rows)}",
        f"Target UnderlyingID: {underlying_id}",
        f"Unique source contract IDs: {len(set(ids))}",
        f"Duplicate source IDs: {len(duplicate_ids)}",
        f"New candidates: {len(new_candidates)}",
        f"Matching existing records: {len(matching_existing)}",
        f"Records with conflicts: {len(conflicts)}",
        f"Validation errors: {len(errors)}",
        "",
        "VALIDATION ERRORS",
        "-" * 72,
        *(errors or ["None"]),
        "",
        "DUPLICATE SOURCE IDS",
        "-" * 72,
        *(duplicate_report or ["None"]),
        "",
        "NEW CANDIDATES",
        "-" * 72,
    ]

    if new_candidates:
        for item in new_candidates:
            lines.append(
                f"{item['contract_code']} | "
                f"{item['option_type']} | "
                f"Strike={item['strike']} | "
                f"Expiry={item['expiry_gregorian']} | "
                f"Persian={item['expiry_persian']} | "
                f"Size={item['contract_size']}"
            )
    else:
        lines.append("None")

    lines += ["", "CONFLICTS", "-" * 72]
    if conflicts:
        for item, differences, existing in conflicts:
            lines.append(
                f"{item['contract_code']} | "
                f"DB UnderlyingID={existing.UnderlyingID}"
            )
            for difference in differences:
                lines.append(f"  - {difference}")
    else:
        lines.append("None")

    # Only writes a local report file; no SQL writes are executed.
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nReport saved: {report_path}")
    print("\nREAD-ONLY PREFLIGHT COMPLETE. NO DATABASE DATA WAS MODIFIED.")

    if errors or duplicate_ids or conflicts or len(underlying_rows) != 1:
        print("STATUS: NOT READY FOR IMPORT.")
        sys.exit(1)

    print("STATUS: PREFLIGHT PASSED; IMPORT NOT EXECUTED.")


if __name__ == "__main__":
    main()
