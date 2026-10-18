
# BR41 - Validate API-to-Snapshot Field Mapping
# READ ONLY: no INSERT, UPDATE, DELETE, or schema changes.

from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_CODE = "17914401175772326"

# Known API suffixes for option contract data.
OPTION_FIELD_MAP = {
    "LastPrice": "pDrCotVal",
    "ClosingPrice": "pClosing",
    "YesterdayPrice": "priceYesterday",
    "BestBuyPrice": "pMeDem",
    "BestBuyVolume": "qTitMeDem",
    "BestSellPrice": "pMeOf",
    "BestSellVolume": "qTitMeOf",
    "TradeCount": "zTotTran",
    "Volume": "qTotTran5J",
    "TradeValue": "qTotCap",
    "OpenInterest": "oP",
}

TARGET_COLUMNS = {
    "OptionLiveSnapshot": [
        "OptionID", "DataDate", "DataTime",
        "LastPrice", "ClosingPrice", "FirstPrice",
        "MinPrice", "MaxPrice", "YesterdayPrice",
        "PriceChange", "PriceChangePercent",
        "TradeCount", "Volume", "TradeValue",
        "BestBuyPrice", "BestBuyVolume",
        "BestSellPrice", "BestSellVolume",
        "OpenInterest", "UnderlyingLastPrice",
        "UnderlyingClosePrice", "ContractSize",
        "SourceRetrievedAt",
    ],
    "UnderlyingLiveSnapshot": [
        "UnderlyingID", "DataDate", "DataTime",
        "LastPrice", "ClosingPrice", "YesterdayPrice",
        "PriceChange", "PriceChangePercent",
        "TradeCount", "Volume", "TradeValue",
        "SourceRetrievedAt",
    ],
}


def normalize_id(value):
    if value is None:
        return None

    result = str(value).strip()

    if result.endswith(".0") and result[:-2].isdigit():
        result = result[:-2]

    return result or None


