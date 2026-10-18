
# BR84 - Safely patch BR36 to fetch TSETMC API directly
# Creates a backup; does not connect to or modify the database.

from pathlib import Path
from datetime import datetime
import re
import sys

PROJECT = Path(r"E:\PythonProject\OptionMonitor_V2")
TARGET = PROJECT / "BR36_capture_live_market_data.py"

OLD_BLOCK = '''        source_file = find_latest_source_file()
        log(f"Source JSON: {source_file}")

        with source_file.open("r", encoding="utf-8-sig") as file:
            source_json = json.load(file)

        underlying_records, source_options, underlying_market_rows = (
            build_source_rows(source_json)
        )

        retrieved_at = utc_now_naive()
'''

NEW_BLOCK = '''        # Fetch a fresh response directly from TSETMC.
        import urllib.request

        request_url = (
            "https://cdn.tsetmc.com/api/Instrument/"
            "GetInstrumentOptionMarketWatch/1"
        )
        request_started_at = utc_now_naive()

        request = urllib.request.Request(
            request_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json, text/plain, */*",
            },
            method="GET",
        )

        log(f"Direct API URL: {request_url}")
        log(f"Request started UTC: {request_started_at}")

        with urllib.request.urlopen(request, timeout=30) as response:
            http_status = response.status
            raw_body = response.read()
            retrieved_at = utc_now_naive()

        if http_status != 200:
            raise RuntimeError(
                f"TSETMC API returned HTTP {http_status}"
            )

        source_json = json.loads(raw_body.decode("utf-8-sig"))

        # Virtual label for reports; no source JSON file is read.
        source_file = Path(
            "TSETMC_DIRECT_API_"
            + retrieved_at.strftime("%Y%m%d_%H%M%S")
            + ".json"
        )

        log(f"HTTP status: {http_status}")
        log(f"Response received UTC: {retrieved_at}")
        log(f"Response bytes: {len(raw_body)}")
        log(f"Source JSON label: {source_file.name}")

        underlying_records, source_options, underlying_market_rows = (
            build_source_rows(source_json)
        )
'''

def main():
    print("=" * 68)
    print("BR84 - SAFE BR36 DIRECT API PATCH")
    print("Database access: NONE")
    print("=" * 68)

    if not TARGET.is_file():
        print(f"ERROR: Target not found: {TARGET}")
        return 1

    original = TARGET.read_text(encoding="utf-8-sig")

    if "Fetch a fresh response directly from TSETMC." in original:
        print("BR36 already appears patched. No changes made.")
        return 0

    if original.count(OLD_BLOCK) != 1:
        print("ERROR: Expected source block was not found exactly once.")
        print("No changes made. Keep the current BR36 unchanged.")
        return 2

    if not re.search(r"^\s*DRY_RUN\s*=\s*True\s*$", original, re.M):
        print("ERROR: DRY_RUN is not explicitly True.")
        print("No changes made.")
        return 3

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(
        f"{TARGET.stem}_backup_BR84_{stamp}{TARGET.suffix}"
    )

    try:
        backup.write_text(original, encoding="utf-8")
        patched = original.replace(OLD_BLOCK, NEW_BLOCK, 1)
        TARGET.write_text(patched, encoding="utf-8")
    except Exception as exc:
        print(f"ERROR while patching: {type(exc).__name__}: {exc}")
        print(f"Backup, if created: {backup}")
        return 4

    print(f"Backup created: {backup}")
    print(f"Patched file: {TARGET}")
    print("DRY_RUN remains True.")
    print("No database connection or database writes were performed.")
    print("BR84 RESULT: PATCH APPLIED")
    print()
    print("Next: run BR36_capture_live_market_data.py once.")
    print("Do not change DRY_RUN to False yet.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
