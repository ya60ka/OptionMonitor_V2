
# BR53 - Raw Financial Field Integrity Audit
# Independent read-only audit of the original TSETMC JSON response.

import csv
import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path


# ============================================================
# BR53.1 - Configuration
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

INPUT_FILE = DATA_DIR / "BR44_live_response_20261015_070837.json"

UNDERLYING_ID = "17914401175772326"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

CSV_FILE = DATA_DIR / f"BR53_raw_integrity_{RUN_ID}.csv"
JSON_FILE = DATA_DIR / f"BR53_report_{RUN_ID}.json"

EXPECTED_NOTIONAL_PER_VOLUME = 75_985_000.0
EXPECTED_CAP_MULTIPLIER = 1000.0

REL_TOL = 1e-9
ABS_TOL = 0.01


# ============================================================
# BR53.2 - Helpers
# ============================================================

def number(value):
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


def divide(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def equal(a, b):
    if a is None or b is None:
        return False

    return math.isclose(
        a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL
    )


def stats(values):
    values = [
        x for x in values
        if x is not None and math.isfinite(x)
    ]

    if not values:
        return {
            "n": 0,
            "unique_count": 0,
            "min": None,
            "median": None,
            "max": None,
        }

    return {
        "n": len(values),
        "unique_count": len(set(values)),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def load_records(path):
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        records = data.get("instrumentOptMarketWatch")
        if isinstance(records, list):
            return records

    raise ValueError(
        "Could not locate instrumentOptMarketWatch array."
    )


# ============================================================
# BR53.3 - Extract values directly from raw API records
# ============================================================

def extract_contracts(records):
    output = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue

        if str(record.get("uaInsCode", "")) != UNDERLYING_ID:
            continue

        for suffix, side in (("C", "CALL"), ("P", "PUT")):
            contract_id = record.get(f"insCode_{suffix}")

            if contract_id is None:
                continue

            volume = number(record.get(f"qTotTran5J_{suffix}"))
            trade_count = number(record.get(f"zTotTran_{suffix}"))
            close_price = number(record.get(f"pClosing_{suffix}"))
            last_price = number(record.get(f"pDrCotVal_{suffix}"))
            yesterday_price = number(
                record.get(f"priceYesterday_{suffix}")
            )
            cap = number(record.get(f"qTotCap_{suffix}"))
            notional = number(
                record.get(f"notionalValue_{suffix}")
            )
            contract_size = number(record.get("contractSize"))

            row = {
                "source_record_index": index,
                "side": side,
                "symbol": record.get(f"lVal18AFC_{suffix}"),
                "contract_id": str(contract_id),
                "strike": number(record.get("strikePrice")),
                "expiry": record.get("endDate"),
                "volume": volume,
                "trade_count": trade_count,
                "last_price": last_price,
                "close_price": close_price,
                "yesterday_price": yesterday_price,
                "contract_size": contract_size,
                "qTotCap": cap,
                "notionalValue": notional,
                "open_interest": number(record.get(f"oP_{suffix}")),
                "yesterday_open_interest": number(
                    record.get(f"yesterdayOP_{suffix}")
                ),
                "raw_notional_per_volume": divide(notional, volume),
                "raw_cap_per_volume": divide(cap, volume),
                "raw_cap_per_volume_close": divide(
                    cap,
                    volume * close_price
                    if volume is not None and close_price is not None
                    else None,
                ),
                "expected_cap_from_close_x_volume_x_1000": (
                    close_price * volume * EXPECTED_CAP_MULTIPLIER
                    if close_price is not None and volume is not None
                    else None
                ),
                "notional_matches_fixed_ratio": equal(
                    divide(notional, volume),
                    EXPECTED_NOTIONAL_PER_VOLUME,
                ),
                "cap_matches_close_x_volume_x_1000": equal(
                    cap,
                    close_price * volume * EXPECTED_CAP_MULTIPLIER
                    if close_price is not None and volume is not None
                    else None,
                ),
            }

            output.append(row)

    return output


# ============================================================
# BR53.4 - Direct raw field inventory
# ============================================================

def field_inventory(records):
    fields = [
        "qTotTran5J_C",
        "qTotTran5J_P",
        "zTotTran_C",
        "zTotTran_P",
        "pClosing_C",
        "pClosing_P",
        "qTotCap_C",
        "qTotCap_P",
        "notionalValue_C",
        "notionalValue_P",
    ]

    result = {}

    for field in fields:
        present = []
        missing = 0

        for record in records:
            if not isinstance(record, dict):
                continue

            value = number(record.get(field))

            if value is None:
                missing += 1
            else:
                present.append(value)

        counts = Counter(present)

        result[field] = {
            **stats(present),
            "missing_or_non_numeric": missing,
            "most_common_values": [
                {"value": value, "count": count}
                for value, count in counts.most_common(10)
            ],
        }

    return result


# ============================================================
# BR53.5 - Check hypotheses independently
# ============================================================

def test_hypotheses(rows):
    results = {}

    tests = {
        "notional_per_volume_equals_75985000":
            lambda r: equal(
                divide(r["notionalValue"], r["volume"]),
                EXPECTED_NOTIONAL_PER_VOLUME,
            ),
        "qTotCap_equals_close_x_volume_x_1000":
            lambda r: equal(
                r["qTotCap"],
                r["expected_cap_from_close_x_volume_x_1000"],
            ),
        "qTotCap_equals_close_x_volume":
            lambda r: equal(
                r["qTotCap"],
                r["close_price"] * r["volume"]
                if r["close_price"] is not None
                and r["volume"] is not None
                else None,
            ),
        "volume_equals_trade_count":
            lambda r: equal(r["volume"], r["trade_count"]),
    }

    for name, predicate in tests.items():
        eligible = [
            r for r in rows
            if (
                r["volume"] is not None
                and (
                    r["volume"] > 0
                    or name != "notional_per_volume_equals_75985000"
                )
            )
        ]

        matched = sum(predicate(r) for r in eligible)

        results[name] = {
            "eligible": len(eligible),
            "matched": matched,
            "mismatched": len(eligible) - matched,
            "match_percent": (
                round(100 * matched / len(eligible), 4)
                if eligible else None
            ),
        }

    return results


# ============================================================
# BR53.6 - Investigate exceptions
# ============================================================

def build_exceptions(rows):
    exceptions = []

    for row in rows:
        reasons = []

        if row["volume"] is None:
            reasons.append("MISSING_VOLUME")

        elif row["volume"] == 0:
            if row["qTotCap"] != 0:
                reasons.append("ZERO_VOLUME_NONZERO_CAP")

            if row["notionalValue"] != 0:
                reasons.append("ZERO_VOLUME_NONZERO_NOTIONAL")

        if row["volume"] is not None and row["volume"] > 0:
            ratio = row["raw_notional_per_volume"]

            if not equal(ratio, EXPECTED_NOTIONAL_PER_VOLUME):
                reasons.append("NOTIONAL_RATIO_DEVIATION")

            if not row["cap_matches_close_x_volume_x_1000"]:
                reasons.append("CAP_FORMULA_DEVIATION")

        if row["qTotCap"] is None:
            reasons.append("MISSING_QTOTCAP")

        if row["notionalValue"] is None:
            reasons.append("MISSING_NOTIONAL")

        if reasons:
            item = dict(row)
            item["exception_reasons"] = ";".join(reasons)
            exceptions.append(item)

    return exceptions


# ============================================================
# BR53.7 - Main
# ============================================================

def main():
    print("=" * 78)
    print("BR53 - RAW FINANCIAL FIELD INTEGRITY AUDIT")
    print("=" * 78)
    print(f"Input: {INPUT_FILE}")
    print("Database access: NONE")
    print("Database changes: NONE")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(str(INPUT_FILE))

    records = load_records(INPUT_FILE)
    rows = extract_contracts(records)

    if not rows:
        raise RuntimeError(
            "No matching option contracts found. "
            "Check uaInsCode and raw field names."
        )

    calls = [r for r in rows if r["side"] == "CALL"]
    puts = [r for r in rows if r["side"] == "PUT"]

    positive_volume = [
        r for r in rows
        if r["volume"] is not None and r["volume"] > 0
    ]

    ratios = [
        r["raw_notional_per_volume"]
        for r in positive_volume
        if r["raw_notional_per_volume"] is not None
    ]

    ratio_counts = Counter(ratios)

    raw_inventory = field_inventory(records)
    hypotheses = test_hypotheses(rows)
    exceptions = build_exceptions(rows)

    side_summary = {}

    for side, subset in (("CALL", calls), ("PUT", puts), ("ALL", rows)):
        eligible = [
            r for r in subset
            if r["volume"] is not None and r["volume"] > 0
        ]

        side_ratios = [
            r["raw_notional_per_volume"]
            for r in eligible
            if r["raw_notional_per_volume"] is not None
        ]

        side_summary[side] = {
            "contracts": len(subset),
            "positive_volume_contracts": len(eligible),
            "zero_volume_contracts": sum(
                r["volume"] == 0 for r in subset
            ),
            "notional_per_volume": stats(side_ratios),
            "fixed_ratio_matches": sum(
                r["notional_matches_fixed_ratio"] for r in eligible
            ),
            "cap_formula_matches": sum(
                r["cap_matches_close_x_volume_x_1000"]
                for r in eligible
            ),
            "cap_formula_eligible": len(eligible),
        }

    report = {
        "script": "BR53_audit_raw_financial_integrity.py",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_file": str(INPUT_FILE),
        "database_access": False,
        "database_changes": False,
        "raw_record_count": len(records),
        "matching_contract_count": len(rows),
        "call_count": len(calls),
        "put_count": len(puts),
        "field_inventory": raw_inventory,
        "hypothesis_tests": hypotheses,
        "side_summary": side_summary,
        "notional_per_volume_unique_value_count": len(ratio_counts),
        "most_common_notional_per_volume_ratios": [
            {"ratio": ratio, "count": count}
            for ratio, count in ratio_counts.most_common(20)
        ],
        "exception_count": len(exceptions),
        "exceptions": exceptions,
        "limitations": [
            "This audit examines one saved API response.",
            "A numerical relationship does not establish official field semantics.",
            "The raw response itself may contain provider-side anomalies.",
        ],
    }

    with CSV_FILE.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        fieldnames = sorted({
            key for row in rows for key in row
        })
        writer = csv.DictWriter(
            file, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    with JSON_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "report": report,
                "contracts": rows,
            },
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print(f"\nRaw records: {len(records)}")
    print(f"Matching contracts: {len(rows)}")
    print(f"CALL: {len(calls)} | PUT: {len(puts)}")

    print("\nRAW FIELD INVENTORY")
    for field, data in raw_inventory.items():
        print(
            f"{field}: n={data['n']}, "
            f"unique={data['unique_count']}, "
            f"missing={data['missing_or_non_numeric']}, "
            f"min={data['min']}, median={data['median']}, "
            f"max={data['max']}"
        )
        print("  Most common:", data["most_common_values"][:5])

    print("\nHYPOTHESIS TESTS")
    for name, result in hypotheses.items():
        print(f"{name}: {result}")

    print("\nSIDE SUMMARY")
    for side, data in side_summary.items():
        print(f"\n[{side}]")
        for key, value in data.items():
            print(f"{key}: {value}")

    print("\nNOTIONAL/VOLUME RATIO VALUES")
    print(f"Unique ratios: {len(ratio_counts)}")
    for item in report["most_common_notional_per_volume_ratios"]:
        print(f"ratio={item['ratio']}, count={item['count']}")

    print("\nEXCEPTIONS")
    print(f"Count: {len(exceptions)}")
    for row in exceptions[:30]:
        print(
            f"{row['side']} | {row['symbol']} | "
            f"volume={row['volume']} | "
            f"qTotCap={row['qTotCap']} | "
            f"notionalValue={row['notionalValue']} | "
            f"reasons={row['exception_reasons']}"
        )

    print("\nOUTPUT FILES")
    print(f"CSV : {CSV_FILE}")
    print(f"JSON: {JSON_FILE}")
    print("\nBR53 completed successfully.")


if __name__ == "__main__":
    main()
