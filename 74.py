
# BR74 - Correct Trade Metrics Mapping Audit
# Read-only: no database writes, no schema changes, legacy DB untouched.

import json
import os
import sys
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import pyodbc


PROJECT_DIR = r"E:\PythonProject\OptionMonitor_V2"
DB_NAME = "OptionMarketDB_V2"
SOURCE_FILE = os.path.join(
    PROJECT_DIR,
    "data",
    "api_tests",
    "BR44_live_response_20261015_070837.json",
)

SERVER = "localhost"
DRIVER = "{ODBC Driver 17 for SQL Server}"

# Direct comparisons requested in BR74.
COMPARISONS = [
    ("TradeCount", "zTotTran"),
    ("TradeCount", "qTotTran5J"),
    ("Volume", "zTotTran"),
    ("Volume", "qTotTran5J"),
    ("TradeValue", "qTotCap"),
    ("TradeValue", "notionalValue"),
]


def heading(text):
    print("\n" + "=" * 110)
    print(text)
    print("=" * 110)


def to_decimal(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value:
                return None

        result = Decimal(str(value))

        if not result.is_finite():
            return None

        return result

    except (InvalidOperation, ValueError, TypeError):
        return None


def values_equal(a, b):
    da = to_decimal(a)
    db = to_decimal(b)

    if da is None or db is None:
        return False

    return da == db


def format_value(value):
    if value is None:
        return "NULL"

    return str(value)


def load_source():
    if not os.path.isfile(SOURCE_FILE):
        raise FileNotFoundError(
            f"BR44 source file not found: {SOURCE_FILE}"
        )

    with open(SOURCE_FILE, "r", encoding="utf-8-sig") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        rows = payload.get("instrumentOptMarketWatch")

        if rows is None:
            raise ValueError(
                "JSON root does not contain instrumentOptMarketWatch."
            )
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("Unsupported JSON root type.")

    if not isinstance(rows, list):
        raise ValueError("instrumentOptMarketWatch is not a list.")

    return rows


def connect_db():
    connection_string = (
        f"DRIVER={DRIVER};"
        f"SERVER={SERVER};"
        f"DATABASE={DB_NAME};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(
        connection_string,
        timeout=15,
        autocommit=True,
    )


def get_columns(cursor, table_name):
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


def resolve_column(columns, candidates, table_name, required=True):
    for candidate in candidates:
        if candidate in columns:
            return candidate

    if required:
        raise RuntimeError(
            f"Could not resolve required column in dbo.{table_name}. "
            f"Tried: {candidates}. Available: {sorted(columns)}"
        )

    return None


def load_db_contracts(cursor):
    contract_columns = get_columns(cursor, "OptionContract")
    live_columns = get_columns(cursor, "OptionLiveCurrent")

    contract_id_col = resolve_column(
        contract_columns,
        ["OptionID"],
        "OptionContract",
    )



    contract_code_col = resolve_column(
        contract_columns,
        ["TSEInsCode", "InsCode", "InstrumentCode", "ContractInsCode"],
        "OptionContract",
    )
    live_id_col = resolve_column(
        live_columns,
        ["OptionID"],
        "OptionLiveCurrent",
    )

    metric_columns = {}

    for metric in ["TradeCount", "Volume", "TradeValue"]:
        metric_columns[metric] = resolve_column(
            live_columns,
            [metric],
            "OptionLiveCurrent",
            required=False,
        )

    selected_metrics = [
        f"L.[{column}] AS [{metric}]"
        for metric, column in metric_columns.items()
        if column is not None
    ]

    sql = f"""
        SELECT
            C.[{contract_id_col}] AS OptionID,
            C.[{contract_code_col}] AS InsCode
            {"," if selected_metrics else ""}
            {", ".join(selected_metrics)}
        FROM dbo.OptionContract AS C
        LEFT JOIN dbo.OptionLiveCurrent AS L
          ON L.[{live_id_col}] = C.[{contract_id_col}]
    """

    cursor.execute(sql)

    results = {}

    for row in cursor.fetchall():
        item = {
            "OptionID": row.OptionID,
            "InsCode": str(row.InsCode).strip(),
        }

        for metric in ["TradeCount", "Volume", "TradeValue"]:
            if metric_columns[metric] is not None:
                item[metric] = getattr(row, metric)
            else:
                item[metric] = None

        code = item["InsCode"]

        if code in results:
            raise RuntimeError(
                f"Duplicate InsCode in OptionContract: {code}"
            )

        results[code] = item

    return results, metric_columns


def build_api_map(rows):
    api_map = {}
    source_counts = {
        "rows": len(rows),
        "underlying_rows": 0,
        "matched_side_records": 0,
        "missing_side_codes": 0,
        "duplicate_side_codes": 0,
    }

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        for side in ("C", "P"):
            code = row.get(f"insCode_{side}")

            if code is None or str(code).strip() == "":
                continue

            code = str(code).strip()
            source_counts["matched_side_records"] += 1

            if code in api_map:
                source_counts["duplicate_side_codes"] += 1
                continue

            api_map[code] = {
                "side": side,
                "source_row_index": index,
                "zTotTran": row.get(f"zTotTran_{side}"),
                "qTotTran5J": row.get(f"qTotTran5J_{side}"),
                "qTotCap": row.get(f"qTotCap_{side}"),
                "notionalValue": row.get(f"notionalValue_{side}"),
            }

        # Underlying rows are repeated within option-market records;
        # this audit does not use them for option contract comparisons.

    return api_map, source_counts


def main():
    started = datetime.now(timezone.utc)

    heading("BR74 - TRADE METRICS MAPPING AUDIT")

    print(f"Started UTC    : {started.isoformat()}")
    print(f"Project        : {PROJECT_DIR}")
    print(f"Database       : {DB_NAME}")
    print("Mode           : READ ONLY")
    print("Writes         : NONE")
    print("Schema changes : NONE")
    print("Legacy DB      : NOT ACCESSED")

    rows = load_source()

    print(f"\nSource file    : {SOURCE_FILE}")
    print(f"JSON rows      : {len(rows)}")
    print(
        "File modified  : "
        + datetime.fromtimestamp(
            os.path.getmtime(SOURCE_FILE),
            tz=timezone.utc,
        ).isoformat()
    )

    api_map, source_counts = build_api_map(rows)

    print(f"API side codes : {len(api_map)}")
    print(
        "Side records   : "
        f"{source_counts['matched_side_records']}"
    )
    print(
        "Duplicate codes: "
        f"{source_counts['duplicate_side_codes']}"
    )

    connection = None

    try:
        connection = connect_db()
        cursor = connection.cursor()

        db_contracts, metric_columns = load_db_contracts(cursor)

        print(f"\nDB contracts   : {len(db_contracts)}")
        print(f"Unique DB codes: {len(db_contracts)}")
        print(f"DB metrics     : {metric_columns}")

        db_codes = set(db_contracts)
        api_codes = set(api_map)

        print(f"Codes in both  : {len(db_codes & api_codes)}")
        print(f"Missing in API : {len(db_codes - api_codes)}")
        print(f"Missing in DB  : {len(api_codes - db_codes)}")

        heading("1. FIELD-BY-FIELD EXACT COMPARISONS")

        summary = []

        for db_field, api_field in COMPARISONS:
            if metric_columns.get(db_field) is None:
                print(
                    f"\n{db_field} vs {api_field}: "
                    "SKIPPED - DB column not found."
                )
                continue

            compared = 0
            matches = 0
            missing_api = 0
            missing_db = 0
            examples = []

            api_values = []
            db_values = []

            for code in sorted(db_codes & api_codes):
                db_item = db_contracts[code]
                api_item = api_map[code]

                db_value = db_item.get(db_field)
                api_value = api_item.get(api_field)

                if db_value is None:
                    missing_db += 1
                    continue

                if api_value is None:
                    missing_api += 1
                    continue

                compared += 1
                db_values.append(to_decimal(db_value))
                api_values.append(to_decimal(api_value))

                if values_equal(db_value, api_value):
                    matches += 1
                elif len(examples) < 3:
                    examples.append(
                        (
                            code,
                            db_item["OptionID"],
                            api_item["side"],
                            db_value,
                            api_value,
                        )
                    )

            rate = (matches / compared * 100) if compared else 0.0

            print(f"\nDB field       : {db_field}")
            print(f"API field      : {api_field}_C/P")
            print(f"Compared       : {compared}")
            print(f"Exact matches  : {matches}")
            print(f"Match rate     : {rate:.2f}%")
            print(f"Missing API    : {missing_api}")
            print(f"Missing DB     : {missing_db}")

            if examples:
                print("Mismatch samples:")
                for code, option_id, side, db_value, api_value in examples:
                    print(
                        f"  InsCode={code} | OptionID={option_id} "
                        f"| Side={side} | DB={db_value} "
                        f"| API={api_value}"
                    )

            summary.append(
                {
                    "db_field": db_field,
                    "api_field": api_field,
                    "compared": compared,
                    "matches": matches,
                    "rate": rate,
                }
            )

        heading("2. BEST API CANDIDATE PER DATABASE FIELD")

        for db_field in ["TradeCount", "Volume", "TradeValue"]:
            candidates = [
                item for item in summary
                if item["db_field"] == db_field
                and item["compared"] > 0
            ]

            candidates.sort(
                key=lambda item: (
                    item["rate"],
                    item["matches"],
                    item["compared"],
                ),
                reverse=True,
            )

            print(f"\n{db_field}:")

            if not candidates:
                print("  No usable candidate comparisons.")
                continue

            for item in candidates:
                print(
                    f"  {item['api_field']:<15} "
                    f"{item['matches']:>3}/{item['compared']:<3} "
                    f"({item['rate']:.2f}%)"
                )

            best = candidates[0]

            if best["rate"] == 100.0:
                print(
                    f"  RESULT: exact match observed for "
                    f"{best['api_field']}_C/P."
                )
            else:
                print(
                    "  RESULT: no fully confirmed mapping; "
                    "do not change database mappings yet."
                )

        heading("3. SAFETY CHECK")

        print("SELECT queries only : YES")
        print("INSERT/UPDATE/DELETE : NONE")
        print("DDL statements       : NONE")
        print("Legacy DB accessed  : NO")

        heading("BR74 COMPLETED")

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nBR74 FAILED")
        print(f"Error: {type(exc).__name__}: {exc}")
        sys.exit(1)
