# BR37 - Validate Live Market Capture
# Project: OptionMonitor_V2
# Purpose:
#   1. Retrieve a fresh response from TSETMC.
#   2. Validate source records against the V2 database.
#   3. Validate required table columns and foreign keys.
#   4. Test the atomic capture plan without writing to the database.
#   5. Keep failed-run audit records independent of capture rollback.
#
# SAFETY:
#   DRY_RUN=True prevents all database writes.
#   OptionMarketDB is never used or modified.

from __future__ import annotations

import json
import sys
import traceback

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyodbc
import requests


# ============================================================
# BR37-A: CONFIGURATION
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

DATABASE_SERVER = "localhost"
DATABASE_NAME = "OptionMarketDB_V2"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_INSCODE = "17914401175772326"

API_URL = (
    "https://cdn.tsetmc.com/api/"
    "Instrument/GetInstrumentOptionMarketWatch/1"
)

JOB_NAME = "BR37_LiveMarketDataCapture"
API_NAME = "TSETMC_GetInstrumentOptionMarketWatch"

# Do not change this yet.
DRY_RUN = True

EXPECTED_OPTION_COUNT = 84
EXPECTED_UNDERLYING_RECORD_COUNT = 42

REPORT_PREFIX = "BR37_validation_report"
PLAN_PREFIX = "BR37_capture_plan"
SOURCE_PREFIX = "BR37_live_response"

HTTP_TIMEOUT_SECONDS = 30


# ============================================================
# BR37-B: GENERAL HELPERS
# ============================================================

