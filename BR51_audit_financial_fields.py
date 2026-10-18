
# BR51 - Deep Audit of Financial Ratios and Trade Fields
# Read-only JSON analysis. No database access or modification.

import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path


# ============================================================
# BR51.1 - Configuration
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

INPUT_FILE = (
    DATA_DIR / "BR44_live_response_20261015_070837.json"
)

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

CSV_FILE = DATA_DIR / f"BR51_contracts_{RUN_ID}.csv"
JSON_FILE = DATA_DIR / f"BR51_report_{RUN_ID}.json"

UNDERLYING_ID = "17914401175772326"

# Tolerance is for numerical comparison only.
ABS_TOL = 0.01
REL_TOL = 1e-6


# ============================================================
# BR51.2 - Helpers
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


def close(a, b):
    return (
        a is not None
        and b is not None
        and math.isclose(
            a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL
        )
    )


def divide(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def safe_median(values):
    values = [
        x for x in values
        if x is not None and math.isfinite(x)
    ]
    return statistics.median(values) if values else None


def stats(values):
    values = [
        x for x in values
        if x is not None and math.isfinite(x)
    ]

    if not values:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "mean": None,
            "max": None,
            "zero_count": 0,
            "negative_count": 0,
        }

    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "max": max(values),
        "zero_count": sum(x == 0 for x in values),
        "negative_count": sum(x < 0 for x in values),
    }


def pearson_correlation(pairs):
    """Pearson correlation without third-party libraries."""
    pairs = [
        (x, y) for x, y in pairs
        if x is not None and y is not None
        and math.isfinite(x) and math.isfinite(y)
    ]

    if len(pairs) < 3:
        return None

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    mx = statistics.mean(xs)
    my = statistics.mean(ys)

    numerator = sum(
        (x - mx) * (y - my) for x, y in pairs
    )

    denominator_x = sum((x - mx) ** 2 for x in xs)
    denominator_y = sum((y - my) ** 2 for y in ys)

    if denominator_x == 0 or denominator_y == 0:
        return None

    return numerator / math.sqrt(
        denominator_x * denominator_y
    )


def load_records(path):
    with path.open("r", encoding="utf-8-sig") as file:
        root = json.load(file)

    if isinstance(root, list):
        return root

    if isinstance(root, dict):
        records = root.get("instrumentOptMarketWatch")
        if isinstance(records, list):
            return records

    raise ValueError(
        "instrumentOptMarketWatch array was not found."
    )


# ============================================================
# BR51.3 - Discover actual API numeric fields
# ============================================================

def discover_numeric_fields(records):
    result = {
        "CALL": {},
        "PUT": {},
        "COMMON": {},
    }

    for record in records:
        if not isinstance(record, dict):
            continue

        for key, value in record.items():
            if number(value) is None:
                continue

            if key.endswith("_C"):
                base = key[:-2]
                result["CALL"].setdefault(base, 0)
                result["CALL"][base] += 1

            elif key.endswith("_P"):
                base = key[:-2]
                result["PUT"].setdefault(base, 0)
                result["PUT"][base] += 1

            else:
                result["COMMON"].setdefault(key, 0)
                result["COMMON"][key] += 1

    return result


# ============================================================
# BR51.4 - Contract extraction
# ============================================================

