
# BR85 - Audit Live TSETMC API Fields
# Read-only: no database connection and no file writes.

import json
import urllib.request
from datetime import datetime, timezone

API_URL = (
    "https://cdn.tsetmc.com/api/Instrument/"
    "GetInstrumentOptionMarketWatch/1"
)
UNDERLYING_INSCODE = "17914401175772326"

def main():
    print("=" * 76)
    print("BR85 - LIVE API FIELD AUDIT")
    print("Database access: NONE")
    print("=" * 76)

    started = datetime.now(timezone.utc)
    request = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        },
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        status = response.status
        body = response.read()
        received = datetime.now(timezone.utc)

    print(f"HTTP status       : {status}")
    print(f"Request started   : {started.isoformat()}")
    print(f"Response received : {received.isoformat()}")
    print(f"Elapsed seconds   : {(received-started).total_seconds():.3f}")
    print(f"Response bytes    : {len(body)}")

    payload = json.loads(body.decode("utf-8-sig"))
    rows = payload.get("instrumentOptMarketWatch", [])

    print(f"API rows          : {len(rows)}")

    matched = [
        row for row in rows
        if any(
            str(value).strip() == UNDERLYING_INSCODE
            for value in row.values()
            if value is not None
        )
    ]

    print(f"Matching rows     : {len(matched)}")

    if not matched:
        print("No rows matched the underlying InsCode.")
        print("Top-level keys:", list(payload.keys()))
        return

    interesting_tokens = (
        "inscode", "price", "cotval", "closing", "first",
        "min", "max", "yesterday", "tran", "cap", "dem",
        "of", "openinterest", "interest", "date", "time",
        "begin", "end", "remain", "volume", "count",
    )

    print("\n--- FIELD NAMES IN MATCHED ROW ---")
    for key in sorted(matched[0].keys()):
        if any(token in key.lower() for token in interesting_tokens):
            print(f"{key}: {matched[0].get(key)!r}")

    print("\n--- SAMPLE MATCHED ROWS (MAX 2) ---")
    for index, row in enumerate(matched[:2], start=1):
        print(f"\nROW {index}")
        print(json.dumps(row, ensure_ascii=False, indent=2))

    print("\nBR85 RESULT: READ-ONLY AUDIT COMPLETE")
    print("No database writes or local files were created.")

if __name__ == "__main__":
    main()
