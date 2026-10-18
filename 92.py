
# BR92 - Audit Market Snapshot History
# Read-only audit of CollectionRunID 2 and 3.
# No API requests. No database writes.

import sys
from pathlib import Path
from datetime import datetime
from collections import Counter

import pyodbc


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"

SQL_SERVER = "localhost"
SQL_DATABASE = "OptionMarketDB_V2"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

RUN_IDS = (2, 3)

SNAPSHOT_TABLES = (
    "OptionLiveSnapshot",
    "UnderlyingLiveSnapshot",
)

PRICE_FIELDS = (
    "LastPrice",
    "ClosingPrice",
    "YesterdayPrice",
    "BestBuyPrice",
    "BestSellPrice",
    "OpenInterest",
    "TradeCount",
    "Volume",
    "TradeValue",
)


def connect_read_only():
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
        "ApplicationIntent=ReadOnly;"
    )
    return pyodbc.connect(connection_string, timeout=15)


def get_columns(cursor, table_name):
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        table_name,
    )
    return [row[0] for row in cursor.fetchall()]


def fetch_rows(cursor, table_name, columns, run_ids):
    lower_columns = {c.lower(): c for c in columns}
    run_column = lower_columns.get("collectionrunid")

    if not run_column:
        print(f"WARNING: {table_name} has no CollectionRunID column.")
        return [], None

    placeholders = ",".join("?" for _ in run_ids)
    cursor.execute(
        f"SELECT * FROM dbo.[{table_name}] "
        f"WHERE [{run_column}] IN ({placeholders})",
        *run_ids,
    )

    names = [item[0] for item in cursor.description]
    rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    return rows, run_column


def normalize(value):
    if value is None:
        return None
    return value


def fmt(value):
    if value is None:
        return "NULL"
    return str(value)


def inspect_run_table(cursor):
    print("\n" + "=" * 78)
    print("COLLECTION RUN DETAILS")
    print("=" * 78)

    columns = get_columns(cursor, "CollectionRun")

    if not columns:
        print("CollectionRun table not found.")
        return

    lower_columns = {c.lower(): c for c in columns}
    run_column = lower_columns.get("collectionrunid")

    if not run_column:
        print("CollectionRunID column not found.")
        return

    cursor.execute(
        f"SELECT * FROM dbo.[CollectionRun] "
        f"WHERE [{run_column}] IN (?, ?) "
        f"ORDER BY [{run_column}]",
        *RUN_IDS,
    )

    names = [item[0] for item in cursor.description]
    rows = [dict(zip(names, row)) for row in cursor.fetchall()]

    if not rows:
        print("No CollectionRun records found for requested IDs.")
        return

    preferred = (
        "CollectionRunID",
        "StartedAt",
        "CompletedAt",
        "Status",
        "RunStatus",
        "IsSuccess",
        "ErrorMessage",
    )

    for row in rows:
        print(f"\nRun {row.get(run_column)}:")
        printed = set()

        for wanted in preferred:
            actual = lower_columns.get(wanted.lower())
            if actual and actual in row:
                print(f"  {actual}: {fmt(row[actual])}")
                printed.add(actual)

        # Include other useful metadata without dumping every column.
        for key, value in row.items():
            if key not in printed and key.lower() not in (
                "collectionrunid",
                "startedat",
                "completedat",
                "status",
                "runstatus",
                "issuccess",
                "errormessage",
            ):
                if value is not None:
                    print(f"  {key}: {fmt(value)}")


