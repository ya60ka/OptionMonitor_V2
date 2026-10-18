
# BR33 - Inspect Market Database Schema (READ ONLY)
# Project: OptionMonitor_V2
# Database: OptionMarketDB_V2
# Purpose: Inspect tables, row counts, columns, and foreign keys.
# Safety: READ ONLY - NO DATABASE DATA MODIFIED.

import sys
import pyodbc


CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    "DATABASE=OptionMarketDB_V2;"
    "Trusted_Connection=yes;"
    "ApplicationIntent=ReadOnly;"
)


def print_section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main():
    connection = None
    cursor = None

    try:
        print("=" * 78)
        print("BR33 - INSPECT MARKET DATABASE SCHEMA")
        print("=" * 78)
        print("Database: OptionMarketDB_V2")
        print("Mode: READ ONLY")
        print("No INSERT, UPDATE, DELETE, or DDL statements will be executed.")

        connection = pyodbc.connect(
            CONNECTION_STRING,
            timeout=15,
            autocommit=True,
        )
        cursor = connection.cursor()

        # --------------------------------------------------------------
        # BR33-A: Tables and approximate row counts
        # --------------------------------------------------------------
        print_section("BR33-A: TABLES AND ROW COUNTS")

        query_tables = """
        SELECT
            s.name AS SchemaName,
            t.name AS TableName,
            COALESCE(SUM(p.rows), 0) AS TotalRows
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s
            ON t.schema_id = s.schema_id
        LEFT JOIN sys.partitions AS p
            ON t.object_id = p.object_id
            AND p.index_id IN (0, 1)
        GROUP BY
            s.name,
            t.name
        ORDER BY
            s.name,
            t.name;
        """

        cursor.execute(query_tables)
        table_rows = cursor.fetchall()

        if not table_rows:
            print("No user tables found.")

        for row in table_rows:
            print(
                f"Schema: {row[0]} | "
                f"Table: {row[1]} | "
                f"Rows: {row[2]}"
            )

        print(f"\nTotal tables found: {len(table_rows)}")

        # --------------------------------------------------------------
        # BR33-B: Columns for all user tables
        # --------------------------------------------------------------
        print_section("BR33-B: TABLE COLUMNS")

        query_columns = """
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
            dc.definition AS DefaultDefinition
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s
            ON t.schema_id = s.schema_id
        INNER JOIN sys.columns AS c
            ON t.object_id = c.object_id
        INNER JOIN sys.types AS ty
            ON c.user_type_id = ty.user_type_id
        LEFT JOIN sys.default_constraints AS dc
            ON c.default_object_id = dc.object_id
        ORDER BY
            s.name,
            t.name,
            c.column_id;
        """

        cursor.execute(query_columns)
        column_rows = cursor.fetchall()

        current_table = None

        for row in column_rows:
            table_key = f"{row[0]}.{row[1]}"

            if table_key != current_table:
                current_table = table_key
                print(f"\n[TABLE] {current_table}")

            nullable = "NULL" if row[8] else "NOT NULL"
            identity = "IDENTITY" if row[9] else ""
            default = row[10] if row[10] is not None else ""

            print(
                f"  {row[2]}. {row[3]} | "
                f"Type={row[4]} | "
                f"MaxLengthBytes={row[5]} | "
                f"Precision={row[6]} | "
                f"Scale={row[7]} | "
                f"{nullable} | "
                f"{identity} | "
                f"Default={default}"
            )

        print(f"\nTotal columns found: {len(column_rows)}")

        # --------------------------------------------------------------
        # BR33-C: Foreign key relationships
        # --------------------------------------------------------------
        print_section("BR33-C: FOREIGN KEYS")

        query_foreign_keys = """
        SELECT
            fk.name AS ForeignKeyName,
            SCHEMA_NAME(parent_table.schema_id) AS ParentSchema,
            parent_table.name AS ParentTable,
            parent_column.name AS ParentColumn,
            SCHEMA_NAME(referenced_table.schema_id) AS ReferencedSchema,
            referenced_table.name AS ReferencedTable,
            referenced_column.name AS ReferencedColumn,
            fk.is_disabled AS IsDisabled,
            fk.is_not_trusted AS IsNotTrusted
        FROM sys.foreign_keys AS fk
        INNER JOIN sys.foreign_key_columns AS fkc
            ON fk.object_id = fkc.constraint_object_id
        INNER JOIN sys.tables AS parent_table
            ON fkc.parent_object_id = parent_table.object_id
        INNER JOIN sys.columns AS parent_column
            ON fkc.parent_object_id = parent_column.object_id
            AND fkc.parent_column_id = parent_column.column_id
        INNER JOIN sys.tables AS referenced_table
            ON fkc.referenced_object_id = referenced_table.object_id
        INNER JOIN sys.columns AS referenced_column
            ON fkc.referenced_object_id = referenced_column.object_id
            AND fkc.referenced_column_id = referenced_column.column_id
        ORDER BY
            ParentSchema,
            ParentTable,
            ForeignKeyName,
            fkc.constraint_column_id;
        """

        cursor.execute(query_foreign_keys)
        foreign_key_rows = cursor.fetchall()

        if not foreign_key_rows:
            print("No foreign keys found.")

        for row in foreign_key_rows:
            print(
                f"{row[0]} | "
                f"{row[1]}.{row[2]}.{row[3]} -> "
                f"{row[4]}.{row[5]}.{row[6]} | "
                f"Disabled={bool(row[7])} | "
                f"NotTrusted={bool(row[8])}"
            )

        print(f"\nTotal foreign key columns found: {len(foreign_key_rows)}")

        # --------------------------------------------------------------
        # BR33-D: Primary keys and unique indexes
        # --------------------------------------------------------------
        print_section("BR33-D: PRIMARY KEYS AND UNIQUE INDEXES")

        query_indexes = """
        SELECT
            s.name AS SchemaName,
            t.name AS TableName,
            i.name AS IndexName,
            i.is_primary_key AS IsPrimaryKey,
            i.is_unique AS IsUnique,
            i.is_disabled AS IsDisabled,
            c.name AS ColumnName,
            ic.key_ordinal AS KeyOrdinal,
            ic.is_included_column AS IsIncludedColumn
        FROM sys.indexes AS i
        INNER JOIN sys.tables AS t
            ON i.object_id = t.object_id
        INNER JOIN sys.schemas AS s
            ON t.schema_id = s.schema_id
        INNER JOIN sys.index_columns AS ic
            ON i.object_id = ic.object_id
            AND i.index_id = ic.index_id
        INNER JOIN sys.columns AS c
            ON ic.object_id = c.object_id
            AND ic.column_id = c.column_id
        WHERE
            i.is_primary_key = 1
            OR i.is_unique = 1
        ORDER BY
            s.name,
            t.name,
            i.name,
            ic.key_ordinal,
            ic.index_column_id;
        """

        cursor.execute(query_indexes)
        index_rows = cursor.fetchall()

        if not index_rows:
            print("No primary keys or unique indexes found.")

        current_index = None

        for row in index_rows:
            index_key = (
                f"{row[0]}.{row[1]}.{row[2]}"
            )

            if index_key != current_index:
                current_index = index_key
                print(
                    f"\n[INDEX] {index_key} | "
                    f"PrimaryKey={bool(row[3])} | "
                    f"Unique={bool(row[4])} | "
                    f"Disabled={bool(row[5])}"
                )

            column_role = (
                "INCLUDED"
                if row[8]
                else f"KEY position={row[7]}"
            )

            print(f"  Column: {row[6]} | {column_role}")

        print(f"\nTotal index-column entries found: {len(index_rows)}")

        # --------------------------------------------------------------
        # BR33-E: Completion
        # --------------------------------------------------------------
        print_section("BR33 COMPLETE")
        print("All inspection queries completed successfully.")
        print("READ ONLY: NO DATABASE DATA MODIFIED.")
        print("Next step: Review the output before designing market-data ingestion.")

    except Exception as exc:
        print()
        print("=" * 78)
        print("BR33 ERROR")
        print("=" * 78)
        print(f"Error type: {type(exc).__name__}")
        print(f"Error details: {exc}")
        sys.exit_code = 1
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
