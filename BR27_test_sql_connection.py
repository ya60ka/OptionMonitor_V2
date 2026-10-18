
# BR27 - SQL Server Connection Diagnostic
# Version: 1.0
# Purpose: Diagnose ODBC connection failures.
# Safety: READ ONLY. No database changes.

from __future__ import annotations

import pyodbc


DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

SERVER_OPTIONS = [
    ("PC1040138", "SERVER=PC1040138;"),
    ("TCP", "SERVER=tcp:PC1040138;"),
    ("LOCALHOST", "SERVER=localhost;"),
]


def main() -> int:
    print("=" * 72)
    print("BR27 - SQL Server Connection Diagnostic")
    print("=" * 72)
    print(f"Python ODBC Driver : {DRIVER}")
    print(f"Target database    : {DATABASE}")
    print("Database writes    : DISABLED")
    print()

    for label, server_setting in SERVER_OPTIONS:
        connection_string = (
            f"DRIVER={{{DRIVER}}};"
            f"{server_setting}"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
            "Connection Timeout=5;"
            "ApplicationIntent=ReadOnly;"
        )

        print("-" * 72)
        print(f"Testing: {label}")

        connection = None

        try:
            connection = pyodbc.connect(connection_string)

            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT
                    @@SERVERNAME AS ServerName,
                    DB_NAME() AS DatabaseName,
                    SUSER_SNAME() AS LoginName;
                """
            )

            row = cursor.fetchone()

            print("RESULT: SUCCESS")
            print(f"Server   : {row.ServerName}")
            print(f"Database : {row.DatabaseName}")
            print(f"Login    : {row.LoginName}")

            cursor.close()

        except pyodbc.Error as exc:
            print("RESULT: FAILED")
            print(f"Error: {exc}")

        finally:
            if connection is not None:
                connection.close()

    print()
    print("=" * 72)
    print("Diagnostic completed. No database writes were performed.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
