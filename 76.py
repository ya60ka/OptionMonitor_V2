
# BR76 - Read-Only Source Timestamp and Trading-Date Audit
# Project: OptionMonitor_V2
# Purpose:
#   1. Inspect the latest BR44 source JSON and file timestamps.
#   2. Audit timestamps in RawApiResponse and CollectionRun.
#   3. Audit DataDate, DataTime and SourceRetrievedAt in live tables.
#   4. Check whether the trading date can be established reliably.
# IMPORTANT:
#   Database operations are SELECT-only.
#   Target database: OptionMarketDB_V2.
#   No INSERT, UPDATE, DELETE or schema changes.

from __future__ import annotations

import json
import sys
import traceback

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pyodbc


# ============================================================
# BR76-A: CONFIGURATION
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_CODE = "17914401175772326"

REPORT_PREFIX = "BR76_timestamp_audit"


# ============================================================
# BR76-B: HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def normalize(value):
    if value is None:
        return ""
    return str(value).strip()


def get_tehran_time(dt):
    if dt is None:
        return None
    return dt.astimezone(
        timezone(timedelta(hours=3, minutes=30))
    )


def connect_read_only():
    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
        "ApplicationIntent=ReadOnly;"
    )

    connection = pyodbc.connect(
        connection_string,
        autocommit=True,
        timeout=20,
    )

    cursor = connection.cursor()
    cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")

    return connection


