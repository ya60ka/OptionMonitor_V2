
from pathlib import Path

ROOT = Path(r"E:\PythonProject\OptionMonitor_V2")

TERMS = [
    "GetInstrumentOptionMarketWatch",
    "zTotTran",
    "qTotTran5J",
    "qTotCap",
    "notionalValue",
    "OptionLiveCurrent",
    "OptionLiveSnapshot",
    "INSERT INTO",
    "executemany",
    "MERGE INTO",
]

EXCLUDED = {
    ".venv", "venv", ".git", "__pycache__", "node_modules"
}

print("=" * 90)
print("BR75B - CONCISE SOURCE FILE INDEX")
print("Read-only | No database access | No file changes")
print("=" * 90)

for path in sorted(ROOT.rglob("*.py")):
    if path.name in {"75.py", "75b.py"}:
        continue

    if any(part in EXCLUDED for part in path.parts):
        continue

    try:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        continue

    found = [
        term for term in TERMS
        if term.lower() in content.lower()
    ]

    if found:
        print(f"{path.relative_to(ROOT)}")
        print("  " + " | ".join(found))

print("\nEND OF BR75B")
