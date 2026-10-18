
# BR79 - Audit Timestamp Generation Logic
# READ ONLY: inspects source code; no database connection or writes.

from pathlib import Path
import re

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")

TARGET_FILES = [
    "BR36_capture_live_market_data.py",
    "BR45_capture_first_offhours_snapshot.py",
]

PATTERNS = [
    r"DataDate",
    r"DataTime",
    r"SourceRetrievedAt",
    r"RetrievedAt",
    r"datetime\.now",
    r"datetime\.utcnow",
    r"fromtimestamp",
    r"timezone",
    r"astimezone",
    r"strftime",
    r"DRY_RUN",
    r"requests\.get",
    r"json\.dump",
    r"CollectionRun",
    r"RawApiResponse",
]

CONTEXT = 3
MAX_MATCHES_PER_FILE = 50


def main():
    print("=" * 72)
    print("BR79 - TIMESTAMP GENERATION LOGIC AUDIT")
    print("Source-code inspection only; no database access.")
    print("=" * 72)

    for filename in TARGET_FILES:
        path = PROJECT_DIR / filename
        print(f"\n--- FILE: {filename} ---")

        if not path.is_file():
            print("FILE NOT FOUND")
            continue

        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        matching = []

        for i, line in enumerate(lines):
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in PATTERNS):
                matching.append(i)

        if not matching:
            print("No timestamp-related lines found.")
            continue

        # Merge nearby matches into small contextual blocks.
        blocks = []
        for idx in matching:
            start = max(0, idx - CONTEXT)
            end = min(len(lines), idx + CONTEXT + 1)

            if blocks and start <= blocks[-1][1]:
                blocks[-1] = (blocks[-1][0], max(blocks[-1][1], end))
            else:
                blocks.append((start, end))

        shown = 0
        for start, end in blocks:
            if shown >= MAX_MATCHES_PER_FILE:
                print("... output limited; additional matches omitted.")
                break

            print(f"\nLines {start + 1}-{end}:")
            for i in range(start, end):
                print(f"{i + 1:4}: {lines[i]}")
            shown += end - start

        print(f"\nTotal source lines: {len(lines)}")
        print(f"Matching lines: {len(matching)}")

    print("\n" + "=" * 72)
    print("BR79 RESULT: COMPLETED")
    print("=" * 72)


if __name__ == "__main__":
    main()