def audit_snapshot_table(cursor, table_name):
    print("\n" + "=" * 78)
    print(f"HISTORY AUDIT: {table_name}")
    print("=" * 78)

    columns = get_columns(cursor, table_name)

    if not columns:
        print(f"ERROR: table dbo.{table_name} not found.")
        return

    lower_columns = {c.lower(): c for c in columns}
    rows, run_column = fetch_rows(
        cursor, table_name, columns, RUN_IDS
    )

    if run_column is None:
        return

    print(f"Columns: {', '.join(columns)}")
    print(f"Total rows for runs {RUN_IDS}: {len(rows)}")

    rows_by_run = {
        run_id: [
            row for row in rows
            if row.get(run_column) == run_id
        ]
        for run_id in RUN_IDS
    }

    for run_id in RUN_IDS:
        run_rows = rows_by_run[run_id]
        print(f"\nRun {run_id}:")
        print(f"  Row count: {len(run_rows)}")

        # Report distinct identifiers and duplicates.
        identifier_name = (
            lower_columns.get("optionid")
            if table_name == "OptionLiveSnapshot"
            else lower_columns.get("underlyingid")
        )

        if identifier_name is None:
            identifier_name = lower_columns.get("inscode")

        if identifier_name:
            identifiers = [
                row.get(identifier_name)
                for row in run_rows
                if row.get(identifier_name) is not None
            ]
            counts = Counter(identifiers)

            print(f"  Identifier field: {identifier_name}")
            print(f"  Distinct identifiers: {len(counts)}")
            print(
                "  Duplicate identifiers: "
                f"{sum(1 for n in counts.values() if n > 1)}"
            )
        else:
            print("  No recognized identifier column.")

        # Timestamp coverage, if present.
        for timestamp_name in (
            "SourceRetrievedAt",
            "CapturedAt",
            "SnapshotAt",
            "CreatedAt",
            "DataDate",
            "DataTime",
        ):
            actual = lower_columns.get(timestamp_name.lower())
            if actual:
                values = [
                    row.get(actual)
                    for row in run_rows
                    if row.get(actual) is not None
                ]
                print(
                    f"  {actual} non-NULL: {len(values)}/{len(run_rows)}"
                )
                if values:
                    print(
                        f"  {actual} range: "
                        f"{min(values)} -> {max(values)}"
                    )

    # Compare runs only when a stable identifier is available.
    identifier_name = (
        lower_columns.get("optionid")
        if table_name == "OptionLiveSnapshot"
        else lower_columns.get("underlyingid")
    )
    if identifier_name is None:
        identifier_name = lower_columns.get("inscode")

    if not identifier_name:
        print("\nComparison skipped: no stable identifier column.")
        return

    def make_map(run_rows):
        result = {}
        duplicate_ids = set()

        for row in run_rows:
            identifier = row.get(identifier_name)
            if identifier is None:
                continue

            if identifier in result:
                duplicate_ids.add(identifier)

            # Keep the last returned row for display only.
            result[identifier] = row

        return result, duplicate_ids

    map2, duplicates2 = make_map(rows_by_run[RUN_IDS[0]])
    map3, duplicates3 = make_map(rows_by_run[RUN_IDS[1]])

    ids2 = set(map2)
    ids3 = set(map3)
    common_ids = ids2 & ids3

    print("\n" + "-" * 78)
    print(f"COMPARISON: Run {RUN_IDS[0]} vs Run {RUN_IDS[1]}")
    print("-" * 78)
    print(f"Run {RUN_IDS[0]} unique IDs: {len(ids2)}")
    print(f"Run {RUN_IDS[1]} unique IDs: {len(ids3)}")
    print(f"IDs in both runs: {len(common_ids)}")
    print(f"Only in run {RUN_IDS[0]}: {len(ids2 - ids3)}")
    print(f"Only in run {RUN_IDS[1]}: {len(ids3 - ids2)}")

    if duplicates2 or duplicates3:
        print(
            "WARNING: duplicate identifiers detected; "
            "price comparison may be ambiguous."
        )
        print(f"  Duplicate IDs in run {RUN_IDS[0]}: {len(duplicates2)}")
        print(f"  Duplicate IDs in run {RUN_IDS[1]}: {len(duplicates3)}")

    available_price_fields = [
        lower_columns.get(field.lower())
        for field in PRICE_FIELDS
        if lower_columns.get(field.lower())
    ]

    if not common_ids or not available_price_fields:
        print("Price comparison skipped: no common IDs or price fields.")
        return

    print("\nField changes across matched identifiers:")
    for field in available_price_fields:
        comparable = 0
        changed = 0
        null2 = 0
        null3 = 0
        examples = []

        for identifier in common_ids:
            old = normalize(map2[identifier].get(field))
            new = normalize(map3[identifier].get(field))

            if old is None:
                null2 += 1
            if new is None:
                null3 += 1

            if old is None or new is None:
                continue

            comparable += 1

            if old != new:
                changed += 1
                if len(examples) < 3:
                    examples.append((identifier, old, new))

        print(
            f"  {field}: changed={changed}/{comparable}, "
            f"NULL run {RUN_IDS[0]}={null2}, "
            f"NULL run {RUN_IDS[1]}={null3}"
        )

        for identifier, old, new in examples:
            print(f"    ID {identifier}: {old} -> {new}")


def main():
    print("=" * 78)
    print("BR92 - Audit Market Snapshot History")
    print("=" * 78)
    print(f"Database: {SQL_DATABASE}")
    print(f"Runs: {RUN_IDS}")
    print("Read only: YES")
    print("API request: NO")
    print("Database writes: NO")

    connection = None

    try:
        connection = connect_read_only()
        cursor = connection.cursor()

        inspect_run_table(cursor)

        for table_name in SNAPSHOT_TABLES:
            audit_snapshot_table(cursor, table_name)

        print("\n" + "=" * 78)
        print("BR92 COMPLETED")
        print("No database changes were made.")
        print("=" * 78)

    except Exception as exc:
        print(
            f"\nBR92 FAILED: {type(exc).__name__}: {exc}"
        )
        sys.exit(1)

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
