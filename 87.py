
# BR87 - Read-only audit of BR36 live capture
# Database: OptionMarketDB_V2
# No INSERT / UPDATE / DELETE

import pyodbc
from datetime import datetime

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"
COLLECTION_RUN_ID = 2

TABLES = [
    "CollectionRun",
    "RawApiResponse",
    "UnderlyingLiveSnapshot",
    "OptionLiveSnapshot",
    "UnderlyingLiveCurrent",
    "OptionLiveCurrent",
]


def print_section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main():
    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
    )

    print_section("BR87 - READ-ONLY LIVE CAPTURE AUDIT")
    print(f"Database: {DATABASE}")
    print(f"CollectionRunID: {COLLECTION_RUN_ID}")
    print("Mode: READ ONLY")

    connection = pyodbc.connect(connection_string, timeout=15)
    connection.autocommit = True

    try:
        cursor = connection.cursor()

        # Confirm database and SQL Server connection.
        cursor.execute(
            "SELECT DB_NAME(), @@SERVERNAME, SYSDATETIME()"
        )
        db_name, server_name, sql_time = cursor.fetchone()

        print_section("A. CONNECTION")
        print(f"Database returned by SQL Server: {db_name}")
        print(f"SQL Server name: {server_name}")
        print(f"SQL Server local time: {sql_time}")

        # Discover tables and their columns without assuming all schemas.
        cursor.execute("""
            SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME,
                   DATA_TYPE, ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME IN (
                'CollectionRun',
                'RawApiResponse',
                'UnderlyingLiveSnapshot',
                'OptionLiveSnapshot',
                'UnderlyingLiveCurrent',
                'OptionLiveCurrent'
            )
            ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
        """)

        metadata = cursor.fetchall()
        columns_by_table = {}

        for schema, table, column, data_type, ordinal in metadata:
            key = (schema, table)
            columns_by_table.setdefault(key, []).append(
                (column, data_type)
            )

        print_section("B. TABLE STRUCTURE AND ROW COUNTS")

        for schema, table in sorted(columns_by_table):
            qualified = f"[{schema}].[{table}]"
            cursor.execute(f"SELECT COUNT_BIG(*) FROM {qualified}")
            total = cursor.fetchone()[0]

            print(f"\n{qualified}: total rows = {total}")
            print("Columns:", ", ".join(
                f"{name} ({dtype})"
                for name, dtype in columns_by_table[(schema, table)]
            ))

            column_names = {
                name for name, _ in columns_by_table[(schema, table)]
            }

            # Where available, count rows belonging to this capture.
            if "CollectionRunID" in column_names:
                cursor.execute(
                    f"SELECT COUNT_BIG(*) FROM {qualified} "
                    "WHERE [CollectionRunID] = ?",
                    COLLECTION_RUN_ID,
                )
                run_count = cursor.fetchone()[0]
                print(
                    f"Rows with CollectionRunID={COLLECTION_RUN_ID}: "
                    f"{run_count}"
                )

        print_section("C. COLLECTION RUN RECORD")

        run_table = next(
            (
                (schema, table)
                for schema, table in columns_by_table
                if table == "CollectionRun"
            ),
            None,
        )

        if not run_table:
            print("ERROR: CollectionRun table was not found.")
        else:
            schema, table = run_table
            run_columns = [
                name for name, _ in columns_by_table[(schema, table)]
            ]

            if "CollectionRunID" not in run_columns:
                print("ERROR: CollectionRunID column was not found.")
            else:
                selected_columns = ", ".join(
                    f"[{name}]" for name in run_columns
                )
                cursor.execute(
                    f"SELECT {selected_columns} "
                    f"FROM [{schema}].[{table}] "
                    "WHERE [CollectionRunID] = ?",
                    COLLECTION_RUN_ID,
                )
                rows = cursor.fetchall()

                if not rows:
                    print(
                        f"ERROR: CollectionRunID={COLLECTION_RUN_ID} "
                        "was not found."
                    )
                else:
                    for row in rows:
                        for name, value in zip(run_columns, row):
                            print(f"{name}: {value}")

        print_section("D. EXPECTED CAPTURE CHECKS")
        print("Expected for the reported BR36 execution:")
        print("- OptionLiveSnapshot: 84 new snapshot rows")
        print("- UnderlyingLiveSnapshot: 1 new snapshot row")
        print("- OptionLiveCurrent: 84 current contract rows")
        print("- UnderlyingLiveCurrent: 1 current underlying row")
        print("- RawApiResponse: 1 raw response row")
        print("- CollectionRun: run ID 2 with successful status")
        print()
        print(
            "NOTE: table totals are not necessarily rows from this run. "
            "Use the CollectionRunID-specific counts above when that "
            "column exists. Current tables may be upserted."
        )

        print_section("BR87 FINISHED")
        print("No database data was modified.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
