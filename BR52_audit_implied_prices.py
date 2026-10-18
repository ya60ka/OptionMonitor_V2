
# BR52 - Audit Implied Prices from Financial API Fields
# Read-only analysis of BR44 raw JSON. No database access.

import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path


# ============================================================
# BR52.1 - Configuration
# ============================================================

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

INPUT_FILE = DATA_DIR / "BR44_live_response_20261015_070837.json"

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_FILE = DATA_DIR / f"BR52_implied_prices_{RUN_ID}.csv"
JSON_FILE = DATA_DIR / f"BR52_report_{RUN_ID}.json"

UNDERLYING_ID = "17914401175772326"
ABS_TOL = 0.01
REL_TOL = 1e-6


# ============================================================
# BR52.2 - Helpers
# ============================================================

def num(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except ValueError:
            return None
    return None


def div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def close(a, b):
    return (
        a is not None
        and b is not None
        and math.isclose(
            a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL
        )
    )


def clean_stats(values):
    values = [
        x for x in values
        if x is not None and math.isfinite(x)
    ]
    if not values:
        return {
            "n": 0,
            "min": None,
            "median": None,
            "mean": None,
            "max": None,
        }
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "max": max(values),
    }


def pearson(pairs):
    pairs = [
        (x, y) for x, y in pairs
        if x is not None and y is not None
        and math.isfinite(x) and math.isfinite(y)
    ]
    if len(pairs) < 3:
        return None

    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)

    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:
        return None

    return sum(
        (x - mx) * (y - my) for x, y in pairs
    ) / math.sqrt(sx * sy)


def average_ranks(values):
    """Assign average ranks to tied values."""
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0

    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1

        average = ((i + 1) + j) / 2.0

        for k in range(i, j):
            ranks[indexed[k][0]] = average

        i = j

    return ranks


def spearman(pairs):
    pairs = [
        (x, y) for x, y in pairs
        if x is not None and y is not None
        and math.isfinite(x) and math.isfinite(y)
    ]
    if len(pairs) < 3:
        return None

    rx = average_ranks([x for x, _ in pairs])
    ry = average_ranks([y for _, y in pairs])

    return pearson(list(zip(rx, ry)))


def load_api(path):
    with path.open("r", encoding="utf-8-sig") as file:
        root = json.load(file)

    if isinstance(root, list):
        return root

    if isinstance(root, dict):
        items = root.get("instrumentOptMarketWatch")
        if isinstance(items, list):
            return items

    raise ValueError(
        "instrumentOptMarketWatch was not found in the input JSON."
    )


# ============================================================
# BR52.3 - Extract contracts
# ============================================================

def extract(records):
    rows = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue

        if str(record.get("uaInsCode", "")) != UNDERLYING_ID:
            continue

        common = {
            "source_index": index,
            "strike": num(record.get("strikePrice")),
            "contract_size": num(record.get("contractSize")),
            "expiry": record.get("endDate"),
            "remaining_days": num(record.get("remainedDay")),
            "underlying_last": num(record.get("pDrCotVal_UA")),
        }

        for suffix, side in (("C", "CALL"), ("P", "PUT")):
            contract_id = record.get(f"insCode_{suffix}")
            if contract_id is None:
                continue

            row = dict(common)
            row.update({
                "side": side,
                "symbol": record.get(f"lVal18AFC_{suffix}"),
                "contract_id": str(contract_id),
                "last_price": num(record.get(f"pDrCotVal_{suffix}")),
                "close_price": num(record.get(f"pClosing_{suffix}")),
                "yesterday_price": num(
                    record.get(f"priceYesterday_{suffix}")
                ),
                "volume": num(record.get(f"qTotTran5J_{suffix}")),
                "trade_count": num(record.get(f"zTotTran_{suffix}")),
                "qTotCap": num(record.get(f"qTotCap_{suffix}")),
                "notionalValue": num(
                    record.get(f"notionalValue_{suffix}")
                ),
                "open_interest": num(record.get(f"oP_{suffix}")),
                "yesterday_open_interest": num(
                    record.get(f"yesterdayOP_{suffix}")
                ),
            })

            rows.append(row)

    return rows


# ============================================================
# BR52.4 - Calculate implied prices and multipliers
# ============================================================

