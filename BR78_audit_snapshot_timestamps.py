
# BR78 - Snapshot Timestamp & Trading Date Audit
# READ ONLY: no INSERT / UPDATE / DELETE / DDL
# Database: OptionMarketDB_V2 only

import pyodbc

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "{ODBC Driver 17 for SQL Server}"

TABLES = [
    "CollectionRun",
    "RawApiResponse",
    "OptionLiveSnapshot",
    "UnderlyingLiveSnapshot",
    "OptionLiveCurrent",
    "UnderlyingLiveCurrent",
]

TIME_HINTS = (
    "date", "time", "retriev", "capture", "snapshot",
    "created", "updated", "timestamp", "collect", "runid",
)

def qname(schema, table):
    return f"[{schema}].[{table}]"

def main():
    print("=" * 72)
    print("BR78 - SNAPSHOT TIMESTAMP & TRADING DATE AUDIT (READ ONLY)")
    print(f"Server: {SERVER}")
    print(f"Database: {DATABASE}")
    print("Database writes: NONE")
    print("=" * 72)

    conn_str = (
        f"DRIVER={DRIVER};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )

    conn = pyodbc.connect(conn_str, timeout=15)
    conn.autocommit = True

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME IN (
                'CollectionRun', 'RawApiResponse',
                'OptionLiveSnapshot', 'UnderlyingLiveSnapshot',
                'OptionLiveCurrent', 'UnderlyingLiveCurrent'
            )
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """)

        schema = {}
        for row in cur.fetchall():
            schema.setdefault((row.TABLE_SCHEMA, row.TABLE_NAME), []).append(
                (row.COLUMN_NAME, row.DATA_TYPE)
            )

        for table in TABLES:
            matches = [
                (key, cols) for key, cols in schema.items()
                if key[1].lower() == table.lower()
            ]

            print(f"\n--- {table} ---")
            if not matches:
                print("Table not found.")
                continue

            for (sch, tbl), columns in matches:
                col_names = [c[0] for c in columns]
                time_cols = [
                    (name, typ) for name, typ in columns
                    if any(h in name.lower() for h in TIME_HINTS)
                ]

                full_table = qname(sch, tbl)
                cur.execute(f"SELECT COUNT_BIG(*) FROM {full_table}")
                print(f"Rows: {cur.fetchone()[0]}")

                if not time_cols:
                    print("Relevant timestamp/date columns: none detected.")
                    continue

                print("Timestamp/date fields:")
                for col, typ in time_cols:
                    print(f"  {col} ({typ})")

                    # Aggregate only SQL date/time-compatible fields.
                    if typ.lower() not in (
                        "date", "datetime", "datetime2", "smalldatetime",
                        "datetimeoffset", "time"
                    ):
                        continue

                    safe_col = "[" + col.replace("]", "]]") + "]"
                    cur.execute(f"""
                        SELECT MIN({safe_col}), MAX({safe_col}),
                               COUNT_BIG({safe_col})
                        FROM {full_table}
                    """)
                    min_v, max_v, populated = cur.fetchone()
                    print(
                        f"    populated={populated}; "
                        f"min={min_v}; max={max_v}"
                    )

        print("\n" + "=" * 72)
        print("BR78 RESULT: COMPLETED")
        print("No database changes were made.")
        print("=" * 72)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