def utc_now_naive():
    """UTC timestamp suitable for SQL Server datetime2 columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        raise ValueError(
            f"Expected integer but received {value!r}"
        )

    return int(number)


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


def make_connection():
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={DATABASE_SERVER};"
        f"DATABASE={DATABASE_NAME};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )

    connection = pyodbc.connect(
        connection_string,
        autocommit=False,
        timeout=20,
    )

    # Defensive check: never continue against the wrong database.
    cursor = connection.cursor()
    cursor.execute("SELECT DB_NAME()")

    actual_database = cursor.fetchone()[0]

    if actual_database != DATABASE_NAME:
        connection.close()
        raise RuntimeError(
            f"Wrong database connected: {actual_database!r}. "
            f"Expected {DATABASE_NAME!r}."
        )

    return connection


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


# ============================================================
# BR37-C: FRESH API RETRIEVAL
# ============================================================

def fetch_live_api():
    retrieved_at = utc_now_naive()

    response = requests.get(
        API_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(
            "TSETMC response was not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            "Unexpected API response root type: "
            f"{type(payload).__name__}"
        )

    records = payload.get("instrumentOptMarketWatch")

    if not isinstance(records, list):
        raise ValueError(
            "API response does not contain a valid "
            "'instrumentOptMarketWatch' array."
        )

    if not records:
        raise ValueError("API returned an empty record array.")

    return {
        "RetrievedAt": retrieved_at,
        "HttpStatusCode": response.status_code,
        "Payload": payload,
        "ResponseText": response.text,
    }


# ============================================================
# BR37-D: SOURCE NORMALIZATION
# ============================================================

def build_source_rows(source_json):
    records = source_json.get("instrumentOptMarketWatch")

    if not isinstance(records, list):
        raise ValueError(
            "Invalid instrumentOptMarketWatch array."
        )

    underlying_records = [
        item
        for item in records
        if normalize_text(item.get("uaInsCode"))
        == UNDERLYING_INSCODE
    ]

    if not underlying_records:
        raise ValueError(
            "No API records matched underlying "
            f"{UNDERLYING_INSCODE}."
        )

    option_rows = []
    seen_ids = set()

    for record in underlying_records:
        for option_type in ("C", "P"):
            inscode = normalize_text(
                record.get(f"insCode_{option_type}")
            )

            if not inscode:
                raise ValueError(
                    f"Missing insCode_{option_type}."
                )

            if inscode in seen_ids:
                raise ValueError(
                    f"Duplicate API contract ID: {inscode}"
                )

            seen_ids.add(inscode)

            option_rows.append({
                "TSEInsCode": inscode,
                "OptionType": option_type,

                "LastPrice": parse_decimal(
                    record.get(f"pDrCotVal_{option_type}")
                ),
                "ClosingPrice": parse_decimal(
                    record.get(f"pClosing_{option_type}")
                ),
                "YesterdayPrice": parse_decimal(
                    record.get(f"priceYesterday_{option_type}")
                ),

                # This endpoint mapping does not provide these
                # three fields reliably.
                "FirstPrice": None,
                "MinPrice": None,
                "MaxPrice": None,

                "TradeCount": parse_int(
                    record.get(f"zTotTran_{option_type}")
                ),
                "Volume": parse_int(
                    record.get(f"qTotTran5J_{option_type}")
                ),
                "TradeValue": parse_decimal(
                    record.get(f"qTotCap_{option_type}")
                ),

                "BestBuyPrice": parse_decimal(
                    record.get(f"pMeDem_{option_type}")
                ),
                "BestBuyVolume": parse_int(
                    record.get(f"qTitMeDem_{option_type}")
                ),
                "BestSellPrice": parse_decimal(
                    record.get(f"pMeOf_{option_type}")
                ),
                "BestSellVolume": parse_int(
                    record.get(f"qTitMeOf_{option_type}")
                ),

                "OpenInterest": parse_int(
                    record.get(f"oP_{option_type}")
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
# BR37-E: DATABASE SCHEMA VALIDATION
# ============================================================

REQUIRED_COLUMNS = {
    "Underlying": {
        "UnderlyingID", "TSEInsCode", "Symbol", "IsActive",
    },
    "OptionContract": {
        "OptionID", "UnderlyingID", "TSEInsCode",
        "OptionType", "ContractSize", "IsActive",
    },
    "CollectionRun": {
        "CollectionRunID", "JobName", "StartedAt",
        "FinishedAt", "Status", "ItemsRequested",
        "ItemsSucceeded", "ItemsFailed", "Summary",
        "ErrorDetails",
    },
    "RawApiResponse": {
        "RawDataID", "CollectionRunID", "UnderlyingID",
        "InsCode", "APIName", "RequestURL", "RetrievedAt",
        "HttpStatusCode", "IsSuccess", "ErrorMessage",
        "ResponseJSON",
    },
    "OptionLiveCurrent": {
        "OptionID", "DataDate", "DataTime", "LastPrice",
        "ClosingPrice", "FirstPrice", "MinPrice", "MaxPrice",
        "YesterdayPrice", "PriceChange", "PriceChangePercent",
        "TradeCount", "Volume", "TradeValue",
        "BestBuyPrice", "BestBuyVolume",
        "BestSellPrice", "BestSellVolume",
        "OpenInterest", "UnderlyingLastPrice",
        "UnderlyingClosePrice", "ContractSize",
        "SourceRetrievedAt", "UpdatedAt",
    },
    "OptionLiveSnapshot": {
        "SnapshotID", "OptionID", "DataDate", "DataTime",
        "LastPrice", "ClosingPrice", "FirstPrice",
        "MinPrice", "MaxPrice", "YesterdayPrice",
        "PriceChange", "PriceChangePercent",
        "TradeCount", "Volume", "TradeValue",
        "BestBuyPrice", "BestBuyVolume",
        "BestSellPrice", "BestSellVolume",
        "OpenInterest", "UnderlyingLastPrice",
        "UnderlyingClosePrice", "ContractSize",
        "SourceRetrievedAt",
    },
    "UnderlyingLiveCurrent": {
        "UnderlyingID", "DataDate", "DataTime",
        "LastPrice", "ClosingPrice", "YesterdayPrice",
        "PriceChange", "PriceChangePercent",
        "TradeCount", "Volume", "TradeValue",
        "SourceRetrievedAt", "UpdatedAt",
    },
    "UnderlyingLiveSnapshot": {
        "SnapshotID", "UnderlyingID", "DataDate", "DataTime",
        "LastPrice", "ClosingPrice", "YesterdayPrice",
        "PriceChange", "PriceChangePercent",
        "TradeCount", "Volume", "TradeValue",
        "SourceRetrievedAt",
    },
}

# Relationships are verified by their actual parent/child
# table and column mappings, not just by constraint names.
REQUIRED_FOREIGN_KEYS = {
    (
        "OptionContract", "UnderlyingID",
        "Underlying", "UnderlyingID",
    ),
    (
        "OptionLiveCurrent", "OptionID",
        "OptionContract", "OptionID",
    ),
    (
        "OptionLiveSnapshot", "OptionID",
        "OptionContract", "OptionID",
    ),
    (
        "UnderlyingLiveCurrent", "UnderlyingID",
        "Underlying", "UnderlyingID",
    ),
    (
        "UnderlyingLiveSnapshot", "UnderlyingID",
        "Underlying", "UnderlyingID",
    ),
    (
        "RawApiResponse", "CollectionRunID",
        "CollectionRun", "CollectionRunID",
    ),
    (
        "RawApiResponse", "UnderlyingID",
        "Underlying", "UnderlyingID",
    ),
}


def validate_database_schema(connection):
    cursor = connection.cursor()
    errors = []

    cursor.execute("""
        SELECT t.name
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s
            ON s.schema_id = t.schema_id
        WHERE s.name = 'dbo'
          AND t.is_ms_shipped = 0
    """)

    actual_tables = {row[0] for row in cursor.fetchall()}

    required_tables = set(REQUIRED_COLUMNS)
    missing_tables = required_tables - actual_tables

    for table in sorted(missing_tables):
        errors.append(f"Missing required table dbo.{table}")

    actual_columns = {}

    for table in sorted(required_tables & actual_tables):
        cursor.execute("""
            SELECT c.name
            FROM sys.columns AS c
            INNER JOIN sys.tables AS t
                ON t.object_id = c.object_id
            INNER JOIN sys.schemas AS s
                ON s.schema_id = t.schema_id
            WHERE s.name = 'dbo'
              AND t.name = ?
        """, table)

        actual_columns[table] = {
            row[0] for row in cursor.fetchall()
        }

        missing = (
            REQUIRED_COLUMNS[table] - actual_columns[table]
        )

        for column in sorted(missing):
            errors.append(
                f"Missing column dbo.{table}.{column}"
            )

    cursor.execute("""
        SELECT
            pt.name AS ParentTable,
            pc.name AS ParentColumn,
            rt.name AS ReferencedTable,
            rc.name AS ReferencedColumn
        FROM sys.foreign_key_columns AS fkc
        INNER JOIN sys.foreign_keys AS fk
            ON fk.object_id = fkc.constraint_object_id
        INNER JOIN sys.tables AS pt
            ON pt.object_id = fkc.parent_object_id
        INNER JOIN sys.columns AS pc
            ON pc.object_id = fkc.parent_object_id
           AND pc.column_id = fkc.parent_column_id
        INNER JOIN sys.tables AS rt
            ON rt.object_id = fkc.referenced_object_id
        INNER JOIN sys.columns AS rc
            ON rc.object_id = fkc.referenced_object_id
           AND rc.column_id = fkc.referenced_column_id
        INNER JOIN sys.schemas AS ps
            ON ps.schema_id = pt.schema_id
        INNER JOIN sys.schemas AS rs
            ON rs.schema_id = rt.schema_id
        WHERE ps.name = 'dbo'
          AND rs.name = 'dbo'
    """)

    actual_fks = {
        (row.ParentTable, row.ParentColumn,
         row.ReferencedTable, row.ReferencedColumn)
        for row in cursor.fetchall()
    }

    missing_fks = REQUIRED_FOREIGN_KEYS - actual_fks

    for fk in sorted(missing_fks):
        errors.append(
            "Missing foreign key relationship: "
            f"dbo.{fk[0]}.{fk[1]} -> "
            f"dbo.{fk[2]}.{fk[3]}"
        )

    return errors, actual_tables, actual_fks


# ============================================================
# BR37-F: READ-ONLY DATABASE REFERENCE DATA
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
            "Expected exactly one matching underlying row; "
            f"found {len(underlying_rows)}."
        )

    underlying = underlying_rows[0]

    if not bool(underlying.IsActive):
        raise ValueError("Underlying is inactive in the database.")

    cursor.execute("""
        SELECT
            OptionID,
            UnderlyingID,
            TSEInsCode,
            OptionType,
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
            "Duplicate TSEInsCode values found in OptionContract."
        )

    return underlying, database_by_code


