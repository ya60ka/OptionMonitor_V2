
# BR24 - اصلاح نوع قراردادهای اختیار معامله اهرم
# فایل JSON تولیدشده توسط BR23 را می‌خواند، نوع CALL/PUT را
# با استفاده از کلیدهای واقعی source_fields و نام قرارداد اصلاح می‌کند
# و گزارش و JSON جدید می‌سازد. هیچ API یا دیتابیسی استفاده نمی‌شود.

import json
from pathlib import Path
from datetime import datetime
from collections import Counter


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data" / "api_tests"
INPUT_PATTERN = "BR23_contracts_*.json"
UNDERLYING_CODE = "17914401175772326"


def detect_contract_type(record):
    """تشخیص نوع قرارداد بر اساس ساختار واقعی داده منبع."""

    source_fields = record.get("source_fields") or {}
    contract = record.get("contract") or {}

    # روش اصلی: شناسه قرارداد در داده منبع
    has_put_id = bool(source_fields.get("insCode_P"))
    has_call_id = bool(source_fields.get("insCode_C"))

    if has_put_id and not has_call_id:
        return "PUT", "source_fields.insCode_P"

    if has_call_id and not has_put_id:
        return "CALL", "source_fields.insCode_C"

    # روش پشتیبان: نام کامل قرارداد
    full_name = str(contract.get("full_name") or "").strip()

    if "اختیارف" in full_name:
        return "PUT", "contract.full_name"

    if "اختیارخ" in full_name:
        return "CALL", "contract.full_name"

    # روش پشتیبان دوم: نام فیلدهای منبع
    put_name = str(source_fields.get("lVal30_P") or "").strip()
    call_name = str(source_fields.get("lVal30_C") or "").strip()

    if put_name and not call_name:
        return "PUT", "source_fields.lVal30_P"

    if call_name and not put_name:
        return "CALL", "source_fields.lVal30_C"

    return "UNKNOWN", "insufficient_or_conflicting_data"


def main():
    print("=" * 70)
    print("BR24 - Fix Option Contract Types")
    print("=" * 70)
    print(f"Project directory : {PROJECT_DIR}")
    print(f"Data directory    : {DATA_DIR}")
    print(f"Underlying code   : {UNDERLYING_CODE}")
    print("API request       : NO")
    print("Database          : NOT USED")
    print("-" * 70)

    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"Data directory not found: {DATA_DIR}"
        )

    input_files = sorted(
        DATA_DIR.glob(INPUT_PATTERN),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not input_files:
        raise FileNotFoundError(
            f"No input file found: {DATA_DIR / INPUT_PATTERN}"
        )

    input_file = input_files[0]
    print(f"Input file        : {input_file}")

    with input_file.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(
            "Unexpected JSON structure: root must be a list."
        )

    total_records = len(data)
    counts = Counter()
    methods = Counter()
    unknown_samples = []
    missing_ids = 0
    contract_ids = []

    for record in data:
        if not isinstance(record, dict):
            counts["INVALID_RECORD"] += 1
            continue

        contract = record.get("contract")

        if not isinstance(contract, dict):
            contract = {}
            record["contract"] = contract

        # فقط رکوردهای مربوط به اهرم پردازش شوند.
        underlying = record.get("underlying") or {}
        underlying_code = str(
            underlying.get("ins_code") or ""
        )

        if underlying_code != UNDERLYING_CODE:
            counts["OTHER_UNDERLYING"] += 1
            continue

        contract_type, method = detect_contract_type(record)

        # فقط فیلد type اصلاح می‌شود؛ سایر داده‌ها حفظ می‌شوند.
        contract["type"] = contract_type

        counts[contract_type] += 1
        methods[method] += 1

        contract_id = str(contract.get("ins_code") or "").strip()

        if contract_id:
            contract_ids.append(contract_id)
        else:
            missing_ids += 1

        if contract_type == "UNKNOWN" and len(unknown_samples) < 10:
            unknown_samples.append({
                "source_record_index": record.get(
                    "source_record_index"
                ),
                "contract": {
                    "ins_code": contract.get("ins_code"),
                    "short_name": contract.get("short_name"),
                    "full_name": contract.get("full_name"),
                    "type": contract_type,
                },
                "source_fields_keys": sorted(
                    (record.get("source_fields") or {}).keys()
                ),
            })

    duplicate_count = sum(
        count - 1
        for count in Counter(contract_ids).values()
        if count > 1
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_json = DATA_DIR / f"BR24_contracts_{timestamp}.json"
    output_report = DATA_DIR / f"BR24_report_{timestamp}.txt"

    with output_json.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    report_lines = [
        "BR24 CONTRACT TYPE CORRECTION REPORT",
        "=" * 70,
        f"Source file: {input_file}",
        f"Total JSON records: {total_records}",
        f"Underlying code: {UNDERLYING_CODE}",
        "",
        "CONTRACT TYPE COUNTS",
        "-" * 70,
        f"CALL: {counts['CALL']}",
        f"PUT: {counts['PUT']}",
        f"UNKNOWN: {counts['UNKNOWN']}",
        f"Invalid records: {counts['INVALID_RECORD']}",
        f"Other underlying records: {counts['OTHER_UNDERLYING']}",
        "",
        "DETECTION METHODS",
        "-" * 70,
    ]

    for method, count in sorted(methods.items()):
        report_lines.append(f"{method}: {count}")

    report_lines.extend([
        "",
        "DATA QUALITY",
        "-" * 70,
        f"Records missing contract ID: {missing_ids}",
        f"Duplicate non-empty contract IDs: {duplicate_count}",
        "",
        "UNKNOWN SAMPLES",
        "-" * 70,
        json.dumps(
            unknown_samples,
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "OUTPUT",
        "-" * 70,
        f"Contracts JSON: {output_json}",
        f"Report: {output_report}",
        "API requested: NO",
        "Database accessed: NO",
        f"Source JSON modified: NO",
        "",
        "RESULT: " + (
            "SUCCESS"
            if counts["UNKNOWN"] == 0
            and counts["INVALID_RECORD"] == 0
            else "REVIEW REQUIRED"
        ),
    ])

    report_text = "\n".join(report_lines)

    with output_report.open("w", encoding="utf-8") as file:
        file.write(report_text)

    print(f"Total records     : {total_records}")
    print(f"CALL records      : {counts['CALL']}")
    print(f"PUT records       : {counts['PUT']}")
    print(f"UNKNOWN types     : {counts['UNKNOWN']}")
    print(f"Missing IDs       : {missing_ids}")
    print(f"Duplicate IDs     : {duplicate_count}")

    print("\nDetection methods:")
    for method, count in sorted(methods.items()):
        print(f"  {method}: {count}")

    print("-" * 70)
    print(f"Contracts JSON    : {output_json}")
    print(f"Report            : {output_report}")
    print("API request       : NO")
    print("Database          : NOT USED")
    print("Source JSON       : NOT MODIFIED")
    print(
        "RESULT            : "
        + (
            "SUCCESS"
            if counts["UNKNOWN"] == 0
            and counts["INVALID_RECORD"] == 0
            else "REVIEW REQUIRED"
        )
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
