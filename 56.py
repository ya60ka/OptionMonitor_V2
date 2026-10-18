
# BR56 - Audit qTotCap and Implied Average Option Trade Price
# Read-only audit. No database access or modifications.

import csv
import json
import math
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
INPUT_FILE = DATA_DIR / "BR54_live_response_20261015_072826.json"

UNDERLYING_CODE = "17914401175772326"
CONTRACT_SIZE_FACTOR = 1000.0


def number(value):
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def get_value(record, *keys):
    for key in keys:
        if key in record:
            return record[key]
    return None


def ratio_error(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b


def main():
    print("=" * 76)
    print("BR56 - qTotCap / IMPLIED OPTION TRADE PRICE AUDIT")
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
            raise ValueError(
                "Could not locate the API array in the input JSON."
            )
    else:
        raise ValueError("Unexpected JSON root type.")

    rows = []

    for raw in records:
        if str(raw.get("uaInsCode", "")) != UNDERLYING_CODE:
            continue

        for side in ("C", "P"):
            contract_id = get_value(raw, f"insCode_{side}")
            if contract_id in (None, "", 0, "0"):
                continue

            volume = number(get_value(raw, f"qTotTran5J_{side}"))
            q_tot_cap = number(get_value(raw, f"qTotCap_{side}"))
            notional = number(get_value(raw, f"notionalValue_{side}"))

            last_price = number(get_value(raw, f"pDrCotVal_{side}"))
            close_price = number(get_value(raw, f"pClosing_{side}"))
            yesterday_price = number(
                get_value(raw, f"priceYesterday_{side}")
            )
            bid_price = number(get_value(raw, f"pMeDem_{side}"))
            ask_price = number(get_value(raw, f"pMeOf_{side}"))
            trade_count = number(get_value(raw, f"zTotTran_{side}"))

            implied_average = None
            if (
                volume is not None
                and volume > 0
                and q_tot_cap is not None
            ):
                implied_average = (
                    q_tot_cap / volume / CONTRACT_SIZE_FACTOR
                )

            bid_ask_valid = (
                implied_average is not None
                and bid_price is not None
                and ask_price is not None
                and bid_price > 0
                and ask_price > 0
                and bid_price <= ask_price
            )

            within_bid_ask = None
            if bid_ask_valid:
                within_bid_ask = (
                    bid_price <= implied_average <= ask_price
                )

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
                "bid_price": bid_price,
                "ask_price": ask_price,
                "implied_average_price": implied_average,
                "implied_minus_last": (
                    implied_average - last_price
                    if implied_average is not None
                    and last_price is not None else None
                ),
                "implied_minus_close": (
                    implied_average - close_price
                    if implied_average is not None
                    and close_price is not None else None
                ),
                "relative_error_vs_last": ratio_error(
                    implied_average, last_price
                ),
                "relative_error_vs_close": ratio_error(
                    implied_average, close_price
                ),
                "within_bid_ask": within_bid_ask,
                "qTotCap_zero": q_tot_cap == 0
                if q_tot_cap is not None else None,
            })

    positive = [
        r for r in rows
        if r["volume"] is not None and r["volume"] > 0
    ]
    zero_volume = [
        r for r in rows
        if r["volume"] is not None and r["volume"] == 0
    ]

    def summarize(group):
        eligible = [
            r for r in group
            if r["implied_average_price"] is not None
        ]

        def count_with_price(field):
            return sum(
                1 for r in eligible
                if r[field] is not None
                and r[field] > 0
            )

        bid_ask_eligible = [
            r for r in eligible
            if r["within_bid_ask"] is not None
        ]

        return {
            "contracts": len(group),
            "positive_volume": len(eligible),
            "implied_average_matches_last_exact": sum(
                1 for r in eligible
                if r["last_price"] is not None
                and r["implied_average_price"] == r["last_price"]
            ),
            "implied_average_matches_close_exact": sum(
                1 for r in eligible
                if r["close_price"] is not None
                and r["implied_average_price"] == r["close_price"]
            ),
            "with_positive_bid": count_with_price("bid_price"),
            "with_positive_ask": count_with_price("ask_price"),
            "bid_ask_comparable": len(bid_ask_eligible),
            "implied_average_within_bid_ask": sum(
                1 for r in bid_ask_eligible
                if r["within_bid_ask"]
            ),
            "implied_average_outside_bid_ask": sum(
                1 for r in bid_ask_eligible
                if not r["within_bid_ask"]
            ),
        }

    report = {
        "stage": "BR56",
        "input_file": str(INPUT_FILE),
        "database_access": False,
        "underlying_code": UNDERLYING_CODE,
        "total_contracts": len(rows),
        "positive_volume_contracts": len(positive),
        "zero_volume_contracts": len(zero_volume),
        "summary_all": summarize(rows),
        "summary_call": summarize(
            [r for r in rows if r["side"] == "CALL"]
        ),
        "summary_put": summarize(
            [r for r in rows if r["side"] == "PUT"]
        ),
        "formula_under_test": (
            "implied_average_price = qTotCap / volume / 1000"
        ),
        "interpretation_note": (
            "This is a hypothesis audit, not proof of field semantics."
        ),
        "samples": rows[:12],
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = DATA_DIR / f"BR56_option_value_{timestamp}.csv"
    json_path = DATA_DIR / f"BR56_report_{timestamp}.json"

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys()) if rows else [
        "side", "symbol", "contract_id"
    ]

    with csv_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print(f"\nContracts: {len(rows)}")
    print(f"Positive volume: {len(positive)}")
    print(f"Zero volume: {len(zero_volume)}")

    for label, group in (
        ("ALL", rows),
        ("CALL", [r for r in rows if r["side"] == "CALL"]),
        ("PUT", [r for r in rows if r["side"] == "PUT"]),
    ):
        print(f"\n{label} SUMMARY")
        print(json.dumps(summarize(group), indent=2))

    print("\nSAMPLE CONTRACTS")
    for r in positive[:10]:
        print(
            f"{r['side']:4} | {r['symbol']} | "
            f"volume={r['volume']} | "
            f"qTotCap={r['qTotCap']} | "
            f"implied_avg={r['implied_average_price']} | "
            f"last={r['last_price']} | "
            f"close={r['close_price']} | "
            f"bid={r['bid_price']} | ask={r['ask_price']} | "
            f"within_bid_ask={r['within_bid_ask']}"
        )

    print("\nOUTPUT FILES")
    print(f"CSV : {csv_path}")
    print(f"JSON: {json_path}")
    print("\nBR56 completed successfully.")


if __name__ == "__main__":
    main()