def extract_contracts(records):
    contracts = []
    matched_source_records = 0

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue

        if str(record.get("uaInsCode", "")) != UNDERLYING_ID:
            continue

        matched_source_records += 1

        common = {
            "source_index": index,
            "strike_price": number(record.get("strikePrice")),
            "contract_size": number(record.get("contractSize")),
            "expiry": record.get("endDate"),
            "remaining_days": number(record.get("remainedDay")),
            "underlying_last": number(record.get("pDrCotVal_UA")),
            "underlying_close": number(record.get("pClosing_UA")),
            "underlying_yesterday": number(
                record.get("priceYesterday_UA")
            ),
        }

        for suffix, side in (("C", "CALL"), ("P", "PUT")):
            contract_id = record.get(f"insCode_{suffix}")

            if contract_id is None:
                continue

            item = dict(common)
            item.update({
                "side": side,
                "suffix": suffix,
                "contract_id": str(contract_id),
                "symbol": record.get(f"lVal18AFC_{suffix}"),
                "name": record.get(f"lVal30_{suffix}"),
                "last_price": number(
                    record.get(f"pDrCotVal_{suffix}")
                ),
                "closing_price": number(
                    record.get(f"pClosing_{suffix}")
                ),
                "yesterday_price": number(
                    record.get(f"priceYesterday_{suffix}")
                ),
                "volume": number(
                    record.get(f"qTotTran5J_{suffix}")
                ),
                "qTotCap": number(
                    record.get(f"qTotCap_{suffix}")
                ),
                "notionalValue": number(
                    record.get(f"notionalValue_{suffix}")
                ),
                "open_interest": number(
                    record.get(f"oP_{suffix}")
                ),
                "yesterday_open_interest": number(
                    record.get(f"yesterdayOP_{suffix}")
                ),
                "best_buy": number(
                    record.get(f"pMeDem_{suffix}")
                ),
                "best_sell": number(
                    record.get(f"pMeOf_{suffix}")
                ),
                "buy_volume": number(
                    record.get(f"qTitMeDem_{suffix}")
                ),
                "sell_volume": number(
                    record.get(f"qTitMeOf_{suffix}")
                ),
            })

            # Preserve every actual numeric side-specific field.
            # This enables investigation of fields not yet mapped.
            for key, value in record.items():
                if key.endswith("_" + suffix):
                    item["raw_" + key] = number(value)

            # Exact observed trade-count key from BR50.
            item["trade_count"] = number(
                record.get(f"zTotTran_{suffix}")
            )

            contracts.append(item)

    return contracts, matched_source_records


# ============================================================
# BR51.5 - Calculate ratios and candidate relationships
# ============================================================

def enrich_contract(contract):
    p = contract["last_price"]
    pc = contract["closing_price"]
    py = contract["yesterday_price"]
    v = contract["volume"]
    size = contract["contract_size"]
    cap = contract["qTotCap"]
    nv = contract["notionalValue"]
    trades = contract["trade_count"]

    candidates = {
        "last_x_volume": (
            p * v if p is not None and v is not None else None
        ),
        "close_x_volume": (
            pc * v if pc is not None and v is not None else None
        ),
        "yesterday_x_volume": (
            py * v if py is not None and v is not None else None
        ),
        "last_x_volume_x_size": (
            p * v * size
            if p is not None and v is not None and size is not None
            else None
        ),
        "close_x_volume_x_size": (
            pc * v * size
            if pc is not None and v is not None and size is not None
            else None
        ),
        "yesterday_x_volume_x_size": (
            py * v * size
            if py is not None and v is not None and size is not None
            else None
        ),
        "last_x_contract_size": (
            p * size if p is not None and size is not None else None
        ),
    }

    contract.update(candidates)

    contract["notional_div_cap"] = divide(nv, cap)
    contract["cap_div_volume"] = divide(cap, v)
    contract["notional_div_volume"] = divide(nv, v)
    contract["cap_div_trades"] = divide(cap, trades)
    contract["notional_div_trades"] = divide(nv, trades)
    contract["volume_div_trades"] = divide(v, trades)

    contract["cap_div_last_x_volume"] = divide(
        cap, candidates["last_x_volume"]
    )
    contract["notional_div_last_x_volume"] = divide(
        nv, candidates["last_x_volume"]
    )

    contract["cap_div_close_x_volume"] = divide(
        cap, candidates["close_x_volume"]
    )
    contract["notional_div_close_x_volume"] = divide(
        nv, candidates["close_x_volume"]
    )

    contract["cap_div_last_x_volume_size"] = divide(
        cap, candidates["last_x_volume_x_size"]
    )
    contract["notional_div_last_x_volume_size"] = divide(
        nv, candidates["last_x_volume_x_size"]
    )

    contract["cap_equals_last_x_volume"] = close(
        cap, candidates["last_x_volume"]
    )
    contract["notional_equals_last_x_volume"] = close(
        nv, candidates["last_x_volume"]
    )
    contract["cap_equals_close_x_volume"] = close(
        cap, candidates["close_x_volume"]
    )
    contract["notional_equals_close_x_volume"] = close(
        nv, candidates["close_x_volume"]
    )
    contract["cap_equals_last_x_volume_size"] = close(
        cap, candidates["last_x_volume_x_size"]
    )
    contract["notional_equals_last_x_volume_size"] = close(
        nv, candidates["last_x_volume_x_size"]
    )

    contract["financial_fields_equal"] = close(cap, nv)
    contract["notional_greater_than_cap"] = (
        nv > cap if nv is not None and cap is not None else None
    )

    contract["zero_volume"] = v == 0
    contract["positive_volume"] = v is not None and v > 0
    contract["zero_trade_count"] = trades == 0
    contract["positive_trade_count"] = (
        trades is not None and trades > 0
    )

    contract["volume_positive_but_trade_count_zero"] = (
        v is not None and v > 0 and trades == 0
    )
    contract["volume_zero_but_trade_count_positive"] = (
        v == 0 and trades is not None and trades > 0
    )

    contract["zero_volume_with_nonzero_financial_value"] = (
        v == 0 and (
            (cap is not None and cap != 0)
            or (nv is not None and nv != 0)
        )
    )

    contract["nonzero_volume_with_zero_financial_value"] = (
        v is not None and v > 0 and (
            cap == 0 or nv == 0
        )
    )

    return contract


