
# BR35 - Validate Live API Mapping Against Database
# Project: OptionMonitor_V2
# Database: OptionMarketDB_V2
# Purpose: Validate all live API fields against registered contracts.
# Safety: READ ONLY DATABASE ACCESS. NO DATABASE WRITES.
# Output: Local JSON dry-run plan and text report.

import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"

UNDERLYING_INSCODE = "17914401175772326"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    "DATABASE=OptionMarketDB_V2;"
    "Trusted_Connection=yes;"
    "ApplicationIntent=ReadOnly;"
)

API_ROOT_KEY = "instrumentOptMarketWatch"
EXPECTED_CONTRACT_COUNT = 84


def print_section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def to_decimal(value):
    """Convert an API value to Decimal, or None if unavailable."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None

    try:
        result = Decimal(str(value))
        if not result.is_finite():
            return None
        return result
    except (InvalidOperation, ValueError, TypeError):
        return None


def json_number(value):
    """Convert Decimal into a JSON-compatible number."""
    if value is None:
        return None

    # Preserve integral values as integers.
    if value == value.to_integral_value():
        return int(value)

    return float(value)


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_date(value):
    """Convert YYYYMMDD into YYYY-MM-DD."""
    value = normalize_text(value)

    if not re.fullmatch(r"\d{8}", value):
        return None

    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def extract_persian_expiry(contract_name):
    """
    Extract the Persian expiry embedded in the full contract name.
    Example: 'اختيارخ اهرم-20000-1405/07/29'
    """
    if not contract_name:
        return None

    match = re.search(
        r"(\d{4}/\d{2}/\d{2})\s*$",
        str(contract_name).strip(),
    )

    return match.group(1) if match else None


def api_value(record, field):
    return record.get(field)


def market_decimal(record, field):
    return to_decimal(api_value(record, field))


def make_option_candidate(record, suffix, option_type, retrieval_time):
    """
    Build a dry-run representation for one option contract.
    No SQL commands are executed here.
    """
    last_price = market_decimal(record, f"pDrCotVal_{suffix}")
    closing_price = market_decimal(record, f"pClosing_{suffix}")
    yesterday_price = market_decimal(
        record,
        f"priceYesterday_{suffix}",
    )

    trade_count = market_decimal(record, f"zTotTran_{suffix}")
    volume = market_decimal(record, f"qTotTran5J_{suffix}")
    trade_value = market_decimal(record, f"qTotCap_{suffix}")

    change = None
    change_percent = None

    if last_price is not None and yesterday_price is not None:
        change = last_price - yesterday_price

        if yesterday_price != 0:
            change_percent = (
                change / yesterday_price * Decimal("100")
            )

    return {
        "TSEInsCode": normalize_text(
            api_value(record, f"insCode_{suffix}")
        ),
        "Symbol": normalize_text(
            api_value(record, f"lVal18AFC_{suffix}")
        ),
        "ContractName": normalize_text(
            api_value(record, f"lVal30_{suffix}")
        ),
        "OptionType": option_type,
        "StrikePrice": json_number(
            to_decimal(api_value(record, "strikePrice"))
        ),
        "ExpiryDate": (
            normalize_date(api_value(record, "endDate")).isoformat()
            if normalize_date(api_value(record, "endDate"))
            else None
        ),
        "ExpiryDatePersian": extract_persian_expiry(
            api_value(record, f"lVal30_{suffix}")
        ),
        "ContractSize": json_number(
            to_decimal(api_value(record, "contractSize"))
        ),
        "MarketData": {
            "DataDate": None,
            "DataTime": None,
            "LastPrice": json_number(last_price),
            "ClosingPrice": json_number(closing_price),
            "FirstPrice": None,
            "MinPrice": None,
            "MaxPrice": None,
            "YesterdayPrice": json_number(yesterday_price),
            "PriceChange": json_number(change),
            "PriceChangePercent": json_number(change_percent),
            "TradeCount": json_number(trade_count),
            "Volume": json_number(volume),
            "TradeValue": json_number(trade_value),
            "BestBuyPrice": json_number(
                market_decimal(record, f"pMeDem_{suffix}")
            ),
            "BestBuyVolume": json_number(
                market_decimal(record, f"qTitMeDem_{suffix}")
            ),
            "BestSellPrice": json_number(
                market_decimal(record, f"pMeOf_{suffix}")
            ),
            "BestSellVolume": json_number(
                market_decimal(record, f"qTitMeOf_{suffix}")
            ),
            "OpenInterest": json_number(
                market_decimal(record, f"oP_{suffix}")
            ),
            "UnderlyingLastPrice": json_number(
                market_decimal(record, "pDrCotVal_UA")
            ),
            "UnderlyingClosePrice": json_number(
                market_decimal(record, "pClosing_UA")
            ),
            "ContractSize": json_number(
                to_decimal(api_value(record, "contractSize"))
            ),
            "SourceRetrievedAtUTC": retrieval_time,
        },
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_files = sorted(
        OUTPUT_DIR.glob("BR34_live_response_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    report_path = OUTPUT_DIR / f"BR35_report_{timestamp}.txt"
    plan_path = OUTPUT_DIR / f"BR35_dry_run_plan_{timestamp}.json"

    report_lines = []
    errors = []
    warnings = []

    def log(message=""):
        print(message)
        report_lines.append(str(message))

    connection = None
    cursor = None

    try:
        print_section("BR35: CONFIGURATION")
        log(f"Project directory: {PROJECT_DIR}")
        log(f"Database: OptionMarketDB_V2")
        log(f"Underlying InsCode: {UNDERLYING_INSCODE}")
        log("Database mode: READ ONLY")
        log("Database writes: NONE")

        if not raw_files:
            raise FileNotFoundError(
                "No BR34_live_response_*.json file was found in "
                f"{OUTPUT_DIR}"
            )

        source_path = raw_files[0]
        log(f"Source API JSON: {source_path}")

        with source_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if not isinstance(payload, dict):
            raise ValueError("API JSON root must be a dictionary.")

        records = payload.get(API_ROOT_KEY)

        if not isinstance(records, list):
            raise ValueError(
                f"Expected list under API key '{API_ROOT_KEY}'."
            )

        matching_records = [
            record
            for record in records
            if isinstance(record, dict)
            and normalize_text(record.get("uaInsCode"))
            == UNDERLYING_INSCODE
        ]

        print_section("BR35-A: SOURCE VALIDATION")
        log(f"Total API records: {len(records)}")
        log(f"Matching underlying records: {len(matching_records)}")

        if not matching_records:
            raise ValueError(
                "No API records matched the configured underlying."
            )

        retrieval_time = (
            datetime.now(timezone.utc)
            .replace(tzinfo=None)
            .isoformat(timespec="seconds")
        )

        source_options = []

        for record in matching_records:
            for suffix, option_type in (
                ("C", "C"),
                ("P", "P"),
            ):
                candidate = make_option_candidate(
                    record,
                    suffix,
                    option_type,
                    retrieval_time,
                )
                source_options.append(candidate)

        source_ids = [
            item["TSEInsCode"]
            for item in source_options
        ]

        duplicate_source_ids = sorted({
            inscode
            for inscode in source_ids
            if source_ids.count(inscode) > 1
        })

        missing_source_ids = [
            item for item in source_options
            if not item["TSEInsCode"]
        ]

        if duplicate_source_ids:
            errors.append(
                "Duplicate source contract IDs: "
                + ", ".join(duplicate_source_ids)
            )

        if missing_source_ids:
            errors.append(
                f"Source contracts with missing IDs: "
                f"{len(missing_source_ids)}"
            )

        if len(source_options) != EXPECTED_CONTRACT_COUNT:
            warnings.append(
                f"Expected {EXPECTED_CONTRACT_COUNT} contracts; "
                f"source produced {len(source_options)}."
            )

        print_section("BR35-B: DATABASE CONTRACT MATCHING")

        connection = pyodbc.connect(
            CONNECTION_STRING,
            timeout=15,
            autocommit=True,
        )
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                UnderlyingID,
                TSEInsCode,
                Symbol,
                InstrumentName
            FROM dbo.Underlying
            WHERE TSEInsCode = ?
            """,
            UNDERLYING_INSCODE,
        )

        underlying_rows = cursor.fetchall()

        if len(underlying_rows) != 1:
            raise RuntimeError(
                "Expected exactly one matching Underlying row; "
                f"found {len(underlying_rows)}."
            )

        underlying_id = underlying_rows[0][0]
        underlying_symbol = underlying_rows[0][2]

        log(f"UnderlyingID: {underlying_id}")
        log(f"Underlying symbol: {underlying_symbol}")

        cursor.execute(
            """
            SELECT
                OptionID,
                TSEInsCode,
                Symbol,
                ContractName,
                OptionType,
                StrikePrice,
                ExpiryDatePersian,
                ExpiryDate,
                ContractSize,
                IsActive
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
            """,
            underlying_id,
        )

        database_rows = cursor.fetchall()

        database_by_code = {
            normalize_text(row[1]): row
            for row in database_rows
        }

        source_by_code = {
            item["TSEInsCode"]: item
            for item in source_options
            if item["TSEInsCode"]
        }

        source_id_set = set(source_by_code)
        database_id_set = set(database_by_code)

        source_only = sorted(source_id_set - database_id_set)
        database_only = sorted(database_id_set - source_id_set)

        log(f"Database contracts for underlying: {len(database_rows)}")
        log(f"Distinct source contract IDs: {len(source_id_set)}")
        log(f"Source IDs missing from database: {len(source_only)}")
        log(f"Database IDs missing from source: {len(database_only)}")

        if source_only:
            errors.append(
                "Source contract IDs not found in database: "
                + ", ".join(source_only[:20])
            )

        if database_only:
            warnings.append(
                "Database contract IDs absent from this API response: "
                + ", ".join(database_only[:20])
            )

        print_section("BR35-C: FIELD-BY-FIELD VALIDATION")

        matched_count = 0
        active_count = 0
        mismatch_count = 0
        expiry_counts = {}

        for code in sorted(source_id_set & database_id_set):
            source = source_by_code[code]
            db_row = database_by_code[code]

            (
                option_id,
                db_code,
                db_symbol,
                db_contract_name,
                db_type,
                db_strike,
                db_persian_expiry,
                db_expiry,
                db_size,
                is_active,
            ) = db_row

            record_errors = []

            if normalize_text(db_type) != source["OptionType"]:
                record_errors.append(
                    f"OptionType DB={db_type}, "
                    f"API={source['OptionType']}"
                )

            source_strike = to_decimal(source["StrikePrice"])
            database_strike = to_decimal(db_strike)

            if (
                source_strike is None
                or database_strike is None
                or source_strike != database_strike
            ):
                record_errors.append(
                    f"StrikePrice DB={db_strike}, "
                    f"API={source['StrikePrice']}"
                )

            source_expiry = source["ExpiryDate"]
            database_expiry = (
                db_expiry.isoformat()
                if db_expiry is not None
                else None
            )

            if source_expiry != database_expiry:
                record_errors.append(
                    f"ExpiryDate DB={database_expiry}, "
                    f"API={source_expiry}"
                )

            if (
                db_size is not None
                and source["ContractSize"] is not None
                and int(db_size) != int(source["ContractSize"])
            ):
                record_errors.append(
                    f"ContractSize DB={db_size}, "
                    f"API={source['ContractSize']}"
                )

            source_symbol = source["Symbol"]
            if (
                normalize_text(db_symbol)
                and source_symbol
                and normalize_text(db_symbol) != source_symbol
            ):
                warnings.append(
                    f"Symbol mismatch for {code}: "
                    f"DB={db_symbol!r}, API={source_symbol!r}"
                )

            source_persian_expiry = source["ExpiryDatePersian"]
            if (
                normalize_text(db_persian_expiry)
                and source_persian_expiry
                and normalize_text(db_persian_expiry)
                != source_persian_expiry
            ):
                record_errors.append(
                    f"ExpiryDatePersian DB={db_persian_expiry}, "
                    f"API={source_persian_expiry}"
                )

            if record_errors:
                mismatch_count += 1
                errors.append(
                    f"OptionID={option_id}, TSEInsCode={code}: "
                    + "; ".join(record_errors)
                )
            else:
                matched_count += 1

            if bool(is_active):
                active_count += 1

            expiry_key = source_expiry or "UNKNOWN"
            expiry_counts.setdefault(
                expiry_key,
                {"C": 0, "P": 0, "Total": 0},
            )
            expiry_counts[expiry_key][source["OptionType"]] += 1
            expiry_counts[expiry_key]["Total"] += 1

        log(f"Exact contract matches: {matched_count}")
        log(f"Contracts with field mismatches: {mismatch_count}")
        log(f"Active database contracts among matches: {active_count}")

        log("\nContract distribution by Gregorian expiry:")
        for expiry, counts in sorted(expiry_counts.items()):
            log(
                f"  {expiry} | Total={counts['Total']} | "
                f"CALL={counts['C']} | PUT={counts['P']}"
            )

        print_section("BR35-D: MARKET FIELD COVERAGE")

        coverage_fields = [
            "LastPrice",
            "ClosingPrice",
            "YesterdayPrice",
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
        ]

        for field in coverage_fields:
            present = sum(
                1
                for item in source_options
                if item["MarketData"].get(field) is not None
            )
            zero_count = sum(
                1
                for item in source_options
                if item["MarketData"].get(field) == 0
            )

            log(
                f"{field}: populated={present}/{len(source_options)} "
                f"| zero_values={zero_count}"
            )

        # These values are not exposed by the inspected API response.
        log("\nFields deliberately left unset because the API did not")
        log("provide them directly in the inspected response:")
        log("  DataDate, DataTime, FirstPrice, MinPrice, MaxPrice")

        print_section("BR35-E: DRY-RUN PLAN")

        option_id_lookup = {
            code: row[0]
            for code, row in database_by_code.items()
        }

        for item in source_options:
            item["DatabaseOptionID"] = option_id_lookup.get(
                item["TSEInsCode"]
            )

        underlying_live = {
            "UnderlyingID": underlying_id,
            "TSEInsCode": UNDERLYING_INSCODE,
            "Symbol": underlying_symbol,
            "DataDate": None,
            "DataTime": None,
            "LastPrice": None,
            "ClosingPrice": None,
            "YesterdayPrice": None,
            "PriceChange": None,
            "PriceChangePercent": None,
            "TradeCount": None,
            "Volume": None,
            "TradeValue": None,
            "SourceRetrievedAtUTC": retrieval_time,
        }

        # All 42 source records share the same underlying prices.
        first_record = matching_records[0]

        ua_last = market_decimal(first_record, "pDrCotVal_UA")
        ua_close = market_decimal(first_record, "pClosing_UA")
        ua_yesterday = market_decimal(first_record, "priceYesterday_UA")

        underlying_live["LastPrice"] = json_number(ua_last)
        underlying_live["ClosingPrice"] = json_number(ua_close)
        underlying_live["YesterdayPrice"] = json_number(ua_yesterday)

        if ua_last is not None and ua_yesterday is not None:
            ua_change = ua_last - ua_yesterday
            underlying_live["PriceChange"] = json_number(ua_change)

            if ua_yesterday != 0:
                underlying_live["PriceChangePercent"] = json_number(
                    ua_change / ua_yesterday * Decimal("100")
                )

        ready = (
            not errors
            and len(source_options) == EXPECTED_CONTRACT_COUNT
            and len(source_id_set) == EXPECTED_CONTRACT_COUNT
            and len(database_by_code) >= EXPECTED_CONTRACT_COUNT
            and matched_count == EXPECTED_CONTRACT_COUNT
            and active_count == EXPECTED_CONTRACT_COUNT
        )

        plan = {
            "script": "BR35",
            "created_at_utc": retrieval_time,
            "database": "OptionMarketDB_V2",
            "read_only_database_inspection": True,
            "database_modified": False,
            "source_file": str(source_path),
            "underlying": underlying_live,
            "source_record_count": len(matching_records),
            "source_contract_count": len(source_options),
            "database_contract_count": len(database_rows),
            "matched_contract_count": matched_count,
            "field_mismatch_count": mismatch_count,
            "ready_for_next_stage": ready,
            "validation_errors": errors,
            "validation_warnings": warnings,
            "options": source_options,
        }

        with plan_path.open("w", encoding="utf-8") as file:
            json.dump(
                plan,
                file,
                ensure_ascii=False,
                indent=2,
            )

        log(f"Dry-run plan saved: {plan_path}")
        log(f"Ready for next stage: {ready}")
        log(f"Validation errors: {len(errors)}")
        log(f"Validation warnings: {len(warnings)}")

        if errors:
            log("\nVALIDATION ERRORS:")
            for error in errors:
                log(f"  ERROR: {error}")

        if warnings:
            log("\nVALIDATION WARNINGS:")
            for warning in warnings:
                log(f"  WARNING: {warning}")

        print_section("BR35 RESULT")

        if ready:
            log("BR35 RESULT: VALIDATION PASSED")
            log("The dry-run mapping matches all 84 expected contracts.")
            log("No database data was inserted, updated, or deleted.")
        else:
            log("BR35 RESULT: REVIEW REQUIRED")
            log("Do not proceed to database writes until discrepancies")
            log("have been reviewed and resolved.")

        log(f"Plan file: {plan_path}")
        log("DATABASE MODIFICATIONS: NONE")

    except Exception as exc:
        log()
        log("=" * 78)
        log("BR35 ERROR")
        log("=" * 78)
        log(f"Error type: {type(exc).__name__}")
        log(f"Error details: {exc}")
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()

        try:
            with report_path.open("w", encoding="utf-8") as file:
                file.write("\n".join(report_lines))
            print(f"\nReport saved: {report_path}")
        except OSError as exc:
            print(f"Could not save report: {exc}")


if __name__ == "__main__":
    main()
