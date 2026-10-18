
# BR93 - Inspect Snapshot Table Relationships
# Read-only schema inspection. No API requests or database writes.

import sys
import pyodbc

SQL_SERVER = "localhost"
SQL_DATABASE = "OptionMarketDB_V2"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

TABLES = [
    "CollectionRun",
    "RawApiResponse",
    "OptionLiveSnapshot",
    "UnderlyingLiveSnapshot",
    "OptionLiveCurrent",
    "UnderlyingLiveCurrent",
]


def main():
    connection = None

    print("=" * 78)
    print("BR93 - Inspect Snapshot Table Relationships")
    print("=" * 78)
    print(f"Database: {SQL_DATABASE}")
    print("Mode: READ ONLY")
    print("Database writes: NO")
    print()

    try:
        connection_string = (
            f"DRIVER={{{ODBC_DRIVER}}};"
            f"SERVER={SQL_SERVER};"
            f"DATABASE={SQL_DATABASE};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
            "ApplicationIntent=ReadOnly;"
        )

        connection = pyodbc.connect(connection_string, timeout=15)
        cursor = connection.cursor()

        # 1. Columns and data types
        print("=" * 78)
        print("1. TABLE COLUMNS")
        print("=" * 78)

        cursor.execute("""
            SELECT
                TABLE_NAME,
                ORDINAL_POSITION,
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo'
              AND TABLE_NAME IN (
                  'CollectionRun',
                  'RawApiResponse',
                  'OptionLiveSnapshot',
                  'UnderlyingLiveSnapshot',
                  'OptionLiveCurrent',
                  'UnderlyingLiveCurrent'
              )
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """)

        rows = cursor.fetchall()
        found_tables = set()

        for row in rows:
            table, position, column, data_type, length, nullable = row
            found_tables.add(table)
            length_text = f"({length})" if length is not None else ""
            print(
                f"{table}.{column:<28} "
                f"{data_type}{length_text:<15} "
                f"nullable={nullable}"
            )

        print("\nTables found:", ", ".join(sorted(found_tables)))

        # 2. Primary keys
        print("\n" + "=" * 78)
        print("2. PRIMARY KEYS")
        print("=" * 78)

        cursor.execute("""
            SELECT
                tc.TABLE_NAME,
                tc.CONSTRAINT_NAME,
                kcu.COLUMN_NAME,
                kcu.ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
              ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
             AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
             AND tc.TABLE_NAME = kcu.TABLE_NAME
            WHERE tc.TABLE_SCHEMA = 'dbo'
              AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
              AND tc.TABLE_NAME IN (
                  'CollectionRun',
                  'RawApiResponse',
                  'OptionLiveSnapshot',
                  'UnderlyingLiveSnapshot',
                  'OptionLiveCurrent',
                  'UnderlyingLiveCurrent'
              )
            ORDER BY tc.TABLE_NAME, kcu.ORDINAL_POSITION
        """)

        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(
                    f"{row.TABLE_NAME}: {row.CONSTRAINT_NAME} -> "
                    f"{row.COLUMN_NAME} (position {row.ORDINAL_POSITION})"
                )
        else:
            print("No primary keys found for the selected tables.")

        # 3. Foreign keys
        print("\n" + "=" * 78)
        print("3. FOREIGN KEYS")
        print("=" * 78)


        cursor.execute("""
            SELECT
                fk.name AS ForeignKeyName,
                OBJECT_NAME(fk.parent_object_id) AS SourceTable,
                pc.name AS SourceColumn,
                OBJECT_NAME(fk.referenced_object_id) AS TargetTable,
                rc.name AS TargetColumn
            FROM sys.foreign_keys AS fk
            JOIN sys.foreign_key_columns AS fkc
              ON fk.object_id = fkc.constraint_object_id
            JOIN sys.tables AS pt
              ON pt.object_id = fk.parent_object_id
            JOIN sys.schemas AS ps
              ON ps.schema_id = pt.schema_id
            JOIN sys.columns AS pc
              ON pc.object_id = fkc.parent_object_id
             AND pc.column_id = fkc.parent_column_id
            JOIN sys.columns AS rc
              ON rc.object_id = fkc.referenced_object_id
             AND rc.column_id = fkc.referenced_column_id
            WHERE ps.name = 'dbo'
              AND (
                  OBJECT_NAME(fk.parent_object_id) IN (
                      'CollectionRun',
                      'RawApiResponse',
                      'OptionLiveSnapshot',
                      'UnderlyingLiveSnapshot',
                      'OptionLiveCurrent',
                      'UnderlyingLiveCurrent'
                  )
                  OR OBJECT_NAME(fk.referenced_object_id) IN (
                      'CollectionRun',
                      'RawApiResponse',
                      'OptionLiveSnapshot',
                      'UnderlyingLiveSnapshot',
                      'OptionLiveCurrent',
                      'UnderlyingLiveCurrent'
                  )
              )
            ORDER BY SourceTable, ForeignKeyName
        """)


        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(
                    f"{row.SourceTable}.{row.SourceColumn} -> "
                    f"{row.TargetTable}.{row.TargetColumn} "
                    f"[{row.ForeignKeyName}]"
                )
        else:
            print("No foreign keys found among the selected tables.")

        # 4. Indexes
        print("\n" + "=" * 78)
        print("4. INDEXES")
        print("=" * 78)

        cursor.execute("""
            SELECT
                t.name AS TableName,
                i.name AS IndexName,
                i.is_primary_key,
                i.is_unique,
                i.type_desc,
                c.name AS ColumnName,
                ic.key_ordinal,
                ic.is_included_column
            FROM sys.indexes i
            JOIN sys.tables t
              ON t.object_id = i.object_id
            JOIN sys.schemas s
              ON s.schema_id = t.schema_id
            JOIN sys.index_columns ic
              ON ic.object_id = i.object_id
             AND ic.index_id = i.index_id
            JOIN sys.columns c
              ON c.object_id = ic.object_id
             AND c.column_id = ic.column_id
            WHERE s.name = 'dbo'
              AND t.name IN (
                  'CollectionRun',
                  'RawApiResponse',
                  'OptionLiveSnapshot',
                  'UnderlyingLiveSnapshot',
                  'OptionLiveCurrent',
                  'UnderlyingLiveCurrent'
              )
              AND i.name IS NOT NULL
            ORDER BY t.name, i.name, ic.key_ordinal, ic.index_column_id
        """)

        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(
                    f"{row.TableName}.{row.IndexName}: "
                    f"{row.ColumnName}, key_order={row.key_ordinal}, "
                    f"included={row.is_included_column}, "
                    f"unique={row.is_unique}, type={row.type_desc}"
                )
        else:
            print("No indexes found for the selected tables.")

        # 5. Snapshot counts and timestamp/ID samples
        print("\n" + "=" * 78)
        print("5. SNAPSHOT COUNTS AND SAMPLE VALUES")
        print("=" * 78)

        for table in (
            "CollectionRun",
            "RawApiResponse",
            "OptionLiveSnapshot",
            "UnderlyingLiveSnapshot",
            "OptionLiveCurrent",
            "UnderlyingLiveCurrent",
        ):
            if table not in found_tables:
                print(f"\n{table}: TABLE NOT FOUND")
                continue

            # Table names are from the fixed allowlist above.
            cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{table}]")
            count = cursor.fetchone()[0]
            print(f"\n{table}: total rows = {count}")

            cursor.execute("""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = 'dbo'
                  AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """, table)

            column_names = [r[0] for r in cursor.fetchall()]
            lower_names = {name.lower(): name for name in column_names}

            interesting = [
                lower_names[name]
                for name in (
                    "collectionrunid",
                    "rawdataid",
                    "optionid",
                    "underlyingid",
                    "inscode",
                    "sourceretrievedat",
                    "capturedat",
                    "snapshotat",
                    "createdat",
                    "startedat",
                    "retrievedat",
                )
                if name in lower_names
            ]

            if interesting:
                selection = ", ".join(f"[{c}]" for c in interesting)
                cursor.execute(
                    f"SELECT TOP (5) {selection} "
                    f"FROM dbo.[{table}]"
                )

                print("  Sample columns:", ", ".join(interesting))
                for sample in cursor.fetchall():
                    print("  ", tuple(sample))
            else:
                print("  No recognized ID/timestamp columns to sample.")

        print("\n" + "=" * 78)
        print("BR93 COMPLETED")
        print("No database changes were made.")
        print("=" * 78)

    except Exception as exc:
        print(f"\nBR93 FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