# ============================================================
# BR37-G: SOURCE/DATABASE VALIDATION
# ============================================================

def validate_capture(
    source_options,
    underlying_records,
    underlying_market_rows,
    database_by_code,
):
    errors = []
    warnings = []

    source_by_code = {
        row["TSEInsCode"]: row
        for row in source_options
    }

    source_ids = set(source_by_code)
    database_ids = set(database_by_code)

    if len(source_by_code) != len(source_options):
        errors.append("Source contract IDs are not unique.")

    if source_ids != database_ids:
        errors.append(
            "Source/database contract sets differ: "
            f"source-only={len(source_ids - database_ids)}, "
            f"database-only={len(database_ids - source_ids)}."
        )

    if len(source_options) != EXPECTED_OPTION_COUNT:
        warnings.append(
            f"Expected {EXPECTED_OPTION_COUNT} contracts; "
            f"received {len(source_options)}."
        )

    if len(underlying_records) != EXPECTED_UNDERLYING_RECORD_COUNT:
        warnings.append(
            f"Expected {EXPECTED_UNDERLYING_RECORD_COUNT} underlying "
            f"records; received {len(underlying_records)}."
        )

    for inscode, source in source_by_code.items():
        db = database_by_code.get(inscode)

        if db is None:
            continue

        if normalize_text(db.OptionType) != source["OptionType"]:
            errors.append(
                f"{inscode}: OptionType mismatch; "
                f"database={db.OptionType}, "
                f"source={source['OptionType']}."
            )

        if not bool(db.IsActive):
            errors.append(
                f"{inscode}: contract is inactive in database."
            )

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

        # Zero values are not automatically rejected because they
        # may be returned for inactive or untraded contracts.
        if source["BestSellPrice"] == 0:
            warnings.append(
                f"{inscode}: BestSellPrice is zero; "
                "verify before using it in analytics."
            )

        if (
            source["TradeCount"] == 0
            and source["Volume"] == 0
        ):
            warnings.append(
                f"{inscode}: zero trades and volume in API response."
            )

    # All repeated underlying prices should be consistent.
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

        if len(values) == 0:
            errors.append(f"Underlying {field} is missing.")
        elif len(values) > 1:
            errors.append(
                f"Underlying {field} differs across API records."
            )

    return errors, warnings


