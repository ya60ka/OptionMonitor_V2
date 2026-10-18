
# BR54 - Live API Financial Field Verification
# Read-only HTTP GET; no database access or changes.

import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
DATA_DIR.mkdir(parents=True, exist_ok=True)

API_URL = (
    "https://cdn.tsetmc.com/api/Instrument/"
    "GetInstrumentOptionMarketWatch/1"
)
UNDERLYING_ID = "17914401175772326"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

RAW_FILE = DATA_DIR / f"BR54_live_response_{RUN_ID}.json"

TIMEOUT_SECONDS = 30


def num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def summarize(records, suffix, side):
    rows = []

    for record in records:
        if str(record.get("uaInsCode", "")) != UNDERLYING_ID:
            continue

        contract_id = record.get(f"insCode_{suffix}")
        if contract_id is None:
            continue

        volume = num(record.get(f"qTotTran5J_{suffix}"))
        cap = num(record.get(f"qTotCap_{suffix}"))
        notional = num(record.get(f"notionalValue_{suffix}"))
        close = num(record.get(f"pClosing_{suffix}"))
        last = num(record.get(f"pDrCotVal_{suffix}"))
        symbol = record.get(f"lVal18AFC_{suffix}")

        if volume is not None and volume > 0:
            notional_ratio = (
                notional / volume if notional is not None else None
            )
            cap_close_ratio = (
                cap / (volume * close)
                if cap is not None and close is not None and close != 0
                else None
            )
        else:
            notional_ratio = None
            cap_close_ratio = None

        rows.append({
            "side": side,
            "symbol": symbol,
            "contract_id": str(contract_id),
            "volume": volume,
            "qTotCap": cap,
            "notionalValue": notional,
            "close_price": close,
            "last_price": last,
            "notional_per_volume": notional_ratio,
            "qTotCap_per_volume_close": cap_close_ratio,
        })

    positive = [r for r in rows if r["volume"] is not None
                and r["volume"] > 0]
    zero = [r for r in rows if r["volume"] == 0]

    ratios = [
        r["notional_per_volume"]
        for r in positive
        if r["notional_per_volume"] is not None
    ]
    cap_ratios = [
        r["qTotCap_per_volume_close"]
        for r in positive
        if r["qTotCap_per_volume_close"] is not None
    ]

    print(f"\n[{side}]")
    print(f"Contracts: {len(rows)}")
    print(f"Positive volume: {len(positive)}")
    print(f"Zero volume: {len(zero)}")
    print(f"Unique notional/volume ratios: {len(set(ratios))}")
    print(f"Median notional/volume: {median(ratios)}")
    print(f"Min notional/volume: {min(ratios) if ratios else None}")
    print(f"Max notional/volume: {max(ratios) if ratios else None}")
    print(f"Median qTotCap/(volume*close): {median(cap_ratios)}")

    ratio_counts = Counter(ratios)
    print("Most common notional/volume ratios:")
    for value, count in ratio_counts.most_common(5):
        print(f"  {value}: {count}")

    print("First 5 positive-volume samples:")
    for row in positive[:5]:
        print(
            f"  {row['symbol']} | volume={row['volume']} | "
            f"qTotCap={row['qTotCap']} | "
            f"notionalValue={row['notionalValue']} | "
            f"close={row['close_price']} | "
            f"notional/volume={row['notional_per_volume']}"
        )

    return rows


def main():
    print("=" * 76)
    print("BR54 - LIVE API FINANCIAL FIELD VERIFICATION")
    print("=" * 76)
    print(f"URL: {API_URL}")
    print("Database access: NONE")
    print("Database changes: NONE")

    response = requests.get(
        API_URL,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=TIMEOUT_SECONDS,
    )

    print(f"HTTP status: {response.status_code}")
    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        records = data.get("instrumentOptMarketWatch")
    elif isinstance(data, list):
        records = data
    else:
        records = None

    if not isinstance(records, list):
        raise ValueError(
            "Unexpected API response structure. "
            f"Root type: {type(data).__name__}"
        )

    with RAW_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(f"Raw records: {len(records)}")
    print(f"Saved raw response: {RAW_FILE}")

    calls = summarize(records, "C", "CALL")
    puts = summarize(records, "P", "PUT")

    combined = calls + puts
    positive = [
        r for r in combined
        if r["volume"] is not None and r["volume"] > 0
    ]
    ratios = [
        r["notional_per_volume"]
        for r in positive
        if r["notional_per_volume"] is not None
    ]

    print("\n[OVERALL]")
    print(f"Matching contracts: {len(combined)}")
    print(f"Positive-volume contracts: {len(positive)}")
    print(f"Unique notional/volume ratios: {len(set(ratios))}")
    print(f"Median notional/volume: {median(ratios)}")

    report_file = DATA_DIR / f"BR54_report_{RUN_ID}.json"
    report = {
        "run_id": RUN_ID,
        "api_url": API_URL,
        "http_status": response.status_code,
        "raw_record_count": len(records),
        "matching_contract_count": len(combined),
        "call_count": len(calls),
        "put_count": len(puts),
        "positive_volume_count": len(positive),
        "unique_notional_volume_ratio_count": len(set(ratios)),
        "median_notional_per_volume": median(ratios),
        "contracts": combined,
        "database_access": False,
        "database_changes": False,
    }

    with report_file.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print(f"Report: {report_file}")
    print("\nBR54 completed successfully.")


if __name__ == "__main__":
    main()
