
# BR71 - Daily History Schema and Integrity Audit
# Read-only inspection before implementing daily history storage.
# Target: OptionMarketDB_V2 only.
# No INSERT, UPDATE, DELETE, or schema changes.

from datetime import datetime
import pyodbc

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

TABLES = [
    "OptionDailyHistory",
    "UnderlyingDailyHistory",
    "OptionLiveSnapshot",
    "UnderlyingLiveSnapshot",
    "OptionLiveCurrent",
    "UnderlyingLiveCurrent",
    "CollectionRun",
    "RawApiResponse",
]

def heading(title):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)

def main():
    connection = None

    print("=" * 110)
    print("BR71 - DAILY HISTORY SCHEMA AND INTEGRITY AUDIT")
    print("=" * 110)
    print(f"Server   : {SERVER}")
    print(f"Database : {DATABASE}")
    print("Mode     : READ ONLY")
    print("Writes   : NONE")

    try:
        connection_string = (
            f"DRIVER={{{DRIVER}}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=15;"
        )

        connection = pyodbc.connect(
            connection_string,
            autocommit=True,
            timeout=15,
        )
        cursor = connection.cursor()

        # ----------------------------------------------------------
        # 1. Database identity
        # ----------------------------------------------------------
        heading("1. DATABASE IDENTITY")

        cursor.execute("""
            SELECT DB_NAME() AS DatabaseName,
                   @@SERVERNAME AS ServerName,
                   GETDATE() AS ServerLocalTime
        """)

        row = cursor.fetchone()
        print(f"Database       : {row.DatabaseName}")
        print(f"Server         : {row.ServerName}")
        print(f"Server time    : {row.ServerLocalTime}")

        if row.DatabaseName != DATABASE:
            raise RuntimeError(
                f"Safety check failed: connected to {row.DatabaseName}"
            )

        # ----------------------------------------------------------
        # 2. Column definitions
        # ----------------------------------------------------------
        heading("2. TABLE COLUMNS")

        for table in TABLES:
            cursor.execute("""
                SELECT
                    c.COLUMN_NAME,
                    c.ORDINAL_POSITION,
                    c.DATA_TYPE,
                    c.CHARACTER_MAXIMUM_LENGTH,
                    c.NUMERIC_PRECISION,
                    c.NUMERIC_SCALE,
                    c.IS_NULLABLE,
                    c.COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS AS c
                WHERE c.TABLE_SCHEMA = 'dbo'
                  AND c.TABLE_NAME = ?
                ORDER BY c.ORDINAL_POSITION
            """, table)

            columns = cursor.fetchall()

            print()
            print(f"[dbo].[{table}]")

            if not columns:
                print("  TABLE NOT FOUND OR NO VISIBLE COLUMNS")
                continue

            for col in columns:
                data_type = col.DATA_TYPE

                if col.CHARACTER_MAXIMUM_LENGTH is not None:
                    length = col.CHARACTER_MAXIMUM_LENGTH
                    if data_type in ("varchar", "nvarchar", "char", "nchar"):
                        length_text = (
                            "MAX" if length == -1 else str(length)
                        )
                        data_type += f"({length_text})"

                elif col.NUMERIC_PRECISION is not None and data_type in (
                    "decimal", "numeric"
                ):
                    data_type += (
                        f"({col.NUMERIC_PRECISION},{col.NUMERIC_SCALE})"
                    )

                default = (
                    str(col.COLUMN_DEFAULT)
                    if col.COLUMN_DEFAULT is not None
                    else "-"
                )

                print(
                    f"  {col.ORDINAL_POSITION:02d}. "
                    f"{col.COLUMN_NAME:<30} "
                    f"{data_type:<24} "
                    f"Nullable={col.IS_NULLABLE:<3} "
                    f"Default={default}"
                )

        # ----------------------------------------------------------
        # 3. Primary keys, unique constraints and indexes
        # ----------------------------------------------------------
        heading("3. INDEXES AND KEY COLUMNS")

        cursor.execute("""
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
            FROM sys.tables AS t
            JOIN sys.schemas AS s
              ON s.schema_id = t.schema_id
            JOIN sys.indexes AS i
              ON i.object_id = t.object_id
            JOIN sys.index_columns AS ic
              ON ic.object_id = i.object_id
             AND ic.index_id = i.index_id
            JOIN sys.columns AS c
              ON c.object_id = ic.object_id
             AND c.column_id = ic.column_id
            WHERE s.name = 'dbo'
              AND t.name IN (
                  'OptionDailyHistory',
                  'UnderlyingDailyHistory',
                  'OptionLiveSnapshot',
                  'UnderlyingLiveSnapshot',
                  'OptionLiveCurrent',
                  'UnderlyingLiveCurrent',
                  'CollectionRun',
                  'RawApiResponse'
              )
              AND i.index_id > 0
            ORDER BY
                t.name,
                i.name,
                ic.is_included_column,
                ic.key_ordinal,
                ic.index_column_id
        """)

        index_rows = cursor.fetchall()
        current_index = None

        if not index_rows:
            print("No index metadata returned.")
        else:
            for row in index_rows:
                index_key = (row.TableName, row.IndexName)

                if index_key != current_index:
                    current_index = index_key
                    print()
                    print(
                        f"[{row.TableName}] {row.IndexName} | "
                        f"Type={row.IndexType} | "
                        f"PK={row.IsPrimaryKey} | "
                        f"Unique={row.IsUnique} | "
                        f"Disabled={row.IsDisabled}"
                    )

                role = (
                    "INCLUDE"
                    if row.IsIncludedColumn
                    else f"KEY#{row.KeyOrdinal}"
                )
                print(f"  {role}: {row.ColumnName}")

        # ----------------------------------------------------------
        # 4. Foreign keys
        # ----------------------------------------------------------
        heading("4. FOREIGN KEY RELATIONSHIPS")

        cursor.execute("""
            SELECT
                OBJECT_NAME(fkc.parent_object_id) AS ChildTable,
                pc.name AS ChildColumn,
                OBJECT_NAME(fkc.referenced_object_id) AS ParentTable,
                rc.name AS ParentColumn,
                fk.name AS ForeignKeyName,
                fk.is_disabled AS IsDisabled
            FROM sys.foreign_key_columns AS fkc
            JOIN sys.foreign_keys AS fk
              ON fk.object_id = fkc.constraint_object_id
            JOIN sys.columns AS pc
              ON pc.object_id = fkc.parent_object_id
             AND pc.column_id = fkc.parent_column_id
            JOIN sys.columns AS rc
              ON rc.object_id = fkc.referenced_object_id
             AND rc.column_id = fkc.referenced_column_id
            WHERE OBJECT_NAME(fkc.parent_object_id) IN (
                'OptionDailyHistory',
                'UnderlyingDailyHistory',
                'OptionLiveSnapshot',
                'UnderlyingLiveSnapshot',
                'OptionLiveCurrent',
                'UnderlyingLiveCurrent',
                'CollectionRun',
                'RawApiResponse'
            )
            OR OBJECT_NAME(fkc.referenced_object_id) IN (
                'OptionDailyHistory',
                'UnderlyingDailyHistory',
                'OptionLiveSnapshot',
                'UnderlyingLiveSnapshot',
                'OptionLiveCurrent',
                'UnderlyingLiveCurrent',
                'CollectionRun',
                'RawApiResponse'
            )
            ORDER BY ChildTable, ForeignKeyName
        """)

        fk_rows = cursor.fetchall()

        if not fk_rows:
            print("No foreign-key relationships found for the audited tables.")
        else:
            for row in fk_rows:
                print(
                    f"{row.ChildTable}.{row.ChildColumn} -> "
                    f"{row.ParentTable}.{row.ParentColumn} | "
                    f"FK={row.ForeignKeyName} | "
                    f"Disabled={row.IsDisabled}"
                )

        # ----------------------------------------------------------
        # 5. Row counts and history date coverage
        # ----------------------------------------------------------
        heading("5. TABLE COUNTS AND HISTORY COVERAGE")

        for table in TABLES:
            cursor.execute("""
                SELECT OBJECT_ID(? , 'U')
            """, f"dbo.{table}")

            object_row = cursor.fetchone()

            if not object_row or object_row[0] is None:
                print(f"{table}: TABLE NOT FOUND")
                continue

            # Table names come exclusively from the fixed TABLES list.
            cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{table}]")
            count = cursor.fetchone()[0]
            print(f"{table:<28} Rows={count}")

            if table in (
                "OptionDailyHistory",
                "UnderlyingDailyHistory",
            ):
                cursor.execute("""
                    SELECT
                        MIN(DataDate) AS FirstDate,
                        MAX(DataDate) AS LastDate,
                        COUNT(DISTINCT DataDate) AS DistinctDates
                    FROM dbo.[PLACEHOLDER]
                """.replace("dbo.[PLACEHOLDER]", f"dbo.[{table}]"))

                coverage = cursor.fetchone()
                print(
                    f"  FirstDate={coverage.FirstDate} | "
                    f"LastDate={coverage.LastDate} | "
                    f"DistinctDates={coverage.DistinctDates}"
                )

        # ----------------------------------------------------------
        # 6. Snapshot timestamps and daily history samples
        # ----------------------------------------------------------
        heading("6. SNAPSHOT TIMESTAMPS")

        for table in (
            "OptionLiveSnapshot",
            "UnderlyingLiveSnapshot",
        ):
            cursor.execute(f"""
                SELECT
                    COUNT_BIG(*) AS TotalRows,
                    COUNT(DISTINCT SourceRetrievedAt) AS DistinctTimes,
                    MIN(SourceRetrievedAt) AS FirstTime,
                    MAX(SourceRetrievedAt) AS LastTime
                FROM dbo.[{table}]
            """)

            row = cursor.fetchone()
            print(
                f"{table}: Rows={row.TotalRows} | "
                f"DistinctTimes={row.DistinctTimes} | "
                f"First={row.FirstTime} | Last={row.LastTime}"
            )

        # ----------------------------------------------------------
        # 7. Collection run and raw response linkage
        # ----------------------------------------------------------
        heading("7. COLLECTION RUN / RAW RESPONSE LINKAGE")

        cursor.execute("""
            SELECT
                cr.CollectionRunID,
                cr.JobName,
                cr.Status,
                cr.ItemsRequested,
                cr.ItemsSucceeded,
                cr.ItemsFailed,
                cr.StartedAt,
                cr.FinishedAt,
                COUNT(rr.RawDataID) AS RawResponseCount
            FROM dbo.CollectionRun AS cr
            LEFT JOIN dbo.RawApiResponse AS rr
              ON rr.CollectionRunID = cr.CollectionRunID
            GROUP BY
                cr.CollectionRunID,
                cr.JobName,
                cr.Status,
                cr.ItemsRequested,
                cr.ItemsSucceeded,
                cr.ItemsFailed,
                cr.StartedAt,
                cr.FinishedAt
            ORDER BY cr.CollectionRunID DESC
        """)

        run_rows = cursor.fetchmany(20)

        if not run_rows:
            print("No collection runs found.")
        else:
            for row in run_rows:
                print(
                    f"RunID={row.CollectionRunID} | "
                    f"Job={row.JobName} | Status={row.Status} | "
                    f"Requested={row.ItemsRequested} | "
                    f"Succeeded={row.ItemsSucceeded} | "
                    f"Failed={row.ItemsFailed} | "
                    f"RawResponses={row.RawResponseCount} | "
                    f"Started={row.StartedAt} | "
                    f"Finished={row.FinishedAt}"
                )

        # ----------------------------------------------------------
        # 8. Finish
        # ----------------------------------------------------------
        heading("8. AUDIT RESULT")

        print("Schema inspection : COMPLETED")
        print("Database writes   : NONE")
        print("Schema changes    : NONE")
        print("Target database   : OptionMarketDB_V2 ONLY")
        print("Next step         : Review output before implementing history writes.")
        print("=" * 110)
        print("END OF BR71")
        print("=" * 110)

    except Exception as exc:
        print()
        print("BR71 FAILED")
        print(f"{type(exc).__name__}: {exc}")
        print("No database writes were issued.")
        raise

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
