## BR36_capture_live_market_data.py


# BR36 - Atomic Live Market Data Capture
# Project: OptionMonitor_V2
# Purpose:
#   1. Validate live API data against OptionContract.
#   2. Save raw API response and collection-run metadata.
#   3. Append OptionLiveSnapshot / UnderlyingLiveSnapshot.
#   4. Insert or update OptionLiveCurrent / UnderlyingLiveCurrent.
#   5. Perform all database writes in one SQL transaction.
#
# IMPORTANT:
#   DRY_RUN=True  : validate and report only; no database writes.
#   DRY_RUN=False : commit the complete capture atomically.

from __future__ import annotations

import json
import sys
import traceback

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyodbc


# ============================================================
# BR36-A: CONFIGURATION
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

DATABASE_SERVER = "localhost"
DATABASE_NAME = "OptionMarketDB_V2"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_INSCODE = "17914401175772326"

# First run with True. Change to False only after reviewing
# the validation report and confirming the intended database.
DRY_RUN = False

JOB_NAME = "BR36_LiveMarketDataCapture"
API_NAME = "TSETMC_GetInstrumentOptionMarketWatch"

REPORT_PREFIX = "BR36_capture_report"
PLAN_PREFIX = "BR36_capture_plan"


# ============================================================
# BR36-B: GENERAL HELPERS
# ============================================================

def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def parse_decimal(value):
    if value is None or value == "":
        return None

    try:
        result = Decimal(str(value).strip())
        if not result.is_finite():
            return None
        return result
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_int(value):
    number = parse_decimal(value)
    if number is None:
        return None

    if number != number.to_integral_value():
        raise ValueError(f"Expected integer but received {value!r}")

    return int(number)


def parse_api_date(value):
    value = normalize_text(value)
    if not value:
        return None

    return datetime.strptime(value, "%Y%m%d").date()


def utc_now_naive():
    # SQL Server datetime2 does not store timezone information.
    # This value is UTC, represented as a naive datetime.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def price_change(last_price, yesterday_price):
    if last_price is None or yesterday_price is None:
        return None
    return last_price - yesterday_price


def price_change_percent(last_price, yesterday_price):
    if (
        last_price is None
        or yesterday_price is None
        or yesterday_price == 0
    ):
        return None

    return (
        (last_price - yesterday_price)
        / yesterday_price
        * Decimal("100")
    )


def find_latest_source_file():
    files = list(DATA_DIR.glob("BR34_live_response_*.json"))

    if not files:
        raise FileNotFoundError(
            f"No BR34 source JSON found in: {DATA_DIR}"
        )

    return max(files, key=lambda item: item.stat().st_mtime)


def make_connection():
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={DATABASE_SERVER};"
        f"DATABASE={DATABASE_NAME};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(
        connection_string,
        autocommit=False,
        timeout=20,
    )


def save_json(path, payload):
    with path.open("w", encoding="utf-8") as file:
        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


# ============================================================
# BR36-C: SOURCE NORMALIZATION
# ============================================================