def to_decimal(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        text = str(value).strip()
        if not text:
            return None
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None


def find_latest_source():
    files = sorted(
        DATA_DIR.glob("BR37_live_response_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise FileNotFoundError(
            f"No BR37 JSON found in {DATA_DIR}"
        )

    return files[0]


def get_market_array(data):
    candidates = []

    def walk(value, path="$"):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")

        elif isinstance(value, list):
            if value and all(isinstance(x, dict) for x in value):
                count = sum(
                    1 for item in value
                    if "insCode_C" in item and "insCode_P" in item
                )
                if count:
                    candidates.append(
                        (count, len(value), path, value)
                    )

            for index, child in enumerate(value):
                if isinstance(child, (dict, list)):
                    walk(child, f"{path}[{index}]")

    walk(data)

    if not candidates:
        raise ValueError(
            "Could not find API records containing insCode_C and insCode_P."
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][3], candidates[0][2]


def quote_identifier(name):
    return "[" + str(name).replace("]", "]]") + "]"


def table_columns(cursor, table_name):
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        table_name,
    )

    return {
        row.COLUMN_NAME: {
            "type": row.DATA_TYPE,
            "nullable": row.IS_NULLABLE,
        }
        for row in cursor.fetchall()
    }


def load_contracts(cursor):
    cursor.execute(
        """
        SELECT OptionID, UnderlyingID, TSEInsCode,
               Symbol, OptionType, ContractSize
        FROM dbo.OptionContract
        """
    )

    contracts = {}

    for row in cursor.fetchall():
        code = normalize_id(row.TSEInsCode)
        if code:
            contracts[code] = {
                "OptionID": row.OptionID,
                "UnderlyingID": row.UnderlyingID,
                "Symbol": row.Symbol,
                "OptionType": row.OptionType,
                "ContractSize": row.ContractSize,
            }

    return contracts


def source_option_rows(records):
    result = []

    for record_index, record in enumerate(records):
        if normalize_id(record.get("uaInsCode")) != UNDERLYING_CODE:
            continue

        for side in ("C", "P"):
            ins_code = normalize_id(record.get(f"insCode_{side}"))
            if not ins_code:
                continue

            mapped = {
                "SourceRecordIndex": record_index,
                "SourceSide": side,
                "TSEInsCode": ins_code,
            }

            for target, source_base in OPTION_FIELD_MAP.items():
                mapped[target] = record.get(f"{source_base}_{side}")

            mapped["ContractSize"] = record.get("contractSize")
            result.append(mapped)

    return result


def inspect_underlying_fields(records):
    keys = set()

    for record in records:
        if normalize_id(record.get("uaInsCode")) == UNDERLYING_CODE:
            keys.update(record.keys())

    return sorted(
        key for key in keys
        if key.endswith("_UA")
        or key.endswith("_U")
        or key.startswith("ua")
        or key == "uaInsCode"
    )


def main():
    print("=" * 76)
    print("BR41 - Validate API-to-Snapshot Field Mapping")
    print("=" * 76)
    print("Mode             : READ ONLY")
    print(f"Database         : {DATABASE}")
    print(f"Underlying code  : {UNDERLYING_CODE}")
    print()

    source_path = find_latest_source()
    with source_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)

    records, array_path = get_market_array(payload)
    underlying_records = [
        record for record in records
        if normalize_id(record.get("uaInsCode")) == UNDERLYING_CODE
    ]
    option_rows = source_option_rows(records)

    print(f"Source file      : {source_path}")
    print(f"API array path   : {array_path}")
    print(f"Total API records: {len(records)}")
    print(f"Underlying rows  : {len(underlying_records)}")
    print(f"Option rows      : {len(option_rows)}")
    print()

    if len(option_rows) != 84:
        print(
            "WARNING: expected 84 option rows, "
            f"found {len(option_rows)}."
        )

    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "Connection Timeout=15;"
    )

    connection = pyodbc.connect(
        connection_string,
        autocommit=False,
    )
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT DB_NAME()")
        actual_database = cursor.fetchone()[0]

        if actual_database != DATABASE:
            raise RuntimeError(
                f"Safety check failed: connected to {actual_database}"
            )

        contracts = load_contracts(cursor)
        print(f"Connected DB     : {actual_database}")
        print(f"DB contracts     : {len(contracts)}")
        print("Database writes  : NONE")
        print()

        report = [
            "BR41 - API-to-Snapshot Field Mapping",
            f"Run time: {datetime.now().isoformat(timespec='seconds')}",
            f"Source: {source_path}",
            f"Database: {actual_database}",
            "Mode: READ ONLY",
            f"API array path: {array_path}",
            f"Total API records: {len(records)}",
            f"Underlying rows: {len(underlying_records)}",
            f"Option rows: {len(option_rows)}",
            "",
            "OPTION ID MATCH",
        ]

        ids_matched = 0
        for item in option_rows:
            contract = contracts.get(item["TSEInsCode"])
            if contract:
                ids_matched += 1
                item["DBOptionID"] = contract["OptionID"]
                item["DBUnderlyingID"] = contract["UnderlyingID"]
                item["DBSymbol"] = contract["Symbol"]
                item["DBOptionType"] = contract["OptionType"]
                item["DBContractSize"] = contract["ContractSize"]

        print("-" * 76)
        print("1. CONTRACT ID MATCH")
        print("-" * 76)
        print(f"Matched source contracts: {ids_matched}/{len(option_rows)}")
        report.append(f"Matched source contracts: {ids_matched}/{len(option_rows)}")

        for item in option_rows:
            if "DBOptionID" not in item:
                line = (
                    f"MISSING DB MATCH: source index={item['SourceRecordIndex']} "
                    f"side={item['SourceSide']} "
                    f"TSEInsCode={item['TSEInsCode']}"
                )
                print(line)
                report.append(line)

        print()
        print("-" * 76)
        print("2. SOURCE FIELD COVERAGE")
        print("-" * 76)
        report.extend(["", "SOURCE FIELD COVERAGE"])

        for target, source_base in OPTION_FIELD_MAP.items():
            source_fields = [
                f"{source_base}_C",
                f"{source_base}_P",
            ]

            present = [
                field for field in source_fields
                if any(field in row for row in underlying_records)
            ]

            populated = 0
            zero = 0
            missing = 0

            for item in option_rows:
                value = item.get(target)
                if value is None:
                    missing += 1
                    continue

                number = to_decimal(value)
                if number is None:
                    missing += 1
                elif number == 0:
                    zero += 1
                else:
                    populated += 1

            line = (
                f"{target:22} <- {source_base:18} "
                f"source_fields={len(present)}/2 | "
                f"positive/nonzero={populated} | "
                f"zero={zero} | missing_or_invalid={missing}"
            )
            print(line)
            report.append(line)

        print()
        print("-" * 76)
        print("3. UNDERLYING FIELD NAMES")
        print("-" * 76)

        underlying_keys = inspect_underlying_fields(records)
        report.extend(["", "UNDERLYING FIELD NAMES"])

        for key in underlying_keys:
            line = f"{key}: " + ", ".join(
                str(record.get(key))
                for record in underlying_records[:3]
            )
            print(line)
            report.append(line)

        print()
        print("-" * 76)
        print("4. TARGET TABLE SCHEMA CHECK")
        print("-" * 76)
        report.extend(["", "TARGET TABLE SCHEMA CHECK"])

        for table_name, required_columns in TARGET_COLUMNS.items():
            columns = table_columns(cursor, table_name)
            missing = [
                column for column in required_columns
                if column not in columns
            ]

            line = (
                f"{table_name}: actual_columns={len(columns)}, "
                f"expected_columns={len(required_columns)}, "
                f"missing={missing}"
            )
            print(line)
            report.append(line)

        print()
        print("-" * 76)
        print("5. SAMPLE CANDIDATE ROWS (NOT INSERTED)")
        print("-" * 76)
        report.extend(["", "SAMPLE CANDIDATE ROWS - NOT INSERTED"])

        for item in option_rows[:6]:
            line = (
                f"side={item['SourceSide']} "
                f"TSEInsCode={item['TSEInsCode']} "
                f"OptionID={item.get('DBOptionID')} "
                f"Last={item.get('LastPrice')} "
                f"Close={item.get('ClosingPrice')} "
                f"Buy={item.get('BestBuyPrice')} "
                f"Sell={item.get('BestSellPrice')} "
                f"Volume={item.get('Volume')} "
                f"OpenInterest={item.get('OpenInterest')}"
            )
            print(line)
            report.append(line)

        print()
        print("-" * 76)
        print("6. FIELDS REQUIRING SEMANTIC CONFIRMATION")
        print("-" * 76)

        warnings = [
            "OpenInterest <- oP: confirm API semantics before saving.",
            "TradeValue <- qTotCap: confirm unit and meaning.",
            "PriceChange and PriceChangePercent are not mapped yet.",
            "FirstPrice, MinPrice and MaxPrice are not mapped yet.",
            "Underlying fields must be explicitly identified from API keys.",
            "Zero values may reflect pre-open conditions; do not convert them "
            "to NULL automatically without a business rule.",
            "DataDate/DataTime and SourceRetrievedAt need a defined timestamp "
            "policy before any production write.",
        ]

        for warning in warnings:
            print(f"- {warning}")
            report.append(f"- {warning}")

        report_path = DATA_DIR / (
            "BR41_field_mapping_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".txt"
        )

        report_path.write_text(
            "\n".join(report) + "\n",
            encoding="utf-8-sig",
        )

        print()
        print("=" * 76)
        print("BR41 FINISHED")
        print("=" * 76)
        print("Database writes : NONE")
        print(f"Report          : {report_path}")

    finally:
        cursor.close()
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("=" * 76)
        print("BR41 FAILED")
        print("=" * 76)
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)
