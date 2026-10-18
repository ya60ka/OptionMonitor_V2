
# BR58 - Validate Option Market Data Quality
# Read-only audit of the saved API response.
# No database access or modifications.

import csv
import json
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
INPUT_FILE = DATA_DIR / "BR54_live_response_20261015_072826.json"
UNDERLYING_CODE = "17914401175772326"


def num(value):
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
    print("BR58 - OPTION MARKET DATA QUALITY VALIDATION")
    print("=" * 76)
    print(f"Input: {INPUT_FILE}")
    print("Database access: NONE")
    print("Database changes: NONE")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(INPUT_FILE)

    with INPUT_FILE.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, dict):
        raw_records = payload.get("instrumentOptMarketWatch")
        if raw_records is None:
            raw_records = payload.get("data")
        if not isinstance(raw_records, list):
            raise ValueError("API array not found in JSON.")
    else:
        raise ValueError("Unexpected JSON root.")

    rows = []

    for raw in raw_records:
        if str(raw.get("uaInsCode", "")) != UNDERLYING_CODE:
            continue

        for side in ("C", "P"):
            contract_id = get_value(raw, f"insCode_{side}")
            if contract_id in (None, "", 0, "0"):
                continue

            volume = num(get_value(raw, f"qTotTran5J_{side}"))
            trade_count = num(get_value(raw, f"zTotTran_{side}"))
            q_tot_cap = num(get_value(raw, f"qTotCap_{side}"))
            notional = num(get_value(raw, f"notionalValue_{side}"))

            last_price = num(get_value(raw, f"pDrCotVal_{side}"))
            close_price = num(get_value(raw, f"pClosing_{side}"))
            yesterday_price = num(
                get_value(raw, f"priceYesterday_{side}")
            )
            bid = num(get_value(raw, f"pMeDem_{side}"))
            ask = num(get_value(raw, f"pMeOf_{side}"))
            bid_volume = num(get_value(raw, f"qTitMeDem_{side}"))
            ask_volume = num(get_value(raw, f"qTitMeOf_{side}"))
            open_interest = num(get_value(raw, f"oP_{side}"))
            previous_oi = num(get_value(raw, f"yesterdayOP_{side}"))

            checks = {
                "negative_volume": volume is not None and volume < 0,
                "negative_trade_count": (
                    trade_count is not None and trade_count < 0
                ),
                "negative_qTotCap": (
                    q_tot_cap is not None and q_tot_cap < 0
                ),
                "negative_notional": (
                    notional is not None and notional < 0
                ),
                "negative_last_price": (
                    last_price is not None and last_price < 0
                ),
                "negative_close_price": (
                    close_price is not None and close_price < 0
                ),
                "negative_yesterday_price": (
                    yesterday_price is not None
                    and yesterday_price < 0
                ),
                "negative_bid": bid is not None and bid < 0,
                "negative_ask": ask is not None and ask < 0,
                "negative_bid_volume": (
                    bid_volume is not None and bid_volume < 0
                ),
                "negative_ask_volume": (
                    ask_volume is not None and ask_volume < 0
                ),
                "negative_open_interest": (
                    open_interest is not None and open_interest < 0
                ),
                "negative_previous_oi": (
                    previous_oi is not None and previous_oi < 0
                ),
                "volume_zero_count_positive": (
                    volume == 0 and trade_count is not None
                    and trade_count > 0
                ),
                "volume_positive_count_zero": (
                    volume is not None and volume > 0
                    and trade_count == 0
                ),
                "volume_zero_but_value_nonzero": (
                    volume == 0
                    and (
                        (q_tot_cap is not None and q_tot_cap != 0)
                        or (notional is not None and notional != 0)
                    )
                ),
                "bid_greater_than_ask": (
                    bid is not None and ask is not None
                    and bid > 0 and ask > 0 and bid > ask
                ),
                "bid_positive_ask_zero": (
                    bid is not None and bid > 0
                    and ask is not None and ask == 0
                ),
                "ask_positive_bid_zero": (
                    ask is not None and ask > 0
                    and bid is not None and bid == 0
                ),
                "positive_volume_missing_qTotCap": (
                    volume is not None and volume > 0
                    and q_tot_cap is None
                ),
                "positive_volume_missing_trade_count": (
                    volume is not None and volume > 0
                    and trade_count is None
                ),
                "missing_last_price": last_price is None,
                "missing_close_price": close_price is None,
                "missing_yesterday_price": yesterday_price is None,
                "missing_open_interest": open_interest is None,
            }

            rows.append({
                "side": "CALL" if side == "C" else "PUT",
                "symbol": get_value(raw, f"lVal18AFC_{side}"),
                "contract_id": str(contract_id),
                "volume": volume,
                "trade_count": trade_count,
                "qTotCap": q_tot_cap,
                "notionalValue": notional,
                "last_price": last_price,
                "close_price": close_price,
                "yesterday_price": yesterday_price,
                "bid": bid,
                "ask": ask,
                "bid_volume": bid_volume,
                "ask_volume": ask_volume,
                "open_interest": open_interest,
                "previous_oi": previous_oi,
                **checks,
                "issue_count": sum(checks.values()),
                "issues": ";".join(
                    name for name, value in checks.items() if value
                ),
            })

    check_names = [
        key for key in rows[0]
        if key in {
            "negative_volume", "negative_trade_count", "negative_qTotCap",
            "negative_notional", "negative_last_price", "negative_close_price",
            "negative_yesterday_price", "negative_bid", "negative_ask",
            "negative_bid_volume", "negative_ask_volume",
            "negative_open_interest", "negative_previous_oi",
            "volume_zero_count_positive", "volume_positive_count_zero",
            "volume_zero_but_value_nonzero", "bid_greater_than_ask",
            "bid_positive_ask_zero", "ask_positive_bid_zero",
            "positive_volume_missing_qTotCap",
            "positive_volume_missing_trade_count",
            "missing_last_price", "missing_close_price",
            "missing_yesterday_price", "missing_open_interest",
        }
    ]

    summary = {
        "stage": "BR58",
        "input_file": str(INPUT_FILE),
        "database_access": False,
        "contracts": len(rows),
        "contracts_with_any_flag": sum(
            row["issue_count"] > 0 for row in rows
        ),
        "total_flags": sum(row["issue_count"] for row in rows),
        "flag_counts": {
            name: sum(bool(row[name]) for row in rows)
            for name in check_names
        },
        "contracts_with_issues": [
            {
                "side": row["side"],
                "symbol": row["symbol"],
                "contract_id": row["contract_id"],
                "issues": row["issues"],
            }
            for row in rows if row["issue_count"] > 0
        ],
        "note": (
            "Flags are diagnostic only. A missing or zero quote may be "
            "legitimate for an illiquid option; no records are modified."
        ),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = DATA_DIR / f"BR58_quality_{timestamp}.csv"
    json_path = DATA_DIR / f"BR58_report_{timestamp}.json"

    with csv_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print(f"\nContracts: {len(rows)}")
    print(f"Contracts with any flagged condition: "
          f"{summary['contracts_with_any_flag']}")
    print(f"Total flags: {summary['total_flags']}")

    print("\nFLAG COUNTS")
    for name, count in summary["flag_counts"].items():
        if count:
            print(f"{name}: {count}")

    print("\nCONTRACTS WITH FLAGS")
    for item in summary["contracts_with_issues"]:
        print(
            f"{item['side']} | {item['symbol']} | "
            f"{item['contract_id']} | {item['issues']}"
        )

    print("\nOUTPUT FILES")
    print(f"CSV : {csv_path}")
    print(f"JSON: {json_path}")
    print("\nBR58 completed successfully.")


if __name__ == "__main__":
    main()
