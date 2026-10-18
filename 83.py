
# BR83 - Direct TSETMC API Probe
# Read-only HTTP request; no database or file writes.

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

URL = (
    "https://cdn.tsetmc.com/api/Instrument/"
    "GetInstrumentOptionMarketWatch/1"
)
UNDERLYING = "17914401175772326"

def main():
    print("=" * 68)
    print("BR83 - DIRECT API PROBE")
    print("Database access: NONE")
    print("File writes: NONE")
    print("=" * 68)

    request = urllib.request.Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        },
        method="GET",
    )

    started = datetime.now(timezone.utc)
    monotonic_start = time.monotonic()

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            body = response.read()
            received = datetime.now(timezone.utc)

        elapsed = time.monotonic() - monotonic_start
        payload = json.loads(body.decode("utf-8-sig"))

        rows = payload.get("instrumentOptMarketWatch")
        if not isinstance(rows, list):
            raise ValueError("Unexpected API JSON structure.")

        matched = [
            row for row in rows
            if str(row.get("uaInsCode", "")).strip() == UNDERLYING
        ]

        print(f"HTTP status: {status}")
        print(f"Request started UTC: {started.isoformat()}")
        print(f"Response received UTC: {received.isoformat()}")
        print(f"Elapsed seconds: {elapsed:.3f}")
        print(f"Response bytes: {len(body)}")
        print(f"Total API rows: {len(rows)}")
        print(f"Underlying matching rows: {len(matched)}")

        if matched:
            print("Sample field names:")
            print(", ".join(sorted(matched[0].keys())))

            print("Sample market fields:")
            sample = matched[0]
            for key in (
                "uaInsCode", "insCode", "beginDate", "endDate",
                "remainedDay", "pDrCotVal_C", "pDrCotVal_P",
                "pClosing_C", "pClosing_P",
            ):
                if key in sample:
                    print(f"  {key}: {sample[key]}")

        print("BR83 RESULT: SUCCESS")

    except (urllib.error.URLError, TimeoutError, OSError,
            json.JSONDecodeError, ValueError) as exc:
        print(f"BR83 RESULT: FAILED")
        print(f"Error: {type(exc).__name__}: {exc}")

if __name__ == "__main__":
    main()