def enrich(row):
    volume = row["volume"]
    size = row["contract_size"]
    cap = row["qTotCap"]
    notional = row["notionalValue"]

    row["cap_per_volume"] = div(cap, volume)
    row["notional_per_volume"] = div(notional, volume)

    row["cap_per_volume_size"] = div(
        cap, volume * size
        if volume is not None and size is not None else None
    )
    row["notional_per_volume_size"] = div(
        notional, volume * size
        if volume is not None and size is not None else None
    )

    for field in ("last_price", "close_price", "yesterday_price"):
        price = row[field]

        row[f"cap_per_volume_vs_{field}"] = div(
            row["cap_per_volume"], price
        )
        row[f"notional_per_volume_vs_{field}"] = div(
            row["notional_per_volume"], price
        )
        row[f"cap_per_volume_size_vs_{field}"] = div(
            row["cap_per_volume_size"], price
        )
        row[f"notional_per_volume_size_vs_{field}"] = div(
            row["notional_per_volume_size"], price
        )

    row["cap_equals_price_volume"] = close(
        cap,
        row["last_price"] * volume
        if row["last_price"] is not None and volume is not None
        else None,
    )

    row["notional_equals_price_volume"] = close(
        notional,
        row["last_price"] * volume
        if row["last_price"] is not None and volume is not None
        else None,
    )

    row["valid_positive_volume"] = (
        volume is not None and volume > 0
    )

    row["zero_volume"] = volume == 0
    row["financial_fields_both_zero"] = (
        cap == 0 and notional == 0
    )

    return row


# ============================================================
# BR52.5 - Evaluate candidate multipliers
# ============================================================

def multiplier_summary(rows, numerator_key, price_key):
    """
    Test whether financial value / (volume * price)
    has a stable ratio. This is exploratory, not semantic proof.
    """
    ratios = []

    for row in rows:
        volume = row["volume"]
        price = row[price_key]
        value = row[numerator_key]

        denominator = (
            volume * price
            if volume is not None and price is not None
            else None
        )

        ratio = div(value, denominator)

        if ratio is not None and math.isfinite(ratio):
            ratios.append(ratio)

    return clean_stats(ratios)


def relation_report(rows):
    results = {}

    for side in ("CALL", "PUT", "ALL"):
        subset = [
            row for row in rows
            if side == "ALL" or row["side"] == side
        ]

        results[side] = {
            "contract_count": len(subset),
            "positive_volume_count": sum(
                row["valid_positive_volume"] for row in subset
            ),
            "zero_volume_count": sum(
                row["zero_volume"] for row in subset
            ),
            "qTotCap_per_volume": clean_stats(
                row["cap_per_volume"] for row in subset
            ),
            "notionalValue_per_volume": clean_stats(
                row["notional_per_volume"] for row in subset
            ),
            "qTotCap_per_volume_size": clean_stats(
                row["cap_per_volume_size"] for row in subset
            ),
            "notionalValue_per_volume_size": clean_stats(
                row["notional_per_volume_size"] for row in subset
            ),
            "notional_to_cap_ratio": clean_stats(
                div(row["notionalValue"], row["qTotCap"])
                for row in subset
            ),
            "qTotCap_multiplier_candidates": {},
            "notional_multiplier_candidates": {},
            "correlations": {},
        }

        for price_key in (
            "last_price", "close_price", "yesterday_price"
        ):
            results[side]["qTotCap_multiplier_candidates"][
                price_key
            ] = multiplier_summary(
                subset, "qTotCap", price_key
            )

            results[side]["notional_multiplier_candidates"][
                price_key
            ] = multiplier_summary(
                subset, "notionalValue", price_key
            )

        pairs_to_test = [
            ("qTotCap", "volume"),
            ("notionalValue", "volume"),
            ("qTotCap", "last_price"),
            ("notionalValue", "last_price"),
            ("qTotCap", "close_price"),
            ("notionalValue", "close_price"),
            ("qTotCap", "trade_count"),
            ("notionalValue", "trade_count"),
        ]

        for left, right in pairs_to_test:
            pairs = [
                (row[left], row[right])
                for row in subset
            ]

            results[side]["correlations"][
                f"{left} vs {right}"
            ] = {
                "n": sum(
                    x is not None and y is not None
                    for x, y in pairs
                ),
                "pearson": pearson(pairs),
                "spearman": spearman(pairs),
            }

    return results


# ============================================================
# BR52.6 - Detect stable ratio candidates
# ============================================================