def get_table_columns(cursor, table_name):
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """, table_name)

    return [row[0] for row in cursor.fetchall()]


def table_exists(cursor, table_name):
    cursor.execute("""
        SELECT COUNT_BIG(*)
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = ?
          AND TABLE_TYPE = 'BASE TABLE'
    """, table_name)

    return cursor.fetchone()[0] > 0


def print_section(title, log):
    log()
    log("=" * 90)
    log(title)
    log("=" * 90)


def inspect_json_timestamps(payload, log):
    log("JSON timestamp/date field inspection:")

    found = set()

    def walk(obj, prefix="", depth=0):
        if depth > 4:
            return

        if isinstance(obj, dict):
            for key, value in obj.items():
                key_text = str(key)
                key_lower = key_text.lower()

                if any(token in key_lower for token in (
                    "date", "time", "timestamp",
                    "update", "receive", "retrieve",
                    "create", "publish"
                )):
                    found.add(
                        (prefix + key_text, type(value).__name__,
                         normalize(value)[:100])
                    )

                if isinstance(value, (dict, list)):
                    walk(value, prefix + key_text + ".", depth + 1)

        elif isinstance(obj, list):
            for item in obj[:3]:
                if isinstance(item, (dict, list)):
                    walk(item, prefix + "[].", depth + 1)

    walk(payload)

    if not found:
        log("No obvious timestamp/date fields found by key-name scan.")
    else:
        for key, value_type, sample in sorted(found)[:100]:
            log(
                f"Field={key} | Type={value_type} | "
                f"Sample={sample}"
            )


def inspect_source_file(log):
    candidates = sorted(
        DATA_DIR.glob("BR44_live_response_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        log("ERROR: No BR44_live_response_*.json file found.")
        return None

    source_path = candidates[0]
    stat = source_path.stat()

    modified_utc = datetime.fromtimestamp(
        stat.st_mtime, timezone.utc
    )
    modified_tehran = get_tehran_time(modified_utc)

    log(f"Source file       : {source_path}")
    log(f"File size bytes   : {stat.st_size}")
    log(f"File modified UTC : {modified_utc.isoformat()}")
    log(f"File modified IR  : {modified_tehran.isoformat()}")

    with source_path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    rows = payload.get("instrumentOptMarketWatch")

    log(f"JSON root type    : {type(payload).__name__}")
    log(f"JSON root keys    : {list(payload.keys()) if isinstance(payload, dict) else 'N/A'}")
    log(f"API array rows    : {len(rows) if isinstance(rows, list) else 'INVALID'}")

    if isinstance(rows, list):
        selected = [
            row for row in rows
            if isinstance(row, dict)
            and normalize(row.get("uaInsCode")) == UNDERLYING_CODE
        ]

        log(f"Matching UA rows  : {len(selected)}")

        if selected:
            log(
                "Sample record keys: "
                + ", ".join(sorted(str(k) for k in selected[0].keys()))
            )

            for key in (
                "uaInsCode",
                "insCode_C",
                "insCode_P",
                "pDrCotVal_UA",
                "pClosing_UA",
                "priceYesterday_UA",
            ):
                log(f"Sample {key}: {selected[0].get(key)!r}")

    inspect_json_timestamps(payload, log)

    return {
        "path": source_path,
        "payload": payload,
        "modified_utc": modified_utc,
    }


# ============================================================
# BR76-C: DATABASE AUDIT
# ============================================================

def audit_collection_run(cursor, log):
    table_name = "CollectionRun"

    print_section("DATABASE: CollectionRun", log)

    if not table_exists(cursor, table_name):
        log("Table not found.")
        return

    columns = get_table_columns(cursor, table_name)
    log(f"Columns: {columns}")

    preferred = [
        "CollectionRunID",
        "JobName",
        "StartedAt",
        "FinishedAt",
        "Status",
        "ItemsRequested",
        "ItemsSucceeded",
        "ItemsFailed",
        "Summary",
    ]

    selected = [name for name in preferred if name in columns]

    if not selected:
        log("No recognized audit columns found.")
        return

    sql = (
        "SELECT TOP (20) "
        + ", ".join(f"[{name}]" for name in selected)
        + " FROM dbo.CollectionRun "
    )

    if "CollectionRunID" in columns:
        sql += " ORDER BY CollectionRunID DESC"

    cursor.execute(sql)
    rows = cursor.fetchall()

    log(f"Rows returned: {len(rows)}")

    for row in rows:
        log(" | ".join(
            f"{name}={getattr(row, name, None)!r}"
            for name in selected
        ))


def audit_raw_api_response(cursor, log):
    table_name = "RawApiResponse"

    print_section("DATABASE: RawApiResponse", log)

    if not table_exists(cursor, table_name):
        log("Table not found.")
        return

    columns = get_table_columns(cursor, table_name)
    log(f"Columns: {columns}")

    preferred = [
        "RawApiResponseID",
        "CollectionRunID",
        "UnderlyingID",
        "InsCode",
        "APIName",
        "RequestURL",
        "RetrievedAt",
        "HttpStatusCode",
        "IsSuccess",
        "ErrorMessage",
    ]

    selected = [name for name in preferred if name in columns]

    if selected:
        sql = (
            "SELECT TOP (20) "
            + ", ".join(f"[{name}]" for name in selected)
            + " FROM dbo.RawApiResponse "
        )

        if "RawApiResponseID" in columns:
            sql += " ORDER BY RawApiResponseID DESC"
        elif "RetrievedAt" in columns:
            sql += " ORDER BY RetrievedAt DESC"

        cursor.execute(sql)

        for row in cursor.fetchall():
            log(" | ".join(
                f"{name}={getattr(row, name, None)!r}"
                for name in selected
            ))

    if "ResponseJSON" in columns:
        log()
        log("Inspecting latest stored ResponseJSON:")

        order_column = (
            "RawApiResponseID"
            if "RawApiResponseID" in columns
            else "RetrievedAt" if "RetrievedAt" in columns else None
        )

        sql = "SELECT TOP (1) [ResponseJSON] FROM dbo.RawApiResponse"

        if order_column:
            sql += f" ORDER BY [{order_column}] DESC"

        cursor.execute(sql)
        row = cursor.fetchone()

        if row and row[0] is not None:
            try:
                raw = row[0]
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8-sig")

                payload = json.loads(raw)
                log(f"Stored JSON root keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")

                rows = (
                    payload.get("instrumentOptMarketWatch")
                    if isinstance(payload, dict)
                    else None
                )
                log(
                    "Stored JSON API rows: "
                    f"{len(rows) if isinstance(rows, list) else 'NOT FOUND'}"
                )
                inspect_json_timestamps(payload, log)

            except Exception as exc:
                log(
                    "Could not parse stored ResponseJSON: "
                    f"{type(exc).__name__}: {exc}"
                )
        else:
            log("No stored ResponseJSON value found.")


def audit_live_table(cursor, table_name, key_column, log):
    print_section(f"DATABASE: {table_name}", log)

    if not table_exists(cursor, table_name):
        log("Table not found.")
        return

    columns = get_table_columns(cursor, table_name)
    log(f"Columns: {columns}")

    cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{table_name}]")
    total_rows = cursor.fetchone()[0]
    log(f"Total rows: {total_rows}")

    if total_rows == 0:
        log("Table is empty.")
        return

    time_columns = [
        name for name in (
            "DataDate",
            "DataTime",
            "SourceRetrievedAt",
            "UpdatedAt",
        )
        if name in columns
    ]

    if not time_columns:
        log("No recognized timestamp/date columns found.")
        return

    # Aggregate timestamp/date range.
    aggregate_parts = []

    for name in time_columns:
        aggregate_parts.extend([
            f"MIN([{name}]) AS [Min_{name}]",
            f"MAX([{name}]) AS [Max_{name}]",
            f"COUNT([{name}]) AS [NonNull_{name}]",
        ])

    cursor.execute(
        "SELECT " + ", ".join(aggregate_parts)
        + f" FROM dbo.[{table_name}]"
    )

    row = cursor.fetchone()

    for name in time_columns:
        log(
            f"{name}: MIN={getattr(row, 'Min_' + name, None)!r}, "
            f"MAX={getattr(row, 'Max_' + name, None)!r}, "
            f"NonNull={getattr(row, 'NonNull_' + name, None)!r}"
        )

    if "SourceRetrievedAt" in columns:
        cursor.execute(
            f"""
            SELECT COUNT_BIG(DISTINCT SourceRetrievedAt)
            FROM dbo.[{table_name}]
            WHERE SourceRetrievedAt IS NOT NULL
            """
        )
        log(
            "Distinct SourceRetrievedAt values: "
            f"{cursor.fetchone()[0]}"
        )

    sample_columns = []

    if key_column in columns:
        sample_columns.append(key_column)

    for name in time_columns:
        if name not in sample_columns:
            sample_columns.append(name)

    for name in (
        "LastPrice",
        "ClosingPrice",
        "YesterdayPrice",
        "PriceChange",
        "PriceChangePercent",
    ):
        if name in columns and name not in sample_columns:
            sample_columns.append(name)

    if sample_columns:
        sql = (
            "SELECT TOP (10) "
            + ", ".join(f"[{name}]" for name in sample_columns)
            + f" FROM dbo.[{table_name}]"
        )

        if "SourceRetrievedAt" in columns:
            sql += " ORDER BY SourceRetrievedAt DESC"
        elif key_column in columns:
            sql += f" ORDER BY [{key_column}]"

        cursor.execute(sql)

        log("Sample rows:")
        for sample in cursor.fetchall():
            log(" | ".join(
                f"{name}={getattr(sample, name, None)!r}"
                for name in sample_columns
            ))


# ============================================================
# BR76-D: MAIN
# ============================================================

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    stamp = utc_now().strftime("%Y%m%d_%H%M%S")
    report_path = DATA_DIR / f"{REPORT_PREFIX}_{stamp}.txt"

    lines = []

    def log(message=""):
        print(message)
        lines.append(str(message))

    connection = None

    try:
        log("=" * 90)
        log("BR76 - READ-ONLY SOURCE TIMESTAMP AND TRADING-DATE AUDIT")
        log("=" * 90)
        log(f"Project         : {PROJECT_DIR}")
        log(f"Target database : {DATABASE}")
        log(f"Underlying code : {UNDERLYING_CODE}")
        log("Database writes : NONE")
        log(f"Audit started   : {utc_now().isoformat()}")

        print_section("SOURCE FILE AUDIT", log)
        source_info = inspect_source_file(log)

        connection = connect_read_only()
        cursor = connection.cursor()

        print_section("DATABASE CONNECTION", log)
        cursor.execute("SELECT DB_NAME(), @@SERVERNAME")
        db_name, server_name = cursor.fetchone()

        log(f"Connected server   : {server_name}")
        log(f"Connected database : {db_name}")

        if normalize(db_name) != DATABASE:
            raise RuntimeError(
                f"Wrong database selected: {db_name!r}"
            )

        audit_collection_run(cursor, log)
        audit_raw_api_response(cursor, log)

        audit_live_table(
            cursor,
            "OptionLiveSnapshot",
            "OptionID",
            log,
        )
        audit_live_table(
            cursor,
            "UnderlyingLiveSnapshot",
            "UnderlyingID",
            log,
        )
        audit_live_table(
            cursor,
            "OptionLiveCurrent",
            "OptionID",
            log,
        )
        audit_live_table(
            cursor,
            "UnderlyingLiveCurrent",
            "UnderlyingID",
            log,
        )

        print_section("PRELIMINARY INTERPRETATION", log)

        if source_info:
            log(
                "The BR44 file modification time is a filesystem "
                "timestamp, not proof of the API response retrieval time."
            )

        log(
            "DataDate/DataTime derived from script execution time "
            "must not automatically be treated as verified trading date/time."
        )
        log(
            "A timestamp embedded in JSON is useful only after its "
            "meaning and timezone are confirmed."
        )
        log(
            "This audit did not insert, update, or delete database rows."
        )

        log()
        log("BR76 RESULT: AUDIT COMPLETED")

    except Exception as exc:
        log()
        log("BR76 RESULT: ERROR")
        log(f"{type(exc).__name__}: {exc}")
        log(traceback.format_exc())

    finally:
        if connection is not None:
            connection.close()

        report_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

        print()
        print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
