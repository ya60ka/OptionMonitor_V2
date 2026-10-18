
# BR72 - API to Daily History Field Mapping Audit
# Read-only audit. No database writes or schema changes.
# Target database: OptionMarketDB_V2 only.

from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import json
import pyodbc

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_CODE = "17914401175772326"
EXPECTED_CONTRACTS = 84

# Candidate database fields that may be populated from live API data.
DB_FIELDS = [
    "LastPrice",
    "ClosingPrice",
    "FirstPrice",
    "MinPrice",
    "MaxPrice",
    "YesterdayPrice",
    "PriceChange",
    "PriceChangePercent",
    "TradeCount",
    "Volume",
    "TradeValue",
    "BestBuyPrice",
    "BestBuyVolume",
    "BestSellPrice",
    "BestSellVolume",
    "OpenInterest",
    "UnderlyingLastPrice",
    "UnderlyingClosePrice",
    "ContractSize",
]

PRICE_FIELD_CANDIDATES = {
    "LastPrice": [
        "pDrCotVal",
        "pClosing",
        "pFirst",
        "pMin",
        "pMax",
        "priceYesterday",
    ],
    "ClosingPrice": ["pClosing"],
    "FirstPrice": ["pFirst"],
    "MinPrice": ["pMin"],
    "MaxPrice": ["pMax"],
    "YesterdayPrice": ["priceYesterday"],
    "PriceChange": ["priceChange"],
    "PriceChangePercent": ["priceChangePercent"],
    "TradeCount": ["qTotTran"],
    "Volume": ["qTotCap"],
    "TradeValue": ["qTotVal"],
    "BestBuyPrice": ["pMeDem"],
    "BestBuyVolume": ["qTitMeDem"],
    "BestSellPrice": ["pMeOf"],
    "BestSellVolume": ["qTitMeOf"],
    "OpenInterest": ["openInterest", "qOIB"],
}


def heading(title):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)


def norm(value):
    return "" if value is None else str(value).strip()


