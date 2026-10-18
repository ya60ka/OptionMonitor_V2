
# BR46 - Verify First Snapshot Capture
# Read-only verification. No database writes.

import sys
from datetime import date, datetime, time
from decimal import Decimal

import pyodbc


SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
EXPECTED_OPTIONS = 84
EXPECTED_UNDERLYING = 1
EXPECTED_RAW_RESPONSES = 1

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
)

OPTION_FIELDS = [
    "DataDate",
    "DataTime",
    "LastPrice",
    "ClosingPrice",
    "FirstPrice",
    "MinPrice",
    "MaxPrice",
    "YesterdayPrice",
    "PriceChange",
    "PriceChangePercent",
    "TradeCount",
    "Volume",
    "TradeValue",
    "BestBuyPrice",
    "BestBuyVolume",
    "BestSellPrice",
    "BestSellVolume",
    "OpenInterest",
    "UnderlyingLastPrice",
    "UnderlyingClosePrice",
    "ContractSize",
    "SourceRetrievedAt",
]

UNDERLYING_FIELDS = [
    "DataDate",
    "DataTime",
    "LastPrice",
    "ClosingPrice",
    "YesterdayPrice",
    "PriceChange",
    "PriceChangePercent",
    "TradeCount",
    "Volume",
    "TradeValue",
    "SourceRetrievedAt",
]


