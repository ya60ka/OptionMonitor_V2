
# BR69 - HISTORY STORAGE READINESS AUDIT
# Database: OptionMarketDB_V2
# Mode: READ ONLY
# Writes: NONE

import pyodbc

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

CONN_STR = (
    f"DRIVER={{{DRIVER}}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def section(title):
    print("\n" + "=" * 110)
    print(title)
    print("=" * 110)


def show_rows(cursor, sql, params=()):
    cursor.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()

    if not rows:
        print("(no records)")
        return

    for row in rows:
        print(" | ".join(
            f"{name}={value}"
            for name, value in zip(columns, row)
        ))


def main():
    section("BR69 - HISTORY STORAGE READINESS AUDIT")
    print(f"Server   : {SERVER}")
    print(f"Database : {DATABASE}")
    print("Mode     : READ ONLY")
    print("Writes   : NONE")

    with pyodbc.connect(CONN_STR, autocommit=True) as conn:
        cur = conn.cursor()

        # 1. Snapshot/current/history table row counts
        section("1. TABLE COUNTS")

        show_rows(cur, """
                   SELECT
                       s.name AS SchemaName,
                       t.name AS TableName,
                       SUM(p.rows) AS [TotalRows]
                   FROM sys.tables t
                   JOIN sys.schemas s
                       ON s.schema_id = t.schema_id
                   LEFT JOIN sys.partitions p
                       ON p.object_id = t.object_id
                      AND p.index_id IN (0, 1)
                   WHERE s.name = 'dbo'
                   GROUP BY s.name, t.name
                   ORDER BY t.name
               """)

        # 2. Relevant table columns and identity settings
        section("2. SNAPSHOT AND HISTORY COLUMN DEFINITIONS")

        relevant_tables = (
            "OptionLiveSnapshot",
            "OptionLiveCurrent",
            "OptionDailyHistory",
            "UnderlyingLiveSnapshot",
            "UnderlyingLiveCurrent",
            "UnderlyingDailyHistory",
            "RawApiResponse",
            "CollectionRun",
        )

        placeholders = ",".join("?" for _ in relevant_tables)

        show_rows(cur, f"""
            SELECT
                t.name AS TableName,
                c.column_id AS ColumnOrder,
                c.name AS ColumnName,
                ty.name AS DataType,
                c.max_length AS MaxLengthBytes,
                c.precision AS NumericPrecision,
                c.scale AS NumericScale,
                c.is_nullable AS IsNullable,
                c.is_identity AS IsIdentity
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            JOIN sys.columns c ON c.object_id = t.object_id
            JOIN sys.types ty ON ty.user_type_id = c.user_type_id
            WHERE s.name = 'dbo'
              AND t.name IN ({placeholders})
            ORDER BY t.name, c.column_id
        """, relevant_tables)

        # 3. Primary keys, unique constraints and foreign keys
        section("3. KEY AND RELATIONSHIP CONSTRAINTS")

        show_rows(cur, """
            SELECT
                t.name AS TableName,
                kc.name AS ConstraintName,
                kc.type_desc AS ConstraintType,
                c.name AS ColumnName,
                ic.key_ordinal AS KeyOrdinal
            FROM sys.key_constraints kc
            JOIN sys.tables t
                ON t.object_id = kc.parent_object_id
            JOIN sys.schemas s
                ON s.schema_id = t.schema_id
            JOIN sys.index_columns ic
                ON ic.object_id = t.object_id
               AND ic.index_id = kc.unique_index_id
            JOIN sys.columns c
                ON c.object_id = t.object_id
               AND c.column_id = ic.column_id
            WHERE s.name = 'dbo'
            ORDER BY t.name, kc.name, ic.key_ordinal
        """)

        print("\nFOREIGN KEYS:")

        show_rows(cur, """
            SELECT
                fk.name AS ForeignKeyName,
                OBJECT_SCHEMA_NAME(fk.parent_object_id)
                    + '.' + OBJECT_NAME(fk.parent_object_id)
                    AS ChildTable,
                pc.name AS ChildColumn,
                OBJECT_SCHEMA_NAME(fk.referenced_object_id)
                    + '.' + OBJECT_NAME(fk.referenced_object_id)
                    AS ParentTable,
                rc.name AS ParentColumn,
                fk.is_disabled AS IsDisabled
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc
                ON fkc.constraint_object_id = fk.object_id
            JOIN sys.columns pc
                ON pc.object_id = fkc.parent_object_id
               AND pc.column_id = fkc.parent_column_id
            JOIN sys.columns rc
                ON rc.object_id = fkc.referenced_object_id
               AND rc.column_id = fkc.referenced_column_id
            WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = 'dbo'
            ORDER BY ChildTable, ForeignKeyName
        """)

        # 4. All indexes on relevant tables
        section("4. INDEX DEFINITIONS")

        show_rows(cur, f"""
            SELECT
                t.name AS TableName,
                i.name AS IndexName,
                i.type_desc AS IndexType,
                i.is_primary_key AS IsPrimaryKey,
                i.is_unique AS IsUnique,
                i.is_disabled AS IsDisabled,
                ic.key_ordinal AS KeyOrdinal,
                ic.is_included_column AS IsIncludedColumn,
                c.name AS ColumnName
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            JOIN sys.indexes i ON i.object_id = t.object_id
            LEFT JOIN sys.index_columns ic
                ON ic.object_id = i.object_id
               AND ic.index_id = i.index_id
            LEFT JOIN sys.columns c
                ON c.object_id = ic.object_id
               AND c.column_id = ic.column_id
            WHERE s.name = 'dbo'
              AND t.name IN ({placeholders})
              AND i.index_id > 0
            ORDER BY t.name, i.name, ic.key_ordinal, ic.index_column_id
        """, relevant_tables)


        # 5. EXISTING SNAPSHOT COVERAGE
        print()
        print("=" * 110)
        print("5. EXISTING SNAPSHOT COVERAGE")

        show_rows(cur, """
            SELECT
                'OptionLiveSnapshot' AS TableName,
                COUNT_BIG(*) AS [TotalRows],
                COUNT(DISTINCT OptionID) AS [DistinctOptions],
                COUNT(DISTINCT SourceRetrievedAt) AS [DistinctSourceTimes],
                MIN(SourceRetrievedAt) AS [FirstSourceRetrievedAt],
                MAX(SourceRetrievedAt) AS [LastSourceRetrievedAt],
                MIN(DataDate) AS [FirstDataDate],
                MAX(DataDate) AS [LastDataDate]
            FROM dbo.OptionLiveSnapshot

            UNION ALL

            SELECT
                'UnderlyingLiveSnapshot' AS TableName,
                COUNT_BIG(*) AS [TotalRows],
                COUNT(DISTINCT UnderlyingID) AS [DistinctOptions],
                COUNT(DISTINCT SourceRetrievedAt) AS [DistinctSourceTimes],
                MIN(SourceRetrievedAt) AS [FirstSourceRetrievedAt],
                MAX(SourceRetrievedAt) AS [LastSourceRetrievedAt],
                MIN(DataDate) AS [FirstDataDate],
                MAX(DataDate) AS [LastDataDate]
            FROM dbo.UnderlyingLiveSnapshot
        """)

        show_rows(cur, """
            SELECT
                'OptionLiveSnapshot' AS TableName,
                COUNT_BIG(*) AS [DuplicateGroups]
            FROM (
                SELECT OptionID, SourceRetrievedAt
                FROM dbo.OptionLiveSnapshot
                GROUP BY OptionID, SourceRetrievedAt
                HAVING COUNT_BIG(*) > 1
            ) AS D

            UNION ALL

            SELECT
                'UnderlyingLiveSnapshot' AS TableName,
                COUNT_BIG(*) AS [DuplicateGroups]
            FROM (
                SELECT UnderlyingID, SourceRetrievedAt
                FROM dbo.UnderlyingLiveSnapshot
                GROUP BY UnderlyingID, SourceRetrievedAt
                HAVING COUNT_BIG(*) > 1
            ) AS D
        """)
        # 6. Duplicate keys in existing snapshot records
        section("6. DUPLICATE CHECKS")

        print("Option snapshot duplicate (OptionID, SourceRetrievedAt):")

        show_rows(cur, """
            SELECT
                OptionID,
                SourceRetrievedAt,
                COUNT_BIG(*) AS DuplicateCount
            FROM dbo.OptionLiveSnapshot
            GROUP BY OptionID, SourceRetrievedAt
            HAVING COUNT_BIG(*) > 1
            ORDER BY SourceRetrievedAt, OptionID
        """)

        print("\nUnderlying snapshot duplicate (UnderlyingID, SourceRetrievedAt):")

        show_rows(cur, """
            SELECT
                UnderlyingID,
                SourceRetrievedAt,
                COUNT_BIG(*) AS DuplicateCount
            FROM dbo.UnderlyingLiveSnapshot
            GROUP BY UnderlyingID, SourceRetrievedAt
            HAVING COUNT_BIG(*) > 1
            ORDER BY SourceRetrievedAt, UnderlyingID
        """)

    section("END OF BR69")
    print("Read-only inspection completed.")
    print("No records inserted, updated, or deleted.")
    print("No schema objects created or altered.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        raise
