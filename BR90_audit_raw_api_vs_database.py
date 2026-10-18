
# BR90 - Raw API vs Database Mapping Audit
# Project: OptionMonitor_V2
# Purpose: Audit CollectionRunID=3 without API requests or DB writes.

from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from collections import Counter
from datetime import datetime, date
from pathlib import Path

import pyodbc


# ============================================================
# BR90-A: CONFIGURATION
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATABASE_SERVER = "localhost"
DATABASE_NAME = "OptionMarketDB_V2"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

COLLECTION_RUN_ID = 3
UNDERLYING_INSCODE = "17914401175772326"

OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"


# ============================================================
# BR90-B: HELPERS
# ============================================================

def connect():
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


def norm_text(value):
    return "" if value is None else str(value).strip()


def as_decimal(value):
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).strip())
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def comparable(value):
    if value is None:
        return None

    number = as_decimal(value)
    if number is not None:
        return number

    return norm_text(value)


def fmt(value):
    if value is None:
        return "NULL"
    return str(value)


def find_date_time_keys(obj, path="$", found=None):
    if found is None:
        found = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()
            if any(token in key_lower for token in ("date", "time", "datetime")):
                found.append((f"{path}.{key}", value))
            find_date_time_keys(value, f"{path}.{key}", found)

    elif isinstance(obj, list):
        # Scan a few entries only to avoid excessive repeated output.
        for index, value in enumerate(obj[:3]):
            find_date_time_keys(value, f"{path}[{index}]", found)

    return found


