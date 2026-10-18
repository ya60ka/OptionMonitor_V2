
# BR49 - Audit Financial Fields and Open Interest
# Read-only JSON analysis. No database connection or writes.

import json
from pathlib import Path
from decimal import Decimal, InvalidOperation


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
UNDERLYING_CODE = "17914401175772326"


def latest_source():
    files = sorted(
        DATA_DIR.glob("BR44_live_response_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError("BR44 source JSON not found.")
    return files[0]


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def fmt(value):
    if value is None:
        return "NULL"
    return f"{value:,.4f}"


def audit_pair(rows, side, field_a, field_b):
    pairs = []

    for row in rows:
        a = number(row.get(f"{field_a}_{side}"))
        b = number(row.get(f"{field_b}_{side}"))
        if a is not None and b is not None:
            pairs.append((row, a, b))

    equal = sum(a == b for _, a, b in pairs)
    different = len(pairs) - equal
    a_greater = sum(a > b for _, a, b in pairs)
    b_greater = sum(b > a for _, a, b in pairs)

    print(f"\n{side}: {field_a} vs {field_b}")
    print(f"Comparable pairs : {len(pairs)}")
    print(f"Equal            : {equal}")
    print(f"Different        : {different}")
    print(f"A > B            : {a_greater}")
    print(f"B > A            : {b_greater}")

    if pairs:
        differences = [a - b for _, a, b in pairs]
        print(f"Difference min   : {fmt(min(differences))}")
        print(f"Difference max   : {fmt(max(differences))}")
        print(
            "Absolute diff sum: "
            + fmt(sum((abs(d) for d in differences), Decimal(0)))
        )

    print("\nFirst 10 unequal examples:")
    shown = 0

    for row, a, b in pairs:
        if a == b:
            continue

        print(
            f"  Symbol={row.get(f'lVal18AFC_{side}')!r}, "
            f"ID={row.get(f'insCode_{side}')}, "
            f"{field_a}={fmt(a)}, {field_b}={fmt(b)}, "
            f"diff={fmt(a - b)}, "
            f"price={row.get(f'pDrCotVal_{side}')}, "
            f"volume={row.get(f'qTotTran5J_{side}')}"
        )

        shown += 1
        if shown >= 10:
            break


def main():
    source = latest_source()

    print("=" * 78)
    print("BR49 - Financial Field and Open Interest Audit")
    print("=" * 78)
    print(f"Source: {source}")
    print("Database connection: NONE")
    print("Database writes: NONE")

    with source.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    all_rows = payload.get("instrumentOptMarketWatch", [])
    rows = [
        row for row in all_rows
        if isinstance(row, dict)
        and str(row.get("uaInsCode", "")) == UNDERLYING_CODE
    ]

    print(f"\nRaw API records: {len(all_rows)}")
    print(f"Matching underlying rows: {len(rows)}")

    if not rows:
        raise ValueError("No matching underlying rows found.")

    for side in ("C", "P"):
        print("\n" + "=" * 78)
        print(f"CONTRACT SIDE: {side}")
        print("=" * 78)

        audit_pair(rows, side, "qTotCap", "notionalValue")
        audit_pair(rows, side, "oP", "yesterdayOP")

        print(f"\n{side}: qTotCap, notionalValue and price-volume examples")

        for row in rows[:10]:
            price = number(row.get(f"pDrCotVal_{side}"))
            volume = number(row.get(f"qTotTran5J_{side}"))
            cap = number(row.get(f"qTotCap_{side}"))
            notional = number(row.get(f"notionalValue_{side}"))
            size = number(row.get("contractSize"))

            price_volume = None
            if price is not None and volume is not None:
                price_volume = price * volume

            price_volume_size = None
            if price_volume is not None and size is not None:
                price_volume_size = price_volume * size

            print(
                f"  {row.get(f'lVal18AFC_{side}')}: "
                f"price={fmt(price)}, volume={fmt(volume)}, "
                f"contractSize={fmt(size)}, "
                f"qTotCap={fmt(cap)}, "
                f"notionalValue={fmt(notional)}, "
                f"price*volume={fmt(price_volume)}, "
                f"price*volume*size={fmt(price_volume_size)}"
            )

    print("\n" + "=" * 78)
    print("BR49 COMPLETE")
    print("This report compares raw values; it does not establish official API semantics.")
    print("No database changes were made.")


if __name__ == "__main__":
    main()