def build_source_rows(source_json):
    records = source_json.get("instrumentOptMarketWatch")

    if not isinstance(records, list):
        raise ValueError(
            "JSON root does not contain a valid "
            "'instrumentOptMarketWatch' array."
        )

    underlying_records = [
        item for item in records
        if normalize_text(item.get("uaInsCode"))
        == UNDERLYING_INSCODE
    ]

    if not underlying_records:
        raise ValueError(
            f"No source records found for underlying "
            f"{UNDERLYING_INSCODE}"
        )

    option_rows = []
    seen_ids = set()

    for record in underlying_records:
        for option_type in ("C", "P"):
            suffix = option_type

            inscode = normalize_text(
                record.get(f"insCode_{suffix}")
            )

            if not inscode:
                raise ValueError(
                    f"Missing insCode_{suffix} in source record."
                )

            if inscode in seen_ids:
                raise ValueError(
                    f"Duplicate source contract ID: {inscode}"
                )

            seen_ids.add(inscode)

            last_price = parse_decimal(
                record.get(f"pDrCotVal_{suffix}")
            )
            closing_price = parse_decimal(
                record.get(f"pClosing_{suffix}")
            )
            yesterday_price = parse_decimal(
                record.get(f"priceYesterday_{suffix}")
            )

            option_rows.append({
                "TSEInsCode": inscode,
                "OptionType": option_type,
                "LastPrice": last_price,
                "ClosingPrice": closing_price,
                "YesterdayPrice": yesterday_price,
                "FirstPrice": None,
                "MinPrice": None,
                "MaxPrice": None,
                "TradeCount": parse_int(
                    record.get(f"zTotTran_{suffix}")
                ),
                "Volume": parse_int(
                    record.get(f"qTotTran5J_{suffix}")
                ),
                "TradeValue": parse_decimal(
                    record.get(f"qTotCap_{suffix}")
                ),
                "BestBuyPrice": parse_decimal(
                    record.get(f"pMeDem_{suffix}")
                ),
                "BestBuyVolume": parse_int(
                    record.get(f"qTitMeDem_{suffix}")
                ),
                "BestSellPrice": parse_decimal(
                    record.get(f"pMeOf_{suffix}")
                ),
                "BestSellVolume": parse_int(
                    record.get(f"qTitMeOf_{suffix}")
                ),
                "OpenInterest": parse_int(
                    record.get(f"oP_{suffix}")
                ),
                "ContractSize": parse_int(
                    record.get("contractSize")
                ),
                "UnderlyingLastPrice": parse_decimal(
                    record.get("pDrCotVal_UA")
                ),
                "UnderlyingClosePrice": parse_decimal(
                    record.get("pClosing_UA")
                ),
            })

    underlying_rows = []

    for record in underlying_records:
        underlying_rows.append({
            "LastPrice": parse_decimal(
                record.get("pDrCotVal_UA")
            ),
            "ClosingPrice": parse_decimal(
                record.get("pClosing_UA")
            ),
            "YesterdayPrice": parse_decimal(
                record.get("priceYesterday_UA")
            ),
            "TradeCount": None,
            "Volume": None,
            "TradeValue": None,
        })

    return underlying_records, option_rows, underlying_rows


# ============================================================
# BR36-D: DATABASE READ-ONLY VALIDATION
# ============================================================

