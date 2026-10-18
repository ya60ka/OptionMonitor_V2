
# BR75 - Locate Trade Metrics Mapping in Project Source
# Read-only source audit. Does not modify files or databases.

import os
from pathlib import Path

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")

SEARCH_TERMS = [
    "TradeCount",
    "Volume",
    "TradeValue",
    "zTotTran",
    "qTotTran5J",
    "qTotCap",
    "notionalValue",
    "OptionLiveCurrent",
    "OptionLiveSnapshot",
]

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".idea",
}

MAX_CONTEXT_LINES = 2


def heading(title):
    print("\n" + "=" * 110)
    print(title)
    print("=" * 110)


def main():
    if not PROJECT_DIR.is_dir():
        raise FileNotFoundError(f"Project directory not found: {PROJECT_DIR}")

    heading("BR75 - SOURCE CODE MAPPING AUDIT")
    print(f"Project       : {PROJECT_DIR}")
    print("Mode          : READ ONLY")
    print("File writes   : NONE")
    print("Database      : NOT ACCESSED")
    print("Legacy DB     : NOT ACCESSED")

    py_files = []

    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_DIRS
        ]

        for filename in files:
            if filename.endswith(".py") and filename != "75.py":
                py_files.append(Path(root) / filename)

    print(f"\nPython files scanned: {len(py_files)}")

    total_hits = 0
    files_with_hits = 0

    for path in sorted(py_files):
        try:
            lines = path.read_text(
                encoding="utf-8-sig",
                errors="replace",
            ).splitlines()
        except OSError as exc:
            print(f"\nREAD ERROR: {path} | {exc}")
            continue

        matching_lines = []

        for index, line in enumerate(lines):
            found_terms = [
                term for term in SEARCH_TERMS
                if term.lower() in line.lower()
            ]

            if found_terms:
                matching_lines.append((index, found_terms))

        if not matching_lines:
            continue

        files_with_hits += 1
        total_hits += len(matching_lines)

        heading(f"FILE: {path.relative_to(PROJECT_DIR)}")
        print(f"Total lines: {len(lines)}")
        print(f"Matching lines: {len(matching_lines)}")

        printed = set()

        for index, found_terms in matching_lines:
            start = max(0, index - MAX_CONTEXT_LINES)
            end = min(len(lines), index + MAX_CONTEXT_LINES + 1)

            print(
                f"\n--- Lines {start + 1}-{end} "
                f"(matched: {', '.join(found_terms)}) ---"
            )

            for line_index in range(start, end):
                if line_index in printed:
                    continue

                printed.add(line_index)
                print(f"{line_index + 1:5}: {lines[line_index]}")

    heading("BR75 SUMMARY")
    print(f"Python files scanned : {len(py_files)}")
    print(f"Files with matches   : {files_with_hits}")
    print(f"Matching lines       : {total_hits}")
    print("Source files modified: NO")
    print("Database accessed    : NO")
    print("\nEND OF BR75")


if __name__ == "__main__":
    main()