# ============================================================
# BR51.6 - Hypothesis report
# ============================================================

def test_formula(contracts, target, candidate):
    eligible = [
        row for row in contracts
        if row.get(target) is not None
        and row.get(candidate) is not None
    ]

    matched = [
        row for row in eligible
        if close(row[target], row[candidate])
    ]

    return {
        "target": target,
        "candidate": candidate,
        "eligible": len(eligible),
        "matched": len(matched),
        "mismatched": len(eligible) - len(matched),
        "match_percentage": (
            round(100 * len(matched) / len(eligible), 2)
            if eligible else None
        ),
    }


def build_hypotheses(contracts):
    hypotheses = []

    for target in ("qTotCap", "notionalValue"):
        for candidate in (
            "last_x_volume",
            "close_x_volume",
            "yesterday_x_volume",
            "last_x_volume_x_size",
            "close_x_volume_x_size",
            "yesterday_x_volume_x_size",
        ):
            hypotheses.append(
                test_formula(contracts, target, candidate)
            )

    return hypotheses


def correlation_report(contracts):
    fields = [
        "last_price",
        "closing_price",
        "yesterday_price",
        "volume",
        "trade_count",
        "contract_size",
        "open_interest",
        "yesterday_open_interest",
        "best_buy",
        "best_sell",
        "buy_volume",
        "sell_volume",
        "qTotCap",
        "notionalValue",
    ]

    results = {}

    for side in ("CALL", "PUT", "ALL"):
        subset = [
            row for row in contracts
            if side == "ALL" or row["side"] == side
        ]

        results[side] = {}

        for i, left in enumerate(fields):
            for right in fields[i + 1:]:
                pairs = [
                    (row.get(left), row.get(right))
                    for row in subset
                ]

                valid = [
                    (x, y) for x, y in pairs
                    if x is not None and y is not None
                ]

                corr = pearson_correlation(valid)

                results[side][f"{left} vs {right}"] = {
                    "n": len(valid),
                    "pearson_r": (
                        round(corr, 6) if corr is not None else None
                    ),
                }

    return results


# ============================================================
# BR51.7 - Special zero-volume analysis
# ============================================================

def zero_volume_analysis(contracts):
    results = []

    for row in contracts:
        if not row["zero_volume"]:
            continue

        results.append({
            "side": row["side"],
            "symbol": row["symbol"],
            "contract_id": row["contract_id"],
            "last_price": row["last_price"],
            "closing_price": row["closing_price"],
            "yesterday_price": row["yesterday_price"],
            "trade_count": row["trade_count"],
            "qTotCap": row["qTotCap"],
            "notionalValue": row["notionalValue"],
            "open_interest": row["open_interest"],
            "yesterday_open_interest": (
                row["yesterday_open_interest"]
            ),
            "best_buy": row["best_buy"],
            "best_sell": row["best_sell"],
            "buy_volume": row["buy_volume"],
            "sell_volume": row["sell_volume"],
            "expiry": row["expiry"],
            "remaining_days": row["remaining_days"],
        })

    return results


# ============================================================
# BR51.8 - Paired CALL/PUT analysis
# ============================================================

def paired_analysis(contracts):
    by_index = {}

    for row in contracts:
        by_index.setdefault(row["source_index"], {})[
            row["side"]
        ] = row

    results = []

    for index, pair in by_index.items():
        if "CALL" not in pair or "PUT" not in pair:
            continue

        call = pair["CALL"]
        put = pair["PUT"]

        results.append({
            "source_index": index,
            "call_symbol": call["symbol"],
            "put_symbol": put["symbol"],
            "call_volume": call["volume"],
            "put_volume": put["volume"],
            "call_trade_count": call["trade_count"],
            "put_trade_count": put["trade_count"],
            "call_qTotCap": call["qTotCap"],
            "put_qTotCap": put["qTotCap"],
            "call_notionalValue": call["notionalValue"],
            "put_notionalValue": put["notionalValue"],
            "call_to_put_volume_ratio": divide(
                call["volume"], put["volume"]
            ),
            "call_to_put_cap_ratio": divide(
                call["qTotCap"], put["qTotCap"]
            ),
            "call_to_put_notional_ratio": divide(
                call["notionalValue"], put["notionalValue"]
            ),
        })

    return results


