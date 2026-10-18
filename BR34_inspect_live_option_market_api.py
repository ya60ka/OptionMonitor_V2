
# BR34 - Inspect Live Option Market API
# Project: OptionMonitor_V2
# Purpose: Discover real API fields before database ingestion.
# Safety: NO DATABASE CONNECTION / NO DATABASE WRITES.

import json
import sys
from datetime import datetime
from pathlib import Path

import requests


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"

API_URL = (
    "https://cdn.tsetmc.com/api/"
    "Instrument/GetInstrumentOptionMarketWatch/1"
)

UNDERLYING_INSCODE = "17914401175772326"
ROOT_KEY = "instrumentOptMarketWatch"
SAMPLE_LIMIT = 5
TIMEOUT_SECONDS = 30


def print_section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def safe_json_value(value, max_length=2500):
    """Convert a value to printable JSON without excessive output."""
    try:
        result = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )
    except Exception:
        result = str(value)

    if len(result) > max_length:
        return result[:max_length] + "... [TRUNCATED]"

    return result


def find_matching_records(records, underlying_code):
    """
    Find records containing the underlying InsCode as an exact
    scalar value in any nested dictionary/list.
    """
    target = str(underlying_code)
    matches = []

    def contains_target(value):
        if isinstance(value, dict):
            return any(
                contains_target(item)
                for item in value.values()
            )

        if isinstance(value, list):
            return any(
                contains_target(item)
                for item in value
            )

        if value is None or isinstance(value, (dict, list)):
            return False

        return str(value).strip() == target

    for index, record in enumerate(records):
        if contains_target(record):
            matches.append((index, record))

    return matches


def collect_field_names(records):
    """Collect field names at every dictionary nesting level."""
    fields = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                fields.add(str(key))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for record in records:
        walk(record)

    return sorted(fields, key=str.lower)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = OUTPUT_DIR / f"BR34_live_response_{timestamp}.json"
    report_path = OUTPUT_DIR / f"BR34_report_{timestamp}.txt"

    report_lines = []

    def log(message=""):
        print(message)
        report_lines.append(str(message))

    log("=" * 78)
    log("BR34 - INSPECT LIVE OPTION MARKET API")
    log("=" * 78)
    log(f"Project directory : {PROJECT_DIR}")
    log(f"API URL           : {API_URL}")
    log(f"Underlying InsCode: {UNDERLYING_INSCODE}")
    log("Database access   : NONE")
    log("Database writes   : NONE")

    try:
        log()
        log("Sending GET request...")

        response = requests.get(
            API_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "OptionMonitor_V2/BR34",
            },
            timeout=TIMEOUT_SECONDS,
        )

        log(f"HTTP status: {response.status_code}")
        log(f"Response bytes: {len(response.content)}")

        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "API response is not valid JSON."
            ) from exc

        # Save the exact decoded JSON response for later inspection.
        with raw_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                payload,
                file,
                ensure_ascii=False,
                indent=2,
            )

        log(f"JSON response saved: {raw_path}")

        # ----------------------------------------------------------
        # BR34-A: Response structure
        # ----------------------------------------------------------
        print_section("BR34-A: RESPONSE STRUCTURE")
        log("Top-level type: " + type(payload).__name__)

        if isinstance(payload, dict):
            top_keys = list(payload.keys())
            log(f"Top-level keys: {top_keys}")

            records = payload.get(ROOT_KEY)

            if records is None:
                log(
                    f"Expected root key '{ROOT_KEY}' not found."
                )
                log("Available top-level values and types:")

                for key, value in payload.items():
                    log(
                        f"  {key}: {type(value).__name__}"
                    )

                raise RuntimeError(
                    "Unexpected API response structure; "
                    "inspect the saved JSON file."
                )
        elif isinstance(payload, list):
            records = payload
            log("API root is a list.")
        else:
            raise RuntimeError(
                f"Unexpected root type: {type(payload).__name__}"
            )

        if not isinstance(records, list):
            raise RuntimeError(
                f"'{ROOT_KEY}' is not a list."
            )

        log(f"Total records in API array: {len(records)}")

        # ----------------------------------------------------------
        # BR34-B: Field inventory
        # ----------------------------------------------------------
        print_section("BR34-B: FIELD INVENTORY")

        fields = collect_field_names(records)
        log(f"Total distinct field names: {len(fields)}")

        for field in fields:
            log(f"  {field}")

        # ----------------------------------------------------------
        # BR34-C: Matching records
        # ----------------------------------------------------------
        print_section("BR34-C: UNDERLYING MATCHES")

        matches = find_matching_records(
            records,
            UNDERLYING_INSCODE,
        )

        log(f"Matching records: {len(matches)}")

        if not matches:
            log(
                "No records contained the underlying InsCode "
                "as an exact value."
            )
            log(
                "The API may use another underlying identifier "
                "or a different response structure."
            )

        for index, record in matches[:SAMPLE_LIMIT]:
            log()
            log("-" * 78)
            log(f"API array index: {index}")
            log("Complete matching record:")
            log(safe_json_value(record, max_length=10000))

        # ----------------------------------------------------------
        # BR34-D: Candidate identifier and market fields
        # ----------------------------------------------------------
        print_section("BR34-D: CANDIDATE FIELD VALUES")

        candidate_terms = (
            "inscode",
            "symbol",
            "name",
            "underlying",
            "ua",
            "strike",
            "expiry",
            "date",
            "price",
            "last",
            "close",
            "volume",
            "value",
            "trade",
            "buy",
            "sell",
            "bid",
            "ask",
            "openinterest",
            "contractsize",
            "count",
            "time",
        )

        if matches:
            for index, record in matches[:SAMPLE_LIMIT]:
                log()
                log(f"[Record index {index}]")

                if not isinstance(record, dict):
                    log(
                        "Record is not a dictionary: "
                        + safe_json_value(record)
                    )
                    continue

                found = False

                for key, value in record.items():
                    key_lower = str(key).lower()

                    if any(
                        term in key_lower
                        for term in candidate_terms
                    ):
                        found = True
                        log(
                            f"  {key} = "
                            f"{safe_json_value(value, 1000)}"
                        )

                if not found:
                    log(
                        "No candidate fields matched the "
                        "field-name filters."
                    )

        # ----------------------------------------------------------
        # BR34-E: Report
        # ----------------------------------------------------------
        print_section("BR34-E: RESULT")

        log(f"API record count: {len(records)}")
        log(f"Matching record count: {len(matches)}")
        log(f"Distinct fields: {len(fields)}")
        log(f"Saved raw JSON: {raw_path}")
        log("DATABASE MODIFICATIONS: NONE")
        log("BR34 COMPLETE")

    except Exception as exc:
        log()
        log("=" * 78)
        log("BR34 ERROR")
        log("=" * 78)
        log(f"Error type: {type(exc).__name__}")
        log(f"Error details: {exc}")

        try:
            with report_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                file.write("\n".join(report_lines))
        except OSError:
            pass

        raise

    finally:
        try:
            with report_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                file.write("\n".join(report_lines))
        except OSError as exc:
            print(f"Warning: Could not save report: {exc}")

        print(f"\nConsole report saved: {report_path}")


if __name__ == "__main__":
    main()
