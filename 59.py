
# BR59 - Read-only Database Schema and Snapshot/Current Inspection
# Target: OptionMarketDB_V2 only.
# No INSERT, UPDATE, DELETE, DDL, or database modifications.

import json
from datetime import datetime, date
from pathlib import Path

import pyodbc

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

CONNECTION_STRING = (
    f"DRIVER={{{DRIVER}}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
    "Connection Timeout=10;"
)


def safe_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def quote_identifier(name):
    return "[" + name.replace("]", "]]") + "]"


def main():
    print("=" * 78)
    print("BR59 - DATABASE SCHEMA AND SNAPSHOT/CURRENT INSPECTION")
    print("=" * 78)
    print(f"Server          : {SERVER}")
    print(f"Database        : {DATABASE}")
    print("Mode            : READ ONLY")
    print("Database changes: NONE")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = pyodbc.connect(
        CONNECTION_STRING,
        timeout=10,
        autocommit=False,
        readonly=True,
    )

    report = {
        "stage": "BR59",
        "server": SERVER,
        "database": DATABASE,
        "read_only": True,
        "tables": [],
        "candidate_tables": [],
        "recent_api_files": [],
    }

    try:
        cursor = connection.cursor()

        actual_database = cursor.execute(
            "SELECT DB_NAME()"
        ).fetchone()[0]

        if actual_database != DATABASE:
            raise RuntimeError(
                f"Safety check failed: connected to {actual_database}"
            )

        print(f"Connected database: {actual_database}")

        # Inspect all user tables and columns.
        metadata_sql = """
        SELECT
            s.name AS schema_name,
            t.name AS table_name,
            c.column_id,
            c.name AS column_name,
            ty.name AS data_type,
            c.max_length,
            c.is_nullable
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s
            ON t.schema_id = s.schema_id
        INNER JOIN sys.columns AS c
            ON t.object_id = c.object_id
        INNER JOIN sys.types AS ty
            ON c.user_type_id = ty.user_type_id
        WHERE t.is_ms_shipped = 0
        ORDER BY s.name, t.name, c.column_id;
        """

        metadata_rows = cursor.execute(metadata_sql).fetchall()
        tables = {}

        for row in metadata_rows:
            key = (row.schema_name, row.table_name)
            if key not in tables:
                tables[key] = []

            tables[key].append({
                "column_id": row.column_id,
                "column_name": row.column_name,
                "data_type": row.data_type,
                "max_length": row.max_length,
                "is_nullable": bool(row.is_nullable),
            })

        print(f"\nUser tables found: {len(tables)}")

        for (schema_name, table_name), columns in tables.items():
            full_name = f"{schema_name}.{table_name}"

            # Read-only approximate row count from SQL Server metadata.
            count_sql = """
            SELECT COALESCE(SUM(p.rows), 0)
            FROM sys.partitions AS p
            INNER JOIN sys.tables AS t
                ON p.object_id = t.object_id
            INNER JOIN sys.schemas AS s
                ON t.schema_id = s.schema_id
            WHERE s.name = ? AND t.name = ?
              AND p.index_id IN (0, 1);
            """
            row_count = cursor.execute(
                count_sql, schema_name, table_name
            ).fetchone()[0]

            table_info = {
                "schema": schema_name,
                "table": table_name,
                "approx_row_count": int(row_count),
                "columns": columns,
            }
            report["tables"].append(table_info)

            print(f"\nTABLE: {full_name} | rows≈{row_count}")
            print("  " + ", ".join(
                f"{col['column_name']} ({col['data_type']})"
                for col in columns
            ))

            normalized_name = table_name.lower()
            normalized_columns = {
                col["column_name"].lower() for col in columns
            }

            name_relevant = any(
                token in normalized_name
                for token in (
                    "collection", "snapshot", "current",
                    "option", "underlying", "market", "run"
                )
            )

            column_relevant = any(
                token in normalized_columns
                for token in (
                    "collectionrunid", "inscode", "contractid",
                    "symbol", "snapshotid", "underlyingid"
                )
            )

            if name_relevant or column_relevant:
                report["candidate_tables"].append(full_name)

        # Inspect up to two rows from candidate tables to learn actual
        # column names and relationships. All statements are SELECT only.
        print("\n" + "=" * 78)
        print("SAMPLE ROWS FROM CANDIDATE TABLES (TOP 2)")
        print("=" * 78)

        for table_info in report["tables"]:
            full_name = (
                f"{table_info['schema']}.{table_info['table']}"
            )
            if full_name not in report["candidate_tables"]:
                continue

            schema_q = quote_identifier(table_info["schema"])
            table_q = quote_identifier(table_info["table"])

            sample_sql = (
                f"SELECT TOP (2) * FROM {schema_q}.{table_q}"
            )
            sample_cursor = connection.cursor()
            sample_cursor.execute(sample_sql)
            column_names = [
                item[0] for item in sample_cursor.description
            ]

            sample_rows = []
            for record in sample_cursor.fetchall():
                sample_rows.append({
                    column_names[i]: safe_value(record[i])
                    for i in range(len(column_names))
                })

            table_info["sample_rows"] = sample_rows
            print(f"\n{full_name}")
            if not sample_rows:
                print("  No rows.")
            else:
                print(json.dumps(
                    sample_rows,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ))

        # List saved BR45/BR54 raw responses without opening or modifying
        # any file. This helps identify whether a matching capture exists.
        print("\n" + "=" * 78)
        print("SAVED BR45/BR54 API FILES")
        print("=" * 78)

        api_files = sorted(
            (
                p for p in DATA_DIR.glob("*")
                if p.is_file()
                and p.suffix.lower() in (".json", ".raw")
                and ("BR45" in p.name.upper()
                     or "BR54" in p.name.upper())
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        report["recent_api_files"] = [
            {
                "name": p.name,
                "path": str(p),
                "size_bytes": p.stat().st_size,
                "modified": datetime.fromtimestamp(
                    p.stat().st_mtime
                ).isoformat(timespec="seconds"),
            }
            for p in api_files[:20]
        ]

        if not api_files:
            print("No BR45/BR54 JSON or RAW files found in api_tests.")
        else:
            for item in report["recent_api_files"]:
                print(
                    f"{item['name']} | "
                    f"{item['size_bytes']} bytes | "
                    f"{item['modified']}"
                )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = DATA_DIR / f"BR59_report_{timestamp}.json"

        with report_path.open("w", encoding="utf-8") as file:
            json.dump(
                report,
                file,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        print("\nREPORT")
        print(report_path)
        print("\nBR59 inspection completed successfully.")

    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
