
# BR73 - Trade Metrics Mapping Audit
# Read-only comparison of API trade metrics against OptionLiveCurrent.
# No database writes or schema changes.
# OptionMarketDB_V2 only.

from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import json
import pyodbc

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"
UNDERLYING_CODE = "17914401175772326"


def heading(title):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)


def norm(value):
    return "" if value is None else str(value).strip()


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def equal_numeric(a, b):
    na = numeric(a)
    nb = numeric(b)

    if na is None or nb is None:
        return False

    return abs(na - nb) <= max(0.0001, abs(nb) * 0.000001)


def main():
    connection = None

    print("=" * 110)
    print("BR73 - TRADE METRICS MAPPING AUDIT")
    print("=" * 110)
    print(f"Database       : {DATABASE}")
    print("Mode           : READ ONLY")
    print("Writes         : NONE")
    print("Schema changes : NONE")
    print("Legacy DB      : NOT ACCESSED")

    try:
        # ----------------------------------------------------------
        # 1. Read the latest BR44 response
        # ----------------------------------------------------------
        heading("1. SOURCE FILE")

        files = sorted(
            DATA_DIR.glob("BR44_live_response_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not files:
            raise FileNotFoundError(
                f"No BR44 response found in {DATA_DIR}"
            )

        source_file = files[0]
        payload = json.loads(
            source_file.read_text(encoding="utf-8")
        )

        rows = payload.get("instrumentOptMarketWatch")

        if not isinstance(rows, list):
            raise ValueError(
                "instrumentOptMarketWatch array not found."
            )

        file_time = datetime.fromtimestamp(
            source_file.stat().st_mtime,
            timezone.utc,
        )

        print(f"File       : {source_file}")
        print(f"Modified   : {file_time.isoformat()}")
        print(f"Array rows : {len(rows)}")

        source_rows = [
            row for row in rows
            if isinstance(row, dict)
            and norm(row.get("uaInsCode")) == UNDERLYING_CODE
            and (
                norm(row.get("insCode_C"))
                or norm(row.get("insCode_P"))
            )
        ]

        print(f"Underlying rows: {len(source_rows)}")

        # ----------------------------------------------------------
        # 2. Connect to the intended database
        # ----------------------------------------------------------
        heading("2. DATABASE CONNECTION")

        connection_string = (
            f"DRIVER={{{DRIVER}}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=15;"
        )

        connection = pyodbc.connect(
            connection_string,
            autocommit=True,
            timeout=15,
        )
        cursor = connection.cursor()

        cursor.execute("SELECT DB_NAME()")
        actual_database = cursor.fetchone()[0]

        if actual_database != DATABASE:
            raise RuntimeError(
                f"Safety check failed: connected to {actual_database}"
            )

        cursor.execute("""
            SELECT
                oc.OptionID,
                oc.TSEInsCode,
                lc.LastPrice,
                lc.ClosingPrice,
                lc.YesterdayPrice,
                lc.TradeCount,
                lc.Volume,
                lc.TradeValue,
                lc.SourceRetrievedAt
            FROM dbo.OptionContract AS oc
            LEFT JOIN dbo.OptionLiveCurrent AS lc
                ON lc.OptionID = oc.OptionID
            WHERE oc.UnderlyingID = (
                SELECT UnderlyingID
                FROM dbo.Underlying
                WHERE TSEInsCode = ?
            )
        """, UNDERLYING_CODE)

        db_rows = cursor.fetchall()

        db_by_code = {
            norm(row.TSEInsCode): row
            for row in db_rows
            if norm(row.TSEInsCode)
        }

        print(f"DB contract rows: {len(db_rows)}")
        print(f"Unique DB codes : {len(db_by_code)}")

        # ----------------------------------------------------------
        # 3. Compare candidate fields
        # ----------------------------------------------------------
        heading("3. API CANDIDATE METRICS VS DATABASE")

        candidates = {
            "TradeCount": [
                "zTotTran",
                "qTotTran5J",
            ],
            "Volume": [
                "qTotCap",
            ],
            "TradeValue": [
                "notionalValue",
            ],
        }

        for db_field, prefixes in candidates.items():
            print()
            print(f"Database field: {db_field}")

            for prefix in prefixes:
                comparisons = 0
                matches = 0
                missing_api = 0
                missing_db = 0
                api_values = []
                db_values = []
                sample = None

                for row in source_rows:
                    for side in ("C", "P"):
                        code = norm(row.get(f"insCode_{side}"))

                        if not code or code not in db_by_code:
                            continue

                        db_row = db_by_code[code]
                        api_key = f"{prefix}_{side}"
                        api_value = row.get(api_key)
                        db_value = getattr(db_row, db_field, None)

                        if api_value is None:
                            missing_api += 1
                            continue

                        if db_value is None:
                            missing_db += 1
                            continue

                        api_num = numeric(api_value)
                        db_num = numeric(db_value)

                        if api_num is None or db_num is None:
                            continue

                        comparisons += 1
                        api_values.append(api_num)
                        db_values.append(db_num)

                        if equal_numeric(api_value, db_value):
                            matches += 1

                        if sample is None:
                            sample = (
                                code,
                                api_key,
                                api_value,
                                db_value,
                            )

                rate = (
                    matches / comparisons
                    if comparisons else 0
                )

                print(
                    f"  API field       : {prefix}_C/P"
                )
                print(
                    f"  Comparisons     : {comparisons}"
                )
                print(
                    f"  Exact matches   : {matches}"
                )
                print(
                    f"  Match rate      : {rate:.1%}"
                )
                print(
                    f"  Missing API     : {missing_api}"
                )
                print(
                    f"  Missing DB      : {missing_db}"
                )

                if api_values:
                    print(
                        f"  API min/max     : "
                        f"{min(api_values):g} / {max(api_values):g}"
                    )

                if db_values:
                    print(
                        f"  DB min/max      : "
                        f"{min(db_values):g} / {max(db_values):g}"
                    )

                if sample:
                    code, api_key, api_value, db_value = sample
                    print(
                        f"  Sample          : ID={code} | "
                        f"{api_key}={api_value!r} | "
                        f"DB={db_value!r}"
                    )

        # ----------------------------------------------------------
        # 4. Source distribution and null checks
        # ----------------------------------------------------------
        heading("4. API FIELD DISTRIBUTION")

        fields = [
            "zTotTran_C",
            "zTotTran_P",
            "qTotTran5J_C",
            "qTotTran5J_P",
            "qTotCap_C",
            "qTotCap_P",
            "notionalValue_C",
            "notionalValue_P",
        ]

        for field in fields:
            values = [
                row.get(field)
                for row in source_rows
                if row.get(field) is not None
            ]

            distinct = Counter(str(value) for value in values)

            print()
            print(f"{field}:")
            print(f"  Non-null count : {len(values)}")
            print(f"  Distinct count : {len(distinct)}")

            if values:
                nums = [
                    numeric(value)
                    for value in values
                ]
                nums = [value for value in nums if value is not None]

                if nums:
                    print(f"  Min            : {min(nums):g}")
                    print(f"  Max            : {max(nums):g}")
                    print(f"  Sum            : {sum(nums):g}")

                print(
                    "  Common values  : "
                    + ", ".join(
                        f"{value} ({count})"
                        for value, count in distinct.most_common(5)
                    )
                )

        # ----------------------------------------------------------
        # 5. Underlying history source coverage
        # ----------------------------------------------------------
        heading("5. UNDERLYING METRICS")

        cursor.execute("""
            SELECT
                LastPrice,
                ClosingPrice,
                YesterdayPrice,
                PriceChange,
                PriceChangePercent,
                TradeCount,
                Volume,
                TradeValue,
                SourceRetrievedAt
            FROM dbo.UnderlyingLiveCurrent
            WHERE UnderlyingID = (
                SELECT UnderlyingID
                FROM dbo.Underlying
                WHERE TSEInsCode = ?
            )
        """, UNDERLYING_CODE)

        underlying = cursor.fetchone()

        if underlying is None:
            print("UnderlyingLiveCurrent row not found.")
        else:
            for field in (
                "LastPrice",
                "ClosingPrice",
                "YesterdayPrice",
                "PriceChange",
                "PriceChangePercent",
                "TradeCount",
                "Volume",
                "TradeValue",
                "SourceRetrievedAt",
            ):
                print(
                    f"DB.{field:<24}: "
                    f"{getattr(underlying, field)}"
                )

            last_price = numeric(underlying.LastPrice)
            yesterday = numeric(underlying.YesterdayPrice)

            if last_price is not None and yesterday not in (None, 0):
                change = last_price - yesterday
                percent = change / yesterday * 100

                print(f"Calculated price change : {change:g}")
                print(f"Calculated change percent: {percent:.6f}%")

        heading("6. FINAL STATUS")
        print("Candidate comparison : COMPLETED")
        print("No mapping decisions were written to the database.")
        print("Database writes      : NONE")
        print("Schema changes       : NONE")
        print("Legacy DB accessed   : NO")
        print("END OF BR73")

    except Exception as exc:
        print()
        print("BR73 FAILED")
        print(f"{type(exc).__name__}: {exc}")
        print("No database writes were issued.")
        raise

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
