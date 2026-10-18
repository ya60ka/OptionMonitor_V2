
#!/usr/bin/env python3
# BR26 - Read-only SQL Server schema inspection for Option Monitor V2.
# No INSERT, UPDATE, DELETE, CREATE, ALTER, or DROP statements.

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pyodbc

PROJECT_DIR = Path(__file__).resolve().parent
REPORT_DIR = PROJECT_DIR / "data" / "api_tests"

SQL_SERVER = r"localhost"
SQL_DATABASE = "OptionMarketDB_V2"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

EXPECTED_TABLES = {
    "AlertHistory",
    "CalculationResults",
    "CollectionRun",
    "OptionContract",
    "OptionDailyHistory",
    "OptionLiveCurrent",
    "OptionLiveSnapshot",
    "RawApiResponse",
    "Underlying",
    "UnderlyingDailyHistory",
    "UnderlyingLiveCurrent",
    "UnderlyingLiveSnapshot",
}

PRIORITY_TABLES = {
    "Underlying",
    "OptionContract",
    "CollectionRun",
    "OptionLiveCurrent",
    "OptionLiveSnapshot",
}


def get_connection() -> pyodbc.Connection:
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string, timeout=10)


def inspect_database(cursor) -> list[str]:
    lines: list[str] = []

    row = cursor.execute(
        "SELECT @@SERVERNAME, DB_NAME(), SUSER_SNAME();"
    ).fetchone()

    server_name, database_name, login_name = row

    lines.extend([
        "DATABASE INFORMATION",
        "-" * 78,
        f"SQL Server: {server_name}",
        f"Database: {database_name}",
        f"Login: {login_name}",
        "",
    ])

    if database_name != SQL_DATABASE:
        raise RuntimeError(
            f"Connected to {database_name!r}, expected {SQL_DATABASE!r}."
        )

    # List user tables.
    table_rows = cursor.execute("""
        SELECT s.name AS SchemaName, t.name AS TableName
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
        WHERE t.is_ms_shipped = 0
        ORDER BY s.name, t.name;
    """).fetchall()

    actual_tables = {row.TableName for row in table_rows}
    missing_tables = sorted(EXPECTED_TABLES - actual_tables)
    extra_tables = sorted(actual_tables - EXPECTED_TABLES)

    lines.extend([
        "TABLE INVENTORY",
        "-" * 78,
        f"User tables found: {len(actual_tables)}",
        f"Expected tables: {len(EXPECTED_TABLES)}",
        f"Missing expected tables: {missing_tables or 'None'}",
        f"Additional tables: {extra_tables or 'None'}",
        "",
    ])

    # Inspect every column, including type, length, precision, scale,
    # nullability, identity, computed status, and default expression.
    column_rows = cursor.execute("""
        SELECT
            s.name AS SchemaName,
            t.name AS TableName,
            c.column_id AS ColumnOrder,
            c.name AS ColumnName,
            ty.name AS DataType,
            c.max_length AS MaxLengthBytes,
            c.precision AS NumericPrecision,
            c.scale AS NumericScale,
            c.is_nullable AS IsNullable,
            c.is_identity AS IsIdentity,
            c.is_computed AS IsComputed,
            dc.definition AS DefaultDefinition,
            cc.definition AS ComputedDefinition
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s
            ON s.schema_id = t.schema_id
        INNER JOIN sys.columns AS c
            ON c.object_id = t.object_id
        INNER JOIN sys.types AS ty
            ON ty.user_type_id = c.user_type_id
        LEFT JOIN sys.default_constraints AS dc
            ON dc.object_id = c.default_object_id
        LEFT JOIN sys.computed_columns AS cc
            ON cc.object_id = c.object_id
            AND cc.column_id = c.column_id
        WHERE t.is_ms_shipped = 0
        ORDER BY s.name, t.name, c.column_id;
    """).fetchall()

    columns_by_table: dict[str, list] = {}

    for row in column_rows:
        columns_by_table.setdefault(row.TableName, []).append(row)

    lines.extend([
        "COLUMN DEFINITIONS",
        "-" * 78,
    ])

    for table_row in table_rows:
        schema_name = table_row.SchemaName
        table_name = table_row.TableName
        columns = columns_by_table.get(table_name, [])

        lines.extend([
            "",
            f"[{schema_name}].[{table_name}]",
            f"Column count: {len(columns)}",
        ])

        for col in columns:
            data_type = col.DataType

            if data_type in ("varchar", "char", "varbinary", "binary"):
                length = (
                    "MAX" if col.MaxLengthBytes == -1
                    else str(col.MaxLengthBytes)
                )
                type_description = f"{data_type}({length})"

            elif data_type in ("nvarchar", "nchar"):
                length = (
                    "MAX" if col.MaxLengthBytes == -1
                    else str(col.MaxLengthBytes // 2)
                )
                type_description = f"{data_type}({length})"

            elif data_type in ("decimal", "numeric"):
                type_description = (
                    f"{data_type}({col.NumericPrecision},"
                    f"{col.NumericScale})"
                )

            elif data_type in ("datetime2", "datetimeoffset", "time"):
                type_description = f"{data_type}({col.NumericScale})"

            else:
                type_description = data_type

            flags = []
            if col.IsIdentity:
                flags.append("IDENTITY")
            if col.IsComputed:
                flags.append("COMPUTED")

            line = (
                f"  {col.ColumnOrder:>3}. {col.ColumnName}: "
                f"{type_description}; "
                f"nullable={'YES' if col.IsNullable else 'NO'}"
            )

            if flags:
                line += f"; {', '.join(flags)}"

            if col.DefaultDefinition is not None:
                line += f"; default={col.DefaultDefinition}"

            if col.ComputedDefinition is not None:
                line += f"; expression={col.ComputedDefinition}"

            lines.append(line)

    # Primary keys, unique constraints, and indexes.
    index_rows = cursor.execute("""
        SELECT
            s.name AS SchemaName,
            t.name AS TableName,
            i.name AS IndexName,
            i.type_desc AS IndexType,
            i.is_primary_key AS IsPrimaryKey,
            i.is_unique AS IsUnique,
            i.is_disabled AS IsDisabled,
            ic.key_ordinal AS KeyOrdinal,
            ic.is_included_column AS IsIncluded,
            c.name AS ColumnName
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s
            ON s.schema_id = t.schema_id
        INNER JOIN sys.indexes AS i
            ON i.object_id = t.object_id
        LEFT JOIN sys.index_columns AS ic
            ON ic.object_id = i.object_id
            AND ic.index_id = i.index_id
        LEFT JOIN sys.columns AS c
            ON c.object_id = ic.object_id
            AND c.column_id = ic.column_id
        WHERE t.is_ms_shipped = 0
          AND i.name IS NOT NULL
          AND i.is_hypothetical = 0
        ORDER BY s.name, t.name, i.name,
                 ic.is_included_column, ic.key_ordinal, ic.index_column_id;
    """).fetchall()

    lines.extend(["", "INDEXES AND PRIMARY KEYS", "-" * 78])

    current_index = None

    for row in index_rows:
        key = (row.SchemaName, row.TableName, row.IndexName)

        if key != current_index:
            current_index = key
            lines.append(
                f"\n[{row.SchemaName}].[{row.TableName}] "
                f"{row.IndexName}: {row.IndexType}; "
                f"primary_key={bool(row.IsPrimaryKey)}; "
                f"unique={bool(row.IsUnique)}; "
                f"disabled={bool(row.IsDisabled)}"
            )

        if row.ColumnName:
            role = (
                f"INCLUDE, position {row.KeyOrdinal}"
                if row.IsIncluded
                else (
                    f"KEY, position {row.KeyOrdinal}"
                    if row.KeyOrdinal
                    else "column"
                )
            )
            lines.append(f"  {row.ColumnName} ({role})")

    # Foreign keys and referential actions.
    fk_rows = cursor.execute("""
        SELECT
            ps.name AS ParentSchema,
            pt.name AS ParentTable,
            fk.name AS ForeignKeyName,
            pc.name AS ParentColumn,
            rs.name AS ReferencedSchema,
            rt.name AS ReferencedTable,
            rc.name AS ReferencedColumn,
            fkc.constraint_column_id AS ColumnOrder,
            fk.delete_referential_action_desc AS OnDelete,
            fk.update_referential_action_desc AS OnUpdate,
            fk.is_disabled AS IsDisabled,
            fk.is_not_trusted AS IsNotTrusted
        FROM sys.foreign_keys AS fk
        INNER JOIN sys.tables AS pt
            ON pt.object_id = fk.parent_object_id
        INNER JOIN sys.schemas AS ps
            ON ps.schema_id = pt.schema_id
        INNER JOIN sys.tables AS rt
            ON rt.object_id = fk.referenced_object_id
        INNER JOIN sys.schemas AS rs
            ON rs.schema_id = rt.schema_id
        INNER JOIN sys.foreign_key_columns AS fkc
            ON fkc.constraint_object_id = fk.object_id
        INNER JOIN sys.columns AS pc
            ON pc.object_id = fkc.parent_object_id
            AND pc.column_id = fkc.parent_column_id
        INNER JOIN sys.columns AS rc
            ON rc.object_id = fkc.referenced_object_id
            AND rc.column_id = fkc.referenced_column_id
        ORDER BY ps.name, pt.name, fk.name, fkc.constraint_column_id;
    """).fetchall()

    lines.extend(["", "FOREIGN KEYS", "-" * 78])

    if not fk_rows:
        lines.append("No foreign keys found.")

    current_fk = None

    for row in fk_rows:
        key = (
            row.ParentSchema,
            row.ParentTable,
            row.ForeignKeyName,
        )

        if key != current_fk:
            current_fk = key
            lines.append(
                f"\n[{row.ParentSchema}].[{row.ParentTable}] "
                f"{row.ForeignKeyName}"
            )
            lines.append(
                f"  References [{row.ReferencedSchema}]."
                f"[{row.ReferencedTable}]"
            )
            lines.append(
                f"  ON DELETE={row.OnDelete}; ON UPDATE={row.OnUpdate}; "
                f"disabled={bool(row.IsDisabled)}; "
                f"not_trusted={bool(row.IsNotTrusted)}"
            )

        lines.append(
            f"  {row.ParentColumn} -> {row.ReferencedColumn}"
        )

    # Priority table summary for the next integration step.
    lines.extend(["", "PRIORITY TABLE SUMMARY", "-" * 78])

    for table_name in sorted(PRIORITY_TABLES):
        if table_name not in actual_tables:
            lines.append(f"{table_name}: MISSING")
            continue

        columns = columns_by_table.get(table_name, [])
        column_names = [col.ColumnName for col in columns]

        lines.append(f"\n{table_name} ({len(column_names)} columns)")
        lines.append("  " + ", ".join(column_names))

    return lines


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("BR26 - Read-only Database Schema Inspection")
    print("=" * 70)
    print(f"SQL Server : {SQL_SERVER}")
    print(f"Database   : {SQL_DATABASE}")
    print("Mode       : READ ONLY METADATA")
    print("API        : NOT USED")
    print("Data writes: NONE")
    print("-" * 70)

    try:
        with get_connection() as connection:
            cursor = connection.cursor()
            lines = inspect_database(cursor)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"BR26_schema_report_{stamp}.txt"
        report_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

        print("\n".join(lines))
        print("-" * 70)
        print(f"Report saved: {report_path}")
        print("RESULT: SCHEMA INSPECTION COMPLETED")
        print("No database objects or market data were modified.")
        return 0

    except pyodbc.Error as exc:
        print("\nSQL SERVER ERROR:")
        print(exc)
        return 2

    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