def load_database_reference_data(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT UnderlyingID, TSEInsCode, Symbol, IsActive
        FROM dbo.Underlying
        WHERE TSEInsCode = ?
    """, UNDERLYING_INSCODE)

    underlying_rows = cursor.fetchall()

    if len(underlying_rows) != 1:
        raise ValueError(
            "Expected exactly one underlying row; "
            f"found {len(underlying_rows)}."
        )

    underlying = underlying_rows[0]

    if not bool(underlying.IsActive):
        raise ValueError("Underlying is not active in the database.")

    cursor.execute("""
        SELECT
            OptionID,
            UnderlyingID,
            TSEInsCode,
            OptionType,
            StrikePrice,
            ExpiryDate,
            ExpiryDatePersian,
            ContractSize,
            IsActive
        FROM dbo.OptionContract
        WHERE UnderlyingID = ?
    """, underlying.UnderlyingID)

    contracts = cursor.fetchall()

    database_by_code = {
        normalize_text(row.TSEInsCode): row
        for row in contracts
    }

    if len(database_by_code) != len(contracts):
        raise ValueError(
            "Duplicate contract InsCodes detected in database."
        )

    return underlying, database_by_code


def validate_capture(
    source_options,
    underlying_records,
    underlying_market_rows,
    underlying,
    database_by_code,
):
    errors = []
    warnings = []

    source_by_code = {
        row["TSEInsCode"]: row
        for row in source_options
    }

    if len(source_by_code) != len(source_options):
        errors.append("Source contract IDs are not unique.")

    source_ids = set(source_by_code)
    database_ids = set(database_by_code)

    if source_ids != database_ids:
        errors.append(
            "Source/database contract sets do not match: "
            f"source-only={len(source_ids - database_ids)}, "
            f"database-only={len(database_ids - source_ids)}."
        )

    if len(source_options) != 84:
        warnings.append(
            f"Expected 84 source contracts; found {len(source_options)}."
        )

    for inscode, source in source_by_code.items():
        db = database_by_code.get(inscode)
        if db is None:
            continue

        if normalize_text(db.OptionType) != source["OptionType"]:
            errors.append(
                f"{inscode}: OptionType mismatch "
                f"(DB={db.OptionType}, source={source['OptionType']})."
            )

        if not bool(db.IsActive):
            errors.append(f"{inscode}: database contract is inactive.")

        if source["ContractSize"] is None or source["ContractSize"] <= 0:
            errors.append(f"{inscode}: invalid ContractSize.")

        for field in (
            "LastPrice",
            "ClosingPrice",
            "YesterdayPrice",
        ):
            if source[field] is None:
                errors.append(f"{inscode}: {field} is missing.")

        for field in (
            "TradeCount",
            "Volume",
            "OpenInterest",
            "BestBuyVolume",
            "BestSellVolume",
        ):
            value = source[field]
            if value is not None and value < 0:
                errors.append(f"{inscode}: negative {field}.")

    # Underlying price values should agree across all 42 API records.
    for field in (
        "LastPrice",
        "ClosingPrice",
        "YesterdayPrice",
    ):
        values = {
            row[field]
            for row in underlying_market_rows
            if row[field] is not None
        }

        if len(values) > 1:
            errors.append(
                f"Underlying {field} differs across source records: "
                f"{sorted(str(v) for v in values)}"
            )

        if len(values) == 0:
            errors.append(f"Underlying {field} is missing.")

    if len(underlying_records) != 42:
        warnings.append(
            "Expected 42 underlying API records; "
            f"found {len(underlying_records)}."
        )

    return errors, warnings


# ============================================================
# BR36-E: MARKET ROW PREPARATION
# ============================================================

def build_market_values(source, retrieved_at):
    last_price = source["LastPrice"]
    yesterday_price = source["YesterdayPrice"]

    return {
        # Not supplied directly by this API endpoint.
        "DataDate": None,
        "DataTime": None,
        "LastPrice": last_price,
        "ClosingPrice": source["ClosingPrice"],
        "FirstPrice": source["FirstPrice"],
        "MinPrice": source["MinPrice"],
        "MaxPrice": source["MaxPrice"],
        "YesterdayPrice": yesterday_price,
        "PriceChange": price_change(
            last_price, yesterday_price
        ),
        "PriceChangePercent": price_change_percent(
            last_price, yesterday_price
        ),
        "TradeCount": source["TradeCount"],
        "Volume": source["Volume"],
        "TradeValue": source["TradeValue"],
        "BestBuyPrice": source["BestBuyPrice"],
        "BestBuyVolume": source["BestBuyVolume"],
        "BestSellPrice": source["BestSellPrice"],
        "BestSellVolume": source["BestSellVolume"],
        "OpenInterest": source["OpenInterest"],
        "UnderlyingLastPrice": source["UnderlyingLastPrice"],
        "UnderlyingClosePrice": source["UnderlyingClosePrice"],
        "ContractSize": source["ContractSize"],
        "SourceRetrievedAt": retrieved_at,
    }


def build_underlying_market_values(source, retrieved_at):
    last_price = source["LastPrice"]
    yesterday_price = source["YesterdayPrice"]

    return {
        "DataDate": None,
        "DataTime": None,
        "LastPrice": last_price,
        "ClosingPrice": source["ClosingPrice"],
        "YesterdayPrice": yesterday_price,
        "PriceChange": price_change(
            last_price, yesterday_price
        ),
        "PriceChangePercent": price_change_percent(
            last_price, yesterday_price
        ),
        # The inspected endpoint provides option trade statistics,
        # but no reliable underlying trade statistics in this mapping.
        "TradeCount": None,
        "Volume": None,
        "TradeValue": None,
        "SourceRetrievedAt": retrieved_at,
    }


# ============================================================
# BR36-F: SQL WRITE HELPERS
# ============================================================

OPTION_MARKET_COLUMNS = [
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

UNDERLYING_MARKET_COLUMNS = [
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


def write_option_snapshot(cursor, option_id, values):
    columns = ["OptionID"] + OPTION_MARKET_COLUMNS
    params = [option_id] + [
        values[column] for column in OPTION_MARKET_COLUMNS
    ]

    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(f"[{column}]" for column in columns)

    cursor.execute(
        f"""
        INSERT INTO dbo.OptionLiveSnapshot ({column_sql})
        VALUES ({placeholders})
        """,
        params,
    )


def upsert_option_current(cursor, option_id, values):
    cursor.execute(
        "SELECT COUNT_BIG(*) FROM dbo.OptionLiveCurrent WHERE OptionID = ?",
        option_id,
    )
    exists = cursor.fetchone()[0] > 0

    if exists:
        assignments = ", ".join(
            f"[{column}] = ?" for column in OPTION_MARKET_COLUMNS
        )
        params = [
            values[column] for column in OPTION_MARKET_COLUMNS
        ] + [option_id]

        cursor.execute(
            f"""
            UPDATE dbo.OptionLiveCurrent
            SET {assignments}, UpdatedAt = SYSUTCDATETIME()
            WHERE OptionID = ?
            """,
            params,
        )
    else:
        columns = ["OptionID"] + OPTION_MARKET_COLUMNS
        params = [option_id] + [
            values[column] for column in OPTION_MARKET_COLUMNS
        ]
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(f"[{column}]" for column in columns)

        cursor.execute(
            f"""
            INSERT INTO dbo.OptionLiveCurrent ({column_sql})
            VALUES ({placeholders})
            """,
            params,
        )


def write_underlying_snapshot(cursor, underlying_id, values):
    columns = ["UnderlyingID"] + UNDERLYING_MARKET_COLUMNS
    params = [underlying_id] + [
        values[column] for column in UNDERLYING_MARKET_COLUMNS
    ]

    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(f"[{column}]" for column in columns)

    cursor.execute(
        f"""
        INSERT INTO dbo.UnderlyingLiveSnapshot ({column_sql})
        VALUES ({placeholders})
        """,
        params,
    )


def upsert_underlying_current(cursor, underlying_id, values):
    cursor.execute(
        """
        SELECT COUNT_BIG(*)
        FROM dbo.UnderlyingLiveCurrent
        WHERE UnderlyingID = ?
        """,
        underlying_id,
    )
    exists = cursor.fetchone()[0] > 0

    if exists:
        assignments = ", ".join(
            f"[{column}] = ?" for column in UNDERLYING_MARKET_COLUMNS
        )
        params = [
            values[column] for column in UNDERLYING_MARKET_COLUMNS
        ] + [underlying_id]

        cursor.execute(
            f"""
            UPDATE dbo.UnderlyingLiveCurrent
            SET {assignments}, UpdatedAt = SYSUTCDATETIME()
            WHERE UnderlyingID = ?
            """,
            params,
        )
    else:
        columns = ["UnderlyingID"] + UNDERLYING_MARKET_COLUMNS
        params = [underlying_id] + [
            values[column] for column in UNDERLYING_MARKET_COLUMNS
        ]
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(f"[{column}]" for column in columns)

        cursor.execute(
            f"""
            INSERT INTO dbo.UnderlyingLiveCurrent ({column_sql})
            VALUES ({placeholders})
            """,
            params,
        )


# ============================================================
# BR36-G: ATOMIC CAPTURE
# ============================================================

def perform_capture(
    connection,
    source_file,
    source_json,
    underlying,
    database_by_code,
    source_options,
    underlying_market_rows,
    request_started_at,
    retrieved_at,
):
    cursor = connection.cursor()

    collection_run_id = None

    try:
        cursor.execute(
            """
            INSERT INTO dbo.CollectionRun
                (JobName, StartedAt, Status, ItemsRequested)
            OUTPUT INSERTED.CollectionRunID
            VALUES (?, ?, 'RUNNING', ?)
            """,
            JOB_NAME,
            request_started_at,
            len(source_options) + 1,
        )
        collection_run_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO dbo.RawApiResponse
                (CollectionRunID, UnderlyingID, InsCode, APIName,
                 RequestURL, RetrievedAt, HttpStatusCode,
                 IsSuccess, ResponseJSON)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            collection_run_id,
            underlying.UnderlyingID,
            UNDERLYING_INSCODE,
            API_NAME,
            "https://cdn.tsetmc.com/api/Instrument/GetInstrumentOptionMarketWatch/1",
            retrieved_at,
            200,
            True,
            json.dumps(source_json, ensure_ascii=False),
        )

        # The API returns the underlying fields repeated across option
        # records. Validation has already confirmed consistency.
        underlying_source = underlying_market_rows[0]
        underlying_values = build_underlying_market_values(
            underlying_source, retrieved_at
        )

        write_underlying_snapshot(
            cursor,
            underlying.UnderlyingID,
            underlying_values,
        )
        upsert_underlying_current(
            cursor,
            underlying.UnderlyingID,
            underlying_values,
        )

        for source in source_options:
            db_contract = database_by_code[source["TSEInsCode"]]
            option_id = db_contract.OptionID

            values = build_market_values(source, retrieved_at)

            write_option_snapshot(cursor, option_id, values)
            upsert_option_current(cursor, option_id, values)

        cursor.execute(
            """
            UPDATE dbo.CollectionRun
            SET FinishedAt = SYSUTCDATETIME(),
                Status = 'SUCCESS',
                ItemsSucceeded = ?,
                ItemsFailed = 0,
                Summary = ?
            WHERE CollectionRunID = ?
            """,
            len(source_options) + 1,
            (
                f"Captured {len(source_options)} option contracts "
                "and one underlying market row. "
                f"Source file: {source_file.name}"
            ),
            collection_run_id,
        )

        connection.commit()

        return {
            "CollectionRunID": collection_run_id,
            "OptionsCaptured": len(source_options),
            "UnderlyingCaptured": 1,
            "OptionSnapshotsInserted": len(source_options),
            "UnderlyingSnapshotsInserted": 1,
            "Status": "SUCCESS",
        }

    except Exception:
        connection.rollback()
        raise


# ============================================================
# BR36-H: MAIN
# ============================================================

def main():
    started_at = utc_now_naive()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")

    report_path = DATA_DIR / f"{REPORT_PREFIX}_{timestamp}.txt"
    plan_path = DATA_DIR / f"{PLAN_PREFIX}_{timestamp}.json"

    lines = []

    def log(message=""):
        print(message)
        lines.append(str(message))

    connection = None

    try:
        log("=" * 78)
        log("BR36: LIVE MARKET DATA CAPTURE")
        log("=" * 78)
        log(f"Project: {PROJECT_DIR}")
        log(f"Database: {DATABASE_NAME}")
        log(f"Underlying InsCode: {UNDERLYING_INSCODE}")
        log(f"Mode: {'DRY RUN - NO DATABASE WRITES' if DRY_RUN else 'LIVE DATABASE WRITE'}")

        # Fetch a fresh response directly from TSETMC.
        import urllib.request

        request_url = (
            "https://cdn.tsetmc.com/api/Instrument/"
            "GetInstrumentOptionMarketWatch/1"
        )
        request_started_at = utc_now_naive()

        request = urllib.request.Request(
            request_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json, text/plain, */*",
            },
            method="GET",
        )

        log(f"Direct API URL: {request_url}")
        log(f"Request started UTC: {request_started_at}")

        with urllib.request.urlopen(request, timeout=30) as response:
            http_status = response.status
            raw_body = response.read()
            retrieved_at = utc_now_naive()

        if http_status != 200:
            raise RuntimeError(
                f"TSETMC API returned HTTP {http_status}"
            )

        source_json = json.loads(raw_body.decode("utf-8-sig"))

        # Virtual label for reports; no source JSON file is read.
        source_file = Path(
            "TSETMC_DIRECT_API_"
            + retrieved_at.strftime("%Y%m%d_%H%M%S")
            + ".json"
        )

        log(f"HTTP status: {http_status}")
        log(f"Response received UTC: {retrieved_at}")
        log(f"Response bytes: {len(raw_body)}")
        log(f"Source JSON label: {source_file.name}")

        underlying_records, source_options, underlying_market_rows = (
            build_source_rows(source_json)
        )

        log()
        log("BR36-A: SOURCE")
        log(f"Total API records: {len(source_json.get('instrumentOptMarketWatch', []))}")
        log(f"Underlying records: {len(underlying_records)}")
        log(f"Normalized option contracts: {len(source_options)}")
        log(f"Unique source contract IDs: {len(set(x['TSEInsCode'] for x in source_options))}")

        connection = make_connection()

        underlying, database_by_code = load_database_reference_data(
            connection
        )

        errors, warnings = validate_capture(
            source_options,
            underlying_records,
            underlying_market_rows,
            underlying,
            database_by_code,
        )

        log()
        log("BR36-B: DATABASE MATCHING")
        log(f"UnderlyingID: {underlying.UnderlyingID}")
        log(f"Underlying symbol: {underlying.Symbol}")
        log(f"Database contracts: {len(database_by_code)}")
        log(
            "Exact source/database matches: "
            f"{len(set(x['TSEInsCode'] for x in source_options) & set(database_by_code))}"
        )

        log()
        log("BR36-C: VALIDATION")
        log(f"Errors: {len(errors)}")
        log(f"Warnings: {len(warnings)}")

        for item in errors:
            log(f"ERROR: {item}")

        for item in warnings:
            log(f"WARNING: {item}")

        option_ids = [
            database_by_code[row["TSEInsCode"]].OptionID
            for row in source_options
            if row["TSEInsCode"] in database_by_code
        ]

        plan = {
            "CreatedAtUTC": retrieved_at.isoformat(),
            "RequestStartedAtUTC": request_started_at.isoformat(),
            "ResponseReceivedAtUTC": retrieved_at.isoformat(),
            "DryRun": DRY_RUN,
            "Database": DATABASE_NAME,
            "SourceFile": str(source_file),
            "UnderlyingID": underlying.UnderlyingID,
            "UnderlyingInsCode": UNDERLYING_INSCODE,
            "SourceRecordCount": len(source_json.get("instrumentOptMarketWatch", [])),
            "UnderlyingRecordCount": len(underlying_records),
            "OptionContractCount": len(source_options),
            "MatchedOptionCount": len(option_ids),
            "ExpectedOptionSnapshotInserts": len(source_options),
            "ExpectedUnderlyingSnapshotInserts": 1,
            "ExpectedCurrentOptionRows": len(source_options),
            "ExpectedCurrentUnderlyingRows": 1,
            "ValidationErrors": errors,
            "ValidationWarnings": warnings,
            "OptionRows": [
                {
                    "OptionID": database_by_code[row["TSEInsCode"]].OptionID,
                    "TSEInsCode": row["TSEInsCode"],
                    "OptionType": row["OptionType"],
                    "LastPrice": row["LastPrice"],
                    "ClosingPrice": row["ClosingPrice"],
                    "YesterdayPrice": row["YesterdayPrice"],
                    "TradeCount": row["TradeCount"],
                    "Volume": row["Volume"],
                    "OpenInterest": row["OpenInterest"],
                    "BestBuyPrice": row["BestBuyPrice"],
                    "BestSellPrice": row["BestSellPrice"],
                }
                for row in source_options
                if row["TSEInsCode"] in database_by_code
            ],
        }

        save_json(plan_path, plan)
        log(f"Plan JSON: {plan_path}")

        if errors:
            log()
            log("BR36 RESULT: FAILED VALIDATION")
            log("No database writes were performed.")
            return 2

        if DRY_RUN:
            log()
            log("BR36 RESULT: DRY RUN PASSED")
            log("No database writes were performed.")
            log("Expected writes on commit:")
            log(f"  OptionLiveSnapshot: {len(source_options)} inserts")
            log("  UnderlyingLiveSnapshot: 1 insert")
            log("  OptionLiveCurrent: insert/update for 84 contracts")
            log("  UnderlyingLiveCurrent: 1 insert/update")
            log("  RawApiResponse: 1 insert")
            log("  CollectionRun: 1 success record")
            log("Next: set DRY_RUN = False and run again to commit.")
            return 0

        # Close the read-only validation transaction before starting
        # the write transaction.
        connection.rollback()

        log()
        log("BR36-D: COMMITTING ATOMIC CAPTURE")

        result = perform_capture(
            connection,
            source_file,
            source_json,
            underlying,
            database_by_code,
            source_options,
            underlying_market_rows,
            request_started_at,
            retrieved_at,
        )

        log(f"CollectionRunID: {result['CollectionRunID']}")
        log(f"Options captured: {result['OptionsCaptured']}")
        log(f"Underlying captured: {result['UnderlyingCaptured']}")
        log(f"Option snapshots inserted: {result['OptionSnapshotsInserted']}")
        log(f"Underlying snapshots inserted: {result['UnderlyingSnapshotsInserted']}")
        log("BR36 RESULT: SUCCESS")
        log("Database transaction committed.")

        return 0

    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass

        log()
        log("BR36 RESULT: ERROR")
        log(f"{type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        log("Any active database transaction was rolled back.")
        return 1

    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        with report_path.open("w", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")

        print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    sys.exit(main())