def load_rows(cursor, sql, *params):
    cursor.execute(sql, *params)
    columns = [column[0] for column in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


# API fields mapped directly by BR36.
DIRECT_FIELD_MAP = {
    "LastPrice": "pDrCotVal",
    "ClosingPrice": "pClosing",
    "YesterdayPrice": "priceYesterday",
    "TradeCount": "zTotTran",
    "Volume": "qTotTran5J",
    "TradeValue": "qTotCap",
    "BestBuyPrice": "pMeDem",
    "BestBuyVolume": "qTitMeDem",
    "BestSellPrice": "pMeOf",
    "BestSellVolume": "qTitMeOf",
    "OpenInterest": "oP",
}

# Underlying price fields are repeated in each option source record.
UNDERLYING_FIELD_MAP = {
    "UnderlyingLastPrice": "pDrCotVal_UA",
    "UnderlyingClosePrice": "pClosing_UA",
}


# ============================================================
# BR90-C: MAIN AUDIT
# ============================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / (
        f"BR90_audit_run_{COLLECTION_RUN_ID}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )

    lines = []

    def log(message=""):
        message = str(message)
        print(message)
        lines.append(message)

    connection = None
    exit_code = 0

    try:
        log("=" * 78)
        log("BR90 - RAW API VS DATABASE MAPPING AUDIT")
        log("=" * 78)
        log(f"Database: {DATABASE_NAME}")
        log(f"CollectionRunID: {COLLECTION_RUN_ID}")
        log("Mode: READ ONLY")
        log("API request: NO")
        log("Database writes: NO")

        connection = connect()
        cursor = connection.cursor()

        # ----------------------------------------------------
        # 1. Retrieve the raw API response for this run.
        # ----------------------------------------------------
        raw_rows = load_rows(
            cursor,
            """
            SELECT
                CollectionRunID,
                UnderlyingID,
                InsCode,
                APIName,
                RetrievedAt,
                HttpStatusCode,
                IsSuccess,
                ResponseJSON
            FROM dbo.RawApiResponse
            WHERE CollectionRunID = ?
            """,
            COLLECTION_RUN_ID,
        )

        if len(raw_rows) != 1:
            raise RuntimeError(
                "Expected exactly one RawApiResponse row for run "
                f"{COLLECTION_RUN_ID}; found {len(raw_rows)}."
            )

        raw_meta = raw_rows[0]
        raw_text = raw_meta["ResponseJSON"]

        if isinstance(raw_text, bytes):
            raw_text = raw_text.decode("utf-8-sig")

        source_json = json.loads(raw_text)

        records = source_json.get("instrumentOptMarketWatch")
        if not isinstance(records, list):
            raise RuntimeError(
                "Raw response does not contain a valid "
                "'instrumentOptMarketWatch' list."
            )

        log()
        log("A. RAW RESPONSE")
        log(f"Run ID: {raw_meta['CollectionRunID']}")
        log(f"API: {raw_meta['APIName']}")
        log(f"HTTP status: {raw_meta['HttpStatusCode']}")
        log(f"Success: {raw_meta['IsSuccess']}")
        log(f"RetrievedAt: {raw_meta['RetrievedAt']}")
        log(f"Response records: {len(records)}")

        underlying_records = [
            row for row in records
            if norm_text(row.get("uaInsCode")) == UNDERLYING_INSCODE
        ]

        log(f"Underlying records: {len(underlying_records)}")

        if not underlying_records:
            raise RuntimeError(
                f"No raw records for underlying {UNDERLYING_INSCODE}."
            )

        # ----------------------------------------------------
        # 2. Load contracts and snapshots for the exact capture.
        #    Snapshots do not have CollectionRunID, so use the
        #    identical RetrievedAt value saved by BR36.
        # ----------------------------------------------------
        contracts = load_rows(
            cursor,
            """
            SELECT
                oc.OptionID,
                oc.TSEInsCode,
                oc.OptionType,
                oc.UnderlyingID
            FROM dbo.OptionContract AS oc
            INNER JOIN dbo.Underlying AS u
                ON u.UnderlyingID = oc.UnderlyingID
            WHERE u.TSEInsCode = ?
            """,
            UNDERLYING_INSCODE,
        )

        db_by_code = {
            norm_text(row["TSEInsCode"]): row
            for row in contracts
        }

        snapshot_rows = load_rows(
            cursor,
            """
            SELECT *
            FROM dbo.OptionLiveSnapshot
            WHERE SourceRetrievedAt = ?
            """,
            raw_meta["RetrievedAt"],
        )

        snapshot_by_id = {
            row["OptionID"]: row
            for row in snapshot_rows
        }

        underlying_snapshots = load_rows(
            cursor,
            """
            SELECT *
            FROM dbo.UnderlyingLiveSnapshot
            WHERE SourceRetrievedAt = ?
            """,
            raw_meta["RetrievedAt"],
        )

        log()
        log("B. SNAPSHOT MATCHING")
        log(f"Database contracts: {len(contracts)}")
        log(f"Snapshots at raw RetrievedAt: {len(snapshot_rows)}")
        log(f"Distinct snapshot OptionIDs: {len(snapshot_by_id)}")
        log(
            "Underlying snapshots at raw RetrievedAt: "
            f"{len(underlying_snapshots)}"
        )

        if len(snapshot_rows) != 84:
            log(
                "WARNING: Expected 84 option snapshots for this capture "
                f"timestamp; found {len(snapshot_rows)}."
            )

        # ----------------------------------------------------
        # 3. Compare raw API values with stored snapshots.
        # ----------------------------------------------------
        comparison_rows = []
        source_ids = set()
        raw_field_presence = Counter()
        raw_field_missing = Counter()
        source_zero_counts = Counter()
        snapshot_zero_counts = Counter()
        mismatch_counts = Counter()

        for record_index, record in enumerate(underlying_records):
            for suffix in ("C", "P"):
                inscode = norm_text(record.get(f"insCode_{suffix}"))
                if not inscode:
                    continue

                source_ids.add(inscode)
                contract = db_by_code.get(inscode)

                if contract is None:
                    comparison_rows.append({
                        "InsCode": inscode,
                        "Type": suffix,
                        "Problem": "SOURCE CONTRACT NOT FOUND IN DATABASE",
                    })
                    continue

                option_id = contract["OptionID"]
                snapshot = snapshot_by_id.get(option_id)

                if snapshot is None:
                    comparison_rows.append({
                        "InsCode": inscode,
                        "Type": suffix,
                        "OptionID": option_id,
                        "Problem": "SNAPSHOT NOT FOUND FOR RUN TIMESTAMP",
                    })
                    continue

                row_result = {
                    "InsCode": inscode,
                    "Type": suffix,
                    "OptionID": option_id,
                    "Problem": "",
                }

                for db_field, api_prefix in DIRECT_FIELD_MAP.items():
                    api_key = f"{api_prefix}_{suffix}"
                    raw_value = record.get(api_key)
                    db_value = snapshot.get(db_field)

                    if api_key in record:
                        raw_field_presence[api_key] += 1
                    else:
                        raw_field_missing[api_key] += 1

                    if comparable(raw_value) == Decimal("0"):
                        source_zero_counts[db_field] += 1

                    if comparable(db_value) == Decimal("0"):
                        snapshot_zero_counts[db_field] += 1

                    if comparable(raw_value) != comparable(db_value):
                        mismatch_counts[db_field] += 1
                        row_result[db_field] = (
                            f"RAW={fmt(raw_value)}; DB={fmt(db_value)}"
                        )

                for db_field, api_key in UNDERLYING_FIELD_MAP.items():
                    raw_value = record.get(api_key)
                    db_value = snapshot.get(db_field)

                    if comparable(raw_value) != comparable(db_value):
                        mismatch_counts[db_field] += 1
                        row_result[db_field] = (
                            f"RAW={fmt(raw_value)}; DB={fmt(db_value)}"
                        )

                comparison_rows.append(row_result)

        log()
        log("C. FIELD MAPPING COUNTS")
        for db_field in DIRECT_FIELD_MAP:
            log(
                f"{db_field:24} "
                f"raw-zero={source_zero_counts[db_field]:3}  "
                f"snapshot-zero={snapshot_zero_counts[db_field]:3}  "
                f"mismatches={mismatch_counts[db_field]:3}"
            )

        log()
        log("D. SOURCE FIELD PRESENCE")
        for db_field, api_prefix in DIRECT_FIELD_MAP.items():
            key_counts = [
                (f"{api_prefix}_C", raw_field_presence[f"{api_prefix}_C"],
                 raw_field_missing[f"{api_prefix}_C"]),
                (f"{api_prefix}_P", raw_field_presence[f"{api_prefix}_P"],
                 raw_field_missing[f"{api_prefix}_P"]),
            ]
            for key, present, missing in key_counts:
                log(
                    f"{key:24} present={present:3} missing={missing:3}"
                )

        log()
        log("E. ZERO OR MISSING ORDER QUOTES")
        zero_quote_rows = []

        for row in comparison_rows:
            if "OptionID" not in row:
                continue

            snapshot = snapshot_by_id.get(row["OptionID"])
            if not snapshot:
                continue

            buy_price = as_decimal(snapshot.get("BestBuyPrice"))
            buy_volume = as_decimal(snapshot.get("BestBuyVolume"))
            sell_price = as_decimal(snapshot.get("BestSellPrice"))
            sell_volume = as_decimal(snapshot.get("BestSellVolume"))

            if any(
                value is None or value == 0
                for value in (buy_price, buy_volume, sell_price, sell_volume)
            ):
                zero_quote_rows.append(row)

                log(
                    f"InsCode={row['InsCode']} "
                    f"Type={row['Type']} "
                    f"OptionID={row['OptionID']} | "
                    f"BuyPrice={fmt(snapshot.get('BestBuyPrice'))} "
                    f"BuyVolume={fmt(snapshot.get('BestBuyVolume'))} | "
                    f"SellPrice={fmt(snapshot.get('BestSellPrice'))} "
                    f"SellVolume={fmt(snapshot.get('BestSellVolume'))}"
                )

                # Show the corresponding raw fields for this contract.
                raw_record = next(
                    (
                        item for item in underlying_records
                        if norm_text(item.get(f"insCode_{row['Type']}"))
                        == row["InsCode"]
                    ),
                    None,
                )

                if raw_record is not None:
                    suffix = row["Type"]
                    log(
                        "  RAW: "
                        f"pMeDem={fmt(raw_record.get(f'pMeDem_{suffix}'))}, "
                        f"qTitMeDem={fmt(raw_record.get(f'qTitMeDem_{suffix}'))}, "
                        f"pMeOf={fmt(raw_record.get(f'pMeOf_{suffix}'))}, "
                        f"qTitMeOf={fmt(raw_record.get(f'qTitMeOf_{suffix}'))}"
                    )

        if not zero_quote_rows:
            log("No zero/missing quote rows found in the matched snapshots.")

        log()
        log("F. DATE/TIME FIELDS IN RAW JSON")
        date_time_keys = find_date_time_keys(source_json)

        if date_time_keys:
            for key_path, value in date_time_keys[:100]:
                log(f"{key_path} = {fmt(value)}")
            if len(date_time_keys) > 100:
                log(f"... {len(date_time_keys) - 100} additional matches omitted")
        else:
            log("No keys containing date/time/datetime found in scanned JSON.")

        log()
        log("G. SNAPSHOT NULL COUNTS")
        for field in (
            "DataDate",
            "DataTime",
            "FirstPrice",
            "MinPrice",
            "MaxPrice",
        ):
            null_count = sum(
                1 for row in snapshot_rows
                if row.get(field) is None
            )
            log(f"{field:24} NULL={null_count:3}/{len(snapshot_rows)}")

        log()
        log("H. UNDERLYING RAW VS SNAPSHOT")
        if underlying_snapshots:
            underlying_snapshot = underlying_snapshots[0]
            source_underlying = underlying_records[0]

            for db_field, api_key in (
                ("LastPrice", "pDrCotVal_UA"),
                ("ClosingPrice", "pClosing_UA"),
                ("YesterdayPrice", "priceYesterday_UA"),
            ):
                raw_value = source_underlying.get(api_key)
                db_value = underlying_snapshot.get(db_field)
                status = (
                    "MATCH"
                    if comparable(raw_value) == comparable(db_value)
                    else "MISMATCH"
                )
                log(
                    f"{db_field:24} RAW={fmt(raw_value)} "
                    f"DB={fmt(db_value)} [{status}]"
                )

            for field in ("DataDate", "DataTime"):
                log(
                    f"{field:24} DB={fmt(underlying_snapshot.get(field))}"
                )
        else:
            log("No underlying snapshot found for this capture timestamp.")

        # ----------------------------------------------------
        # 4. Summary
        # ----------------------------------------------------
        all_mismatches = sum(mismatch_counts.values())
        source_only = source_ids - set(db_by_code)
        db_only = set(db_by_code) - source_ids

        log()
        log("=" * 78)
        log("I. AUDIT SUMMARY")
        log("=" * 78)
        log(f"Raw source contract IDs: {len(source_ids)}")
        log(f"Source-only contract IDs: {len(source_only)}")
        log(f"Database-only contract IDs: {len(db_only)}")
        log(f"Matched snapshot count: {len(snapshot_by_id)}")
        log(f"Direct field mismatch count: {all_mismatches}")
        log(f"Contracts with zero/missing quotes: {len(zero_quote_rows)}")

        if source_only:
            log(f"Source-only IDs: {sorted(source_only)}")
        if db_only:
            log(f"Database-only IDs: {sorted(db_only)}")

        log()
        log("Interpretation:")
        log("- A RAW/DB mismatch indicates a value discrepancy to investigate.")
        log("- A RAW zero stored as DB zero is not a mapping discrepancy.")
        log("- Absent date/time keys in raw JSON support the current NULL mapping.")
        log("- This audit does not modify data or correct any field automatically.")
        log("BR90 FINISHED - READ ONLY")

    except Exception as exc:
        exit_code = 1
        log()
        log("BR90 ERROR")
        log(f"{type(exc).__name__}: {exc}")

    finally:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass

        try:
            with report_path.open("w", encoding="utf-8") as file:
                file.write("\n".join(lines) + "\n")
            print(f"\nReport saved: {report_path}")
        except Exception as exc:
            print(f"Could not save report: {exc}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
