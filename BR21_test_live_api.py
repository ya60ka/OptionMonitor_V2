
# BR21 - Test live TSETMC API and save raw response
# Purpose:
# 1. Request the option market watch endpoint.
# 2. Save the original HTTP response body without reformatting it.
# 3. Save HTTP diagnostics and inspect the JSON structure generically.
# 4. Do not connect to or modify any database.

from datetime import datetime
from pathlib import Path
import json
import sys
import traceback

import requests


# --------------------------------------------------
# Configuration
# --------------------------------------------------

API_URL = (
    "https://cdn.tsetmc.com/api/"
    "Instrument/GetInstrumentOptionMarketWatch/1"
)

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
OUTPUT_DIR = PROJECT_DIR / "data" / "api_tests"

TIMEOUT_SECONDS = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.tsetmc.com/",
}


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def describe_structure(value, depth=0, max_depth=5):
    """
    Describe JSON types, object keys and array samples.
    Does not assume specific API field names.
    """
    indent = "  " * depth

    if isinstance(value, dict):
        print(f"{indent}Object: {len(value)} keys")

        if depth >= max_depth:
            print(f"{indent}  ... maximum inspection depth reached")
            return

        for key, item in value.items():
            print(f"{indent}  Key: {key!r}")
            describe_structure(item, depth + 2, max_depth)

    elif isinstance(value, list):
        print(f"{indent}Array: {len(value)} items")

        if not value:
            return

        if depth >= max_depth:
            print(f"{indent}  ... maximum inspection depth reached")
            return

        # Inspect the first item only to keep output manageable.
        print(f"{indent}  First item structure:")
        describe_structure(value[0], depth + 2, max_depth)

        if len(value) > 1:
            print(f"{indent}  Remaining items not expanded")

    else:
        print(f"{indent}Type: {type(value).__name__}")


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_path = OUTPUT_DIR / f"BR21_response_{timestamp}.raw"
    metadata_path = OUTPUT_DIR / f"BR21_metadata_{timestamp}.json"
    structure_path = OUTPUT_DIR / f"BR21_structure_{timestamp}.txt"

    print("=" * 70)
    print("BR21 - TSETMC Live API Test")
    print("=" * 70)
    print(f"Python       : {sys.executable}")
    print(f"API URL      : {API_URL}")
    print(f"Output       : {OUTPUT_DIR}")
    print("Database     : NOT USED")
    print("-" * 70)

    session = requests.Session()

    try:
        started_at = datetime.now().astimezone().isoformat()

        response = session.get(
            API_URL,
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )

        received_at = datetime.now().astimezone().isoformat()

        # Save the original response bytes before parsing.
        # No JSON reformatting or database operations.
        raw_path.write_bytes(response.content)

        print(f"HTTP status  : {response.status_code}")
        print(f"Content-Type : {response.headers.get('Content-Type')}")
        print(f"Body bytes   : {len(response.content):,}")
        print(f"Raw response : {raw_path}")

        metadata = {
            "test": "BR21",
            "request_url": API_URL,
            "started_at": started_at,
            "received_at": received_at,
            "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "content_length_header": response.headers.get("Content-Length"),
            "response_bytes": len(response.content),
            "response_encoding": response.encoding,
            "raw_file": str(raw_path),
            "database_accessed": False,
        }

        try:
            metadata["final_url"] = response.url
            metadata["redirect_history"] = [
                {
                    "status": item.status_code,
                    "url": item.url,
                    "location": item.headers.get("Location"),
                }
                for item in response.history
            ]
        except Exception:
            pass

        # Record HTTP details even when the server returns an error.
        if not response.ok:
            metadata["http_error_body_saved"] = True
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            print(f"Metadata     : {metadata_path}")
            print("RESULT       : HTTP ERROR")
            print("The response body was saved for diagnosis.")
            print("No database was accessed.")
            return

        # Parse the response only for inspection.
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            metadata["json_parse_error"] = str(exc)
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            print("RESULT       : Response is not valid JSON")
            print(f"Raw response : {raw_path}")
            print(f"Metadata     : {metadata_path}")
            print(f"Parse error  : {exc}")
            print("No database was accessed.")
            return

        metadata["json_root_type"] = type(payload).__name__

        # Inspect structure and capture it in a separate text file.
        original_stdout = sys.stdout

        try:
            with structure_path.open("w", encoding="utf-8") as file:
                sys.stdout = file
                print("BR21 JSON STRUCTURE")
                print("=" * 70)
                describe_structure(payload)
        finally:
            sys.stdout = original_stdout

        # Print a concise summary to the console.
        print(f"JSON root    : {type(payload).__name__}")

        if isinstance(payload, dict):
            print(f"Root keys    : {list(payload.keys())}")
        elif isinstance(payload, list):
            print(f"Root items   : {len(payload)}")

        metadata["structure_file"] = str(structure_path)
        metadata["json_parse_success"] = True

        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"Raw response : {raw_path}")
        print(f"Structure    : {structure_path}")
        print(f"Metadata     : {metadata_path}")
        print("-" * 70)
        print("RESULT       : SUCCESS")
        print("No database was accessed or modified.")

    except requests.RequestException as exc:
        print("RESULT       : REQUEST ERROR")
        print(f"Error        : {exc}")
        print("\nTraceback:")
        traceback.print_exc()

    except Exception:
        print("RESULT       : UNEXPECTED ERROR")
        traceback.print_exc()

    finally:
        session.close()


if __name__ == "__main__":
    main()