def heading(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def same_value(a, b):
    # SQL Server may return equivalent numeric values
    # using different Python numeric types.
    if a is None or b is None:
        return a is None and b is None

    if isinstance(a, (int, float, Decimal)) and isinstance(
        b, (int, float, Decimal)
    ):
        return Decimal(str(a)) == Decimal(str(b))

    return a == b


def compare_rows(cursor, table_snapshot, table_current, key, fields):
    select_fields = ", ".join(f"[{field}]" for field in fields)

    cursor.execute(
        f"SELECT [{key}], {select_fields} "
        f"FROM dbo.{table_snapshot}"
    )
    snapshot_rows = {
        row[0]: tuple(row[1:])
        for row in cursor.fetchall()
    }

    cursor.execute(
        f"SELECT [{key}], {select_fields} "
        f"FROM dbo.{table_current}"
    )
    current_rows = {
        row[0]: tuple(row[1:])
        for row in cursor.fetchall()
    }

    missing_current = sorted(set(snapshot_rows) - set(current_rows))
    missing_snapshot = sorted(set(current_rows) - set(snapshot_rows))
    mismatches = []

    for record_id in sorted(set(snapshot_rows) & set(current_rows)):
        snap = snapshot_rows[record_id]
        curr = current_rows[record_id]

        for index, field in enumerate(fields):
            if not same_value(snap[index], curr[index]):
                mismatches.append(
                    (record_id, field, snap[index], curr[index])
                )

    print(f"Snapshot table       : {table_snapshot}")
    print(f"Current table        : {table_current}")
    print(f"Snapshot records     : {len(snapshot_rows)}")
    print(f"Current records      : {len(current_rows)}")
    print(f"Missing from Current : {len(missing_current)}")
    print(f"Missing from Snapshot: {len(missing_snapshot)}")
    print(f"Field mismatches     : {len(mismatches)}")

    if mismatches:
        print("\nFirst 20 mismatches:")
        for item in mismatches[:20]:
            record_id, field, snap, curr = item
            print(
                f"  ID={record_id}, field={field}, "
                f"snapshot={snap!r}, current={curr!r}"
            )

    passed = (
        not missing_current
        and not missing_snapshot
        and not mismatches
    )
    print(f"Result               : {'PASS' if passed else 'FAIL'}")
    return passed


def main():
    connection = None
    overall_pass = True

    heading("BR46 - First Snapshot Read-Only Verification")
    print(f"SQL Server : {SERVER}")
    print(f"Database   : {DATABASE}")
    print("Mode       : READ ONLY")

    try:
        connection = pyodbc.connect(
            CONNECTION_STRING,
            timeout=15,
            autocommit=True,
        )
        cursor = connection.cursor()

        heading("1. Latest Collection Run")

        cursor.execute("""
            SELECT TOP (1)
                CollectionRunID,
                JobName,
                StartedAt,
                FinishedAt,
                Status,
                ItemsRequested,
                ItemsSucceeded,
                ItemsFailed,
                Summary
            FROM dbo.CollectionRun
            ORDER BY CollectionRunID DESC
        """)

        run = cursor.fetchone()
        if run is None:
            print("FAIL: No CollectionRun record found.")
            sys.exit(1)

        run_id = run.CollectionRunID
        print(f"CollectionRunID : {run_id}")
        print(f"JobName         : {run.JobName}")
        print(f"StartedAt       : {run.StartedAt}")
        print(f"FinishedAt      : {run.FinishedAt}")
        print(f"Status          : {run.Status}")
        print(f"ItemsRequested  : {run.ItemsRequested}")
        print(f"ItemsSucceeded  : {run.ItemsSucceeded}")
        print(f"ItemsFailed     : {run.ItemsFailed}")
        print(f"Summary         : {run.Summary}")

        if str(run.Status).upper() != "SUCCESS":
            overall_pass = False
            print("FAIL: Latest run status is not SUCCESS.")
        else:
            print("PASS: Latest run status is SUCCESS.")

        heading("2. Raw API Response")

        cursor.execute("""
            SELECT
                COUNT(*) AS TotalResponses,
                SUM(CASE WHEN IsSuccess = 1 THEN 1 ELSE 0 END)
                    AS SuccessfulResponses
            FROM dbo.RawApiResponse
            WHERE CollectionRunID = ?
        """, run_id)

        raw = cursor.fetchone()
        raw_count = raw.TotalResponses or 0
        raw_success = raw.SuccessfulResponses or 0

        print(f"Raw responses for run : {raw_count}")
        print(f"Successful responses  : {raw_success}")

        if (
            raw_count != EXPECTED_RAW_RESPONSES
            or raw_success != EXPECTED_RAW_RESPONSES
        ):
            overall_pass = False
            print("FAIL: Raw response count does not match expectation.")
        else:
            print("PASS: Raw response stored successfully.")

        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.RawApiResponse
            WHERE CollectionRunID = ?
              AND IsSuccess = 1
              AND ResponseJSON IS NOT NULL
              AND LEN(ResponseJSON) > 0
        """, run_id)

        json_count = cursor.fetchone()[0]
        print(f"Non-empty JSON payloads : {json_count}")

        if json_count != EXPECTED_RAW_RESPONSES:
            overall_pass = False
            print("FAIL: Expected raw JSON payload is missing.")
        else:
            print("PASS: Raw JSON payload exists.")

        heading("3. Snapshot and Current Record Counts")

        count_queries = [
            (
                "OptionLiveSnapshot",
                "SELECT COUNT(*) FROM dbo.OptionLiveSnapshot",
                EXPECTED_OPTIONS,
            ),
            (
                "OptionLiveCurrent",
                "SELECT COUNT(*) FROM dbo.OptionLiveCurrent",
                EXPECTED_OPTIONS,
            ),
            (
                "UnderlyingLiveSnapshot",
                "SELECT COUNT(*) FROM dbo.UnderlyingLiveSnapshot",
                EXPECTED_UNDERLYING,
            ),
            (
                "UnderlyingLiveCurrent",
                "SELECT COUNT(*) FROM dbo.UnderlyingLiveCurrent",
                EXPECTED_UNDERLYING,
            ),
        ]

        for name, query, expected in count_queries:
            cursor.execute(query)
            actual = cursor.fetchone()[0]
            passed = actual == expected
            print(
                f"{name:<26} actual={actual:<5} "
                f"expected={expected:<5} "
                f"{'PASS' if passed else 'FAIL'}"
            )
            if not passed:
                overall_pass = False

        heading("4. Option Snapshot vs Current")

        option_pass = compare_rows(
            cursor,
            "OptionLiveSnapshot",
            "OptionLiveCurrent",
            "OptionID",
            OPTION_FIELDS,
        )
        if not option_pass:
            overall_pass = False

        heading("5. Underlying Snapshot vs Current")

        underlying_pass = compare_rows(
            cursor,
            "UnderlyingLiveSnapshot",
            "UnderlyingLiveCurrent",
            "UnderlyingID",
            UNDERLYING_FIELDS,
        )
        if not underlying_pass:
            overall_pass = False

        heading("6. Contract Mapping and NULL Price Extrema")

        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.OptionContract
            WHERE UnderlyingID = 1
        """)
        contract_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.OptionLiveSnapshot s
            INNER JOIN dbo.OptionContract c
                ON c.OptionID = s.OptionID
            WHERE c.UnderlyingID = 1
        """)
        mapped_snapshot_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM dbo.OptionLiveSnapshot
            WHERE FirstPrice IS NULL
              AND MinPrice IS NULL
              AND MaxPrice IS NULL
        """)
        null_extrema_count = cursor.fetchone()[0]

        print(f"Registered contracts       : {contract_count}")
        print(f"Snapshots joined to contracts: {mapped_snapshot_count}")
        print(f"Snapshots with all extrema NULL: {null_extrema_count}")

        if contract_count != EXPECTED_OPTIONS:
            overall_pass = False
            print("FAIL: Registered contract count differs from expectation.")

        if mapped_snapshot_count != EXPECTED_OPTIONS:
            overall_pass = False
            print("FAIL: Some snapshots do not map to expected contracts.")

        if null_extrema_count != EXPECTED_OPTIONS:
            overall_pass = False
            print("FAIL: Unexpected non-NULL price extrema detected.")
        else:
            print("PASS: Unmapped extrema remain NULL as intended.")

        heading("BR46 FINAL RESULT")
        print("Overall result:", "PASS" if overall_pass else "FAIL")
        print("Database writes: NONE")
        print("Old database touched: NO")

        if not overall_pass:
            sys.exit(2)

    except SystemExit:
        raise
    except Exception as exc:
        print(f"\nBR46 ERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
