
# BR60 - Compare Stored Raw API with Snapshot and Current
# READ ONLY: No database writes.
# Database: OptionMarketDB_V2 only.

import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pyodbc


SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_INSCODE = "17914401175772326"
API_ARRAY_KEY = "instrumentOptMarketWatch"

# Database field -> API field suffix
FIELD_MAP = {
    "LastPrice": "pDrCotVal",
    "ClosingPrice": "pClosing",
    "YesterdayPrice": "priceYesterday",
    "BestBuyPrice": "pMeDem",
    "BestBuyVolume": "qTitMeDem",
    "BestSellPrice": "pMeOf",
    "BestSellVolume": "qTitMeOf",
    "Volume": "qTotTran5J",
    "OpenInterest": "oP",
}

# TradeValue is checked separately because its scale is not
# independently confirmed. Candidate API field: qTotCap.
TOLERANCE = Decimal("0.0001")


def normalize_code(value):
    if value is None:
        return None
    return str(value).strip()


def to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def find_api_array(payload):
    """Find the API array without assuming unnecessary wrapper levels."""
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        candidate = payload.get(API_ARRAY_KEY)
        if isinstance(candidate, list):
            return candidate

        for value in payload.values():
            if isinstance(value, (dict, list)):
                result = find_api_array(value)
                if result is not None:
                    return result

    return None


def get_contract_value(api_record, field, option_type):
    """Read fields such as pClosing_C or pClosing_P."""
    suffix = "_C" if option_type == "C" else "_P"
    return api_record.get(field + suffix)


def get_contract_code(api_record, option_type):
    suffix = "_C" if option_type == "C" else "_P"
    return normalize_code(api_record.get("insCode" + suffix))


def connect_read_only():
    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "ApplicationIntent=ReadOnly;"
    )
    return pyodbc.connect(connection_string, timeout=15)


