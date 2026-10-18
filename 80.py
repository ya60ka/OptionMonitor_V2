
# BR80 - Focused Capture Timestamp Audit
# Read-only source inspection; no database access.

from pathlib import Path

ROOT = Path(r"E:\PythonProject\OptionMonitor_V2")

TARGETS = {
    "BR36_capture_live_market_data.py": [
        "requests.get", "urlopen", "API_URL", "REQUEST_URL",
        "retrieved_at", "utc_now_naive", "DataDate", "DataTime",
        "SourceRetrievedAt", "datetime.now", "ResponseJSON",
        "response.json", "save_json",
    ],
    "BR45_capture_first_offhours_snapshot.py": [
        "requests.get", "urlopen", "API_URL", "REQUEST_URL",
        "retrieved_utc", "retrieved_local", "data_date",
        "data_time", "SourceRetrievedAt", "DataDate", "DataTime",
        "source_path", "glob(", "json.load", "response.json",
    ],
}

def main():
    print("=" * 68)
    print("BR80 - FOCUSED TIMESTAMP AUDIT (READ ONLY)")
    print("=" * 68)

    for filename, keywords in TARGETS.items():
        path = ROOT / filename
        print(f"\n--- {filename} ---")

        if not path.exists():
            print("FILE NOT FOUND")
            continue

        lines = path.read_text(
            encoding="utf-8-sig", errors="replace"
        ).splitlines()

        hits = []
        for i, line in enumerate(lines):
            if any(word.lower() in line.lower() for word in keywords):
                hits.append(i)

        # Merge adjacent context windows, but cap the output.
        selected = set()
        for i in hits:
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                selected.add(j)

        ordered = sorted(selected)
        limit = 100
        if len(ordered) > limit:
            # Prioritize lines containing exact target keywords.
            priority = set(hits)
            keep = set(priority)
            for i in hits:
                keep.update(range(max(0, i - 1), min(len(lines), i + 2)))
            ordered = sorted(keep)[:limit]

        previous = -2
        for i in ordered:
            if i > previous + 1:
                print("   ...")
            print(f"{i + 1:4}: {lines[i]}")
            previous = i

        print(f"Matched source lines: {len(hits)}")

    print("\nBR80 RESULT: COMPLETED")

if __name__ == "__main__":
    main()
