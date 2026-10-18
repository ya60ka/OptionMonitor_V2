
# BR91 - Inspect Raw TSETMC API Fields
# Read-only audit: no API request and no database changes.

import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

import pyodbc


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"

SQL_SERVER = "localhost"
SQL_DATABASE = "OptionMarketDB_V2"
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

COLLECTION_RUN_ID = 3

CANDIDATE_WORDS = (
    "first", "min", "max", "low", "high",
    "price", "date", "time", "datetime",
    "open", "close", "begin", "end",
)

JSON_COLUMN_CANDIDATES = (
    "ResponseJSON",
    "ResponseJson",
    "RawResponse",
    "ResponseBody",
    "ResponseText",
    "ResponsePayload",
    "Response",
)


def connect_read_only():
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
        "ApplicationIntent=ReadOnly;"
    )
    return pyodbc.connect(connection_string, timeout=15)


def parse_json(value):
    if value is None:
        return None

    if isinstance(value, bytes):
        value = value.decode("utf-8-sig", errors="replace")

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return json.loads(value)

    if isinstance(value, (dict, list)):
        return value

    return json.loads(str(value))


def get_nested_records(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    # Find the known API collection, allowing minor naming variations.
    for key, value in payload.items():
        if (
            key.lower() == "instrumentoptmarketwatch"
            and isinstance(value, list)
        ):
            return value

    return []


def collect_key_paths(value, prefix="$"):
    """Return every nested JSON key path and its value."""
    result = []

    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            result.append((path, child))
            result.extend(collect_key_paths(child, path))

    elif isinstance(value, list):
        # Inspect every element, not just the first few.
        for index, child in enumerate(value):
            result.extend(
                collect_key_paths(child, f"{prefix}[{index}]")
            )

    return result


def display_value(value, limit=100):
    text = json.dumps(
        value,
        ensure_ascii=False,
        default=str,
    )
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def main():
    print("=" * 78)
    print("BR91 - Inspect Raw TSETMC API Fields")
    print("=" * 78)
    print(f"Database          : {SQL_DATABASE}")
    print(f"CollectionRunID    : {COLLECTION_RUN_ID}")
    print("Mode               : READ ONLY")
    print("New API request    : NO")
    print("Database writes    : NO")
    print()

    connection = None

    try:
        connection = connect_read_only()
        cursor = connection.cursor()

        # Inspect actual table columns rather than assuming the schema.
        cursor.execute("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'RawApiResponse'
            ORDER BY ORDINAL_POSITION
        """)
        columns = [row[0] for row in cursor.fetchall()]

        if not columns:
            raise RuntimeError(
                "Table RawApiResponse was not found in the selected database."
            )

        print("RawApiResponse columns:")
        for column in columns:
            print(f"  - {column}")

        run_column = next(
            (c for c in columns if c.lower() == "collectionrunid"),
            None,
        )

        if not run_column:
            raise RuntimeError(
                "CollectionRunID column was not found in RawApiResponse."
            )

        # Identifiers come from INFORMATION_SCHEMA, not user input.
        cursor.execute(
            f"SELECT * FROM dbo.RawApiResponse "
            f"WHERE [{run_column}] = ?",
            COLLECTION_RUN_ID,
        )

        result_columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()

        if not rows:
            raise RuntimeError(
                f"No RawApiResponse row found for "
                f"CollectionRunID={COLLECTION_RUN_ID}."
            )

        print(f"\nRawApiResponse rows found: {len(rows)}")

        column_indexes = {
            name.lower(): index
            for index, name in enumerate(result_columns)
        }

        json_column = next(
            (
                name for name in JSON_COLUMN_CANDIDATES
                if name.lower() in column_indexes
            ),
            None,
        )

        payload = None
        selected_json_column = None

        # Prefer a known JSON column; fall back to detecting JSON content.
        for row in rows:
            if json_column:
                value = row[column_indexes[json_column.lower()]]
                try:
                    parsed = parse_json(value)
                except (ValueError, TypeError, UnicodeError):
                    parsed = None

                if isinstance(parsed, (dict, list)):
                    payload = parsed
                    selected_json_column = json_column
                    break

            for column_name, value in zip(result_columns, row):
                if not isinstance(value, (str, bytes)):
                    continue

                sample = (
                    value.decode("utf-8", errors="replace")
                    if isinstance(value, bytes)
                    else value
                ).lstrip()

                if not sample.startswith(("{", "[")):
                    continue

                try:
                    parsed = parse_json(value)
                except (ValueError, TypeError, UnicodeError):
                    continue

                if isinstance(parsed, (dict, list)):
                    payload = parsed
                    selected_json_column = column_name
                    break

            if payload is not None:
                break

        if payload is None:
            raise RuntimeError(
                "Could not find a JSON payload in the returned rows."
            )

        print(f"JSON column used    : {selected_json_column}")

        if isinstance(payload, dict):
            print("JSON root keys:")
            for key in payload:
                print(f"  - {key}")

        records = get_nested_records(payload)

        if not records:
            raise RuntimeError(
                "instrumentOptMarketWatch list was not found in the JSON."
            )

        print(f"\nAPI records         : {len(records)}")

        # Count keys and nested key paths across all API records.
        top_key_counts = Counter()
        path_counts = Counter()
        path_samples = defaultdict(list)

        for record_index, record in enumerate(records):
            if isinstance(record, dict):
                top_key_counts.update(record.keys())

            for path, value in collect_key_paths(record):
                path_counts[path] += 1
                if len(path_samples[path]) < 3:
                    path_samples[path].append(
                        (record_index, display_value(value))
                    )

        print("\n" + "=" * 78)
        print("ALL DISTINCT TOP-LEVEL RECORD KEYS")
        print("=" * 78)

        for key, count in sorted(
            top_key_counts.items(),
            key=lambda item: item[0].lower(),
        ):
            print(f"{key:<42} present in {count:>4}/{len(records)} records")

        print("\n" + "=" * 78)
        print("CANDIDATE FIELDS: PRICE / FIRST / MIN / MAX / DATE / TIME")
        print("=" * 78)

        candidates = []

        for path, count in path_counts.items():
            final_key = path.rsplit(".", 1)[-1].lower()
            if any(word in final_key for word in CANDIDATE_WORDS):
                candidates.append((path, count))

        for path, count in sorted(candidates, key=lambda item: item[0].lower()):
            print(f"\n{path}")
            print(f"  Occurrences: {count}")

            for record_index, sample in path_samples[path]:
                print(f"  Sample record #{record_index}: {sample}")

        if not candidates:
            print("No candidate fields found.")

        print("\n" + "=" * 78)
        print("FIRST THREE API RECORDS - COMPLETE KEY LIST")
        print("=" * 78)

        for index, record in enumerate(records[:3]):
            print(f"\nRecord #{index}")

            if isinstance(record, dict):
                for key in sorted(record.keys(), key=str.lower):
                    print(f"  {key}: {display_value(record[key])}")
            else:
                print(f"  Non-dictionary record: {display_value(record)}")

        # Save a report for later reference; database remains unchanged.
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = OUTPUT_DIR / (
            f"BR91_inspect_raw_api_fields_run_{COLLECTION_RUN_ID}_"
            f"{datetime.now():%Y%m%d_%H%M%S}.txt"
        )

        # Redirect-free report generation: repeat the key findings to file.
        with report_path.open("w", encoding="utf-8") as report:
            report.write("BR91 - Inspect Raw TSETMC API Fields\n")
            report.write(f"CollectionRunID: {COLLECTION_RUN_ID}\n")
            report.write(f"JSON column: {selected_json_column}\n")
            report.write(f"API records: {len(records)}\n\n")

            report.write("TOP-LEVEL KEYS\n")
            for key, count in sorted(
                top_key_counts.items(),
                key=lambda item: item[0].lower(),
            ):
                report.write(f"{key}: {count}/{len(records)}\n")

            report.write("\nCANDIDATE FIELDS\n")
            for path, count in sorted(
                candidates,
                key=lambda item: item[0].lower(),
            ):
                report.write(f"\n{path} (occurrences={count})\n")
                for record_index, sample in path_samples[path]:
                    report.write(
                        f"  record #{record_index}: {sample}\n"
                    )

            report.write("\nFIRST THREE RECORDS\n")
            for index, record in enumerate(records[:3]):
                report.write(f"\nRecord #{index}\n")
                report.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                )
                report.write("\n")

        print("\n" + "=" * 78)
        print("BR91 COMPLETED")
        print(f"Report: {report_path}")
        print("No database changes were made.")
        print("=" * 78)

    except Exception as exc:
        print(f"\nBR91 FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
