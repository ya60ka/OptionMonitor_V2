
# BR62 - Independent API Financial Formula Audit
# READ ONLY - No database writes

import json
import pyodbc
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections import Counter

PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DB_NAME = "OptionMarketDB_V2"
SERVER = "localhost"
DRIVER = "{ODBC Driver 17 for SQL Server}"

TOLERANCE = Decimal("1.00")
SCALE = Decimal("1000")

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
    except (InvalidOperation, TypeError, ValueError):
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
        "Name": record.get(f"lVal30_{side}"),
        "TradeValue": dec(record.get(f"qTotCap_{side}")),
        "Volume": dec(record.get(f"qTotTran5J_{side}")),
        "ClosingPrice": dec(record.get(f"pClosing_{side}")),
        "LastPrice": dec(record.get(f"pDrCotVal_{side}")),
        "BestBuyPrice": dec(record.get(f"pMeDem_{side}")),
        "BestSellPrice": dec(record.get(f"pMeOf_{side}")),
        "OpenInterest": dec(record.get(f"oP_{side}")),
        "StrikePrice": dec(record.get("strikePrice")),
        "ContractSize": dec(record.get("contractSize")),
        "UnderlyingLast": dec(record.get("pDrCotVal_UA")),
        "UnderlyingClose": dec(record.get("pClosing_UA")),
        "UnderlyingCode": str(record.get("uaInsCode", "")).strip(),
        "Expiry": record.get("endDate"),
    }


