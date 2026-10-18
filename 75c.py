
from pathlib import Path

ROOT = Path(r"E:\PythonProject\OptionMonitor_V2")

FILES = [
    "BR36_capture_live_market_data.py",
    "BR45_capture_first_offhours_snapshot.py",
    "database.py",
]

TERMS = [
    "zTotTran",
    "qTotTran5J",
    "qTotCap",
    "notionalValue",
    "TradeCount",
    "TradeValue",
    "Volume",
    "OptionLiveCurrent",
    "OptionLiveSnapshot",
    "INSERT INTO",
    "UPDATE ",
    "executemany",
    "execute(",
]

print("=" * 100)
print("BR75C - TARGETED STORAGE MAPPING REVIEW")
print("READ ONLY | No file changes | No database connection")
print("=" * 100)

for filename in FILES:
    path = ROOT / filename
    print(f"\n{'=' * 100}\nFILE: {filename}\n{'=' * 100}")

    if not path.is_file():
        print("FILE NOT FOUND")
        continue

    lines = path.read_text(
        encoding="utf-8-sig",
        errors="replace"
    ).splitlines()

    hits = [
        i for i, line in enumerate(lines)
        if any(term.lower() in line.lower() for term in TERMS)
    ]

    selected = set()
    for i in hits:
        selected.update(range(max(0, i - 2), min(len(lines), i + 3)))

    if not selected:
        print("No matching lines.")
        continue

    previous = -2
    for i in sorted(selected):
        if i > previous + 1:
            print("    ...")
        print(f"{i + 1:5}: {lines[i]}")
        previous = i

print("\nBR75C COMPLETE")
