
# BR70 - Live Capture Readiness Audit
# Read-only audit of latest BR44 response and OptionMarketDB_V2 mapping.
# No INSERT, UPDATE, DELETE, or schema changes.
# The legacy database OptionMarketDB is never accessed.

from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import json
import sys

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_CODE = "17914401175772326"

EXPECTED_ROWS = 42
EXPECTED_CONTRACTS = 84
MAX_FILE_AGE_HOURS = 24


def section(title):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)


def normalize_code(value):
    return "" if value is None else str(value).strip()


def parse_timestamp(value):
    if value is None:
        return None

    text = str(value).strip()

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def find_api_array(payload):
    if not isinstance(payload, dict):
        raise ValueError("API root is not a JSON object.")

    rows = payload.get("instrumentOptMarketWatch")

    if not isinstance(rows, list):
        raise ValueError(
            "Expected $.instrumentOptMarketWatch array was not found."
        )

    return rows


def main():
    print("=" * 110)
    print("BR70 - LIVE CAPTURE READINESS AUDIT")
    print("=" * 110)
    print(f"Server             : {SERVER}")
    print(f"Database           : {DATABASE}")
    print("Mode               : READ ONLY")
    print("Database writes    : NONE")
    print("Schema changes     : NONE")
    print("Legacy DB accessed : NO")

    findings = []
    connection = None

    try:
        # ----------------------------------------------------------
        # 1. Locate the latest BR44 response
        # ----------------------------------------------------------
        section("1. LATEST BR44 RESPONSE")

        candidates = sorted(
            DATA_DIR.glob("BR44_live_response_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        if not candidates:
            raise FileNotFoundError(
                f"No BR44 response files found in {DATA_DIR}"
            )

        source_path = candidates[0]
        file_mtime = datetime.fromtimestamp(
            source_path.stat().st_mtime,
            tz=timezone.utc,
        )
        now_utc = datetime.now(timezone.utc)
        file_age_hours = (
            now_utc - file_mtime
        ).total_seconds() / 3600

        print(f"Source file        : {source_path}")
        print(f"File modified UTC  : {file_mtime.isoformat()}")
        print(f"File age hours     : {file_age_hours:.2f}")
        print(f"Age threshold hours: {MAX_FILE_AGE_HOURS}")

        if file_age_hours < 0:
            findings.append("File modification time is in the future.")
        elif file_age_hours > MAX_FILE_AGE_HOURS:
            findings.append("Latest BR44 response file is older than 24 hours.")

        raw_text = source_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        rows = find_api_array(payload)

        print(f"Response bytes     : {source_path.stat().st_size:,}")
        print(f"Total API rows     : {len(rows)}")

        # ----------------------------------------------------------
        # 2. Select underlying rows and validate contract IDs
        # ----------------------------------------------------------
        section("2. SOURCE CONTRACT VALIDATION")

        underlying_rows = [
            row for row in rows
            if isinstance(row, dict)
            and normalize_code(row.get("uaInsCode")) == UNDERLYING_CODE
            and (
                row.get("insCode_C") is not None
                or row.get("insCode_P") is not None
            )
        ]

        print(f"Matching rows      : {len(underlying_rows)}")

        side_counts = Counter()
        source_ids = []
        source_id_counts = Counter()
        missing_side_ids = 0

        for row in underlying_rows:
            for side in ("C", "P"):
                code = normalize_code(row.get(f"insCode_{side}"))

                if not code:
                    continue

                side_counts[side] += 1
                source_ids.append(code)
                source_id_counts[code] += 1

            if (
                not normalize_code(row.get("insCode_C"))
                or not normalize_code(row.get("insCode_P"))
            ):
                missing_side_ids += 1

        duplicate_ids = sorted(
            code for code, count in source_id_counts.items()
            if count > 1
        )

        source_id_set = set(source_ids)

        print(f"CALL contracts     : {side_counts['C']}")
        print(f"PUT contracts      : {side_counts['P']}")
        print(f"Total IDs          : {len(source_ids)}")
        print(f"Unique IDs         : {len(source_id_set)}")
        print(f"Duplicate IDs      : {len(duplicate_ids)}")
        print(f"Rows missing a side: {missing_side_ids}")

        if duplicate_ids:
            print("Duplicate samples  : " + ", ".join(duplicate_ids[:10]))

        if len(underlying_rows) != EXPECTED_ROWS:
            findings.append(
                f"Expected {EXPECTED_ROWS} source rows; "
                f"found {len(underlying_rows)}."
            )

        if len(source_ids) != EXPECTED_CONTRACTS:
            findings.append(
                f"Expected {EXPECTED_CONTRACTS} contracts; "
                f"found {len(source_ids)}."
            )

        if len(source_id_set) != EXPECTED_CONTRACTS:
            findings.append("Source contract IDs are not all unique.")

        if side_counts["C"] != 42 or side_counts["P"] != 42:
            findings.append("Expected 42 CALL and 42 PUT contracts.")

        if duplicate_ids:
            findings.append("Duplicate source contract IDs were found.")

        if missing_side_ids:
            findings.append("One or more source rows are missing CALL or PUT IDs.")

        # ----------------------------------------------------------
        # 3. Underlying price consistency
        # ----------------------------------------------------------
        section("3. UNDERLYING PRICE VALIDATION")

        price_fields = [
            "pDrCotVal_UA",
            "pClosing_UA",
            "priceYesterday_UA",
        ]

        underlying_values = {}

        if not underlying_rows:
            findings.append("No underlying rows are available for validation.")
        else:
            for field in price_fields:
                values = {
                    str(row.get(field)).strip()
                    for row in underlying_rows
                }

                underlying_values[field] = values

                print(
                    f"{field:<24}: "
                    f"distinct_values={len(values)}"
                )

                if len(values) != 1:
                    findings.append(
                        f"Inconsistent underlying field: {field}."
                    )

                value = underlying_rows[0].get(field)

                try:
                    number = float(value)
                except (TypeError, ValueError):
                    number = None

                print(f"{'Sample value':<24}: {value!r}")

                if number is None or number <= 0:
                    findings.append(
                        f"Missing, invalid, or non-positive {field}."
                    )

        # ----------------------------------------------------------
        # 4. Read-only database contract mapping
        # ----------------------------------------------------------
        section("4. DATABASE CONTRACT MAPPING")

        connection_string = (
            f"DRIVER={{{DRIVER}}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=15;"
        )

        connection = pyodbc.connect(
            connection_string,
            autocommit=True,
            timeout=15,
        )

        cursor = connection.cursor()

        cursor.execute("""
            SELECT UnderlyingID
            FROM dbo.Underlying
            WHERE TSEInsCode = ?
        """, UNDERLYING_CODE)

        underlying_matches = cursor.fetchall()

        if len(underlying_matches) != 1:
            raise ValueError(
                "Expected exactly one database underlying; "
                f"found {len(underlying_matches)}."
            )

        underlying_id = underlying_matches[0][0]

        cursor.execute("""
            SELECT TSEInsCode, OptionID
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
        """, underlying_id)

        db_rows = cursor.fetchall()

        db_code_counts = Counter(
            normalize_code(row.TSEInsCode)
            for row in db_rows
        )

        db_ids = set(db_code_counts)

        duplicate_db_ids = sorted(
            code for code, count in db_code_counts.items()
            if count > 1
        )

        missing_in_db = sorted(source_id_set - db_ids)
        missing_in_api = sorted(db_ids - source_id_set)

        print(f"UnderlyingID       : {underlying_id}")
        print(f"DB contract rows   : {len(db_rows)}")
        print(f"DB unique IDs      : {len(db_ids)}")
        print(f"Missing in DB      : {len(missing_in_db)}")
        print(f"Missing in API     : {len(missing_in_api)}")
        print(f"Duplicate DB IDs   : {len(duplicate_db_ids)}")

        if missing_in_db:
            print("Missing DB samples : " + ", ".join(missing_in_db[:10]))

        if missing_in_api:
            print("Missing API samples: " + ", ".join(missing_in_api[:10]))

        if duplicate_db_ids:
            findings.append("Duplicate contract IDs exist in the database.")

        if missing_in_db or missing_in_api:
            findings.append("API and database contract mappings do not match.")

        if len(db_rows) != EXPECTED_CONTRACTS:
            findings.append(
                f"Expected {EXPECTED_CONTRACTS} database contracts; "
                f"found {len(db_rows)}."
            )

        # ----------------------------------------------------------
        # 5. Snapshot and collection coverage
        # ----------------------------------------------------------
        section("5. EXISTING SNAPSHOT AND COLLECTION COVERAGE")

        coverage_queries = [
            (
                "OptionLiveSnapshot",
                """
                SELECT
                    COUNT_BIG(*) AS TotalRows,
                    COUNT(DISTINCT OptionID) AS DistinctInstruments,
                    COUNT(DISTINCT SourceRetrievedAt) AS DistinctSourceTimes,
                    MIN(SourceRetrievedAt) AS FirstSourceTime,
                    MAX(SourceRetrievedAt) AS LastSourceTime
                FROM dbo.OptionLiveSnapshot
                """
            ),
            (
                "UnderlyingLiveSnapshot",
                """
                SELECT
                    COUNT_BIG(*) AS TotalRows,
                    COUNT(DISTINCT UnderlyingID) AS DistinctInstruments,
                    COUNT(DISTINCT SourceRetrievedAt) AS DistinctSourceTimes,
                    MIN(SourceRetrievedAt) AS FirstSourceTime,
                    MAX(SourceRetrievedAt) AS LastSourceTime
                FROM dbo.UnderlyingLiveSnapshot
                """
            ),
            (
                "OptionDailyHistory",
                """
                SELECT
                    COUNT_BIG(*) AS TotalRows,
                    COUNT(DISTINCT OptionID) AS DistinctInstruments,
                    COUNT(DISTINCT DataDate) AS DistinctDates,
                    MIN(DataDate) AS FirstDate,
                    MAX(DataDate) AS LastDate
                FROM dbo.OptionDailyHistory
                """
            ),
            (
                "UnderlyingDailyHistory",
                """
                SELECT
                    COUNT_BIG(*) AS TotalRows,
                    COUNT(DISTINCT UnderlyingID) AS DistinctInstruments,
                    COUNT(DISTINCT DataDate) AS DistinctDates,
                    MIN(DataDate) AS FirstDate,
                    MAX(DataDate) AS LastDate
                FROM dbo.UnderlyingDailyHistory
                """
            ),
        ]

        for table_name, query in coverage_queries:
            cursor.execute(query)
            result = cursor.fetchone()

            print(f"{table_name}:")
            for index, column in enumerate(result.cursor_description or []):
                print(f"  {column[0]}: {result[index]}")

        cursor.execute("""
            SELECT
                CollectionRunID,
                JobName,
                StartedAt,
                FinishedAt,
                Status,
                ItemsRequested,
                ItemsSucceeded,
                ItemsFailed
            FROM dbo.CollectionRun
            ORDER BY CollectionRunID DESC
        """)

        run_rows = cursor.fetchmany(10)

        print()
        print("Latest collection runs:")
        if not run_rows:
            print("  (no records)")
        else:
            for row in run_rows:
                print(
                    f"  RunID={row.CollectionRunID} | "
                    f"Job={row.JobName} | Status={row.Status} | "
                    f"Requested={row.ItemsRequested} | "
                    f"Succeeded={row.ItemsSucceeded} | "
                    f"Failed={row.ItemsFailed} | "
                    f"Started={row.StartedAt} | Finished={row.FinishedAt}"
                )

        # ----------------------------------------------------------
        # 6. Final readiness decision
        # ----------------------------------------------------------
        section("6. FINAL READINESS DECISION")

        mapping_ok = (
            len(underlying_rows) == EXPECTED_ROWS
            and len(source_ids) == EXPECTED_CONTRACTS
            and len(source_id_set) == EXPECTED_CONTRACTS
            and side_counts["C"] == 42
            and side_counts["P"] == 42
            and not duplicate_ids
            and not missing_side_ids
            and not duplicate_db_ids
            and not missing_in_db
            and not missing_in_api
            and len(db_rows) == EXPECTED_CONTRACTS
        )

        freshness_ok = (
            0 <= file_age_hours <= MAX_FILE_AGE_HOURS
        )

        prices_ok = (
            len(underlying_rows) > 0
            and all(
                len(underlying_values.get(field, set())) == 1
                for field in price_fields
            )
        )

        ready = mapping_ok and freshness_ok and prices_ok

        print(f"Freshness check    : {'PASS' if freshness_ok else 'FAIL'}")
        print(f"Contract mapping   : {'PASS' if mapping_ok else 'FAIL'}")
        print(f"Underlying prices : {'PASS' if prices_ok else 'FAIL'}")
        print(f"Overall readiness  : {'PASS' if ready else 'NOT READY'}")

        if findings:
            print()
            print("FINDINGS:")
            for number, finding in enumerate(findings, 1):
                print(f"{number}. {finding}")
        else:
            print()
            print("No readiness issues detected by these checks.")

        print()
        print("Database writes    : NONE")
        print("Schema changes     : NONE")
        print("Legacy DB accessed : NO")

        print("=" * 110)
        print("END OF BR70")
        print("=" * 110)

    except Exception as exc:
        print()
        print("=" * 110)
        print("BR70 AUDIT FAILED")
        print(f"{type(exc).__name__}: {exc}")
        print("No database writes were performed.")
        print("=" * 110)
        raise

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
