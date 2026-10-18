
from pathlib import Path

p = Path(r"E:\PythonProject\OptionMonitor_V2\BR36_capture_live_market_data.py")
lines = p.read_text(encoding="utf-8-sig", errors="replace").splitlines()

for start, end in [(650, 780)]:
    print(f"--- BR36 lines {start}-{end} ---")
    for i in range(start - 1, min(end, len(lines))):
        print(f"{i + 1:4}: {lines[i]}")
