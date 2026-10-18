"""Option Monitor V2 - database connection module.

Purpose:
- Connect to SQL Server database OptionMarketDB_V2 using Windows Authentication.
- Verify the active database and required schema tables.
- Confirm that the underlying instrument اهرم is registered.

This file does not create, delete, or modify database tables or market data.
"""

from __future__ import annotations

import sys
from typing import Final

import pyodbc

SQL_SERVER: Final[str] = r"localhost"
SQL_DATABASE: Final[str] = "OptionMarketDB_V2"
ODBC_DRIVER: Final[str] = "ODBC Driver 17 for SQL Server"

EXPECTED_TABLES: Final[set[str]] = {
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


def get_connection() -> pyodbc.Connection:
    """Return a connection to OptionMarketDB_V2 using Windows Authentication."""
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string, timeout=10)


def check_database() -> int:
    """Run read-only checks and return a process exit code (0=success)."""
    print("Option Monitor V2 - Database Connection Check")
    print("=" * 48)

    try:
        with get_connection() as connection:
            cursor = connection.cursor()

            row = cursor.execute(
                "SELECT @@SERVERNAME AS ServerName, DB_NAME() AS DatabaseName;"
            ).fetchone()
            server_name, database_name = row[0], row[1]
            print(f"SQL Server : {server_name}")
            print(f"Database   : {database_name}")

            if database_name != SQL_DATABASE:
                print(f"ERROR: Connected to unexpected database: {database_name}")
                return 1

            rows = cursor.execute(
                "SELECT name FROM sys.tables WHERE is_ms_shipped = 0 ORDER BY name;"
            ).fetchall()
            actual_tables = {r[0] for r in rows}
            missing = sorted(EXPECTED_TABLES - actual_tables)
            extra = sorted(actual_tables - EXPECTED_TABLES)

            print(f"Tables found: {len(actual_tables)}")
            if missing:
                print("Missing expected tables:")
                for table in missing:
                    print(f"  - {table}")
            else:
                print("Schema check: all 12 expected tables exist.")

            if extra:
                print("Additional tables:")
                for table in extra:
                    print(f"  - {table}")

            underlying = cursor.execute(
                """
                SELECT UnderlyingID, TSEInsCode, Symbol, InstrumentName, IsActive
                FROM dbo.Underlying
                WHERE TSEInsCode = ?;
                """,
                "17914401175772326",
            ).fetchone()

            if underlying:
                print("Underlying اهرم: found")
                print(f"  UnderlyingID : {underlying[0]}")
                print(f"  TSEInsCode   : {underlying[1]}")
                print(f"  Symbol       : {underlying[2]}")
                print(f"  IsActive     : {underlying[4]}")
            else:
                print("ERROR: Underlying اهرم was not found in dbo.Underlying.")

            if missing or not underlying:
                print("\nRESULT: CHECK FAILED. No data was changed.")
                return 1

            print("\nRESULT: CONNECTION AND BASIC SCHEMA CHECK PASSED.")
            print("No data was inserted, updated, or deleted by this test.")
            return 0

    except pyodbc.Error as exc:
        print("\nSQL SERVER CONNECTION/QUERY ERROR:")
        print(exc)
        print("\nCheck SQL_SERVER, Windows Authentication, and ODBC Driver 17.")
        return 2
    except Exception as exc:
        print("\nUNEXPECTED ERROR:")
        print(exc)
        return 3


if __name__ == "__main__":
    sys.exit(check_database())