def main():
    print("=" * 78)
    print("BR60 - RAW API vs SNAPSHOT/CURRENT")
    print("=" * 78)
    print(f"Server       : {SERVER}")
    print(f"Database     : {DATABASE}")
    print("Mode         : READ ONLY")
    print("Database writes: NONE")
    print()

    conn = connect_read_only()
    conn.timeout = 30

    try:
        cursor = conn.cursor()

        # Find the latest successful raw response containing JSON.
        cursor.execute("""
            SELECT TOP (10)
                RawDataID,
                CollectionRunID,
                RetrievedAt,
                APIName,
                InsCode,
                HttpStatusCode,
                IsSuccess,
                ResponseJSON
            FROM dbo.RawApiResponse
            WHERE ResponseJSON IS NOT NULL
              AND IsSuccess = 1
            ORDER BY RetrievedAt DESC, RawDataID DESC
        """)

        raw_rows = cursor.fetchall()

        if not raw_rows:
            print("ERROR: No successful raw API response was found.")
            print("Cannot perform same-capture comparison.")
            return

        selected = None
        payload = None
        api_records = None

        for row in raw_rows:
            try:
                candidate_payload = json.loads(row.ResponseJSON)
                candidate_array = find_api_array(candidate_payload)
                if candidate_array is not None:
                    selected = row
                    payload = candidate_payload
                    api_records = candidate_array
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        if selected is None:
            print("ERROR: No stored response contained the expected API array.")
            print("Recent response metadata:")
            for row in raw_rows:
                print(
                    f"  RawDataID={row.RawDataID}, "
                    f"RetrievedAt={row.RetrievedAt}, "
                    f"APIName={row.APIName}, "
                    f"InsCode={row.InsCode}"
                )
            print()
            print("BR60 cannot safely infer the JSON structure.")
            return

        print("SELECTED RAW RESPONSE")
        print("-" * 78)
        print(f"RawDataID       : {selected.RawDataID}")
        print(f"CollectionRunID : {selected.CollectionRunID}")
        print(f"RetrievedAt     : {selected.RetrievedAt}")
        print(f"APIName         : {selected.APIName}")
        print(f"HTTP status     : {selected.HttpStatusCode}")
        print(f"API array key   : {API_ARRAY_KEY}")
        print(f"API array items : {len(api_records)}")
        print()

        # Read contract metadata and both live tables.
        cursor.execute("""
            SELECT
                oc.OptionID,
                oc.TSEInsCode,
                oc.Symbol,
                oc.OptionType,
                oc.StrikePrice,
                oc.ContractSize,
                s.SnapshotID,
                s.DataDate AS SnapshotDate,
                s.DataTime AS SnapshotTime,
                s.SourceRetrievedAt AS SnapshotRetrievedAt,
                s.LastPrice AS S_LastPrice,
                s.ClosingPrice AS S_ClosingPrice,
                s.YesterdayPrice AS S_YesterdayPrice,
                s.BestBuyPrice AS S_BestBuyPrice,
                s.BestBuyVolume AS S_BestBuyVolume,
                s.BestSellPrice AS S_BestSellPrice,
                s.BestSellVolume AS S_BestSellVolume,
                s.Volume AS S_Volume,
                s.TradeCount AS S_TradeCount,
                s.TradeValue AS S_TradeValue,
                s.OpenInterest AS S_OpenInterest,
                c.SourceRetrievedAt AS C_RetrievedAt,
                c.LastPrice AS C_LastPrice,
                c.ClosingPrice AS C_ClosingPrice,
                c.YesterdayPrice AS C_YesterdayPrice,
                c.BestBuyPrice AS C_BestBuyPrice,
                c.BestBuyVolume AS C_BestBuyVolume,
                c.BestSellPrice AS C_BestSellPrice,
                c.BestSellVolume AS C_BestSellVolume,
                c.Volume AS C_Volume,
                c.TradeCount AS C_TradeCount,
                c.TradeValue AS C_TradeValue,
                c.OpenInterest AS C_OpenInterest
            FROM dbo.OptionContract oc
            LEFT JOIN dbo.OptionLiveSnapshot s
                ON s.OptionID = oc.OptionID
            LEFT JOIN dbo.OptionLiveCurrent c
                ON c.OptionID = oc.OptionID
            WHERE oc.UnderlyingID = (
                SELECT TOP (1) UnderlyingID
                FROM dbo.Underlying
                WHERE TSEInsCode = ?
            )
            ORDER BY oc.Symbol
        """, UNDERLYING_INSCODE)

        db_rows = cursor.fetchall()

        if not db_rows:
            print("ERROR: No option contracts found for the target underlying.")
            return

        # An API parent record may contain both CALL and PUT fields.
        api_by_code = {}
        duplicate_api_codes = []

        for record_index, record in enumerate(api_records):
            if not isinstance(record, dict):
                continue

            for option_type in ("C", "P"):
                code = get_contract_code(record, option_type)
                if not code:
                    continue

                if code in api_by_code:
                    duplicate_api_codes.append(code)
                else:
                    api_by_code[code] = (record, option_type, record_index)

        print(f"API contract codes found: {len(api_by_code)}")
        print(f"Database contracts      : {len(db_rows)}")
        print(f"Duplicate API codes     : {len(duplicate_api_codes)}")
        if duplicate_api_codes:
            print("Duplicate codes:", ", ".join(duplicate_api_codes[:20]))
        print()

        totals = {
            "matched": 0,
            "unmatched": 0,
            "snapshot_missing": 0,
            "current_missing": 0,
            "snapshot_compared": 0,
            "current_compared": 0,
            "snapshot_mismatch": 0,
            "current_mismatch": 0,
            "unknown_api_value": 0,
        }

        for row in db_rows:
            code = normalize_code(row.TSEInsCode)
            symbol = row.Symbol or "?"
            option_type = (row.OptionType or "").strip().upper()

            print("-" * 78)
            print(f"{symbol} | OptionID={row.OptionID} | InsCode={code}")

            api_match = api_by_code.get(code)
            if api_match is None:
                totals["unmatched"] += 1
                print("  API MATCH: NOT FOUND")
                continue

            api_record, api_type, record_index = api_match
            totals["matched"] += 1

            if option_type in ("C", "P") and option_type != api_type:
                print(
                    f"  WARNING: OptionType mismatch: "
                    f"DB={option_type}, API={api_type}"
                )

            print(
                f"  API record index={record_index}, "
                f"contract side={api_type}"
            )

            snapshot_exists = row.SnapshotID is not None
            current_exists = row.C_RetrievedAt is not None

            if not snapshot_exists:
                totals["snapshot_missing"] += 1
                print("  SNAPSHOT: MISSING")
            else:
                print(
                    f"  SNAPSHOT RetrievedAt={row.SnapshotRetrievedAt}"
                )

            if not current_exists:
                totals["current_missing"] += 1
                print("  CURRENT: MISSING")
            else:
                print(f"  CURRENT RetrievedAt={row.C_RetrievedAt}")

            for db_field, api_field in FIELD_MAP.items():
                api_value = to_decimal(
                    get_contract_value(api_record, api_field, api_type)
                )

                snapshot_value = (
                    to_decimal(getattr(row, "S_" + db_field))
                    if snapshot_exists else None
                )
                current_value = (
                    to_decimal(getattr(row, "C_" + db_field))
                    if current_exists else None
                )

                if api_value is None:
                    totals["unknown_api_value"] += 1
                    print(
                        f"  {db_field}: API value missing/non-numeric; "
                        "comparison skipped"
                    )
                    continue

                if snapshot_exists and snapshot_value is not None:
                    totals["snapshot_compared"] += 1
                    snapshot_match = (
                        abs(api_value - snapshot_value) <= TOLERANCE
                    )
                    if not snapshot_match:
                        totals["snapshot_mismatch"] += 1

                    print(
                        f"  {db_field}: API={api_value} | "
                        f"Snapshot={snapshot_value} | "
                        f"{'MATCH' if snapshot_match else 'DIFF'}"
                    )

                if current_exists and current_value is not None:
                    totals["current_compared"] += 1
                    current_match = (
                        abs(api_value - current_value) <= TOLERANCE
                    )
                    if not current_match:
                        totals["current_mismatch"] += 1

                    print(
                        f"      Current={current_value} | "
                        f"{'MATCH' if current_match else 'DIFF'}"
                    )

            # TradeValue/qTotCap is intentionally diagnostic only.
            api_qtotcap = to_decimal(
                get_contract_value(api_record, "qTotCap", api_type)
            )
            api_volume = to_decimal(
                get_contract_value(api_record, "qTotTran5J", api_type)
            )

            print("  TradeValue diagnostic (not a confirmed mapping):")
            print(f"      DB Snapshot TradeValue={row.S_TradeValue}")
            print(f"      DB Current  TradeValue={row.C_TradeValue}")
            print(f"      API qTotCap={api_qtotcap}")
            if api_qtotcap is not None and api_volume:
                print(
                    "      qTotCap / volume = "
                    f"{api_qtotcap / api_volume}"
                )
                print(
                    "      qTotCap / volume / 1000 = "
                    f"{api_qtotcap / api_volume / Decimal(1000)}"
                )

        print()
        print("=" * 78)
        print("BR60 SUMMARY")
        print("=" * 78)
        for key, value in totals.items():
            print(f"{key:24}: {value}")

        print()
        print("IMPORTANT INTERPRETATION")
        print("-" * 78)
        print(
            "A matching InsCode proves identity matching, not time alignment."
        )
        print(
            "Review RetrievedAt timestamps before interpreting differences "
            "as mapping errors."
        )
        print(
            "TradeValue/qTotCap scale remains unconfirmed; it is diagnostic only."
        )
        print("Database changes: NONE")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except pyodbc.Error as exc:
        print("SQL SERVER ERROR:")
        print(exc)
        sys.exit(1)
    except Exception as exc:
        print("UNEXPECTED ERROR:")
        print(type(exc).__name__, exc)
        raise
