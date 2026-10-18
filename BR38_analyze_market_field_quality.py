
# BR38 - Analyze Live Market Field Quality
# Read-only analysis of the latest BR37 API response.
# No database connection and no database writes.

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import Counter

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
UNDERLYING_CODE = "17914401175772326"

FIELDS = [
    "pDrCotVal",       # Last traded price
    "pClosing",        # Closing price
    "priceYesterday",  # Previous-day price
    "pMeDem",          # Best buy price (semantics to verify)
    "pMeOf",           # Best sell price (semantics to verify)
    "qTitMeDem",       # Best-buy order quantity
    "qTitMeOf",        # Best-sell order quantity
    "zTotTran",        # Number of trades
    "qTotTran5J",      # Traded volume
    "qTotCap",         # Traded value
]

SIDES = ("C", "P")


def as_number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_latest_source():
    files = list(DATA_DIR.glob("BR37_live_response_*.json"))
    if not files:
        raise FileNotFoundError(
            f"No BR37 live response JSON found in: {DATA_DIR}"
        )
    return max(files, key=lambda p: p.stat().st_mtime)


def load_api_records(path):
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("instrumentOptMarketWatch")
        if records is None:
            # Support a wrapper object if the API response was saved with one.
            for value in payload.values():
                if isinstance(value, dict):
                    records = value.get("instrumentOptMarketWatch")
                    if records is not None:
                        break
    else:
        records = None

    if not isinstance(records, list):
        raise ValueError(
            "Could not find the API array 'instrumentOptMarketWatch'. "
            f"Root type: {type(payload).__name__}"
        )

    return records


def matches_underlying(record):
    # Handle the common API field name and case variations.
    for key in ("uaInsCode", "UAInsCode", "ua_ins_code"):
        value = record.get(key)
        if value is not None and str(value) == UNDERLYING_CODE:
            return True

    # Some saved/normalized files may carry the underlying code separately.
    for key in ("underlyingInsCode", "UnderlyingInsCode"):
        value = record.get(key)
        if value is not None and str(value) == UNDERLYING_CODE:
            return True

    return False


def extract_contracts(records):
    result = []
    for record_index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        if not matches_underlying(record):
            continue

        for side in SIDES:
            contract_id = record.get(f"insCode_{side}")
            if contract_id is None:
                continue

            item = {
                "source_record_index": record_index,
                "contract_id": str(contract_id),
                "option_type": "CALL" if side == "C" else "PUT",
            }

            for field in FIELDS:
                item[field] = record.get(f"{field}_{side}")

            result.append(item)

    return result


def classify(value):
    number = as_number(value)
    if value is None or value == "":
        return "missing"
    if number is None:
        return "non_numeric"
    if number == 0:
        return "zero"
    if number < 0:
        return "negative"
    return "positive"


def field_statistics(contracts):
    stats = {}
    for field in FIELDS:
        counts = Counter(classify(row.get(field)) for row in contracts)
        stats[field] = {
            "total": len(contracts),
            "missing": counts["missing"],
            "zero": counts["zero"],
            "positive": counts["positive"],
            "negative": counts["negative"],
            "non_numeric": counts["non_numeric"],
            "zero_percent": round(
                counts["zero"] * 100 / len(contracts), 2
            ) if contracts else 0,
        }
    return stats


def build_combinations(contracts):
    keys = [
        "pMeDem", "pMeOf", "qTitMeDem", "qTitMeOf",
        "zTotTran", "qTotTran5J", "qTotCap",
    ]
    combinations = Counter()

    for row in contracts:
        pattern = tuple(
            f"{key}={classify(row.get(key))}" for key in keys
        )
        combinations[pattern] += 1

    return [
        {
            "pattern": dict(part.split("=", 1) for part in pattern),
            "count": count,
        }
        for pattern, count in combinations.most_common()
    ]