# ============================================================
# BR51.9 - CSV export
# ============================================================

def export_contracts_csv(contracts):
    # Raw numeric fields are retained as additional CSV columns.
    fields = set()

    for row in contracts:
        fields.update(
            key for key in row
            if not key.startswith("raw_")
        )

    fields = sorted(fields)

    with CSV_FILE.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()

        for row in contracts:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else value
                for key, value in row.items()
                if not key.startswith("raw_")
            })


# ============================================================
# BR51.10 - Main
# ============================================================

def main():
    print("=" * 78)
    print("BR51 - DEEP FINANCIAL RELATIONSHIP AUDIT")
    print("=" * 78)
    print(f"Input: {INPUT_FILE}")
    print("Database access: NONE")
    print("Database changes: NONE")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(str(INPUT_FILE))

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    records = load_records(INPUT_FILE)
    contracts, matched_sources = extract_contracts(records)

    for row in contracts:
        enrich_contract(row)

    field_inventory = discover_numeric_fields(records)
    hypotheses = build_hypotheses(contracts)
    correlations = correlation_report(contracts)
    zero_volume = zero_volume_analysis(contracts)
    pairs = paired_analysis(contracts)

    summary = {
        "script": "BR51",
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "input_file": str(INPUT_FILE),
        "database_access": False,
        "database_changes": False,
        "raw_record_count": len(records),
        "matching_underlying_source_records": matched_sources,
        "contract_count": len(contracts),
        "call_count": sum(
            row["side"] == "CALL" for row in contracts
        ),
        "put_count": sum(
            row["side"] == "PUT" for row in contracts
        ),
        "numeric_field_inventory": field_inventory,
        "formula_hypotheses": hypotheses,
        "correlations": correlations,
        "zero_volume_contracts": zero_volume,
        "call_put_pairs": pairs,
        "methodology": [
            "Correlation does not prove causation or field semantics.",
            "The sample contains a single API snapshot.",
            "Last price may not equal the average execution price.",
            "No official field definition is inferred from numerical "
            "relationships alone.",
            "Ratios with zero denominators are reported as null.",
        ],
    }

    export_contracts_csv(contracts)

    with JSON_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "summary": summary,
                "contracts": contracts,
            },
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print(f"\nRaw API records: {len(records)}")
    print(f"Matching underlying records: {matched_sources}")
    print(f"Normalized contracts: {len(contracts)}")
    print(f"CALL: {summary['call_count']}")
    print(f"PUT : {summary['put_count']}")

    print("\nFORMULA TESTS")
    for item in hypotheses:
        print(
            f"{item['target']} vs {item['candidate']}: "
            f"n={item['eligible']}, "
            f"matched={item['matched']}, "
            f"match%={item['match_percentage']}"
        )

    print("\nZERO-VOLUME CONTRACTS")
    print(f"Count: {len(zero_volume)}")

    for row in zero_volume:
        print(
            f"{row['side']:4} | {row['symbol']} | "
            f"trades={row['trade_count']} | "
            f"qTotCap={row['qTotCap']} | "
            f"notionalValue={row['notionalValue']} | "
            f"OI={row['open_interest']}"
        )

    print("\nTRADE COUNT CONSISTENCY")
    print(
        "Volume positive but trade count zero:",
        sum(
            row["volume_positive_but_trade_count_zero"]
            for row in contracts
        ),
    )
    print(
        "Volume zero but trade count positive:",
        sum(
            row["volume_zero_but_trade_count_positive"]
            for row in contracts
        ),
    )

    print("\nFIELD INVENTORY")
    for group, fields in field_inventory.items():
        print(f"\n[{group}]")
        for key, count in sorted(fields.items()):
            print(f"{key}: present in {count} records")

    print("\nOUTPUT FILES")
    print(f"CSV : {CSV_FILE}")
    print(f"JSON: {JSON_FILE}")
    print("\nBR51 completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("BR51 FAILED")
        print(f"{type(exc).__name__}: {exc}")
        raise
