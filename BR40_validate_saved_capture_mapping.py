
# BR40 - Validate Saved Market Data Against Database Schema
# Read-only: no database writes.
# Old database OptionMarketDB must never be accessed.

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_CODE = "17914401175772326"
UNDERLYING_SYMBOL = "اهرم"

TARGET_TABLES = [
    "CollectionRun",
    "RawApiResponse",
    "OptionContract",
    "OptionLiveSnapshot",
    "UnderlyingLiveSnapshot",
    "OptionLiveCurrent",
    "UnderlyingLiveCurrent",
]


def normalize_id(value):
    """Normalize numeric/string instrument identifiers for comparison."""
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    return text


def find_market_records(obj):
    """Find the API list containing records with insCode_C / insCode_P."""
    candidates = []

    def walk(value, path="$"):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")

        elif isinstance(value, list):
            if value and all(isinstance(item, dict) for item in value):
                matching = sum(
                    1
                    for item in value
                    if any(
                        key in item
                        for key in (
                            "insCode_C",
                            "insCode_P",
                            "insCode_C ",
                            "insCode_P ",
                        )
                    )
                )

                if matching:
                    candidates.append((matching, len(value), path, value))

            for index, child in enumerate(value):
                if isinstance(child, (dict, list)):
                    walk(child, f"{path}[{index}]")

    walk(obj)

    if not candidates:
        raise ValueError(
            "Could not locate an API array containing insCode_C/insCode_P."
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0]


