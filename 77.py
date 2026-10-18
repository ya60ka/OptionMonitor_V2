
# BR77 - Read-Only Source Payload Identity Audit
# Compares the latest BR44 JSON file with RawApiResponse.ResponseJSON.
# Database writes: NONE.

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def get_row_count(payload):
    if isinstance(payload, dict):
        rows = payload.get("instrumentOptMarketWatch")
        if isinstance(rows, list):
            return len(rows)
    return None


def main():
    print("=" * 90)
    print("BR77 - SOURCE PAYLOAD IDENTITY AUDIT (READ ONLY)")
    print("=" * 90)

    print(f"Database target: {DATABASE}")
    print("Database writes: NONE")

    files = sorted(
        DATA_DIR.glob("BR44_live_response_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        print("ERROR: No BR44_live_response_*.json file found.")
        return

    source_file = files[0]
    file_bytes = source_file.read_bytes()
    file_payload = json.loads(file_bytes.decode("utf-8-sig"))

    file_stat = source_file.stat()
    file_mtime = datetime.fromtimestamp(
        file_stat.st_mtime, timezone.utc
    )

    print()
    print("SOURCE FILE")
    print(f"Path              : {source_file}")
    print(f"Size bytes        : {len(file_bytes)}")
    print(f"Modified UTC      : {file_mtime.isoformat()}")
    print(f"Raw file SHA256   : {sha256(file_bytes)}")
    print(f"Canonical SHA256  : {sha256(canonical_json(file_payload))}")
    print(f"JSON row count    : {get_row_count(file_payload)}")

    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
        "ApplicationIntent=ReadOnly;"
    )

    connection = None

    try:
        connection = pyodbc.connect(
            connection_string,
            autocommit=True,
            timeout=20,
        )
        cursor = connection.cursor()

        cursor.execute("SELECT DB_NAME(), @@SERVERNAME")
        db_name, server_name = cursor.fetchone()

        print()
        print("DATABASE CONNECTION")
        print(f"Server             : {server_name}")
        print(f"Database           : {db_name}")

        if db_name != DATABASE:
            raise RuntimeError(f"Unexpected database: {db_name}")

        cursor.execute("""
            SELECT TOP (1)
                RawDataID,
                CollectionRunID,
                APIName,
                RequestURL,
                RetrievedAt,
                HttpStatusCode,
                IsSuccess,
                ResponseJSON
            FROM dbo.RawApiResponse
            WHERE ResponseJSON IS NOT NULL
            ORDER BY RawDataID DESC
        """)

        row = cursor.fetchone()

        if row is None:
            print("ERROR: No stored ResponseJSON found.")
            return

        (
            raw_data_id,
            run_id,
            api_name,
            request_url,
            retrieved_at,
            http_status,
            is_success,
            stored_json,
        ) = row

        if isinstance(stored_json, bytes):
            stored_text = stored_json.decode("utf-8-sig")
        else:
            stored_text = str(stored_json)

        stored_payload = json.loads(stored_text)
        stored_canonical = canonical_json(stored_payload)
        file_canonical = canonical_json(file_payload)

        print()
        print("DATABASE RAW RESPONSE")
        print(f"RawDataID          : {raw_data_id}")
        print(f"CollectionRunID    : {run_id}")
        print(f"APIName            : {api_name}")
        print(f"RequestURL         : {request_url}")
        print(f"RetrievedAt        : {retrieved_at!r}")
        print(f"HttpStatusCode     : {http_status}")
        print(f"IsSuccess          : {is_success}")
        print(f"Stored row count   : {get_row_count(stored_payload)}")
        print(f"Stored JSON bytes  : {len(stored_canonical)}")
        print(f"Stored SHA256      : {sha256(stored_canonical)}")

        print()
        print("COMPARISON")
        print(
            "Canonical payloads identical: "
            f"{file_canonical == stored_canonical}"
        )
        print(
            "File canonical SHA256       : "
            f"{sha256(file_canonical)}"
        )
        print(
            "DB canonical SHA256          : "
            f"{sha256(stored_canonical)}"
        )
        print(
            "File row count               : "
            f"{get_row_count(file_payload)}"
        )
        print(
            "DB row count                 : "
            f"{get_row_count(stored_payload)}"
        )

        if file_canonical == stored_canonical:
            print()
            print(
                "CONCLUSION: The database JSON payload is semantically "
                "identical to the selected BR44 file."
            )
        else:
            print()
            print(
                "CONCLUSION: The payloads differ. "
                "The stored JSON is not identical to the selected BR44 file."
            )

        print()
        print(
            "LIMITATION: Payload equality proves content identity, "
            "not the original time at which the API response was fetched."
        )
        print("BR77 RESULT: COMPLETED")

    except Exception as exc:
        print(f"BR77 ERROR: {type(exc).__name__}: {exc}")
        raise

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
