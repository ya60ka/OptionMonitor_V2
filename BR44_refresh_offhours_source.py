
# BR44 - Refresh Off-Hours API Data and Validate DB Mapping
# API FETCH + READ-ONLY DATABASE VALIDATION
# No INSERT, UPDATE, DELETE, or schema changes.

from pathlib import Path
from datetime import datetime
from collections import Counter
import json
import sys

import requests
import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_CODE = "17914401175772326"
API_URL = "https://cdn.tsetmc.com/api/Instrument/GetInstrumentOptionMarketWatch/1"

API_NAME = "GetInstrumentOptionMarketWatch"
TIMEOUT_SECONDS = 30


def normalize_code(value):
    if value is None:
        return ""
    return str(value).strip()


def to_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_api_array(payload):
    if isinstance(payload, dict):
        data = payload.get("instrumentOptMarketWatch")
        if isinstance(data, list):
            return "$.instrumentOptMarketWatch", data

    raise ValueError(
        "Expected API array $.instrumentOptMarketWatch was not found."
    )


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    run_stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    raw_path = DATA_DIR / f"BR44_live_response_{run_stamp}.json"
    report_path = DATA_DIR / f"BR44_refresh_report_{run_stamp}.txt"

    lines = []

    def log(message=""):
        message = str(message)
        print(message)
        lines.append(message)

    log("=" * 78)
    log("BR44 - Refresh Off-Hours API Data and Validate DB Mapping")
    log("=" * 78)
    log(f"Started locally : {datetime.now().astimezone().isoformat(timespec='seconds')}")
    log(f"Underlying code : {UNDERLYING_CODE}")
    log(f"API URL         : {API_URL}")
    log(f"Database        : {DATABASE}")
    log("Mode            : API FETCH + DATABASE READ ONLY")
    log("")

    connection = None

    try:
        # --------------------------------------------------------------
        # 1. Fetch a fresh API response
        # --------------------------------------------------------------
        log("1. FETCHING API")
        response = requests.get(
            API_URL,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": "OptionMonitor_V2/1.0"},
        )

        log(f"HTTP status     : {response.status_code}")
        response.raise_for_status()

        raw_text = response.text
        payload = response.json()

        # Save the fresh response before further validation.
        raw_path.write_text(raw_text, encoding="utf-8")

        log(f"Response bytes  : {len(response.content):,}")
        log(f"Saved raw JSON  : {raw_path}")

        array_path, all_rows = find_api_array(payload)
        log(f"API array path  : {array_path}")
        log(f"Total API rows  : {len(all_rows):,}")

        # --------------------------------------------------------------
        # 2. Select only rows for the requested underlying
        # --------------------------------------------------------------
        underlying_rows = [
            row for row in all_rows
            if isinstance(row, dict)
            and normalize_code(row.get("uaInsCode")) == UNDERLYING_CODE
            and (
                row.get("insCode_C") is not None
                or row.get("insCode_P") is not None
            )
        ]

        log(f"Matching rows   : {len(underlying_rows)}")

        if not underlying_rows:
            raise ValueError(
                "No option rows matched the requested underlying code. "
                "Inspect the saved raw response before proceeding."
            )

        # --------------------------------------------------------------
        # 3. Build option IDs and inspect source field quality
        # --------------------------------------------------------------
        source_ids = []
        side_counts = Counter()
        source_id_counts = Counter()

        fields = [
            "pDrCotVal",
            "pClosing",
            "priceYesterday",
            "pMeDem",
            "qTitMeDem",
            "pMeOf",
            "qTitMeOf",
            "oP",
            "yesterdayOP",
            "notionalValue",
            "qTotCap",
            "zTotTran",
            "qTotTran5J",
        ]

        field_stats = {
            field: {"valid": 0, "positive": 0, "zero": 0, "negative": 0}
            for field in fields
        }

        for row in underlying_rows:
            for side in ("C", "P"):
                ins_code = normalize_code(row.get(f"insCode_{side}"))
                if not ins_code:
                    continue

                source_ids.append(ins_code)
                side_counts[side] += 1
                source_id_counts[ins_code] += 1

                for field in fields:
                    value = to_number(row.get(f"{field}_{side}"))
                    if value is None:
                        continue

                    stats = field_stats[field]
                    stats["valid"] += 1

                    if value > 0:
                        stats["positive"] += 1
                    elif value == 0:
                        stats["zero"] += 1
                    else:
                        stats["negative"] += 1

        duplicate_source_ids = sorted(
            code for code, count in source_id_counts.items() if count > 1
        )

        log("")
        log("2. SOURCE CONTRACT VALIDATION")
        log(f"CALL contracts   : {side_counts['C']}")
        log(f"PUT contracts    : {side_counts['P']}")
        log(f"Total IDs        : {len(source_ids)}")
        log(f"Unique IDs       : {len(set(source_ids))}")
        log(f"Duplicate IDs    : {len(duplicate_source_ids)}")

        if duplicate_source_ids:
            log("Duplicate samples: " + ", ".join(duplicate_source_ids[:10]))

        log("")
        log("3. SOURCE FIELD QUALITY")
        log(
            f"{'Field':<20} {'Valid':>7} {'Positive':>10} "
            f"{'Zero':>8} {'Negative':>10}"
        )

        for field in fields:
            stats = field_stats[field]
            log(
                f"{field:<20} {stats['valid']:>7} "
                f"{stats['positive']:>10} {stats['zero']:>8} "
                f"{stats['negative']:>10}"
            )

        # --------------------------------------------------------------
        # 4. Read-only database validation
        # --------------------------------------------------------------
        log("")
        log("4. DATABASE CONTRACT MATCHING")

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
                "Expected exactly one matching underlying in the database; "
                f"found {len(underlying_matches)}."
            )

        underlying_id = underlying_matches[0][0]
        log(f"UnderlyingID    : {underlying_id}")

        cursor.execute("""
            SELECT TSEInsCode
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
        """, underlying_id)

        db_ids = {
            normalize_code(row[0])
            for row in cursor.fetchall()
        }

        source_id_set = set(source_ids)
        missing_in_db = sorted(source_id_set - db_ids)
        missing_in_api = sorted(db_ids - source_id_set)

        log(f"DB contracts    : {len(db_ids)}")
        log(f"API unique IDs  : {len(source_id_set)}")
        log(f"Missing in DB   : {len(missing_in_db)}")
        log(f"Missing in API  : {len(missing_in_api)}")

        if missing_in_db:
            log("Missing DB samples: " + ", ".join(missing_in_db[:10]))
        if missing_in_api:
            log("Missing API samples: " + ", ".join(missing_in_api[:10]))

        # --------------------------------------------------------------
        # 5. Inspect underlying values available in the fresh response
        # --------------------------------------------------------------
        log("")
        log("5. UNDERLYING FIELDS")

        sample = underlying_rows[0]
        underlying_fields = [
            "lval30_UA",
            "pDrCotVal_UA",
            "pClosing_UA",
            "priceYesterday_UA",
        ]

        for field in underlying_fields:
            log(f"{field:<22}: {sample.get(field)!r}")

        # --------------------------------------------------------------
        # 6. Readiness decision (no DB writes)
        # --------------------------------------------------------------
        mapping_ok = (
            len(underlying_rows) > 0
            and len(source_ids) == len(source_id_set)
            and not duplicate_source_ids
            and not missing_in_db
            and not missing_in_api
            and len(source_id_set) == len(db_ids)
        )

        log("")
        log("=" * 78)
        log("BR44 RESULT")
        log(f"Fresh response saved : YES")
        log(f"Source/database match: {'PASS' if mapping_ok else 'CHECK REQUIRED'}")
        log("Database writes      : NONE")
        log("Schema changes       : NONE")
        log("=" * 78)

    except Exception as exc:
        log("")
        log("BR44 ERROR")
        log(f"{type(exc).__name__}: {exc}")
        log("No database writes were performed.")
        raise

    finally:
        if connection is not None:
            connection.close()

        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
