
# BR50 - Read-only Audit of API Financial Fields
# Version: 1.0
# Database access: NONE
# Input: BR44 raw API JSON
# Output: Console report + CSV + JSON
# Purpose: Investigate numerical relationships without assuming official field meanings.

import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path


# ============================================================
# BR50.1 - Configuration
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

INPUT_FILE = (
    DATA_DIR / "BR44_live_response_20261015_070837.json"
)

RUN_TIME = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_CSV = DATA_DIR / f"BR50_audit_{RUN_TIME}.csv"
OUTPUT_JSON = DATA_DIR / f"BR50_audit_{RUN_TIME}.json"

UNDERLYING_ID = "17914401175772326"

# Numerical tolerance used only for comparing candidate formulas.
ABS_TOLERANCE = 0.01
REL_TOLERANCE = 0.000001


# ============================================================
# BR50.2 - Utility functions
# ============================================================

def to_number(value):
    """Convert a JSON value to a finite number; otherwise None."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None

    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except ValueError:
            return None

    return None


def get_number(record, key):
    return to_number(record.get(key))


def close_enough(a, b):
    if a is None or b is None:
        return False
    return math.isclose(
        a,
        b,
        rel_tol=REL_TOLERANCE,
        abs_tol=ABS_TOLERANCE,
    )


def safe_divide(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def fmt(value):
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000:
        return f"{value:,.2f}"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def get_api_array(root):
    """Locate the expected API array without modifying the input."""
    if isinstance(root, list):
        return root

    if not isinstance(root, dict):
        raise ValueError("JSON root must be an object or an array.")

    candidates = [
        root.get("instrumentOptMarketWatch"),
    ]

    for item in candidates:
        if isinstance(item, list):
            return item

    raise ValueError(
        "Array 'instrumentOptMarketWatch' was not found. "
        f"Root keys: {list(root.keys())}"
    )


def get_contract_type(record, suffix):
    return {
        "contract_id": record.get(f"insCode_{suffix}"),
        "symbol": record.get(f"lVal18AFC_{suffix}"),
        "name": record.get(f"lVal30_{suffix}"),
        "last_price": get_number(record, f"pDrCotVal_{suffix}"),
        "closing_price": get_number(record, f"pClosing_{suffix}"),
        "yesterday_price": get_number(
            record, f"priceYesterday_{suffix}"
        ),
        "volume": get_number(record, f"qTotTran5J_{suffix}"),
        "turnover_candidate": get_number(
            record, f"qTotCap_{suffix}"
        ),
        "notional_candidate": get_number(
            record, f"notionalValue_{suffix}"
        ),
        "open_interest": get_number(record, f"oP_{suffix}"),
        "yesterday_open_interest": get_number(
            record, f"yesterdayOP_{suffix}"
        ),
        "best_buy": get_number(record, f"pMeDem_{suffix}"),
        "best_sell": get_number(record, f"pMeOf_{suffix}"),
        "buy_volume": get_number(record, f"qTitMeDem_{suffix}"),
        "sell_volume": get_number(record, f"qTitMeOf_{suffix}"),
        "trade_count": None,
        "raw_record": record,
        "suffix": suffix,
    }


# ============================================================
# BR50.3 - Identify actual trade-count fields
# ============================================================

def find_trade_count(record, suffix):
    """
    Report candidate keys actually present in the raw API.
    Do not assume which key has the official meaning.
    """
    candidate_keys = [
        f"zTotTran5J_{suffix}",
        f"zTotTran_{suffix}",
        f"zTotTran5J{suffix}",
        f"zTotTran{suffix}",
    ]

    found = {}
    for key in candidate_keys:
        if key in record:
            found[key] = record[key]

    return found


# ============================================================
# BR50.4 - Build one row per option contract
# ============================================================

def build_rows(records):
    rows = []
    matching_underlyings = 0
    nonmatching_with_contracts = 0
    trade_count_key_frequency = {}

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue

        underlying_code = str(record.get("uaInsCode", ""))

        has_target_contract = any(
            record.get(f"insCode_{side}") is not None
            for side in ("C", "P")
        )

        if underlying_code == UNDERLYING_ID:
            matching_underlyings += 1
        elif has_target_contract:
            nonmatching_with_contracts += 1
            continue
        else:
            continue

        contract_size = get_number(record, "contractSize")
        strike_price = get_number(record, "strikePrice")
        expiry = record.get("endDate")
        remaining_days = get_number(record, "remainedDay")

        underlying_last = get_number(record, "pDrCotVal_UA")
        underlying_close = get_number(record, "pClosing_UA")
        underlying_yesterday = get_number(
            record, "priceYesterday_UA"
        )

        for side in ("C", "P"):
            contract_id = record.get(f"insCode_{side}")
            if contract_id is None:
                continue

            item = get_contract_type(record, side)
            item["side"] = "CALL" if side == "C" else "PUT"
            item["source_record_index"] = index
            item["underlying_code"] = underlying_code
            item["strike_price"] = strike_price
            item["contract_size"] = contract_size
            item["expiry"] = expiry
            item["remaining_days"] = remaining_days
            item["underlying_last_price"] = underlying_last
            item["underlying_closing_price"] = underlying_close
            item["underlying_yesterday_price"] = (
                underlying_yesterday
            )

            item["trade_count_candidates"] = find_trade_count(
                record, side
            )

            for key in item["trade_count_candidates"]:
                trade_count_key_frequency[key] = (
                    trade_count_key_frequency.get(key, 0) + 1
                )

            # Preserve candidate formulas as hypotheses only.
            price = item["last_price"]
            closing = item["closing_price"]
            yesterday = item["yesterday_price"]
            volume = item["volume"]
            cap = item["turnover_candidate"]
            notional = item["notional_candidate"]

            item["last_price_x_volume"] = (
                price * volume
                if price is not None and volume is not None
                else None
            )

            item["last_price_x_volume_x_size"] = (
                price * volume * contract_size
                if price is not None
                and volume is not None
                and contract_size is not None
                else None
            )

            item["closing_price_x_volume"] = (
                closing * volume
                if closing is not None and volume is not None
                else None
            )

            item["closing_price_x_volume_x_size"] = (
                closing * volume * contract_size
                if closing is not None
                and volume is not None
                and contract_size is not None
                else None
            )

            item["yesterday_price_x_volume"] = (
                yesterday * volume
                if yesterday is not None and volume is not None
                else None
            )

            item["yesterday_price_x_volume_x_size"] = (
                yesterday * volume * contract_size
                if yesterday is not None
                and volume is not None
                and contract_size is not None
                else None
            )

            item["cap_div_last_price_volume"] = safe_divide(
                cap, item["last_price_x_volume"]
            )
            item["notional_div_last_price_volume"] = safe_divide(
                notional, item["last_price_x_volume"]
            )
            item["cap_div_last_price_volume_size"] = safe_divide(
                cap, item["last_price_x_volume_x_size"]
            )
            item["notional_div_last_price_volume_size"] = (
                safe_divide(
                    notional, item["last_price_x_volume_x_size"]
                )
            )
            item["notional_div_cap"] = safe_divide(notional, cap)

            item["cap_equals_last_price_volume"] = close_enough(
                cap, item["last_price_x_volume"]
            )
            item["notional_equals_last_price_volume"] = (
                close_enough(
                    notional, item["last_price_x_volume"]
                )
            )
            item["cap_equals_last_price_volume_size"] = (
                close_enough(
                    cap, item["last_price_x_volume_x_size"]
                )
            )
            item["notional_equals_last_price_volume_size"] = (
                close_enough(
                    notional,
                    item["last_price_x_volume_x_size"],
                )
            )
            item["cap_equals_closing_volume"] = close_enough(
                cap, item["closing_price_x_volume"]
            )
            item["notional_equals_closing_volume"] = close_enough(
                notional, item["closing_price_x_volume"]
            )
            item["cap_equals_closing_volume_size"] = close_enough(
                cap, item["closing_price_x_volume_x_size"]
            )
            item["notional_equals_closing_volume_size"] = (
                close_enough(
                    notional,
                    item["closing_price_x_volume_x_size"],
                )
            )

            # Zero/missing/anomaly classifications.
            item["missing_last_price"] = price is None
            item["missing_closing_price"] = closing is None
            item["missing_volume"] = volume is None
            item["missing_cap"] = cap is None
            item["missing_notional"] = notional is None

            item["zero_last_price"] = price == 0
            item["zero_closing_price"] = closing == 0
            item["zero_volume"] = volume == 0
            item["zero_cap"] = cap == 0
            item["zero_notional"] = notional == 0

            item["negative_value_detected"] = any(
                value is not None and value < 0
                for value in (
                    price, closing, yesterday, volume,
                    cap, notional, contract_size
                )
            )

            item["no_trade_candidate"] = (
                volume == 0
                or (
                    volume is None
                    and all(
                        value in (None, 0)
                        for value in (price, closing, cap, notional)
                    )
                )
            )

            # Simple cross-field consistency indicators.
            item["last_vs_close_difference"] = (
                price - closing
                if price is not None and closing is not None
                else None
            )

            item["last_vs_close_ratio"] = safe_divide(
                price, closing
            )

            item["last_vs_underlying_ratio"] = safe_divide(
                price, underlying_last
            )

            item["financial_fields_both_present"] = (
                cap is not None and notional is not None
            )

            item["notional_greater_than_cap"] = (
                notional > cap
                if cap is not None and notional is not None
                else None
            )

            rows.append(item)

    return (
        rows,
        matching_underlyings,
        trade_count_key_frequency,
    )


# ============================================================
# BR50.5 - Statistical hypothesis evaluation
# ============================================================

FORMULA_TESTS = {
    "qTotCap = last_price * volume":
        ("turnover_candidate", "last_price_x_volume"),
    "notionalValue = last_price * volume":
        ("notional_candidate", "last_price_x_volume"),
    "qTotCap = last_price * volume * contractSize":
        ("turnover_candidate", "last_price_x_volume_x_size"),
    "notionalValue = last_price * volume * contractSize":
        ("notional_candidate", "last_price_x_volume_x_size"),
    "qTotCap = closing_price * volume":
        ("turnover_candidate", "closing_price_x_volume"),
    "notionalValue = closing_price * volume":
        ("notional_candidate", "closing_price_x_volume"),
    "qTotCap = closing_price * volume * contractSize":
        ("turnover_candidate", "closing_price_x_volume_x_size"),
    "notionalValue = closing_price * volume * contractSize":
        ("notional_candidate", "closing_price_x_volume_x_size"),
    "qTotCap = yesterday_price * volume":
        ("turnover_candidate", "yesterday_price_x_volume"),
    "notionalValue = yesterday_price * volume":
        ("notional_candidate", "yesterday_price_x_volume"),
    "qTotCap = yesterday_price * volume * contractSize":
        ("turnover_candidate", "yesterday_price_x_volume_x_size"),
    "notionalValue = yesterday_price * volume * contractSize":
        ("notional_candidate", "yesterday_price_x_volume_x_size"),
}


def evaluate_formulas(rows):
    report = {}

    for label, (actual_key, expected_key) in FORMULA_TESTS.items():
        eligible = [
            row for row in rows
            if row.get(actual_key) is not None
            and row.get(expected_key) is not None
        ]

        matched = [
            row for row in eligible
            if close_enough(
                row.get(actual_key), row.get(expected_key)
            )
        ]

        report[label] = {
            "eligible_count": len(eligible),
            "matched_count": len(matched),
            "mismatched_count": len(eligible) - len(matched),
            "match_percentage": (
                round(100 * len(matched) / len(eligible), 2)
                if eligible else None
            ),
            "status": (
                "NO_COMPARABLE_SAMPLES"
                if not eligible
                else "MATCHED_ALL_SAMPLES"
                if len(matched) == len(eligible)
                else "PARTIAL_MATCH"
                if matched
                else "NOT_MATCHED"
            ),
            "interpretation": (
                "Numerical comparison only; does not establish "
                "the official semantic definition."
            ),
        }

    return report


# ============================================================
# BR50.6 - Field and anomaly summaries
# ============================================================

def count_true(rows, key):
    return sum(row.get(key) is True for row in rows)


def count_missing(rows, key):
    return sum(row.get(key) is None for row in rows)


def summarize_values(rows, key):
    values = [
        row[key] for row in rows
        if row.get(key) is not None
    ]

    if not values:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "max": None,
            "zero_count": 0,
            "negative_count": 0,
        }

    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "zero_count": sum(value == 0 for value in values),
        "negative_count": sum(value < 0 for value in values),
    }


def build_summary(rows, formula_report, trade_count_keys):
    sides = {}

    for side in ("CALL", "PUT"):
        subset = [row for row in rows if row["side"] == side]

        sides[side] = {
            "contract_count": len(subset),
            "missing_last_price": count_missing(
                subset, "last_price"
            ),
            "missing_closing_price": count_missing(
                subset, "closing_price"
            ),
            "missing_volume": count_missing(subset, "volume"),
            "missing_qTotCap": count_missing(
                subset, "turnover_candidate"
            ),
            "missing_notionalValue": count_missing(
                subset, "notional_candidate"
            ),
            "zero_last_price": count_true(
                subset, "zero_last_price"
            ),
            "zero_closing_price": count_true(
                subset, "zero_closing_price"
            ),
            "zero_volume": count_true(subset, "zero_volume"),
            "zero_qTotCap": count_true(subset, "zero_cap"),
            "zero_notionalValue": count_true(
                subset, "zero_notional"
            ),
            "negative_value_detected": count_true(
                subset, "negative_value_detected"
            ),
            "no_trade_candidate": count_true(
                subset, "no_trade_candidate"
            ),
            "qTotCap": summarize_values(
                subset, "turnover_candidate"
            ),
            "notionalValue": summarize_values(
                subset, "notional_candidate"
            ),
            "volume": summarize_values(subset, "volume"),
            "last_price": summarize_values(subset, "last_price"),
            "closing_price": summarize_values(
                subset, "closing_price"
            ),
            "notional_greater_than_qTotCap": sum(
                row["notional_greater_than_cap"] is True
                for row in subset
            ),
            "both_financial_fields_present": sum(
                row["financial_fields_both_present"] is True
                for row in subset
            ),
        }

    all_pairs = []
    by_underlying_record = {}

    for row in rows:
        key = row["source_record_index"]
        by_underlying_record.setdefault(key, {})[row["side"]] = row

    for source_index, pair in by_underlying_record.items():
        if "CALL" not in pair or "PUT" not in pair:
            continue

        call = pair["CALL"]
        put = pair["PUT"]

        all_pairs.append({
            "source_record_index": source_index,
            "call_symbol": call["symbol"],
            "put_symbol": put["symbol"],
            "same_volume": (
                call["volume"] == put["volume"]
                if call["volume"] is not None
                and put["volume"] is not None
                else None
            ),
            "same_qTotCap": (
                call["turnover_candidate"]
                == put["turnover_candidate"]
                if call["turnover_candidate"] is not None
                and put["turnover_candidate"] is not None
                else None
            ),
            "same_notionalValue": (
                call["notional_candidate"]
                == put["notional_candidate"]
                if call["notional_candidate"] is not None
                and put["notional_candidate"] is not None
                else None
            ),
        })

    paired_summary = {
        "complete_call_put_pairs": len(all_pairs),
        "same_volume_pairs": sum(
            p["same_volume"] is True for p in all_pairs
        ),
        "same_qTotCap_pairs": sum(
            p["same_qTotCap"] is True for p in all_pairs
        ),
        "same_notionalValue_pairs": sum(
            p["same_notionalValue"] is True for p in all_pairs
        ),
    }

    return {
        "script": "BR50_audit_financial_fields.py",
        "version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_file": str(INPUT_FILE),
        "database_access": False,
        "database_changes": False,
        "underlying_id": UNDERLYING_ID,
        "total_normalized_contract_rows": len(rows),
        "call_count": sum(r["side"] == "CALL" for r in rows),
        "put_count": sum(r["side"] == "PUT" for r in rows),
        "trade_count_candidate_keys_found": trade_count_keys,
        "side_summary": sides,
        "paired_contract_summary": paired_summary,
        "formula_tests": formula_report,
        "methodology_notes": [
            "Only the selected raw JSON file is analyzed.",
            "No database connection is created.",
            "Formula matches are numerical observations, not proof "
            "of official field definitions.",
            "Last traded price may differ from average trade price.",
            "Units, aggregation rules and API field semantics "
            "remain unverified unless supported by documentation.",
            "A zero volume alone is treated as a no-trade candidate, "
            "not conclusive proof of no trading activity.",
        ],
    }


# ============================================================
# BR50.7 - Export detailed CSV
# ============================================================

def export_csv(rows, path):
    fields = [
        "source_record_index",
        "side",
        "contract_id",
        "symbol",
        "name",
        "expiry",
        "remaining_days",
        "strike_price",
        "contract_size",
        "last_price",
        "closing_price",
        "yesterday_price",
        "volume",
        "turnover_candidate",
        "notional_candidate",
        "open_interest",
        "yesterday_open_interest",
        "best_buy",
        "buy_volume",
        "best_sell",
        "sell_volume",
        "trade_count_candidates",
        "underlying_last_price",
        "underlying_closing_price",
        "last_price_x_volume",
        "last_price_x_volume_x_size",
        "closing_price_x_volume",
        "closing_price_x_volume_x_size",
        "yesterday_price_x_volume",
        "yesterday_price_x_volume_x_size",
        "cap_div_last_price_volume",
        "notional_div_last_price_volume",
        "cap_div_last_price_volume_size",
        "notional_div_last_price_volume_size",
        "notional_div_cap",
        "cap_equals_last_price_volume",
        "notional_equals_last_price_volume",
        "cap_equals_last_price_volume_size",
        "notional_equals_last_price_volume_size",
        "cap_equals_closing_volume",
        "notional_equals_closing_volume",
        "cap_equals_closing_volume_size",
        "notional_equals_closing_volume_size",
        "missing_last_price",
        "missing_closing_price",
        "missing_volume",
        "missing_cap",
        "missing_notional",
        "zero_last_price",
        "zero_closing_price",
        "zero_volume",
        "zero_cap",
        "zero_notional",
        "negative_value_detected",
        "no_trade_candidate",
        "last_vs_close_difference",
        "last_vs_close_ratio",
        "last_vs_underlying_ratio",
        "notional_greater_than_cap",
    ]

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()

        for row in rows:
            writer.writerow({
                key: json.dumps(
                    row.get(key), ensure_ascii=False
                ) if isinstance(row.get(key), (dict, list)) else row.get(key)
                for key in fields
            })


# ============================================================
# BR50.8 - Console report
# ============================================================

def print_report(summary):
    print("=" * 78)
    print("BR50 - READ-ONLY API FINANCIAL FIELD AUDIT")
    print("=" * 78)
    print(f"Input file             : {summary['input_file']}")
    print(f"Database access        : {summary['database_access']}")
    print(f"Database changes       : {summary['database_changes']}")
    print(f"Underlying ID          : {summary['underlying_id']}")
    print(f"Contract rows          : {summary['total_normalized_contract_rows']}")
    print(f"CALL contracts         : {summary['call_count']}")
    print(f"PUT contracts          : {summary['put_count']}")

    print("\n" + "-" * 78)
    print("FIELD QUALITY SUMMARY")
    print("-" * 78)

    for side, data in summary["side_summary"].items():
        print(f"\n[{side}]")
        print(f"  Contracts                 : {data['contract_count']}")
        print(f"  Missing last price        : {data['missing_last_price']}")
        print(f"  Missing closing price     : {data['missing_closing_price']}")
        print(f"  Missing volume            : {data['missing_volume']}")
        print(f"  Missing qTotCap           : {data['missing_qTotCap']}")
        print(f"  Missing notionalValue     : {data['missing_notionalValue']}")
        print(f"  Zero volume               : {data['zero_volume']}")
        print(f"  Zero qTotCap              : {data['zero_qTotCap']}")
        print(f"  Zero notionalValue        : {data['zero_notionalValue']}")
        print(f"  Negative values detected  : {data['negative_value_detected']}")
        print(f"  No-trade candidates       : {data['no_trade_candidate']}")
        print(
            "  notionalValue > qTotCap  : "
            f"{data['notional_greater_than_qTotCap']}"
        )

        for field in (
            "last_price", "volume", "qTotCap", "notionalValue"
        ):
            stats = data[field]
            print(
                f"  {field}: n={stats['count']}, "
                f"min={fmt(stats['min'])}, "
                f"median={fmt(stats['median'])}, "
                f"max={fmt(stats['max'])}"
            )

    print("\n" + "-" * 78)
    print("FORMULA HYPOTHESIS TESTS")
    print("-" * 78)

    for label, result in summary["formula_tests"].items():
        print(
            f"{label}\n"
            f"  Eligible={result['eligible_count']}, "
            f"Matched={result['matched_count']}, "
            f"Mismatched={result['mismatched_count']}, "
            f"Match%={result['match_percentage']}, "
            f"Status={result['status']}"
        )

    print("\n" + "-" * 78)
    print("CALL/PUT PAIR COMPARISON")
    print("-" * 78)

    for key, value in summary["paired_contract_summary"].items():
        print(f"{key}: {value}")

    print("\n" + "-" * 78)
    print("ACTUAL TRADE-COUNT CANDIDATE KEYS")
    print("-" * 78)

    print(json.dumps(
        summary["trade_count_candidate_keys_found"],
        ensure_ascii=False,
        indent=2,
    ))

    print("\n" + "-" * 78)
    print("IMPORTANT")
    print(
        "Numerical matches do not establish official field semantics. "
        "No database was accessed or changed."
    )


# ============================================================
# BR50.9 - Main
# ============================================================

def main():
    print("BR50 starting...")
    print(f"Project directory: {PROJECT_DIR}")
    print(f"Input file: {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input JSON file not found: {INPUT_FILE}"
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with INPUT_FILE.open("r", encoding="utf-8-sig") as file:
        root = json.load(file)

    records = get_api_array(root)

    rows, matching_underlyings, trade_count_keys = build_rows(
        records
    )

    formula_report = evaluate_formulas(rows)

    summary = build_summary(
        rows,
        formula_report,
        trade_count_keys,
    )

    summary["raw_api_array_count"] = len(records)
    summary["matching_underlying_source_records"] = (
        matching_underlyings
    )

    export_csv(rows, OUTPUT_CSV)

    # Export compact audit data. Raw source records are deliberately
    # excluded to avoid duplicating the entire API response.
    json_rows = []

    for row in rows:
        json_rows.append({
            key: value
            for key, value in row.items()
            if key != "raw_record"
        })

    output = {
        "summary": summary,
        "contracts": json_rows,
    }

    with OUTPUT_JSON.open("w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print_report(summary)

    print("\n" + "=" * 78)
    print("OUTPUT FILES")
    print("=" * 78)
    print(f"CSV : {OUTPUT_CSV}")
    print(f"JSON: {OUTPUT_JSON}")
    print("BR50 completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nBR50 FAILED")
        print(f"Error type: {type(exc).__name__}")
        print(f"Error     : {exc}")
        raise
