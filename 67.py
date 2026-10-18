
# BR67 - DATABASE HISTORY DISCOVERY
# READ ONLY - NO DATABASE WRITES

import pyodbc

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
)

KEYWORDS = (
    "time", "date", "snapshot", "history", "raw",
    "option", "market", "price", "quote", "volume",
    "retrieved", "created", "updated", "capture"
)


def main():
    print("=" * 100)
    print("BR67 - DATABASE HISTORY DISCOVERY")
    print("=" * 100)
    print(f"Server   : {SERVER}")
    print(f"Database : {DATABASE}")
    print("Mode     : READ ONLY")
    print("Writes   : NONE")

    conn = pyodbc.connect(CONNECTION_STRING, timeout=15)

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                TABLE_SCHEMA,
                TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """)

        tables = cur.fetchall()

        print(f"\nTABLE COUNT: {len(tables)}")
        print("-" * 100)

        for schema, table in tables:
            qualified = f"[{schema}].[{table}]"
            safe_name = f"[{schema.replace(']', ']]')}].[{table.replace(']', ']]')}]"

            try:
                cur.execute(f"SELECT COUNT_BIG(*) FROM {safe_name}")
                row_count = cur.fetchone()[0]
            except Exception as exc:
                row_count = f"COUNT ERROR: {exc}"

            print(f"\nTABLE: {qualified}")
            print(f"ROWS : {row_count}")

            cur.execute("""
                SELECT
                    COLUMN_NAME,
                    DATA_TYPE,
                    IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ?
                  AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """, schema, table)

            columns = cur.fetchall()

            for column, data_type, nullable in columns:
                searchable = (
                    f"{table} {column}"
                ).lower()

                if any(word in searchable for word in KEYWORDS):
                    print(
                        f"  * {column:<35} "
                        f"{data_type:<20} nullable={nullable}"
                    )

        print("\n" + "=" * 100)
        print("END OF DISCOVERY")
        print("No records inserted, updated, or deleted.")
        print("=" * 100)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
