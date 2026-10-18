
# BR68 - READ-ONLY TIMESTAMP AND SNAPSHOT AUDIT
# Database: OptionMarketDB_V2
# Writes: NONE

import pyodbc

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

CONN_STR = (
    f"DRIVER={{{DRIVER}}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def print_section(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def main():
    print_section("BR68 - TIMESTAMP AND SNAPSHOT AUDIT")
    print(f"Server   : {SERVER}")
    print(f"Database : {DATABASE}")
    print("Mode     : READ ONLY")
    print("Writes   : NONE")

    with pyodbc.connect(CONN_STR, autocommit=True) as conn:
        cur = conn.cursor()

        # 1. CollectionRun: inspect schema and records
        print_section("1. COLLECTION RUN")

        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo'
              AND TABLE_NAME = 'CollectionRun'
            ORDER BY ORDINAL_POSITION
        """)

        columns = [row.COLUMN_NAME for row in cur.fetchall()]
        print("Columns:", ", ".join(columns) if columns else "(none)")

        if columns:
            cur.execute("SELECT TOP (10) * FROM dbo.CollectionRun")
            names = [d[0] for d in cur.description]
            for row in cur.fetchall():
                print(" | ".join(
                    f"{name}={value}"
                    for name, value in zip(names, row)
                ))

        # 2. Raw API response metadata only
        print_section("2. RAW API RESPONSE METADATA")

        cur.execute("""
            SELECT
                RawDataID,
                CollectionRunID,
                APIName,
                RetrievedAt,
                HttpStatusCode,
                IsSuccess,
                CASE
                    WHEN ResponseJSON IS NULL THEN 0
                    ELSE DATALENGTH(ResponseJSON)
                END AS ResponseBytes
            FROM dbo.RawApiResponse
            ORDER BY RetrievedAt DESC
        """)

        for row in cur.fetchall():
            print(
                f"RawDataID={row.RawDataID} | "
                f"CollectionRunID={row.CollectionRunID} | "
                f"API={row.APIName} | "
                f"RetrievedAt={row.RetrievedAt} | "
                f"HTTP={row.HttpStatusCode} | "
                f"Success={row.IsSuccess} | "
                f"ResponseBytes={row.ResponseBytes}"
            )

        # 3. Option snapshot time distribution
        print_section("3. OPTION SNAPSHOT TIMESTAMPS")

        cur.execute("""
            SELECT
                COUNT(*) AS RecordCount,
                COUNT(DISTINCT SourceRetrievedAt) AS DistinctSourceTimes,
                MIN(SourceRetrievedAt) AS FirstSourceTime,
                MAX(SourceRetrievedAt) AS LastSourceTime,
                MIN(DataDate) AS MinDataDate,
                MAX(DataDate) AS MaxDataDate,
                MIN(DataTime) AS MinDataTime,
                MAX(DataTime) AS MaxDataTime,
                MIN(SnapshotID) AS MinSnapshotID,
                MAX(SnapshotID) AS MaxSnapshotID
            FROM dbo.OptionLiveSnapshot
        """)

        row = cur.fetchone()
        for name, value in zip(
            [d[0] for d in cur.description], row
        ):
            print(f"{name}: {value}")

        print("\nSnapshot rows grouped by source retrieval time:")

        cur.execute("""
            SELECT
                SourceRetrievedAt,
                COUNT(*) AS RecordCount,
                MIN(DataDate) AS MinDataDate,
                MAX(DataDate) AS MaxDataDate,
                MIN(DataTime) AS MinDataTime,
                MAX(DataTime) AS MaxDataTime,
                MIN(SnapshotID) AS MinSnapshotID,
                MAX(SnapshotID) AS MaxSnapshotID
            FROM dbo.OptionLiveSnapshot
            GROUP BY SourceRetrievedAt
            ORDER BY SourceRetrievedAt
        """)

        for row in cur.fetchall():
            print(
                f"SourceRetrievedAt={row.SourceRetrievedAt} | "
                f"Count={row.RecordCount} | "
                f"DataDate={row.MinDataDate}..{row.MaxDataDate} | "
                f"DataTime={row.MinDataTime}..{row.MaxDataTime} | "
                f"SnapshotID={row.MinSnapshotID}..{row.MaxSnapshotID}"
            )

        # 4. Current option data timestamps
        print_section("4. OPTION LIVE CURRENT TIMESTAMPS")

        cur.execute("""
            SELECT
                COUNT(*) AS RecordCount,
                COUNT(DISTINCT SourceRetrievedAt) AS DistinctSourceTimes,
                MIN(SourceRetrievedAt) AS FirstSourceTime,
                MAX(SourceRetrievedAt) AS LastSourceTime,
                MIN(UpdatedAt) AS FirstUpdatedAt,
                MAX(UpdatedAt) AS LastUpdatedAt,
                MIN(DataDate) AS MinDataDate,
                MAX(DataDate) AS MaxDataDate,
                MIN(DataTime) AS MinDataTime,
                MAX(DataTime) AS MaxDataTime
            FROM dbo.OptionLiveCurrent
        """)

        row = cur.fetchone()
        for name, value in zip(
            [d[0] for d in cur.description], row
        ):
            print(f"{name}: {value}")

        # 5. Underlying timestamps
        print_section("5. UNDERLYING TIMESTAMPS")

        for table in ("UnderlyingLiveCurrent", "UnderlyingLiveSnapshot"):
            cur.execute(f"""
                SELECT
                    COUNT(*) AS RecordCount,
                    MIN(SourceRetrievedAt) AS FirstSourceTime,
                    MAX(SourceRetrievedAt) AS LastSourceTime,
                    MIN(DataDate) AS MinDataDate,
                    MAX(DataDate) AS MaxDataDate,
                    MIN(DataTime) AS MinDataTime,
                    MAX(DataTime) AS MaxDataTime
                FROM dbo.{table}
            """)

            row = cur.fetchone()
            print(f"\nTable: dbo.{table}")
            for name, value in zip(
                [d[0] for d in cur.description], row
            ):
                print(f"  {name}: {value}")

    print_section("END OF BR68")
    print("No records inserted, updated, or deleted.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        raise
