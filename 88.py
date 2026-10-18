
# BR88 - Verify snapshot rows for CollectionRunID 2
# Read-only. No database writes.

import pyodbc

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"
RUN_ID = 2


def main():
    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
    )

    print("=" * 72)
    print("BR88 - CAPTURE ROW AUDIT")
    print("=" * 72)
    print(f"Database: {DATABASE}")
    print(f"CollectionRunID: {RUN_ID}")
    print("Mode: READ ONLY")

    conn = pyodbc.connect(conn_str, timeout=15)
    conn.autocommit = True

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT StartedAt, FinishedAt, Status,
                   ItemsRequested, ItemsSucceeded, ItemsFailed
            FROM dbo.CollectionRun
            WHERE CollectionRunID = ?
        """, RUN_ID)

        run = cur.fetchone()
        if not run:
            print("ERROR: CollectionRun not found.")
            return

        started, finished, status, requested, succeeded, failed = run

        print("\nA. RUN")
        print(f"StartedAt: {started}")
        print(f"FinishedAt: {finished}")
        print(f"Status: {status}")
        print(f"ItemsRequested: {requested}")
        print(f"ItemsSucceeded: {succeeded}")
        print(f"ItemsFailed: {failed}")

        # The snapshot tables do not have CollectionRunID.
        # Attribute rows to this capture using its recorded time window.
        print("\nB. OPTION SNAPSHOTS IN RUN WINDOW")

        cur.execute("""
            SELECT COUNT_BIG(*),
                   COUNT(DISTINCT OptionID),
                   MIN(SourceRetrievedAt),
                   MAX(SourceRetrievedAt)
            FROM dbo.OptionLiveSnapshot
            WHERE SourceRetrievedAt >= ?
              AND SourceRetrievedAt <= ?
        """, started, finished)

        total, distinct_options, min_time, max_time = cur.fetchone()
        print(f"Snapshot rows in window: {total}")
        print(f"Distinct OptionIDs: {distinct_options}")
        print(f"First SourceRetrievedAt: {min_time}")
        print(f"Last SourceRetrievedAt: {max_time}")

        cur.execute("""
            
            SELECT OptionID, COUNT_BIG(*) AS SnapshotCount
            FROM dbo.OptionLiveSnapshot
            WHERE SourceRetrievedAt >= ?
              AND SourceRetrievedAt <= ?
            GROUP BY OptionID
            HAVING COUNT_BIG(*) > 1
            ORDER BY OptionID
        """, started, finished)

        duplicates = cur.fetchall()
        print(f"OptionIDs with duplicate snapshots: {len(duplicates)}")
        for option_id, count in duplicates:
            print(f"  OptionID={option_id}, rows={count}")

        print("\nC. UNDERLYING SNAPSHOTS IN RUN WINDOW")

        cur.execute("""
            SELECT COUNT_BIG(*),
                   COUNT(DISTINCT UnderlyingID),
                   MIN(SourceRetrievedAt),
                   MAX(SourceRetrievedAt)
            FROM dbo.UnderlyingLiveSnapshot
            WHERE SourceRetrievedAt >= ?
              AND SourceRetrievedAt <= ?
        """, started, finished)

        u_total, u_distinct, u_min, u_max = cur.fetchone()
        print(f"Underlying snapshot rows: {u_total}")
        print(f"Distinct UnderlyingIDs: {u_distinct}")
        print(f"First SourceRetrievedAt: {u_min}")
        print(f"Last SourceRetrievedAt: {u_max}")

        print("\nD. CURRENT TABLES")

        cur.execute("""
            SELECT COUNT_BIG(*),
                   SUM(CASE WHEN SourceRetrievedAt >= ?
                                 AND SourceRetrievedAt <= ?
                            THEN 1 ELSE 0 END)
            FROM dbo.OptionLiveCurrent
        """, started, finished)

        current_total, current_matching = cur.fetchone()
        print(f"OptionLiveCurrent total rows: {current_total}")
        print(f"Rows with source time in run window: {current_matching}")

        cur.execute("""
            SELECT COUNT_BIG(*),
                   SUM(CASE WHEN SourceRetrievedAt >= ?
                                 AND SourceRetrievedAt <= ?
                            THEN 1 ELSE 0 END)
            FROM dbo.UnderlyingLiveCurrent
        """, started, finished)

        u_current_total, u_current_matching = cur.fetchone()
        print(f"UnderlyingLiveCurrent total rows: {u_current_total}")
        print(
            "Rows with source time in run window: "
            f"{u_current_matching}"
        )

        print("\nE. RAW API RESPONSE")

        cur.execute("""
            SELECT COUNT_BIG(*),
                   SUM(CASE WHEN IsSuccess = 1 THEN 1 ELSE 0 END),
                   MIN(HttpStatusCode),
                   MAX(HttpStatusCode),
                   MIN(RetrievedAt),
                   MAX(RetrievedAt)
            FROM dbo.RawApiResponse
            WHERE CollectionRunID = ?
        """, RUN_ID)

        raw_total, raw_success, http_min, http_max, raw_min, raw_max = (
            cur.fetchone()
        )

        print(f"Raw response rows for run: {raw_total}")
        print(f"Successful raw responses: {raw_success}")
        print(f"HTTP status range: {http_min} to {http_max}")
        print(f"RetrievedAt range: {raw_min} to {raw_max}")

        print("\nF. AUTOMATIC SUMMARY")

        checks = {
            "Run status SUCCESS": status == "SUCCESS",
            "85 items succeeded": succeeded == 85 and failed == 0,
            "84 option snapshots": total == 84,
            "84 distinct options": distinct_options == 84,
            "No duplicate option snapshots": len(duplicates) == 0,
            "One underlying snapshot": u_total == 1,
            "One distinct underlying": u_distinct == 1,
            "One successful raw response": (
                raw_total == 1 and raw_success == 1
            ),
            "HTTP 200": http_min == 200 and http_max == 200,
        }

        for label, passed in checks.items():
            print(f"[{'PASS' if passed else 'CHECK'}] {label}")

        if all(checks.values()):
            print("\nBR88 RESULT: ALL CHECKS PASSED")
        else:
            print("\nBR88 RESULT: REVIEW CHECKS MARKED CHECK")

        print("\nNote: snapshots are attributed by their timestamp window.")
        print("The schema has no direct CollectionRunID on snapshot rows.")
        print("No database data was modified.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