# ============================================================
# BR37-H: MARKET VALUE PREPARATION
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


def build_market_values(source, retrieved_at):
    last_price = source["LastPrice"]
    yesterday_price = source["YesterdayPrice"]

    return {
        # API does not supply reliable market date/time fields
        # through this mapping; do not invent them.
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

        # Do not fabricate underlying trade statistics.
        "TradeCount": None,
        "Volume": None,
        "TradeValue": None,

        "SourceRetrievedAt": retrieved_at,
    }


# ============================================================
# BR37-I: SQL WRITE HELPERS
# These functions are not called during DRY_RUN.
# ============================================================

def insert_snapshot(
    cursor,
    table_name,
    key_column,
    key_value,
    columns,
    values,
):
    all_columns = [key_column] + columns
    params = [key_value] + [values[column] for column in columns]

    column_sql = ", ".join(
        f"[{column}]" for column in all_columns
    )
    placeholders = ", ".join("?" for _ in all_columns)

    cursor.execute(
        f"""
        INSERT INTO dbo.{table_name} ({column_sql})
        VALUES ({placeholders})
        """,
        params,
    )


def upsert_current(
    cursor,
    table_name,
    key_column,
    key_value,
    columns,
    values,
):
    cursor.execute(
        f"""
        SELECT COUNT_BIG(*)
        FROM dbo.{table_name}
        WHERE [{key_column}] = ?
        """,
        key_value,
    )

    exists = cursor.fetchone()[0] > 0

    if exists:
        assignments = ", ".join(
            f"[{column}] = ?" for column in columns
        )

        params = [values[column] for column in columns]
        params.append(key_value)

        cursor.execute(
            f"""
            UPDATE dbo.{table_name}
            SET {assignments},
                UpdatedAt = SYSUTCDATETIME()
            WHERE [{key_column}] = ?
            """,
            params,
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                f"Expected one row updated in {table_name}; "
                f"rowcount={cursor.rowcount}."
            )

    else:
        all_columns = [key_column] + columns
        params = [key_value] + [
            values[column] for column in columns
        ]

        column_sql = ", ".join(
            f"[{column}]" for column in all_columns
        )
        placeholders = ", ".join("?" for _ in all_columns)

        cursor.execute(
            f"""
            INSERT INTO dbo.{table_name} ({column_sql})
            VALUES ({placeholders})
            """,
            params,
        )


