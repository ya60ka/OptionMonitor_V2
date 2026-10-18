
# BR86 - Correct BR36 collection start timestamp
# Creates a backup. Does not connect to the database.

from pathlib import Path
from datetime import datetime
import sys

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
TARGET = PROJECT_DIR / "BR36_capture_live_market_data.py"


def replace_once(source, old, new, description):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"{description}: expected exactly 1 match, found {count}. "
            "No changes have been written."
        )
    return source.replace(old, new, 1)


def main():
    print("=" * 70)
    print("BR86 - BR36 TIMESTAMP PATCH")
    print("Database access: NONE")
    print("=" * 70)

    if not TARGET.is_file():
        print(f"ERROR: File not found: {TARGET}")
        return 1

    original = TARGET.read_text(encoding="utf-8-sig")

    if (
        "request_started_at,\n    retrieved_at,\n):"
        in original
        and "StartedAt, Status, ItemsRequested)" in original
        and "            request_started_at,\n            len(source_options) + 1,"
        in original
    ):
        print("The timestamp patch appears to be already applied.")
        print("No changes made.")
        return 0

    patched = original

    try:
        patched = replace_once(
            patched,
            """    source_options,
    underlying_market_rows,
    retrieved_at,
):
    cursor = connection.cursor()""",
            """    source_options,
    underlying_market_rows,
    request_started_at,
    retrieved_at,
):
    cursor = connection.cursor()""",
            "perform_capture function signature",
        )

        patched = replace_once(
            patched,
            """            JOB_NAME,
            retrieved_at,
            len(source_options) + 1,""",
            """            JOB_NAME,
            request_started_at,
            len(source_options) + 1,""",
            "CollectionRun StartedAt parameter",
        )

        patched = replace_once(
            patched,
            """            "CreatedAtUTC": retrieved_at.isoformat(),
            "DryRun": DRY_RUN,""",
            """            "CreatedAtUTC": retrieved_at.isoformat(),
            "RequestStartedAtUTC": request_started_at.isoformat(),
            "ResponseReceivedAtUTC": retrieved_at.isoformat(),
            "DryRun": DRY_RUN,""",
            "Plan timestamp metadata",
        )

        patched = replace_once(
            patched,
            """            source_options,
            underlying_market_rows,
            retrieved_at,
        )

        log(f"CollectionRunID:""",
            """            source_options,
            underlying_market_rows,
            request_started_at,
            retrieved_at,
        )

        log(f"CollectionRunID:""",
            "perform_capture call",
        )

    except RuntimeError as exc:
        print(f"PATCH ABORTED: {exc}")
        print("Original file was not changed.")
        return 2

    backup_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(
        f"{TARGET.stem}_backup_BR86_{backup_stamp}{TARGET.suffix}"
    )

    try:
        backup.write_text(original, encoding="utf-8")
        TARGET.write_text(patched, encoding="utf-8")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print(f"Backup path, if created: {backup}")
        return 3

    print(f"Backup created: {backup}")
    print(f"Patched file: {TARGET}")
    print("CollectionRun.StartedAt now uses request start time.")
    print("Plan now records request-start and response-received times.")
    print("No database connection or database writes were performed.")
    print("BR86 RESULT: PATCH APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
