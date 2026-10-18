
# BR57 - Audit Trade Count vs Traded Volume
# Read-only audit of the saved TSETMC API response.
# No database access or modifications.

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
INPUT_FILE = DATA_DIR / "BR54_live_response_20261015_072826.json"
UNDERLYING_CODE = "17914401175772326"


def number(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_value(record, *keys):
    for key in keys:
        if key in record:
            return record[key]
    return None


def main():
    print("=" * 76)
    print("BR57 - TRADE COUNT vs TRADED VOLUME AUDIT")
    print("=" * 76)
    print(f"Input: {INPUT_FILE}")
    print("Database access: NONE")
    print("Database changes: NONE")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    with INPUT_FILE.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("instrumentOptMarketWatch")
        if records is None:
            records = payload.get("data")
        if not isinstance(records, list):
            raise ValueError("API array not found in JSON.")
    else:
        raise ValueError("Unexpected JSON root type.")

    results = []

    for raw in records:
        if str(raw.get("uaInsCode", "")) != UNDERLYING_CODE:
            continue

        for side in ("C", "P"):
            contract_id = get_value(raw, f"insCode_{side}")
            if contract_id in (None, "", 0, "0"):
                continue

            volume = number(get_value(raw, f"qTotTran5J_{side}"))
            trade_count = number(get_value(raw, f"zTotTran_{side}"))

            results.append({
                "side": "CALL" if side == "C" else "PUT",
                "symbol": get_value(raw, f"lVal18AFC_{side}"),
                "contract_id": str(contract_id),
                "volume": volume,
                "trade_count": trade_count,
                "volume_equals_trade_count": (
                    volume == trade_count
                    if volume is not None and trade_count is not None
                    else None
                ),
                "volume_zero": volume == 0 if volume is not None else None,
                "trade_count_zero": (
                    trade_count == 0 if trade_count is not None else None
                ),
                "trade_count_greater_than_volume": (
                    trade_count > volume
                    if volume is not None and trade_count is not None
                    else None
                ),
                "volume_per_trade": (
                    volume / trade_count
                    if volume is not None
                    and trade_count is not None
                    and trade_count > 0
                    else None
                ),
            })

    def summarize(group):
        valid = [
            r for r in group
            if r["volume"] is not None and r["trade_count"] is not None
        ]
        ratios = [
            r["volume_per_trade"]
            for r in valid
            if r["volume_per_trade"] is not None
        ]

        return {
            "contracts": len(group),
            "both_fields_present": len(valid),
            "volume_equals_trade_count": sum(
                r["volume_equals_trade_count"] is True for r in valid
            ),
            "volume_zero": sum(r["volume"] == 0 for r in valid),
            "trade_count_zero": sum(r["trade_count"] == 0 for r in valid),
            "volume_positive_trade_count_zero": sum(
                r["volume"] > 0 and r["trade_count"] == 0
                for r in valid
            ),
            "trade_count_greater_than_volume": sum(
                r["trade_count_greater_than_volume"] is True
                for r in valid
            ),
            "volume_less_than_trade_count": sum(
                r["volume"] < r["trade_count"] for r in valid
            ),
            "volume_per_trade_min": min(ratios) if ratios else None,
            "volume_per_trade_max": max(ratios) if ratios else None,
            "volume_per_trade_mean": (
                sum(ratios) / len(ratios) if ratios else None
            ),
        }

    groups = {
        "ALL": results,
        "CALL": [r for r in results if r["side"] == "CALL"],
        "PUT": [r for r in results if r["side"] == "PUT"],
    }

    report = {
        "stage": "BR57",
        "input_file": str(INPUT_FILE),
        "database_access": False,
        "total_contracts": len(results),
        "summaries": {
            name: summarize(group) for name, group in groups.items()
        },
        "trade_count_distribution": dict(sorted(
            Counter(
                str(r["trade_count"])
                for r in results
                if r["trade_count"] is not None
            ).items(),
            key=lambda item: float(item[0])
        )),
        "contracts": results,
        "interpretation": (
            "This audit compares the two API fields only. "
            "It does not independently prove the provider's field definition."
        ),
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = DATA_DIR / f"BR57_trade_count_{timestamp}.csv"
    json_path = DATA_DIR / f"BR57_report_{timestamp}.json"

    import csv

    with csv_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    for name, group in groups.items():
        print(f"\n{name} SUMMARY")
        print(json.dumps(summarize(group), ensure_ascii=False, indent=2))

    print("\nSAMPLE CONTRACTS")
    for r in results[:12]:
        print(
            f"{r['side']:4} | {r['symbol']} | "
            f"volume={r['volume']} | "
            f"trade_count={r['trade_count']} | "
            f"equal={r['volume_equals_trade_count']} | "
            f"volume_per_trade={r['volume_per_trade']}"
        )

    print("\nOUTPUT FILES")
    print(f"CSV : {csv_path}")
    print(f"JSON: {json_path}")
    print("\nBR57 completed successfully.")


if __name__ == "__main__":
    main()
