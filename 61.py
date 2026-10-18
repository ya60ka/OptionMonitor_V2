
# BR61 - Trade Value and Financial Consistency Audit
# READ ONLY - No database writes

import json
import pyodbc
from decimal import Decimal, InvalidOperation
from collections import Counter
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DB_NAME = "OptionMarketDB_V2"
SERVER = "localhost"
DRIVER = "{ODBC Driver 17 for SQL Server}"

TOLERANCE = Decimal("0.01")
PRICE_TOLERANCE = Decimal("1.00")
SCALE_FACTOR = Decimal("1000")

CONN_STR = (
    f"DRIVER={DRIVER};"
    f"SERVER={SERVER};"
    f"DATABASE={DB_NAME};"
    "Trusted_Connection=yes;"
    "ApplicationIntent=ReadOnly;"
)


def dec(value):
    """Convert a value to Decimal, returning None if invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            return None
        return result
    except (InvalidOperation, ValueError, TypeError):
        return None


def fmt(value, places=4):
    if value is None:
        return "N/A"
    return f"{value:,.{places}f}"


def find_api_array(obj):
    """Find instrumentOptMarketWatch recursively."""
    if isinstance(obj, dict):
        value = obj.get("instrumentOptMarketWatch")
        if isinstance(value, list):
            return value
        for child in obj.values():
            found = find_api_array(child)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for child in obj:
            found = find_api_array(child)
            if found is not None:
                return found
    return None


def get_api_side(record, side):
    """Extract the fields for one option side: C or P."""
    code = record.get(f"insCode_{side}")
    if code is None:
        return None

    return {
        "InsCode": str(code).strip(),
        "qTotCap": dec(record.get(f"qTotCap_{side}")),
        "Volume": dec(record.get(f"qTotTran5J_{side}")),
        "ClosingPrice": dec(record.get(f"pClosing_{side}")),
        "LastPrice": dec(record.get(f"pDrCotVal_{side}")),
        "OpenInterest": dec(record.get(f"oP_{side}")),
    }


def main():
    print("=" * 78)
    print("BR61 - TRADE VALUE AND FINANCIAL CONSISTENCY AUDIT")
    print("=" * 78)
    print(f"Server          : {SERVER}")
    print(f"Database        : {DB_NAME}")
    print("Mode            : READ ONLY")
    print("Database writes : NONE")
    print()

    conn = pyodbc.connect(CONN_STR, timeout=15)
    conn.timeout = 30

    try:
        cur = conn.cursor()

        # Safety: verify the actual database.
        cur.execute("SELECT DB_NAME()")
        actual_db = cur.fetchone()[0]
        if actual_db != DB_NAME:
            raise RuntimeError(
                f"Wrong database selected: {actual_db!r}; "
                f"expected {DB_NAME!r}"
            )

        # Select the newest successful response containing the API array.
        cur.execute("""
            SELECT TOP (20)
                RawDataID,
                CollectionRunID,
                RetrievedAt,
                APIName,
                HttpStatusCode,
                IsSuccess,
                ResponseJSON
            FROM dbo.RawApiResponse
            WHERE IsSuccess = 1
              AND ResponseJSON IS NOT NULL
            ORDER BY RetrievedAt DESC, RawDataID DESC
        """)

        raw_row = None
        api_records = None

        for row in cur.fetchall():
            try:
                payload = json.loads(row.ResponseJSON)
            except (json.JSONDecodeError, TypeError):
                continue

            found = find_api_array(payload)
            if found is not None:
                raw_row = row
                api_records = found
                break

        if raw_row is None:
            raise RuntimeError(
                "No successful RawApiResponse containing "
                "instrumentOptMarketWatch was found."
            )

        raw_id = raw_row.RawDataID
        retrieved_at = raw_row.RetrievedAt

        print("SELECTED RAW RESPONSE")
        print("-" * 78)
        print(f"RawDataID       : {raw_id}")
        print(f"CollectionRunID : {raw_row.CollectionRunID}")
        print(f"RetrievedAt     : {retrieved_at}")
        print(f"APIName         : {raw_row.APIName}")
        print(f"HTTP status     : {raw_row.HttpStatusCode}")
        print(f"API array items : {len(api_records)}")
        print()

        # Load database rows from the exact matching snapshot time.
        cur.execute("""
            SELECT
                o.OptionID,
                o.TSEInsCode,
                o.Symbol,
                o.OptionType,
                s.DataDate,
                s.DataTime,
                s.SourceRetrievedAt,
                s.TradeValue,
                s.Volume,
                s.ClosingPrice,
                s.LastPrice
            FROM dbo.OptionContract AS o
            INNER JOIN dbo.OptionLiveSnapshot AS s
                ON s.OptionID = o.OptionID
            WHERE s.SourceRetrievedAt = ?
            ORDER BY o.OptionID
        """, retrieved_at)

        db_rows = cur.fetchall()

        # Fallback only if the schema's source timestamp does not match.
        # Use the latest snapshot per contract and clearly flag the mode.
        snapshot_mode = "EXACT_SOURCE_TIMESTAMP"

        if not db_rows:
            snapshot_mode = "LATEST_SNAPSHOT_FALLBACK"
            cur.execute("""
                WITH Ranked AS (
                    SELECT
                        o.OptionID,
                        o.TSEInsCode,
                        o.Symbol,
                        o.OptionType,
                        s.DataDate,
                        s.DataTime,
                        s.SourceRetrievedAt,
                        s.TradeValue,
                        s.Volume,
                        s.ClosingPrice,
                        s.LastPrice,
                        ROW_NUMBER() OVER (
                            PARTITION BY o.OptionID
                            ORDER BY s.SourceRetrievedAt DESC,
                                     s.SnapshotID DESC
                        ) AS rn
                    FROM dbo.OptionContract AS o
                    INNER JOIN dbo.OptionLiveSnapshot AS s
                        ON s.OptionID = o.OptionID
                )
                SELECT
                    OptionID, TSEInsCode, Symbol, OptionType,
                    DataDate, DataTime, SourceRetrievedAt,
                    TradeValue, Volume, ClosingPrice, LastPrice
                FROM Ranked
                WHERE rn = 1
                ORDER BY OptionID
            """)
            db_rows = cur.fetchall()

        print(f"Snapshot selection: {snapshot_mode}")
        print(f"Database snapshots: {len(db_rows)}")
        print()

        # Index database rows by exchange contract code.
        db_by_code = {}
        for row in db_rows:
            code = str(row.TSEInsCode).strip()
            db_by_code[code] = row

        # Index API contract sides by exchange contract code.
        api_by_code = {}
        duplicate_api_codes = []
        malformed_api_sides = 0

        for index, record in enumerate(api_records):
            if not isinstance(record, dict):
                continue

            for side in ("C", "P"):
                item = get_api_side(record, side)
                if item is None:
                    continue

                item["APIRecordIndex"] = index
                item["Side"] = side

                code = item["InsCode"]
                if code in api_by_code:
                    duplicate_api_codes.append(code)
                else:
                    api_by_code[code] = item

        print(f"API contract codes : {len(api_by_code)}")
        print(f"Database codes     : {len(db_by_code)}")
        print(f"Duplicate API codes: {len(duplicate_api_codes)}")
        print()

        matched = 0
        unmatched_api = 0
        missing_api = 0
        missing_trade_value = 0
        missing_volume = 0
        zero_volume = 0
        negative_values = 0
        trade_value_mismatch = 0
        volume_mismatch = 0
        zero_cap_with_volume = 0
        positive_cap_without_volume = 0
        normalized_price_checked = 0
        close_price_matches = 0
        last_price_matches = 0
        neither_price_matches = 0
        zero_close_price = 0
        scale_check_count = 0

        ratios = []
        price_diffs_close = []
        price_diffs_last = []
        anomaly_lines = []
        zero_volume_symbols = []
        price_match_symbols = []
        matched_rows = []

        # Database -> API audit, including missing API codes.
        for code, db in db_by_code.items():
            api = api_by_code.get(code)
            if api is None:
                missing_api += 1
                anomaly_lines.append(
                    f"MISSING API | {db.Symbol} | InsCode={code}"
                )
                continue

            matched += 1
            db_trade_value = dec(db.TradeValue)
            db_volume = dec(db.Volume)
            db_close = dec(db.ClosingPrice)
            db_last = dec(db.LastPrice)

            api_cap = api["qTotCap"]
            api_volume = api["Volume"]
            api_close = api["ClosingPrice"]
            api_last = api["LastPrice"]

            # Compare stored TradeValue with API qTotCap.
            if api_cap is None or db_trade_value is None:
                missing_trade_value += 1
            elif abs(db_trade_value - api_cap) > TOLERANCE:
                trade_value_mismatch += 1
                anomaly_lines.append(
                    f"TRADE VALUE DIFF | {db.Symbol} | "
                    f"DB={fmt(db_trade_value)} | API qTotCap={fmt(api_cap)}"
                )

            # Compare stored volume with API volume.
            if api_volume is None or db_volume is None:
                missing_volume += 1
            elif db_volume != api_volume:
                volume_mismatch += 1
                anomaly_lines.append(
                    f"VOLUME DIFF | {db.Symbol} | "
                    f"DB={fmt(db_volume)} | API={fmt(api_volume)}"
                )

            if any(
                value is not None and value < 0
                for value in (
                    db_trade_value, db_volume, api_cap, api_volume
                )
            ):
                negative_values += 1
                anomaly_lines.append(
                    f"NEGATIVE VALUE | {db.Symbol} | "
                    f"DB TradeValue={fmt(db_trade_value)} | "
                    f"DB Volume={fmt(db_volume)} | "
                    f"API qTotCap={fmt(api_cap)} | "
                    f"API Volume={fmt(api_volume)}"
                )

            if api_volume == 0:
                zero_volume += 1
                zero_volume_symbols.append(str(db.Symbol))
                if api_cap is not None and api_cap > 0:
                    positive_cap_without_volume += 1
                    anomaly_lines.append(
                        f"CAP>0 WITH ZERO VOLUME | {db.Symbol} | "
                        f"qTotCap={fmt(api_cap)}"
                    )

            if api_volume is not None and api_volume > 0:
                if api_cap is not None and api_cap == 0:
                    zero_cap_with_volume += 1
                    anomaly_lines.append(
                        f"ZERO CAP WITH POSITIVE VOLUME | {db.Symbol} | "
                        f"Volume={fmt(api_volume)}"
                    )

                if api_cap is not None:
                    # Candidate implied price under a 1000 scale factor.
                    implied_price = api_cap / api_volume / SCALE_FACTOR
                    scale_check_count += 1

                    if api_cap >= 0:
                        ratios.append(implied_price)

                    if api_close is not None and api_close > 0:
                        diff_close = abs(implied_price - api_close)
                        price_diffs_close.append(diff_close)
                        close_match = diff_close <= PRICE_TOLERANCE
                    else:
                        close_match = False
                        zero_close_price += 1

                    if api_last is not None and api_last > 0:
                        diff_last = abs(implied_price - api_last)
                        price_diffs_last.append(diff_last)
                        last_match = diff_last <= PRICE_TOLERANCE
                    else:
                        last_match = False

                    if close_match:
                        close_price_matches += 1
                    if last_match:
                        last_price_matches += 1

                    if not close_match and not last_match:
                        neither_price_matches += 1
                        anomaly_lines.append(
                            f"IMPLIED PRICE DIFF | {db.Symbol} | "
                            f"qTotCap/Volume/1000={fmt(implied_price)} | "
                            f"API ClosingPrice={fmt(api_close)} | "
                            f"API LastPrice={fmt(api_last)}"
                        )
                    elif len(price_match_symbols) < 5:
                        price_match_symbols.append(
                            (
                                str(db.Symbol), implied_price,
                                api_close, api_last, close_match, last_match
                            )
                        )

            matched_rows.append(
                (
                    str(db.Symbol), code, api["Side"],
                    api_cap, api_volume, db_trade_value, db_volume
                )
            )

        # API codes that do not exist in the current contract table.
        for code in api_by_code:
            if code not in db_by_code:
                unmatched_api += 1

        print("=" * 78)
        print("BR61 SUMMARY")
        print("=" * 78)
        print(f"Matched contracts                 : {matched}")
        print(f"API codes absent from database    : {unmatched_api}")
        print(f"Database codes absent from API    : {missing_api}")
        print(f"Missing TradeValue/qTotCap        : {missing_trade_value}")
        print(f"Missing Volume                    : {missing_volume}")
        print(f"TradeValue != qTotCap             : {trade_value_mismatch}")
        print(f"Database Volume != API Volume     : {volume_mismatch}")
        print(f"Negative-value contracts          : {negative_values}")
        print(f"Zero-volume contracts             : {zero_volume}")
        print(f"qTotCap > 0 with zero volume      : {positive_cap_without_volume}")
        print(f"qTotCap = 0 with positive volume  : {zero_cap_with_volume}")
        print(f"Implied-price checks (volume > 0) : {scale_check_count}")
        print(f"Implied price matches closing     : {close_price_matches}")
        print(f"Implied price matches last        : {last_price_matches}")
        print(f"Matches neither price             : {neither_price_matches}")
        print()

        print("SCALE TEST: qTotCap / Volume / 1000")
        print("-" * 78)
        print("This is a diagnostic hypothesis, not a confirmed API definition.")
        print(f"Rows evaluated: {scale_check_count}")
        if ratios:
            print(f"Minimum implied price: {fmt(min(ratios))}")
            print(f"Maximum implied price: {fmt(max(ratios))}")
        if price_diffs_close:
            print(
                "Mean absolute difference vs ClosingPrice: "
                f"{fmt(sum(price_diffs_close) / len(price_diffs_close))}"
            )
            print(
                "Maximum absolute difference vs ClosingPrice: "
                f"{fmt(max(price_diffs_close))}"
            )
        if price_diffs_last:
            print(
                "Mean absolute difference vs LastPrice: "
                f"{fmt(sum(price_diffs_last) / len(price_diffs_last))}"
            )
            print(
                "Maximum absolute difference vs LastPrice: "
                f"{fmt(max(price_diffs_last))}"
            )

        print()
        print("SAMPLE PRICE MATCHES")
        print("-" * 78)
        if price_match_symbols:
            for (
                symbol, implied, close_price, last_price,
                close_match, last_match
            ) in price_match_symbols:
                print(
                    f"{symbol}: implied={fmt(implied)} | "
                    f"close={fmt(close_price)} "
                    f"({'MATCH' if close_match else 'DIFF'}) | "
                    f"last={fmt(last_price)} "
                    f"({'MATCH' if last_match else 'DIFF'})"
                )
        else:
            print("No positive-volume samples available for display.")

        print()
        print("ANOMALIES")
        print("-" * 78)
        if anomaly_lines:
            for line in anomaly_lines:
                print(line)
        else:
            print("No anomalies detected by the defined checks.")

        print()
        print("ZERO-VOLUME SYMBOLS")
        print("-" * 78)
        if zero_volume_symbols:
            print(", ".join(zero_volume_symbols))
        else:
            print("None")

        print()
        print("IMPORTANT NOTES")
        print("-" * 78)
        print("1. TradeValue == qTotCap confirms stored-value parity for this capture.")
        print("2. It does not by itself prove the official meaning or unit of qTotCap.")
        print("3. The /1000 implied-price test is exploratory, not a trading signal.")
        print("4. Snapshot selection mode:", snapshot_mode)
        if snapshot_mode != "EXACT_SOURCE_TIMESTAMP":
            print("WARNING: snapshot data may not be time-aligned with the API.")
        print("Database changes: NONE")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
