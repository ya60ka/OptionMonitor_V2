
# BR32 - Final Imported Contract Verification (READ ONLY)

import sys
import pyodbc

DB_NAME = "OptionMarketDB_V2"
UNDERLYING_CODE = "17914401175772326"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    f"DATABASE={DB_NAME};"
    "Trusted_Connection=yes;"
    "ApplicationIntent=ReadOnly;"
)


def main():
    print("=" * 72)
    print("BR32 - Final Imported Contract Verification (READ ONLY)")
    print("=" * 72)

    connection = None

    try:
        connection = pyodbc.connect(CONNECTION_STRING, timeout=15)
        cursor = connection.cursor()

        cursor.execute("SELECT DB_NAME();")
        database = cursor.fetchone()[0]

        if database != DB_NAME:
            raise RuntimeError(f"Unexpected database: {database}")

        cursor.execute(
            """
            SELECT UnderlyingID
            FROM dbo.Underlying
            WHERE TSEInsCode = ?;
            """,
            UNDERLYING_CODE,
        )
        underlying_rows = cursor.fetchall()

        if len(underlying_rows) != 1:
            raise RuntimeError(
                f"Expected one underlying, found {len(underlying_rows)}"
            )

        underlying_id = underlying_rows[0][0]

        cursor.execute(
            """
            SELECT
                COUNT(*) AS TotalContracts,
                COUNT(DISTINCT TSEInsCode) AS UniqueContractCodes,
                SUM(CASE WHEN OptionType = 'C' THEN 1 ELSE 0 END) AS Calls,
                SUM(CASE WHEN OptionType = 'P' THEN 1 ELSE 0 END) AS Puts,
                SUM(CASE WHEN TSEInsCode IS NULL THEN 1 ELSE 0 END)
                    AS MissingCodes,
                SUM(CASE WHEN StrikePrice IS NULL THEN 1 ELSE 0 END)
                    AS MissingStrikes,
                SUM(CASE WHEN ExpiryDate IS NULL THEN 1 ELSE 0 END)
                    AS MissingGregorianExpiry,
                SUM(CASE WHEN ExpiryDatePersian IS NULL THEN 1 ELSE 0 END)
                    AS MissingPersianExpiry,
                SUM(CASE WHEN ContractSize IS NULL OR ContractSize <= 0
                    THEN 1 ELSE 0 END) AS InvalidContractSize,
                SUM(CASE WHEN IsActive = 1 THEN 1 ELSE 0 END) AS ActiveContracts
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?;
            """,
            underlying_id,
        )

        row = cursor.fetchone()

        print(f"Database: {database}")
        print(f"UnderlyingID: {underlying_id}")
        print()
        print(f"Total contracts: {row.TotalContracts}")
        print(f"Unique contract IDs: {row.UniqueContractCodes}")
        print(f"CALL: {row.Calls}")
        print(f"PUT: {row.Puts}")
        print(f"Missing IDs: {row.MissingCodes or 0}")
        print(f"Missing strikes: {row.MissingStrikes or 0}")
        print(
            f"Missing Gregorian expiry: "
            f"{row.MissingGregorianExpiry or 0}"
        )
        print(
            f"Missing Persian expiry: "
            f"{row.MissingPersianExpiry or 0}"
        )
        print(f"Invalid contract sizes: {row.InvalidContractSize or 0}")
        print(f"Active contracts: {row.ActiveContracts}")

        print("\nContracts grouped by expiry:")
        cursor.execute(
            """
            SELECT
                ExpiryDate,
                ExpiryDatePersian,
                COUNT(*) AS ContractCount,
                SUM(CASE WHEN OptionType = 'C' THEN 1 ELSE 0 END) AS Calls,
                SUM(CASE WHEN OptionType = 'P' THEN 1 ELSE 0 END) AS Puts
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
            GROUP BY ExpiryDate, ExpiryDatePersian
            ORDER BY ExpiryDate;
            """,
            underlying_id,
        )

        for expiry in cursor.fetchall():
            print(
                f"{expiry.ExpiryDate} | {expiry.ExpiryDatePersian} | "
                f"Total={expiry.ContractCount} | "
                f"CALL={expiry.Calls} | PUT={expiry.Puts}"
            )

        checks = {
            "Total contracts": row.TotalContracts == 84,
            "Unique contract IDs": row.UniqueContractCodes == 84,
            "CALL count": row.Calls == 42,
            "PUT count": row.Puts == 42,
            "No missing IDs": (row.MissingCodes or 0) == 0,
            "No missing strikes": (row.MissingStrikes or 0) == 0,
            "No missing Gregorian expiry":
                (row.MissingGregorianExpiry or 0) == 0,
            "No missing Persian expiry":
                (row.MissingPersianExpiry or 0) == 0,
            "Valid contract sizes": (row.InvalidContractSize or 0) == 0,
            "All contracts active": row.ActiveContracts == 84,
        }

        print("\nVERIFICATION CHECKS")
        print("-" * 72)

        for name, passed in checks.items():
            print(f"{'PASS' if passed else 'FAIL'} | {name}")

        if all(checks.values()):
            print("\nBR32 RESULT: ALL CHECKS PASSED")
        else:
            print("\nBR32 RESULT: CHECKS FAILED")
            sys.exit(1)

    except Exception as exc:
        print(f"\nBR32 ERROR: {type(exc).__name__}: {exc}")
        sys.exit(2)

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