def get_latest_br37_json():
    files = sorted(
        DATA_DIR.glob("BR37_live_response_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not files:
        raise FileNotFoundError(
            f"No BR37_live_response_*.json file found in:\n{DATA_DIR}"
        )

    return files[0]


def quote_identifier(identifier):
    """Safely quote a SQL Server identifier."""
    return "[" + str(identifier).replace("]", "]]") + "]"


def get_table_metadata(cursor):
    cursor.execute(
        """
        SELECT
            TABLE_SCHEMA,
            TABLE_NAME,
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            ORDINAL_POSITION
        FROM INFORMATION_SCHEMA.COLUMNS
        ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
        """
    )

    metadata = {}
    for row in cursor.fetchall():
        schema, table, column, data_type, nullable, ordinal = row
        key = (schema, table)
        metadata.setdefault(key, []).append(
            {
                "column": column,
                "data_type": data_type,
                "nullable": nullable,
                "ordinal": ordinal,
            }
        )

    return metadata


def find_table(metadata, table_name):
    matches = [
        key for key in metadata
        if key[1].lower() == table_name.lower()
    ]

    if not matches:
        return None

    # Prefer dbo if more than one schema contains the same table name.
    matches.sort(key=lambda key: (key[0].lower() != "dbo", key[0].lower()))
    return matches[0]


def get_foreign_keys(cursor):
    cursor.execute(
        """
        SELECT
            fk.name AS FK_Name,
            SCHEMA_NAME(parent_table.schema_id) AS ParentSchema,
            parent_table.name AS ParentTable,
            parent_column.name AS ParentColumn,
            SCHEMA_NAME(ref_table.schema_id) AS ReferencedSchema,
            ref_table.name AS ReferencedTable,
            ref_column.name AS ReferencedColumn
        FROM sys.foreign_key_columns fkc
        JOIN sys.foreign_keys fk
            ON fk.object_id = fkc.constraint_object_id
        JOIN sys.tables parent_table
            ON parent_table.object_id = fkc.parent_object_id
        JOIN sys.columns parent_column
            ON parent_column.object_id = fkc.parent_object_id
           AND parent_column.column_id = fkc.parent_column_id
        JOIN sys.tables ref_table
            ON ref_table.object_id = fkc.referenced_object_id
        JOIN sys.columns ref_column
            ON ref_column.object_id = fkc.referenced_object_id
           AND ref_column.column_id = fkc.referenced_column_id
        ORDER BY ParentSchema, ParentTable, FK_Name
        """
    )

    return cursor.fetchall()


def find_contract_id_matches(cursor, metadata, source_ids):
    table_key = find_table(metadata, "OptionContract")

    if table_key is None:
        return None, [], "OptionContract table not found."

    schema, table = table_key
    sql = (
        f"SELECT * FROM {quote_identifier(schema)}."
        f"{quote_identifier(table)}"
    )

    cursor.execute(sql)
    column_names = [description[0] for description in cursor.description]
    rows = cursor.fetchall()

    source_set = set(source_ids)
    matches = []

    for index, column_name in enumerate(column_names):
        found_values = set()

        for row in rows:
            value = normalize_id(row[index])
            if value in source_set:
                found_values.add(value)

        if found_values:
            matches.append(
                {
                    "column": column_name,
                    "matched_count": len(found_values),
                    "missing_count": len(source_set - found_values),
                    "row_count": len(rows),
                }
            )

    return table_key, matches, f"Rows inspected: {len(rows)}"


def write_report(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")



def main():
    print("=" * 76)
    print("BR40 - Validate Saved Market Data Against Database Schema")
    print("=" * 76)
    print("Mode              : READ ONLY")
    print(f"Project           : {PROJECT_DIR}")
    print(f"Database          : {DATABASE}")
    print(f"Underlying        : {UNDERLYING_SYMBOL}")
    print(f"Underlying code   : {UNDERLYING_CODE}")
    print()

    source_path = get_latest_br37_json()
    print(f"Source file       : {source_path}")

    with source_path.open("r", encoding="utf-8-sig") as file:
        source_json = json.load(file)

    _, total_records, array_path, records = find_market_records(source_json)

    # IMPORTANT: only records belonging to the requested underlying.
    underlying_records = [
        record
        for record in records
        if normalize_id(record.get("uaInsCode")) == UNDERLYING_CODE
    ]

    source_ids = set()
    missing_side_ids = 0
    duplicate_side_ids = 0
    seen_ids = set()

    for record in underlying_records:
        for suffix in ("C", "P"):
            contract_id = normalize_id(record.get(f"insCode_{suffix}"))

            if not contract_id:
                missing_side_ids += 1
                continue

            if contract_id in seen_ids:
                duplicate_side_ids += 1

            seen_ids.add(contract_id)
            source_ids.add(contract_id)

    print(f"API array path       : {array_path}")
    print(f"Total API records    : {total_records}")
    print(f"Underlying records   : {len(underlying_records)}")
    print(f"Unique option IDs    : {len(source_ids)}")
    print(f"Missing side IDs     : {missing_side_ids}")
    print(f"Duplicate ID entries : {duplicate_side_ids}")
    print()

    if not underlying_records:
        raise RuntimeError(
            "No API records matched uaInsCode="
            f"{UNDERLYING_CODE}. Check the raw JSON field and value."
        )

    if len(source_ids) != 84:
        print(
            "WARNING: expected 84 option IDs for اهرم, "
            f"but found {len(source_ids)}."
        )

    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "Connection Timeout=15;"
    )

    # Read-only checks only.
    connection = pyodbc.connect(
        connection_string,
        autocommit=False
    )
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT DB_NAME()")
        actual_database = cursor.fetchone()[0]

        if actual_database != DATABASE:
            raise RuntimeError(
                f"Safety check failed: connected to {actual_database}, "
                f"not {DATABASE}."
            )

        print(f"Connected database : {actual_database}")
        print("Database writes    : DISABLED")
        print()

        metadata = get_table_metadata(cursor)
        foreign_keys = get_foreign_keys(cursor)

        report_lines = [
            "BR40 - Saved Data / Database Schema Validation",
            f"Run time: {datetime.now().isoformat(timespec='seconds')}",
            f"Source file: {source_path}",
            f"Connected database: {actual_database}",
            "Mode: READ ONLY",
            f"API array path: {array_path}",
            f"Total API records: {total_records}",
            f"Underlying records: {len(underlying_records)}",
            f"Unique option IDs: {len(source_ids)}",
            f"Missing side IDs: {missing_side_ids}",
            f"Duplicate ID entries: {duplicate_side_ids}",
            "",
            "TABLE INVENTORY",
        ]

        print("-" * 76)
        print("1. TABLE AND COLUMN INVENTORY")
        print("-" * 76)

        for table_name in TARGET_TABLES:
            table_key = find_table(metadata, table_name)

            if table_key is None:
                line = f"MISSING TABLE: {table_name}"
                print(line)
                report_lines.append(line)
                continue

            schema, actual_table = table_key
            columns = metadata[table_key]

            line = (
                f"\n[{schema}].[{actual_table}] "
                f"- {len(columns)} columns"
            )
            print(line)
            report_lines.append(line)

            for column in columns:
                line = (
                    f"  {column['column']} "
                    f"({column['data_type']}, "
                    f"nullable={column['nullable']})"
                )
                print(line)
                report_lines.append(line)

        print()
        print("-" * 76)
        print("2. OPTION CONTRACT ID MATCH")
        print("-" * 76)

        table_key, matches, status = find_contract_id_matches(
            cursor, metadata, source_ids
        )

        print(status)
        report_lines.extend(["", "OPTION CONTRACT ID MATCH", status])

        if table_key:
            print(f"Table: [{table_key[0]}].[{table_key[1]}]")
            report_lines.append(
                f"Table: [{table_key[0]}].[{table_key[1]}]"
            )

        if matches:
            for match in sorted(
                matches,
                key=lambda item: (
                    -item["matched_count"],
                    item["missing_count"],
                    item["column"],
                ),
            ):
                line = (
                    f"Column={match['column']} | "
                    f"Matched={match['matched_count']}/{len(source_ids)} | "
                    f"Missing={match['missing_count']} | "
                    f"DB rows={match['row_count']}"
                )
                print(line)
                report_lines.append(line)
        else:
            line = (
                "No database column values matched the source contract IDs."
            )
            print(line)
            report_lines.append(line)

        print()
        print("-" * 76)
        print("3. FOREIGN KEY INVENTORY")
        print("-" * 76)
        print(f"Foreign keys found: {len(foreign_keys)}")
        report_lines.extend(
            ["", "FOREIGN KEYS", f"Count: {len(foreign_keys)}"]
        )

        for fk in foreign_keys:
            line = (
                f"{fk.FK_Name}: "
                f"[{fk.ParentSchema}].[{fk.ParentTable}]."
                f"[{fk.ParentColumn}] -> "
                f"[{fk.ReferencedSchema}].[{fk.ReferencedTable}]."
                f"[{fk.ReferencedColumn}]"
            )
            print(line)
            report_lines.append(line)

        report_path = DATA_DIR / (
            "BR40_schema_mapping_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".txt"
        )

        write_report(report_path, report_lines)

        print()
        print("=" * 76)
        print("BR40 FINISHED")
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
        print("BR40 FAILED")
        print("=" * 76)
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)
