
# BR43 - Inspect Database Constraints Before Market Capture
# READ ONLY: no INSERT, UPDATE, DELETE, or schema changes.

from pathlib import Path
from datetime import datetime

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
REPORT_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

TARGET_TABLES = [
    "CollectionRun",
    "RawApiResponse",
    "OptionContract",
    "OptionLiveSnapshot",
    "UnderlyingLiveSnapshot",
    "OptionLiveCurrent",
    "UnderlyingLiveCurrent",
]

EXPECTED_UNDERLYING_CODE = "17914401175772326"


def section(title):
    print("\n" + "-" * 78)
    print(title)
    print("-" * 78)


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_lines = []

    def log(message=""):
        print(message)
        report_lines.append(str(message))

    log("=" * 78)
    log("BR43 - Database Constraints and Capture Readiness")
    log("=" * 78)
    log("Mode       : READ ONLY")
    log(f"Server     : {SERVER}")
    log(f"Database   : {DATABASE}")
    log(f"Started at : {datetime.now().isoformat(timespec='seconds')}")
    log("")

    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=15;"
    )

    connection = None

    try:
        connection = pyodbc.connect(
            connection_string,
            autocommit=True,
            timeout=15,
        )
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                DB_NAME() AS DatabaseName,
                @@SERVERNAME AS ServerName
        """)
        row = cursor.fetchone()

        log(f"Connected server   : {row.ServerName}")
        log(f"Connected database : {row.DatabaseName}")

        # --------------------------------------------------------------
        # 1. Column definitions, nullability, identity, and defaults
        # --------------------------------------------------------------
        section("1. COLUMN DEFINITIONS")
        log("")

        for table in TARGET_TABLES:
            cursor.execute("""
                SELECT
                    c.column_id,
                    c.name AS ColumnName,
                    TYPE_NAME(c.user_type_id) AS DataType,
                    c.max_length,
                    c.precision,
                    c.scale,
                    c.is_nullable,
                    c.is_identity,
                    dc.definition AS DefaultDefinition
                FROM sys.tables t
                INNER JOIN sys.schemas s
                    ON s.schema_id = t.schema_id
                INNER JOIN sys.columns c
                    ON c.object_id = t.object_id
                LEFT JOIN sys.default_constraints dc
                    ON dc.object_id = c.default_object_id
                WHERE s.name = 'dbo'
                  AND t.name = ?
                ORDER BY c.column_id
            """, table)

            columns = cursor.fetchall()

            log(f"[dbo].[{table}]")
            if not columns:
                log("  ERROR: table not found or metadata unavailable")
                log("")
                continue

            for col in columns:
                if col.max_length == -1:
                    length_text = "MAX"
                elif col.DataType in ("nvarchar", "nchar"):
                    length_text = str(col.max_length // 2)
                elif col.DataType in ("varchar", "char", "varbinary", "binary"):
                    length_text = str(col.max_length)
                else:
                    length_text = "-"

                nullable = "NULL" if col.is_nullable else "NOT NULL"
                identity = " IDENTITY" if col.is_identity else ""
                default = (
                    f" DEFAULT {col.DefaultDefinition}"
                    if col.DefaultDefinition is not None
                    else ""
                )

                log(
                    f"  {col.column_id:02d}. {col.ColumnName:<28} "
                    f"{col.DataType:<14} "
                    f"length={length_text:<6} "
                    f"{nullable}{identity}{default}"
                )
            log("")

        # --------------------------------------------------------------
        # 2. Primary keys, unique indexes, and filtered indexes
        # --------------------------------------------------------------
        section("2. PRIMARY KEYS AND INDEXES")
        log("")

        for table in TARGET_TABLES:
            cursor.execute("""
                SELECT
                    i.name AS IndexName,
                    i.type_desc AS IndexType,
                    i.is_primary_key,
                    i.is_unique,
                    i.has_filter,
                    i.filter_definition,
                    c.name AS ColumnName,
                    ic.key_ordinal,
                    ic.is_included_column
                FROM sys.tables t
                INNER JOIN sys.schemas s
                    ON s.schema_id = t.schema_id
                INNER JOIN sys.indexes i
                    ON i.object_id = t.object_id
                INNER JOIN sys.index_columns ic
                    ON ic.object_id = i.object_id
                   AND ic.index_id = i.index_id
                INNER JOIN sys.columns c
                    ON c.object_id = ic.object_id
                   AND c.column_id = ic.column_id
                WHERE s.name = 'dbo'
                  AND t.name = ?
                  AND i.index_id > 0
                ORDER BY i.name, ic.key_ordinal, ic.index_column_id
            """, table)

            rows = cursor.fetchall()
            log(f"[dbo].[{table}]")

            if not rows:
                log("  No index metadata returned.")
            else:
                last_index = None
                for r in rows:
                    if r.IndexName != last_index:
                        last_index = r.IndexName
                        flags = []
                        if r.is_primary_key:
                            flags.append("PRIMARY KEY")
                        if r.is_unique:
                            flags.append("UNIQUE")
                        if r.has_filter:
                            flags.append(f"FILTER={r.filter_definition}")

                        log(
                            f"  INDEX {r.IndexName} "
                            f"({r.IndexType}) "
                            f"{' '.join(flags)}"
                        )

                    role = (
                        "INCLUDE"
                        if r.is_included_column
                        else f"KEY[{r.key_ordinal}]"
                    )
                    log(f"      {role}: {r.ColumnName}")
            log("")

        # --------------------------------------------------------------
        # 3. Foreign key relationships
        # --------------------------------------------------------------
        section("3. FOREIGN KEYS")
        log("")

        cursor.execute("""
            SELECT
                fk.name AS FKName,
                OBJECT_SCHEMA_NAME(fk.parent_object_id) AS ParentSchema,
                OBJECT_NAME(fk.parent_object_id) AS ParentTable,
                pc.name AS ParentColumn,
                OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS RefSchema,
                OBJECT_NAME(fk.referenced_object_id) AS RefTable,
                rc.name AS RefColumn,
                fk.is_disabled,
                fk.is_not_trusted
            FROM sys.foreign_keys fk
            INNER JOIN sys.foreign_key_columns fkc
                ON fkc.constraint_object_id = fk.object_id
            INNER JOIN sys.columns pc
                ON pc.object_id = fkc.parent_object_id
               AND pc.column_id = fkc.parent_column_id
            INNER JOIN sys.columns rc
                ON rc.object_id = fkc.referenced_object_id
               AND rc.column_id = fkc.referenced_column_id
            WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = 'dbo'
               OR OBJECT_SCHEMA_NAME(fk.referenced_object_id) = 'dbo'
            ORDER BY ParentTable, FKName, fkc.constraint_column_id
        """)

        fk_rows = cursor.fetchall()
        log(f"Foreign-key column relationships returned: {len(fk_rows)}")

        for r in fk_rows:
            status = []
            if r.is_disabled:
                status.append("DISABLED")
            if r.is_not_trusted:
                status.append("NOT TRUSTED")

            log(
                f"  {r.FKName}: "
                f"{r.ParentSchema}.{r.ParentTable}.{r.ParentColumn}"
                f" -> {r.RefSchema}.{r.RefTable}.{r.RefColumn}"
                f"{' [' + ', '.join(status) + ']' if status else ''}"
            )

        # --------------------------------------------------------------
        # 4. Approximate row counts for target tables
        # --------------------------------------------------------------
        section("4. CURRENT TABLE ROW COUNTS")
        log("")

        for table in TARGET_TABLES:
            cursor.execute("""
                SELECT COALESCE(SUM(ps.row_count), 0)
                FROM sys.dm_db_partition_stats ps
                INNER JOIN sys.tables t
                    ON t.object_id = ps.object_id
                INNER JOIN sys.schemas s
                    ON s.schema_id = t.schema_id
                WHERE s.name = 'dbo'
                  AND t.name = ?
                  AND ps.index_id IN (0, 1)
            """, table)

            result = cursor.fetchone()
            count = result[0] if result else 0
            log(f"  dbo.{table:<28} rows={count:,}")

        # --------------------------------------------------------------
        # 5. Verify the target underlying exists
        # --------------------------------------------------------------
        section("5. UNDERLYING AND CONTRACT COUNTS")
        log("")

        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.Underlying
            WHERE TSEInsCode = ?
        """, EXPECTED_UNDERLYING_CODE)

        underlying_count = cursor.fetchone()[0]
        log(f"Underlying code matches: {underlying_count}")

        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.OptionContract
            WHERE UnderlyingID = (
                SELECT TOP (1) UnderlyingID
                FROM dbo.Underlying
                WHERE TSEInsCode = ?
            )
        """, EXPECTED_UNDERLYING_CODE)

        contract_count = cursor.fetchone()[0]
        log(f"Option contracts for underlying: {contract_count}")

        log("")
        log("=" * 78)
        log("BR43 FINISHED")
        log("Database writes : NONE")
        log("Schema changes  : NONE")
        log("=" * 78)

    except Exception as exc:
        log("")
        log("BR43 ERROR")
        log(f"{type(exc).__name__}: {exc}")
        raise

    finally:
        if connection is not None:
            connection.close()

        report_path = REPORT_DIR / (
            f"BR43_capture_constraints_{datetime.now():%Y%m%d_%H%M%S}.txt"
        )
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