def main():
    print("=" * 76)
    print("BR38 - Live Market Field Quality Analysis")
    print("=" * 76)

    source_path = find_latest_source()
    print(f"Source file: {source_path}")

    all_records = load_api_records(source_path)
    contracts = extract_contracts(all_records)

    if not contracts:
        print("\nERROR: No contracts matched the configured underlying code.")
        print(f"Underlying code: {UNDERLYING_CODE}")
        print("Check the raw JSON field names before proceeding.")
        sys.exit(2)

    unique_ids = {row["contract_id"] for row in contracts}
    type_counts = Counter(row["option_type"] for row in contracts)
    stats = field_statistics(contracts)
    combinations = build_combinations(contracts)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = DATA_DIR / f"BR38_field_quality_{timestamp}.txt"
    json_path = DATA_DIR / f"BR38_field_quality_{timestamp}.json"

    lines = []
    lines.append("=" * 76)
    lines.append("BR38 - LIVE MARKET FIELD QUALITY REPORT")
    lines.append("=" * 76)
    lines.append(f"Source file          : {source_path}")
    lines.append(f"Underlying code      : {UNDERLYING_CODE}")
    lines.append(f"Total API records    : {len(all_records)}")
    lines.append(f"Normalized contracts : {len(contracts)}")
    lines.append(f"Unique contract IDs  : {len(unique_ids)}")
    lines.append(f"CALL contracts       : {type_counts['CALL']}")
    lines.append(f"PUT contracts        : {type_counts['PUT']}")
    lines.append("")
    lines.append("FIELD STATISTICS")
    lines.append("-" * 76)
    lines.append(
        f"{'Field':<18} {'Missing':>8} {'Zero':>8} "
        f"{'Positive':>10} {'Negative':>10} {'Zero %':>9}"
    )

    for field, values in stats.items():
        lines.append(
            f"{field:<18} {values['missing']:>8} "
            f"{values['zero']:>8} {values['positive']:>10} "
            f"{values['negative']:>10} {values['zero_percent']:>8.2f}%"
        )

    lines.append("")
    lines.append("MOST COMMON QUOTATION / TRADE FIELD PATTERNS")
    lines.append("-" * 76)

    for entry in combinations[:15]:
        pattern = entry["pattern"]
        description = ", ".join(
            f"{key}:{value}" for key, value in pattern.items()
        )
        lines.append(f"{entry['count']:>4} contracts | {description}")

    lines.append("")
    lines.append("CONTRACT EXAMPLES")
    lines.append("-" * 76)

    # Show a representative sample, prioritizing contracts with any
    # non-positive or missing quotation/trade field.
    important_fields = [
        "pMeDem", "pMeOf", "qTitMeDem", "qTitMeOf",
        "zTotTran", "qTotTran5J", "qTotCap",
    ]

    sample = sorted(
        contracts,
        key=lambda row: (
            sum(
                classify(row.get(field)) in ("zero", "missing", "negative")
                for field in important_fields
            ),
            row["option_type"],
            row["contract_id"],
        ),
        reverse=True,
    )[:20]

    for row in sample:
        values = " | ".join(
            f"{field}={row.get(field)!r}" for field in FIELDS
        )
        lines.append(
            f"{row['option_type']} | ID={row['contract_id']} | {values}"
        )

    lines.append("")
    lines.append("INTERPRETATION NOTES")
    lines.append("-" * 76)
    lines.append(
        "- This report classifies values as returned by the API; it does "
        "not change or replace any raw value."
    )
    lines.append(
        "- A zero value is not automatically considered missing or invalid."
    )
    lines.append(
        "- Field names and market semantics must be confirmed before using "
        "these values in analytics."
    )
    lines.append(
        "- No database connection was opened and no database was modified."
    )

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")

    output = {
        "source_file": str(source_path),
        "underlying_code": UNDERLYING_CODE,
        "total_api_records": len(all_records),
        "normalized_contracts": len(contracts),
        "unique_contract_ids": len(unique_ids),
        "contract_type_counts": dict(type_counts),
        "field_statistics": stats,
        "common_patterns": combinations,
        "sample_contracts": sample,
        "interpretation_notes": [
            "Values are classified as returned by the API.",
            "Zero is not automatically treated as missing.",
            "Field semantics require confirmation before analytics.",
            "No database connection or database writes were performed.",
        ],
    }
    json_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("")
    print(report_text)
    print(f"Text report: {report_path}")
    print(f"JSON report: {json_path}")
    print("Database writes: NONE")
    print("BR38 completed.")
    print("=" * 76)


if __name__ == "__main__":
    main()