def main():
    print("=" * 78)
    print("BR62 - INDEPENDENT API FINANCIAL FORMULA AUDIT")
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

        # Get the latest successful raw API response.
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

        # Only analyze option contracts belonging to the target underlying.
        target_underlying = "17914401175772326"
        api_contracts = {}
        duplicate_codes = []
        target_records = 0
        other_underlying_records = 0

        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                continue

            ua_code = str(record.get("uaInsCode", "")).strip()
            if ua_code != target_underlying:
                other_underlying_records += 1
                continue

            target_records += 1
            for side in ("C", "P"):
                item = get_side(record, side)
                if item is None:
                    continue
                item["APIRecordIndex"] = idx
                item["Side"] = side
                code = item["InsCode"]

                if code in api_contracts:
                    duplicate_codes.append(code)
                else:
                    api_contracts[code] = item

        print("UNDERLYING FILTER")
        print("-" * 78)
        print(f"Target underlying InsCode : {target_underlying}")
        print(f"Records matching target   : {target_records}")
        print(f"Other underlying records  : {other_underlying_records}")
        print(f"Unique target option codes: {len(api_contracts)}")
        print(f"Duplicate target codes    : {len(duplicate_codes)}")
        print()

        # Compare target API contracts to the contract master.
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

        matched = 0
        missing_in_db = []
        missing_in_api = []
        strike_mismatch = []
        size_mismatch = []
        symbol_mismatch = []

        volume_positive = 0
        volume_zero = 0
        missing_value = 0
        value_zero_with_volume = 0
        value_positive_without_volume = 0
        negative_data = 0

        closing_matches = 0
        last_matches = 0
        neither_matches = 0
        buy_matches = 0
        sell_matches = 0
        no_quote_price = 0

        implied_prices = []
        close_differences = []
        last_differences = []
        contract_sizes = Counter()
        side_counts = Counter()
        anomaly_lines = []
        samples = []

        for code, api in api_contracts.items():
            db = db_contracts.get(code)
            if db is None:
                missing_in_db.append(
                    (api.get("Symbol"), code, api["Side"])
                )
                continue

            matched += 1
            side_counts[api["Side"]] += 1

            db_strike = dec(db.StrikePrice)
            db_size = dec(db.ContractSize)
            api_strike = api["StrikePrice"]
            api_size = api["ContractSize"]

            if api_strike is not None and db_strike is not None:
                if api_strike != db_strike:
                    strike_mismatch.append(
                        (api.get("Symbol"), code, api_strike, db_strike)
                    )

            if api_size is not None and db_size is not None:
                if api_size != db_size:
                    size_mismatch.append(
                        (api.get("Symbol"), code, api_size, db_size)
                    )

            if api_size is not None:
                contract_sizes[str(api_size)] += 1

            if api.get("Symbol") and db.Symbol:
                if str(api["Symbol"]).strip() != str(db.Symbol).strip():
                    symbol_mismatch.append(
                        (api["Symbol"], db.Symbol, code)
                    )

            cap = api["TradeValue"]
            volume = api["Volume"]
            close = api["ClosingPrice"]
            last = api["LastPrice"]
            buy = api["BestBuyPrice"]
            sell = api["BestSellPrice"]

            if any(
                value is not None and value < 0
                for value in (cap, volume, close, last, buy, sell)
            ):
                negative_data += 1
                anomaly_lines.append(
                    f"NEGATIVE API VALUE | {api.get('Symbol')} | "
                    f"cap={fmt(cap)} volume={fmt(volume)} "
                    f"close={fmt(close)} last={fmt(last)}"
                )

            if cap is None or volume is None:
                missing_value += 1
                continue

            if volume == 0:
                volume_zero += 1
                if cap > 0:
                    value_positive_without_volume += 1
                    anomaly_lines.append(
                        f"VALUE WITHOUT VOLUME | {api.get('Symbol')} | "
                        f"qTotCap={fmt(cap)}"
                    )
                continue

            if volume < 0:
                continue

            volume_positive += 1
            if cap == 0:
                value_zero_with_volume += 1

            implied = cap / volume / SCALE
            implied_prices.append(implied)

            close_diff = (
                abs(implied - close) if close is not None else None
            )
            last_diff = (
                abs(implied - last) if last is not None else None
            )

            if close_diff is not None:
                close_differences.append(close_diff)
            if last_diff is not None:
                last_differences.append(last_diff)

            close_match = (
                close_diff is not None and close_diff <= TOLERANCE
            )
            last_match = (
                last_diff is not None and last_diff <= TOLERANCE
            )

            if close_match:
                closing_matches += 1
            if last_match:
                last_matches += 1

            if not close_match and not last_match:
                neither_matches += 1
                anomaly_lines.append(
                    f"IMPLIED PRICE DIFF | {api.get('Symbol')} | "
                    f"implied={fmt(implied)} close={fmt(close)} "
                    f"last={fmt(last)}"
                )

            if buy is not None and buy > 0:
                if abs(implied - buy) <= TOLERANCE:
                    buy_matches += 1
            if sell is not None and sell > 0:
                if abs(implied - sell) <= TOLERANCE:
                    sell_matches += 1
            if (buy is None or buy == 0) and (sell is None or sell == 0):
                no_quote_price += 1

            if len(samples) < 8:
                samples.append({
                    "symbol": api.get("Symbol"),
                    "side": api["Side"],
                    "cap": cap,
                    "volume": volume,
                    "implied": implied,
                    "close": close,
                    "last": last,
                    "buy": buy,
                    "sell": sell,
                    "strike": api_strike,
                    "size": api_size,
                    "underlying_close": api["UnderlyingClose"],
                })

        for code, db in db_contracts.items():
            if code not in api_contracts:
                missing_in_api.append((db.Symbol, code))

        print("=" * 78)
        print("CONTRACT MASTER VALIDATION")
        print("=" * 78)
        print(f"Matched API contracts       : {matched}")
        print(f"API contracts absent in DB  : {len(missing_in_db)}")
        print(f"DB contracts absent in API  : {len(missing_in_api)}")
        print(f"Strike-price mismatches     : {len(strike_mismatch)}")
        print(f"Contract-size mismatches    : {len(size_mismatch)}")
        print(f"Symbol mismatches           : {len(symbol_mismatch)}")
        print(f"Option-side counts          : {dict(side_counts)}")
        print(f"Contract-size distribution : {dict(contract_sizes)}")
        print()

        print("=" * 78)
        print("INDEPENDENT TRADE VALUE FORMULA")
        print("=" * 78)
        print(f"Positive-volume contracts       : {volume_positive}")
        print(f"Zero-volume contracts           : {volume_zero}")
        print(f"Missing cap or volume           : {missing_value}")
        print(f"qTotCap=0 with positive volume  : {value_zero_with_volume}")
        print(f"qTotCap>0 with zero volume      : {value_positive_without_volume}")
        print(f"Negative-data contracts         : {negative_data}")
        print()
        print("Candidate formula: qTotCap / Volume / 1000")
        print(f"Price checks vs ClosingPrice    : {closing_matches}")
        print(f"Price checks vs LastPrice       : {last_matches}")
        print(f"Matching neither                : {neither_matches}")
        print(f"Best-buy price matches          : {buy_matches}")
        print(f"Best-sell price matches         : {sell_matches}")
        print(f"Contracts with no buy/sell quote: {no_quote_price}")

        if implied_prices:
            print(f"Implied price minimum           : {fmt(min(implied_prices))}")
            print(f"Implied price maximum           : {fmt(max(implied_prices))}")

        if close_differences:
            print(
                "Mean difference vs close        : "
                f"{fmt(sum(close_differences) / len(close_differences))}"
            )
            print(
                "Maximum difference vs close     : "
                f"{fmt(max(close_differences))}"
            )

        if last_differences:
            print(
                "Mean difference vs last         : "
                f"{fmt(sum(last_differences) / len(last_differences))}"
            )
            print(
                "Maximum difference vs last      : "
                f"{fmt(max(last_differences))}"
            )

        print()
        print("=" * 78)
        print("SAMPLE API FORMULA DETAILS")
        print("=" * 78)

        for s in samples:
            print(
                f"{s['symbol']} [{s['side']}] | "
                f"qTotCap={fmt(s['cap'])} | "
                f"Volume={fmt(s['volume'])} | "
                f"Implied={fmt(s['implied'])} | "
                f"Close={fmt(s['close'])} | "
                f"Last={fmt(s['last'])} | "
                f"Buy={fmt(s['buy'])} | "
                f"Sell={fmt(s['sell'])} | "
                f"Strike={fmt(s['strike'])} | "
                f"Size={fmt(s['size'])} | "
                f"UnderlyingClose={fmt(s['underlying_close'])}"
            )

        print()
        print("=" * 78)
        print("ANOMALIES")
        print("=" * 78)

        all_master_issues = (
            missing_in_db
            or missing_in_api
            or strike_mismatch
            or size_mismatch
            or symbol_mismatch
        )

        if not anomaly_lines and not all_master_issues:
            print("No anomalies detected.")
        else:
            for item in missing_in_db[:20]:
                print(f"API_NOT_IN_DB | {item}")
            for item in missing_in_api[:20]:
                print(f"DB_NOT_IN_API | {item}")
            for item in strike_mismatch[:20]:
                print(f"STRIKE_MISMATCH | {item}")
            for item in size_mismatch[:20]:
                print(f"SIZE_MISMATCH | {item}")
            for item in symbol_mismatch[:20]:
                print(f"SYMBOL_MISMATCH | {item}")
            for line in anomaly_lines[:50]:
                print(line)

        print()
        print("INTERPRETATION")
        print("-" * 78)
        print("This audit uses the raw API response, not stored TradeValue.")
        print("It tests a candidate scale relationship; it does not establish")
        print("an official API unit definition or a trading recommendation.")
        print("Database writes: NONE")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