def number(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        result = float(str(value).replace(",", "").strip())
        return result
    except (ValueError, TypeError):
        return None


def equivalent(a, b):
    na = number(a)
    nb = number(b)

    if na is None or nb is None:
        return False

    return abs(na - nb) <= max(0.0001, abs(nb) * 0.000001)


def main():
    connection = None

    print("=" * 110)
    print("BR72 - API TO DAILY HISTORY FIELD MAPPING AUDIT")
    print("=" * 110)
    print(f"Database        : {DATABASE}")
    print("Mode            : READ ONLY")
    print("Writes          : NONE")
    print("Schema changes  : NONE")
    print("Legacy DB       : NOT ACCESSED")

    try:
        # ----------------------------------------------------------
        # 1. Load latest BR44 response
        # ----------------------------------------------------------
        heading("1. SOURCE RESPONSE")

        files = sorted(
            DATA_DIR.glob("BR44_live_response_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not files:
            raise FileNotFoundError(
                f"No BR44 response JSON found in {DATA_DIR}"
            )

        source_file = files[0]
        payload = json.loads(source_file.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            raise ValueError("API response root is not an object.")

        rows = payload.get("instrumentOptMarketWatch")

        if not isinstance(rows, list):
            raise ValueError(
                "instrumentOptMarketWatch array not found."
            )

        mtime = datetime.fromtimestamp(
            source_file.stat().st_mtime,
            timezone.utc,
        )

        age_hours = (
            datetime.now(timezone.utc) - mtime
        ).total_seconds() / 3600

        print(f"File             : {source_file}")
        print(f"File modified UTC: {mtime.isoformat()}")
        print(f"File age hours   : {age_hours:.2f}")
        print(f"API array rows   : {len(rows)}")

        source_rows = [
            row for row in rows
            if isinstance(row, dict)
            and norm(row.get("uaInsCode")) == UNDERLYING_CODE
            and (
                norm(row.get("insCode_C"))
                or norm(row.get("insCode_P"))
            )
        ]

        source_ids = set()

        for row in source_rows:
            for side in ("C", "P"):
                code = norm(row.get(f"insCode_{side}"))
                if code:
                    source_ids.add(code)

        print(f"Underlying rows  : {len(source_rows)}")
        print(f"Unique contract IDs: {len(source_ids)}")

        if len(source_ids) != EXPECTED_CONTRACTS:
            print(
                "WARNING: source contract count differs from "
                f"expected {EXPECTED_CONTRACTS}."
            )

        # ----------------------------------------------------------
        # 2. Connect to V2 database, read-only queries only
        # ----------------------------------------------------------
        heading("2. DATABASE CONNECTION AND CURRENT DATA")

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
        actual_db = cursor.fetchone()[0]

        if actual_db != DATABASE:
            raise RuntimeError(
                f"Safety check failed: connected to {actual_db}"
            )

        cursor.execute("""
            SELECT
                oc.OptionID,
                oc.TSEInsCode,
                lc.LastPrice,
                lc.ClosingPrice,
                lc.FirstPrice,
                lc.MinPrice,
                lc.MaxPrice,
                lc.YesterdayPrice,
                lc.PriceChange,
                lc.PriceChangePercent,
                lc.TradeCount,
                lc.Volume,
                lc.TradeValue,
                lc.BestBuyPrice,
                lc.BestBuyVolume,
                lc.BestSellPrice,
                lc.BestSellVolume,
                lc.OpenInterest,
                lc.UnderlyingLastPrice,
                lc.UnderlyingClosePrice,
                lc.ContractSize,
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

        print(f"DB contracts     : {len(db_rows)}")
        print(f"DB contracts with current rows: "
              f"{sum(1 for r in db_rows if r.SourceRetrievedAt is not None)}")

        matched_ids = source_ids.intersection(db_by_code)
        print(f"Source/DB ID overlap: {len(matched_ids)}")

        # ----------------------------------------------------------
        # 3. Identify API field names for each side
        # ----------------------------------------------------------
        heading("3. API FIELD INVENTORY")

        all_keys = set()
        for row in source_rows:
            all_keys.update(row.keys())

        for side in ("C", "P"):
            suffix_keys = sorted(
                key for key in all_keys
                if key.endswith("_" + side)
            )

            print()
            print(f"Fields ending _{side}: {len(suffix_keys)}")

            for key in suffix_keys:
                sample = next(
                    (
                        row.get(key)
                        for row in source_rows
                        if row.get(key) is not None
                    ),
                    None,
                )
                print(f"  {key:<32} sample={sample!r}")

        print()
        print("Underlying-related fields:")
        for key in sorted(all_keys):
            if key.endswith("_UA"):
                sample = next(
                    (
                        row.get(key)
                        for row in source_rows
                        if row.get(key) is not None
                    ),
                    None,
                )
                print(f"  {key:<32} sample={sample!r}")

        # ----------------------------------------------------------
        # 4. Compare API candidates against current database values
        # ----------------------------------------------------------
        heading("4. FIELD-TO-COLUMN VALUE MATCH AUDIT")

        # Map candidate API keys to database columns.
        results = []

        for side in ("C", "P"):
            side_pairs = []

            for row in source_rows:
                code = norm(row.get(f"insCode_{side}"))

                if not code or code not in db_by_code:
                    continue

                db_row = db_by_code[code]

                for db_field in DB_FIELDS:
                    db_value = getattr(db_row, db_field, None)

                    if db_value is None:
                        continue

                    candidates = PRICE_FIELD_CANDIDATES.get(
                        db_field, []
                    )

                    for prefix in candidates:
                        api_key = f"{prefix}_{side}"

                        if api_key not in row:
                            continue

                        api_value = row.get(api_key)

                        if number(api_value) is None:
                            continue

                        side_pairs.append(
                            (
                                db_field,
                                api_key,
                                equivalent(api_value, db_value),
                                api_value,
                                db_value,
                            )
                        )

            grouped = defaultdict(list)

            for item in side_pairs:
                grouped[(item[0], item[1])].append(item)

            print()
            print(f"Side {side}:")

            if not grouped:
                print("  No comparable candidate fields found.")
                continue

            ranked = []

            for (db_field, api_key), items in grouped.items():
                comparisons = len(items)
                matches = sum(1 for item in items if item[2])
                rate = matches / comparisons if comparisons else 0

                ranked.append(
                    (
                        rate,
                        matches,
                        comparisons,
                        db_field,
                        api_key,
                        items[0][3],
                        items[0][4],
                    )
                )

            ranked.sort(
                key=lambda x: (x[0], x[1], x[2]),
                reverse=True,
            )

            for (
                rate,
                matches,
                comparisons,
                db_field,
                api_key,
                sample_api,
                sample_db,
            ) in ranked:
                print(
                    f"  DB.{db_field:<22} <- {api_key:<28} "
                    f"matches={matches}/{comparisons} "
                    f"rate={rate:.1%} "
                    f"sample_API={sample_api!r} "
                    f"sample_DB={sample_db!r}"
                )

        # ----------------------------------------------------------
        # 5. Underlying candidate field values
        # ----------------------------------------------------------
        heading("5. UNDERLYING FIELD SAMPLES")

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

        underlying_db = cursor.fetchone()

        if underlying_db is None:
            print("No UnderlyingLiveCurrent row found.")
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
                print(f"DB.{field:<24}: {getattr(underlying_db, field)}")

        for field in (
            "pDrCotVal_UA",
            "pClosing_UA",
            "priceYesterday_UA",
            "priceChange_UA",
            "priceChangePercent_UA",
            "qTotTran5J_UA",
            "qTotCap_UA",
            "qTotVal_UA",
        ):
            values = [
                row.get(field)
                for row in source_rows
                if row.get(field) is not None
            ]

            if values:
                print(
                    f"API.{field:<24}: "
                    f"sample={values[0]!r}, "
                    f"distinct={len(set(map(str, values)))}"
                )

        # ----------------------------------------------------------
        # 6. Daily-history readiness checks
        # ----------------------------------------------------------
        heading("6. DAILY HISTORY READINESS")

        cursor.execute("""
            SELECT COUNT_BIG(*)
            FROM dbo.OptionDailyHistory
        """)
        option_history_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT_BIG(*)
            FROM dbo.UnderlyingDailyHistory
        """)
        underlying_history_count = cursor.fetchone()[0]

        print(f"OptionDailyHistory rows    : {option_history_count}")
        print(f"UnderlyingDailyHistory rows: {underlying_history_count}")
        print("Source timestamp is file modification time, not API receipt time.")
        print("BR72 does not write history or modify any records.")

        heading("7. FINAL STATUS")
        print("API field inventory : COMPLETED")
        print("Candidate mapping   : REPORTED")
        print("Database writes     : NONE")
        print("Schema changes      : NONE")
        print("Legacy DB accessed  : NO")
        print("END OF BR72")

    except Exception as exc:
        print()
        print("BR72 FAILED")
        print(f"{type(exc).__name__}: {exc}")
        print("No database writes were issued.")
        raise

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
