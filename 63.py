
# BR63 - Option Intrinsic Value and Economic Consistency Audit
# READ ONLY - No database writes

import json
import pyodbc
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DB_NAME = "OptionMarketDB_V2"
SERVER = "localhost"
DRIVER = "{ODBC Driver 17 for SQL Server}"

TOLERANCE = Decimal("1.00")
TARGET_UNDERLYING = "17914401175772326"

CONN_STR = (
    f"DRIVER={DRIVER};"
    f"SERVER={SERVER};"
    f"DATABASE={DB_NAME};"
    "Trusted_Connection=yes;"
    "ApplicationIntent=ReadOnly;"
)


def dec(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def fmt(value, digits=4):
    return "N/A" if value is None else f"{value:,.{digits}f}"


def find_api_array(obj):
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


def get_side(record, side):
    code = record.get(f"insCode_{side}")
    if code is None:
        return None

    return {
        "InsCode": str(code).strip(),
        "Symbol": record.get(f"lVal18AFC_{side}"),
        "OptionType": "CALL" if side == "C" else "PUT",
        "ClosingPrice": dec(record.get(f"pClosing_{side}")),
        "LastPrice": dec(record.get(f"pDrCotVal_{side}")),
        "BestBuyPrice": dec(record.get(f"pMeDem_{side}")),
        "BestSellPrice": dec(record.get(f"pMeOf_{side}")),
        "StrikePrice": dec(record.get("strikePrice")),
        "ContractSize": dec(record.get("contractSize")),
        "UnderlyingCode": str(record.get("uaInsCode", "")).strip(),
        "UnderlyingClose": dec(record.get("pClosing_UA")),
        "UnderlyingLast": dec(record.get("pDrCotVal_UA")),
        "Expiry": record.get("endDate"),
        "RemainingDays": dec(record.get("remainedDay")),
    }


def main():
    print("=" * 78)
    print("BR63 - OPTION INTRINSIC VALUE AUDIT")
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
        cur.execute("SELECT DB_NAME()")
        actual_db = cur.fetchone()[0]
        if actual_db != DB_NAME:
            raise RuntimeError(
                f"Safety check failed: connected to {actual_db}, "
                f"expected {DB_NAME}"
            )

        # Select newest successful response with the expected API array.
        cur.execute("""
            SELECT TOP (20)
                RawDataID, RetrievedAt, APIName, ResponseJSON
            FROM dbo.RawApiResponse
            WHERE IsSuccess = 1
              AND ResponseJSON IS NOT NULL
            ORDER BY RetrievedAt DESC, RawDataID DESC
        """)

        selected = None
        records = None

        for row in cur.fetchall():
            try:
                payload = json.loads(row.ResponseJSON)
            except (json.JSONDecodeError, TypeError):
                continue

            found = find_api_array(payload)
            if found is not None:
                selected = row
                records = found
                break

        if selected is None:
            raise RuntimeError("No valid raw API response found.")

        print("RAW RESPONSE")
        print("-" * 78)
        print(f"RawDataID       : {selected.RawDataID}")
        print(f"RetrievedAt     : {selected.RetrievedAt}")
        print(f"APIName         : {selected.APIName}")
        print(f"Array items     : {len(records)}")
        print()

        # Get database contract master.
        cur.execute("""
            SELECT
                OptionID, TSEInsCode, Symbol, OptionType,
                StrikePrice, ContractSize, ExpiryDate
            FROM dbo.OptionContract
            WHERE UnderlyingID = 1
        """)
        db_contracts = {
            str(row.TSEInsCode).strip(): row
            for row in cur.fetchall()
        }

        api_contracts = {}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue

            if str(record.get("uaInsCode", "")).strip() != TARGET_UNDERLYING:
                continue

            for side in ("C", "P"):
                item = get_side(record, side)
                if item is None:
                    continue
                item["APIRecordIndex"] = index
                api_contracts[item["InsCode"]] = item

        # Exact timestamp snapshot data is used only for cross-checking
        # the API closing price; calculations below use the raw API.
        cur.execute("""
            SELECT
                o.TSEInsCode,
                s.ClosingPrice,
                s.UnderlyingClosePrice,
                s.SourceRetrievedAt
            FROM dbo.OptionContract AS o
            INNER JOIN dbo.OptionLiveSnapshot AS s
                ON s.OptionID = o.OptionID
            WHERE s.SourceRetrievedAt = ?
        """, selected.RetrievedAt)

        snapshot_by_code = {
            str(row.TSEInsCode).strip(): row
            for row in cur.fetchall()
        }

        counts = {
            "matched": 0,
            "missing_strike": 0,
            "missing_underlying": 0,
            "missing_option_close": 0,
            "missing_snapshot": 0,
            "snapshot_mismatch": 0,
            "intrinsic_zero": 0,
            "intrinsic_positive": 0,
            "at_or_above_intrinsic": 0,
            "below_intrinsic": 0,
            "below_intrinsic_beyond_tolerance": 0,
            "negative_option_close": 0,
            "negative_intrinsic": 0,
        }

        call_count = 0
        put_count = 0
        anomalies = []
        samples = []
        time_value_values = []
        moneyness_counts = {
            "ITM": 0,
            "ATM_WITHIN_TOLERANCE": 0,
            "OTM": 0,
        }

        for code, item in api_contracts.items():
            db = db_contracts.get(code)
            if db is None:
                continue

            counts["matched"] += 1
            if item["OptionType"] == "CALL":
                call_count += 1
            else:
                put_count += 1

            strike = item["StrikePrice"]
            underlying = item["UnderlyingClose"]
            option_close = item["ClosingPrice"]

            if strike is None or strike <= 0:
                counts["missing_strike"] += 1
                anomalies.append(
                    f"INVALID STRIKE | {item['Symbol']} | "
                    f"Strike={fmt(strike)}"
                )
                continue

            if underlying is None or underlying <= 0:
                counts["missing_underlying"] += 1
                anomalies.append(
                    f"INVALID UNDERLYING CLOSE | {item['Symbol']} | "
                    f"UnderlyingClose={fmt(underlying)}"
                )
                continue

            if option_close is None:
                counts["missing_option_close"] += 1
                anomalies.append(
                    f"MISSING OPTION CLOSE | {item['Symbol']}"
                )
                continue

            if option_close < 0:
                counts["negative_option_close"] += 1
                anomalies.append(
                    f"NEGATIVE OPTION CLOSE | {item['Symbol']} | "
                    f"Close={fmt(option_close)}"
                )
                continue

            if item["OptionType"] == "CALL":
                intrinsic = max(underlying - strike, Decimal("0"))
                if underlying - strike > TOLERANCE:
                    moneyness = "ITM"
                elif strike - underlying > TOLERANCE:
                    moneyness = "OTM"
                else:
                    moneyness = "ATM_WITHIN_TOLERANCE"
            else:
                intrinsic = max(strike - underlying, Decimal("0"))
                if strike - underlying > TOLERANCE:
                    moneyness = "ITM"
                elif underlying - strike > TOLERANCE:
                    moneyness = "OTM"
                else:
                    moneyness = "ATM_WITHIN_TOLERANCE"

            moneyness_counts[moneyness] += 1

            if intrinsic < 0:
                counts["negative_intrinsic"] += 1

            if intrinsic == 0:
                counts["intrinsic_zero"] += 1
            else:
                counts["intrinsic_positive"] += 1

            # For a standard option, the option price should not be
            # below intrinsic value, subject to data conventions.
            difference = option_close - intrinsic
            if difference >= -TOLERANCE:
                counts["at_or_above_intrinsic"] += 1
            else:
                counts["below_intrinsic"] += 1

            if difference < -TOLERANCE:
                counts["below_intrinsic_beyond_tolerance"] += 1
                anomalies.append(
                    f"BELOW INTRINSIC | {item['Symbol']} | "
                    f"Type={item['OptionType']} | "
                    f"S={fmt(underlying)} | K={fmt(strike)} | "
                    f"OptionClose={fmt(option_close)} | "
                    f"Intrinsic={fmt(intrinsic)} | "
                    f"Difference={fmt(difference)}"
                )

            # Negative time value is not automatically a confirmed error:
            # market conventions and field definitions must be checked.
            time_value = option_close - intrinsic
            time_value_values.append(time_value)

            snapshot = snapshot_by_code.get(code)
            if snapshot is None:
                counts["missing_snapshot"] += 1
            else:
                snapshot_close = dec(snapshot.ClosingPrice)
                if snapshot_close is not None:
                    if abs(snapshot_close - option_close) > TOLERANCE:
                        counts["snapshot_mismatch"] += 1
                        anomalies.append(
                            f"SNAPSHOT/API CLOSE DIFF | {item['Symbol']} | "
                            f"API={fmt(option_close)} | "
                            f"Snapshot={fmt(snapshot_close)}"
                        )

            if len(samples) < 12:
                samples.append({
                    "symbol": item["Symbol"],
                    "type": item["OptionType"],
                    "S": underlying,
                    "K": strike,
                    "close": option_close,
                    "intrinsic": intrinsic,
                    "time_value": time_value,
                    "moneyness": moneyness,
                    "expiry": item["Expiry"],
                    "days": item["RemainingDays"],
                })

        print("=" * 78)
        print("SUMMARY")
        print("=" * 78)
        print(f"Matched contracts                   : {counts['matched']}")
        print(f"CALL contracts                      : {call_count}")
        print(f"PUT contracts                       : {put_count}")
        print(f"Missing/invalid strike              : {counts['missing_strike']}")
        print(f"Missing/invalid underlying close    : {counts['missing_underlying']}")
        print(f"Missing option close                : {counts['missing_option_close']}")
        print(f"Negative option close               : {counts['negative_option_close']}")
        print(f"Intrinsic value = 0                 : {counts['intrinsic_zero']}")
        print(f"Intrinsic value > 0                 : {counts['intrinsic_positive']}")
        print(f"Option close at/above intrinsic     : {counts['at_or_above_intrinsic']}")
        print(f"Option close below intrinsic        : {counts['below_intrinsic']}")
        print(
            "Below intrinsic beyond tolerance   : "
            f"{counts['below_intrinsic_beyond_tolerance']}"
        )
        print(f"Missing exact-time snapshot         : {counts['missing_snapshot']}")
        print(f"Snapshot/API closing mismatches     : {counts['snapshot_mismatch']}")
        print()

        print("MONEYNESS DISTRIBUTION")
        print("-" * 78)
        for label, count in moneyness_counts.items():
            print(f"{label:28}: {count}")
        print()

        if time_value_values:
            print("TIME VALUE (OPTION CLOSE - INTRINSIC)")
            print("-" * 78)
            print(f"Minimum time value: {fmt(min(time_value_values))}")
            print(f"Maximum time value: {fmt(max(time_value_values))}")
            print(
                "Negative time-value contracts: "
                f"{sum(1 for x in time_value_values if x < -TOLERANCE)}"
            )
            print(
                "Near-zero time-value contracts: "
                f"{sum(1 for x in time_value_values if abs(x) <= TOLERANCE)}"
            )
            print()

        print("SAMPLE CONTRACTS")
        print("-" * 78)
        for s in samples:
            print(
                f"{s['symbol']} | {s['type']} | "
                f"S={fmt(s['S'])} | K={fmt(s['K'])} | "
                f"Close={fmt(s['close'])} | "
                f"Intrinsic={fmt(s['intrinsic'])} | "
                f"TimeValue={fmt(s['time_value'])} | "
                f"{s['moneyness']} | "
                f"Expiry={s['expiry']} | Days={fmt(s['days'])}"
            )
        print()

        print("ANOMALIES")
        print("-" * 78)
        if anomalies:
            for line in anomalies:
                print(line)
        else:
            print("No anomalies detected by these checks.")

        print()
        print("INTERPRETATION")
        print("-" * 78)
        print("Intrinsic value uses API pClosing_UA and strikePrice.")
        print("Option price uses API pClosing_C/P.")
        print("A below-intrinsic result is a review flag, not proof of an API error.")
        print("This audit does not calculate implied volatility or trading signals.")
        print("Database writes: NONE")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