# ============================================================
# BR37-J: ATOMIC CAPTURE TRANSACTION
# ============================================================

def perform_capture(
    connection,
    source_json,
    source_text,
    http_status,
    source_file,
    retrieved_at,
    underlying,
    database_by_code,
    source_options,
    underlying_market_rows,
):
    cursor = connection.cursor()
    collection_run_id = None

    try:
        # Every successful capture write is in this transaction.
        cursor.execute("""
            INSERT INTO dbo.CollectionRun
                (JobName, StartedAt, Status, ItemsRequested)
            OUTPUT INSERTED.CollectionRunID
            VALUES (?, ?, 'RUNNING', ?)
        """, JOB_NAME, retrieved_at, len(source_options) + 1)

        collection_run_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO dbo.RawApiResponse
                (
                    CollectionRunID, UnderlyingID, InsCode,
                    APIName, RequestURL, RetrievedAt,
                    HttpStatusCode, IsSuccess, ErrorMessage,
                    ResponseJSON
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            collection_run_id,
            underlying.UnderlyingID,
            UNDERLYING_INSCODE,
            API_NAME,
            API_URL,
            retrieved_at,
            http_status,
            True,
            None,
            source_text,
        )

        underlying_values = build_underlying_market_values(
            underlying_market_rows[0],
            retrieved_at,
        )

        insert_snapshot(
            cursor,
            "UnderlyingLiveSnapshot",
            "UnderlyingID",
            underlying.UnderlyingID,
            UNDERLYING_MARKET_COLUMNS,
            underlying_values,
        )

        upsert_current(
            cursor,
            "UnderlyingLiveCurrent",
            "UnderlyingID",
            underlying.UnderlyingID,
            UNDERLYING_MARKET_COLUMNS,
            underlying_values,
        )

        for source in source_options:
            db_contract = database_by_code[source["TSEInsCode"]]
            option_id = db_contract.OptionID

            values = build_market_values(
                source,
                retrieved_at,
            )

            insert_snapshot(
                cursor,
                "OptionLiveSnapshot",
                "OptionID",
                option_id,
                OPTION_MARKET_COLUMNS,
                values,
            )

            upsert_current(
                cursor,
                "OptionLiveCurrent",
                "OptionID",
                option_id,
                OPTION_MARKET_COLUMNS,
                values,
            )

        cursor.execute("""
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
                "and one underlying row. "
                f"Source file: {source_file.name}"
            ),
            collection_run_id,
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                "Could not mark CollectionRun as SUCCESS."
            )

        connection.commit()

        return {
            "CollectionRunID": collection_run_id,
            "OptionsCaptured": len(source_options),
            "UnderlyingCaptured": 1,
            "Status": "SUCCESS",
        }

    except Exception:
        # This removes every partial write from the capture.
        connection.rollback()
        raise


# ============================================================
# BR37-K: INDEPENDENT FAILURE AUDIT
# ============================================================

def record_failed_run(
    connection,
    retrieved_at,
    error_message,
    source_text=None,
    http_status=None,
):
    """
    Best-effort audit in a separate transaction after capture rollback.
    This function is called only when DRY_RUN is False.
    """
    cursor = connection.cursor()

    try:
        connection.rollback()

        cursor.execute("""
            INSERT INTO dbo.CollectionRun
                (
                    JobName, StartedAt, FinishedAt,
                    Status, ItemsRequested, ItemsSucceeded,
                    ItemsFailed, Summary, ErrorDetails
                )
            OUTPUT INSERTED.CollectionRunID
            VALUES (?, ?, SYSUTCDATETIME(),
                    'FAILED', 0, 0, 1, ?, ?)
        """,
            JOB_NAME,
            retrieved_at,
            "Live market capture failed; capture transaction rolled back.",
            str(error_message)[:4000],
        )

        failed_run_id = cursor.fetchone()[0]

        # Raw response is optional if no valid response was received.
        cursor.execute("""
            INSERT INTO dbo.RawApiResponse
                (
                    CollectionRunID, UnderlyingID, InsCode,
                    APIName, RequestURL, RetrievedAt,
                    HttpStatusCode, IsSuccess, ErrorMessage,
                    ResponseJSON
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            failed_run_id,
            None,
            UNDERLYING_INSCODE,
            API_NAME,
            API_URL,
            retrieved_at,
            http_status,
            False,
            str(error_message)[:2000],
            source_text,
        )

        connection.commit()
        return failed_run_id

    except Exception:
        connection.rollback()
        raise


# ============================================================
# BR37-L: MAIN
# ============================================================

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_naive()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")

    report_path = DATA_DIR / f"{REPORT_PREFIX}_{timestamp}.txt"
    plan_path = DATA_DIR / f"{PLAN_PREFIX}_{timestamp}.json"
    source_file = DATA_DIR / f"{SOURCE_PREFIX}_{timestamp}.json"

    lines = []

    def log(message=""):
        message = str(message)
        print(message)
        lines.append(message)

    connection = None
    api_result = None
    underlying = None
    source_options = []
    underlying_market_rows = []
    database_by_code = {}
    errors = []
    warnings = []

    exit_code = 0

    log("=" * 78)
    log("BR37 - LIVE MARKET CAPTURE VALIDATION")
    log("=" * 78)
    log(f"Project       : {PROJECT_DIR}")
    log(f"Database      : {DATABASE_NAME}")
    log(f"Underlying    : {UNDERLYING_INSCODE}")
    log(f"Mode          : {'DRY RUN - NO DATABASE WRITES' if DRY_RUN else 'LIVE WRITE'}")
    log(f"API           : {API_URL}")

    try:
        # Step 1: fetch fresh API data.
        log()
        log("BR37-A: FETCHING FRESH API RESPONSE")

        api_result = fetch_live_api()

        retrieved_at = api_result["RetrievedAt"]
        source_json = api_result["Payload"]
        source_text = api_result["ResponseText"]
        http_status = api_result["HttpStatusCode"]

        save_json(source_file, source_json)

        log(f"HTTP status   : {http_status}")
        log(f"Retrieved UTC : {retrieved_at.isoformat()}")
        log(
            "Total API records: "
            f"{len(source_json['instrumentOptMarketWatch'])}"
        )
        log(f"Saved source  : {source_file}")

        # Step 2: normalize source data.
        log()
        log("BR37-B: SOURCE NORMALIZATION")

        (
            underlying_records,
            source_options,
            underlying_market_rows,
        ) = build_source_rows(source_json)

        log(f"Underlying API records : {len(underlying_records)}")
        log(f"Normalized contracts   : {len(source_options)}")
        log(
            "Unique source IDs      : "
            f"{len({x['TSEInsCode'] for x in source_options})}"
        )

        # Step 3: database connection and schema inspection.
        log()
        log("BR37-C: DATABASE AND SCHEMA VALIDATION")

        connection = make_connection()

        schema_errors, actual_tables, actual_fks = (
            validate_database_schema(connection)
        )

        errors.extend(schema_errors)

        log(f"Connected database     : {DATABASE_NAME}")
        log(f"Tables discovered      : {len(actual_tables)}")
        log(f"Foreign keys discovered: {len(actual_fks)}")
        log(f"Schema errors          : {len(schema_errors)}")

        # Do not query the capture references if required schema
        # objects are missing.
        if not schema_errors:
            underlying, database_by_code = (
                load_database_reference_data(connection)
            )

            log(f"UnderlyingID           : {underlying.UnderlyingID}")
            log(f"Underlying symbol      : {underlying.Symbol}")
            log(f"Database contracts     : {len(database_by_code)}")

            validation_errors, warnings = validate_capture(
                source_options,
                underlying_records,
                underlying_market_rows,
                database_by_code,
            )

            errors.extend(validation_errors)

            matched = (
                set(row["TSEInsCode"] for row in source_options)
                & set(database_by_code)
            )

            log(f"Exact contract matches : {len(matched)}")
            log(f"Data validation errors : {len(validation_errors)}")

        log()
        log("BR37-D: VALIDATION DETAILS")
        log(f"Total errors   : {len(errors)}")
        log(f"Total warnings : {len(warnings)}")

        for item in errors:
            log(f"ERROR: {item}")

        for item in warnings:
            log(f"WARNING: {item}")

        plan = {
            "CreatedAtUTC": started_at.isoformat(),
            "SourceRetrievedAtUTC": (
                api_result["RetrievedAt"].isoformat()
                if api_result else None
            ),
            "DryRun": DRY_RUN,
            "Database": DATABASE_NAME,
            "APIURL": API_URL,
            "SourceFile": str(source_file),
            "UnderlyingInsCode": UNDERLYING_INSCODE,
            "UnderlyingID": (
                underlying.UnderlyingID if underlying else None
            ),
            "HttpStatusCode": (
                api_result["HttpStatusCode"] if api_result else None
            ),
            "SourceRecordCount": (
                len(source_json["instrumentOptMarketWatch"])
                if api_result else 0
            ),
            "UnderlyingRecordCount": len(underlying_records)
                if "underlying_records" in locals() else 0,
            "OptionContractCount": len(source_options),
            "DatabaseContractCount": len(database_by_code),
            "MatchedOptionCount": (
                len({
                    row["TSEInsCode"] for row in source_options
                } & set(database_by_code))
            ),
            "ExpectedOptionSnapshotInserts": len(source_options),
            "ExpectedUnderlyingSnapshotInserts": 1,
            "ExpectedOptionCurrentRows": len(source_options),
            "ExpectedUnderlyingCurrentRows": 1,
            "ExpectedRawApiResponseRows": 1,
            "ExpectedCollectionRunRows": 1,
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
        log(f"Plan JSON     : {plan_path}")

        if errors:
            log()
            log("BR37 RESULT: FAILED VALIDATION")
            log("No market-data writes were performed.")
            exit_code = 2

        elif DRY_RUN:
            log()
            log("BR37 RESULT: DRY RUN PASSED")
            log("No database writes were performed.")
            log("Fresh API response was retrieved and saved.")
            log("Database schema and source contracts were validated.")
            log()
            log("Expected writes if a later approved live run is enabled:")
            log(f"  OptionLiveSnapshot      : {len(source_options)} inserts")
            log("  UnderlyingLiveSnapshot  : 1 insert")
            log(f"  OptionLiveCurrent       : {len(source_options)} upserts")
            log("  UnderlyingLiveCurrent   : 1 upsert")
            log("  RawApiResponse          : 1 insert")
            log("  CollectionRun           : 1 success record")
            log()
            log("DRY_RUN remains True. Do not enable live writes yet.")

        else:
            # End the read-only validation transaction.
            connection.rollback()

            log()
            log("BR37-E: ATOMIC LIVE CAPTURE")

            result = perform_capture(
                connection=connection,
                source_json=source_json,
                source_text=source_text,
                http_status=http_status,
                source_file=source_file,
                retrieved_at=retrieved_at,
                underlying=underlying,
                database_by_code=database_by_code,
                source_options=source_options,
                underlying_market_rows=underlying_market_rows,
            )

            log(f"CollectionRunID : {result['CollectionRunID']}")
            log(f"Options captured: {result['OptionsCaptured']}")
            log("Underlying rows : 1")
            log("BR37 RESULT     : SUCCESS")
            log("Atomic transaction committed.")

    except Exception as exc:
        exit_code = 1

        log()
        log("BR37 RESULT: ERROR")
        log(f"{type(exc).__name__}: {exc}")
        log(traceback.format_exc())

        if connection is not None:
            try:
                connection.rollback()
                log("Active transaction rolled back.")
            except Exception as rollback_exc:
                log(f"Rollback error: {rollback_exc}")

        # In live mode, persist failure audit separately from the
        # failed capture transaction. Dry-run never writes to DB.
        if not DRY_RUN and connection is not None:
            try:
                audit_time = (
                    api_result["RetrievedAt"]
                    if api_result else utc_now_naive()
                )

                response_text = (
                    api_result["ResponseText"]
                    if api_result else None
                )

                http_status = (
                    api_result["HttpStatusCode"]
                    if api_result else None
                )

                failed_run_id = record_failed_run(
                    connection=connection,
                    retrieved_at=audit_time,
                    error_message=f"{type(exc).__name__}: {exc}",
                    source_text=response_text,
                    http_status=http_status,
                )

                log(
                    "Independent failure audit saved. "
                    f"CollectionRunID={failed_run_id}"
                )

            except Exception as audit_exc:
                log(
                    "WARNING: Independent failure audit could not "
                    f"be saved: {audit_exc}"
                )

    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

        try:
            with report_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                file.write("\n".join(lines) + "\n")

            print(f"\nReport saved: {report_path}")

        except Exception as report_exc:
            print(f"Could not save report: {report_exc}")
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())