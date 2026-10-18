
# BR78 - Read-Only Source File Creator and Timestamp Logic Audit
# Scans project Python files to locate BR44 creation and timestamp logic.
# No source files or database records are modified.

from pathlib import Path
import re

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")

EXCLUDED_DIRS = {
    ".venv", "venv", "__pycache__", ".git",
    "site-packages", "node_modules"
}

PATTERNS = [
    r"BR44_live_response",
    r"instrumentOptMarketWatch",
    r"GetInstrumentOptionMarketWatch",
    r"datetime\.now",
    r"datetime\.utcnow",
    r"astimezone",
    r"timezone\.utc",
    r"strftime",
    r"json\.dump",
    r"json\.dumps",
    r"write_text",
    r"open\(.*['\"]w",
    r"SourceRetrievedAt",
    r"RetrievedAt",
    r"ResponseJSON",
]

compiled = [
    (pattern, re.compile(pattern, re.IGNORECASE))
    for pattern in PATTERNS
]


def main():
    print("=" * 100)
    print("BR78 - SOURCE CREATOR AND TIMESTAMP LOGIC AUDIT")
    print("=" * 100)
    print(f"Project: {PROJECT_DIR}")
    print("Mode: READ ONLY")
    print("Database access: NONE")
    print("File modifications: NONE")

    if not PROJECT_DIR.exists():
        print(f"ERROR: Project directory not found: {PROJECT_DIR}")
        return

    python_files = []

    for path in PROJECT_DIR.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        python_files.append(path)

    print(f"\nPython files scanned: {len(python_files)}")

    matches_found = 0
    creator_candidates = []

    for path in sorted(python_files):
        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
            lines = content.splitlines()
        except Exception as exc:
            print(f"READ ERROR: {path} | {exc}")
            continue

        matching_lines = []

        for index, line in enumerate(lines):
            matched_patterns = [
                pattern
                for pattern, regex in compiled
                if regex.search(line)
            ]

            if matched_patterns:
                matching_lines.append(
                    (index + 1, line.rstrip(), matched_patterns)
                )

        if not matching_lines:
            continue

        is_creator_candidate = any(
            "BR44_live_response" in line
            and any(
                token in line.lower()
                for token in ("open", "write", "dump", "save", "path")
            )
            for _, line, _ in matching_lines
        )

        if is_creator_candidate:
            creator_candidates.append(path)

        matches_found += len(matching_lines)

        print("\n" + "-" * 100)
        print(f"FILE: {path.relative_to(PROJECT_DIR)}")
        print("-" * 100)

        # Print matching lines and nearby context, capped per file.
        selected_numbers = set()

        for line_number, _, _ in matching_lines:
            for number in range(
                max(1, line_number - 2),
                min(len(lines), line_number + 2) + 1
            ):
                selected_numbers.add(number)

        for number in sorted(selected_numbers):
            print(f"{number:5}: {lines[number - 1]}")

        if len(matching_lines) > 60:
            print(
                f"... {len(matching_lines) - 60} additional matching "
                "lines omitted from the detailed listing."
            )

    print("\n" + "=" * 100)
    print("BR78 SUMMARY")
    print("=" * 100)
    print(f"Files scanned                : {len(python_files)}")
    print(f"Matching lines               : {matches_found}")
    print(f"Potential creator candidates : {len(creator_candidates)}")

    for path in creator_candidates:
        print(f"CANDIDATE: {path}")

    print("\nBR78 RESULT: COMPLETED")
    print(
        "Identify the script that actually writes the BR44 JSON file. "
        "A filename match alone is not proof of the source retrieval time."
    )


if __name__ == "__main__":
    main()