def ratio_candidates(rows, side):
    subset = [
        row for row in rows
        if side == "ALL" or row["side"] == side
    ]

    candidates = []

    for target in ("qTotCap", "notionalValue"):
        for price_key in (
            "last_price", "close_price", "yesterday_price"
        ):
            ratios = []

            for row in subset:
                volume = row["volume"]
                price = row[price_key]
                value = row[target]
                denominator = (
                    volume * price
                    if volume is not None and price is not None
                    else None
                )
                ratio = div(value, denominator)

                if ratio is not None and ratio > 0:
                    ratios.append(ratio)

            if len(ratios) < 3:
                continue

            median = statistics.median(ratios)
            mean = statistics.mean(ratios)

            # Relative median absolute deviation.
            deviations = [
                abs(x - median) for x in ratios
            ]
            mad = statistics.median(deviations)
            relative_mad = div(mad, abs(median))

            candidates.append({
                "financial_field": target,
                "price_field": price_key,
                "n": len(ratios),
                "median_ratio": median,
                "mean_ratio": mean,
                "relative_median_absolute_deviation": relative_mad,
                "interpretation": (
                    "Exploratory ratio only; stability does not "
                    "prove an official formula."
                ),
            })

    return sorted(
        candidates,
        key=lambda item: (
            item["relative_median_absolute_deviation"]
            if item["relative_median_absolute_deviation"] is not None
            else float("inf")
        ),
    )


# ============================================================
# BR52.7 - Main
# ============================================================

def main():
    print("=" * 78)
    print("BR52 - IMPLIED PRICE AND FINANCIAL RATIO AUDIT")
    print("=" * 78)
    print(f"Input file: {INPUT_FILE}")
    print("Database access: NONE")
    print("Database changes: NONE")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(str(INPUT_FILE))

    records = load_api(INPUT_FILE)
    rows = extract(records)

    for row in rows:
        enrich(row)

    relations = relation_report(rows)

    candidates = {
        side: ratio_candidates(rows, side)
        for side in ("CALL", "PUT", "ALL")
    }

    zero_volume_rows = [
        {
            "side": row["side"],
            "symbol": row["symbol"],
            "volume": row["volume"],
            "trade_count": row["trade_count"],
            "qTotCap": row["qTotCap"],
            "notionalValue": row["notionalValue"],
            "open_interest": row["open_interest"],
            "last_price": row["last_price"],
            "close_price": row["close_price"],
        }
        for row in rows
        if row["volume"] == 0
    ]

    report = {
        "script": "BR52_audit_implied_prices.py",
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "input_file": str(INPUT_FILE),
        "database_access": False,
        "database_changes": False,
        "raw_api_record_count": len(records),
        "contract_count": len(rows),
        "call_count": sum(r["side"] == "CALL" for r in rows),
        "put_count": sum(r["side"] == "PUT" for r in rows),
        "relationship_summary": relations,
        "exploratory_ratio_candidates": candidates,
        "zero_volume_contracts": zero_volume_rows,
        "methodology": [
            "Ratios use only positive denominators.",
            "Pearson measures linear association.",
            "Spearman measures monotonic rank association.",
            "A stable ratio is not proof of official field semantics.",
            "One API snapshot cannot establish time-dependent formulas.",
        ],
    }

    # CSV contains one row per contract.
    with CSV_FILE.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        fields = sorted({
            key for row in rows for key in row
        })
        writer = csv.DictWriter(
            file, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    with JSON_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {"report": report, "contracts": rows},
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    print(f"\nRaw records: {len(records)}")
    print(f"Contracts: {len(rows)}")

    for side in ("CALL", "PUT", "ALL"):
        section = relations[side]
        print(f"\n[{side}]")
        print(
            "Positive volume:",
            section["positive_volume_count"],
        )
        print(
            "Zero volume:",
            section["zero_volume_count"],
        )
        print(
            "qTotCap / volume:",
            section["qTotCap_per_volume"],
        )
        print(
            "notionalValue / volume:",
            section["notionalValue_per_volume"],
        )
        print(
            "notionalValue / qTotCap:",
            section["notional_to_cap_ratio"],
        )

        print("\nCandidate multiplier ratios:")
        for target in (
            "qTotCap_multiplier_candidates",
            "notional_multiplier_candidates",
        ):
            for price_key, value in section[target].items():
                print(f"{target} / {price_key}: {value}")

        print("\nCorrelations:")
        for label, value in section["correlations"].items():
            print(f"{label}: {value}")

    print("\nMOST STABLE EXPLORATORY RATIOS")
    for side, items in candidates.items():
        print(f"\n[{side}]")
        for item in items:
            print(
                f"{item['financial_field']} / "
                f"(volume * {item['price_field']}): "
                f"n={item['n']}, "
                f"median={item['median_ratio']:.8g}, "
                f"relative_MAD="
                f"{item['relative_median_absolute_deviation']}"
            )

    print("\nZERO-VOLUME CONTRACTS")
    for row in zero_volume_rows:
        print(row)

    print("\nOUTPUT FILES")
    print(f"CSV : {CSV_FILE}")
    print(f"JSON: {JSON_FILE}")
    print("\nBR52 completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("BR52 FAILED")
        print(f"{type(exc).__name__}: {exc}")
        raise
