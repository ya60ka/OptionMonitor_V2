
# BR64 - Option Market Price vs Intrinsic Value Audit
# Version: 1.0
# Mode: READ ONLY - NO DATABASE WRITES

import json
import sys
from decimal import Decimal, InvalidOperation
from collections import Counter

import pyodbc


SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
UNDERLYING_ID = 1
UNDERLYING_INSCODE = "17914401175772326"
TOLERANCE = Decimal("1.00")


def to_decimal(value):
    """Convert API values to Decimal; return None when unavailable."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def fmt(value):
    if value is None:
        return "N/A"
    return f"{value:,.4f}"


def get_intrinsic(option_type, underlying_price, strike):
    if underlying_price is None or strike is None:
        return None

    if option_type == "CALL":
        return max(underlying_price - strike, Decimal("0"))

    if option_type == "PUT":
        return max(strike - underlying_price, Decimal("0"))

    return None


def get_api_value(record, field):
    return to_decimal(record.get(field))


def main():
    connection = None

    print("=" * 86)
    print("BR64 - OPTION MARKET PRICE VS INTRINSIC VALUE AUDIT")
    print("=" * 86)
    print(f"Server          : {SERVER}")
    print(f"Database        : {DATABASE}")
    print("Mode            : READ ONLY")
    print("Database writes : NONE")
    print(f"Tolerance       : {TOLERANCE}")
    print()

    try:
        connection_string = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
        )

        connection = pyodbc.connect(
            connection_string,
            timeout=15,
            autocommit=True
        )
        cursor = connection.cursor()

        # --------------------------------------------------------------
        # 1. Read the latest successful raw API response.
        # --------------------------------------------------------------
        cursor.execute("""
            SELECT TOP (1)
                RawDataID,
                RetrievedAt,
                APIName,
                HttpStatusCode,
                ResponseJSON
            FROM dbo.RawApiResponse
            WHERE IsSuccess = 1
              AND ResponseJSON IS NOT NULL
              AND APIName = 'GetInstrumentOptionMarketWatch'
            ORDER BY RetrievedAt DESC, RawDataID DESC
        """)

        raw_row = cursor.fetchone()
        if raw_row is None:
            raise RuntimeError(
                "No successful GetInstrumentOptionMarketWatch response "
                "was found in RawApiResponse."
            )

        raw_data_id = raw_row[0]
        retrieved_at = raw_row[1]
        api_name = raw_row[2]
        http_status = raw_row[3]
        response_json = raw_row[4]

        if isinstance(response_json, bytes):
            response_json = response_json.decode("utf-8")

        payload = json.loads(response_json)

        api_records = payload.get("instrumentOptMarketWatch")
        if not isinstance(api_records, list):
            raise RuntimeError(
                "Expected JSON array 'instrumentOptMarketWatch' "
                "was not found."
            )

        print("RAW RESPONSE")
        print("-" * 86)
        print(f"RawDataID       : {raw_data_id}")
        print(f"RetrievedAt     : {retrieved_at}")
        print(f"APIName         : {api_name}")
        print(f"HTTP status     : {http_status}")
        print(f"Array items     : {len(api_records)}")

        # --------------------------------------------------------------
        # 2. Select the target underlying's option contracts.
        # --------------------------------------------------------------
        target_records = [
            record for record in api_records
            if str(record.get("uaInsCode", "")).strip()
            == UNDERLYING_INSCODE
        ]

        # One API record can contain both a CALL and a PUT.
        api_contracts = {}

        for record in target_records:
            strike = to_decimal(record.get("strikePrice"))

            for side, suffix in (("CALL", "C"), ("PUT", "P")):
                code = record.get(f"insCode_{suffix}")
                if code is None or str(code).strip() == "":
                    continue

                code = str(code).strip()

                api_contracts[code] = {
                    "code": code,
                    "symbol": str(
                        record.get(f"lVal18AFC_{suffix}", "")
                    ).strip(),
                    "type": side,
                    "strike": strike,
                    "underlying_close": to_decimal(
                        record.get("pClosing_UA")
                    ),
                    "underlying_last": to_decimal(
                        record.get("pDrCotVal_UA")
                    ),
                    "close": to_decimal(
                        record.get(f"pClosing_{suffix}")
                    ),
                    "last": to_decimal(
                        record.get(f"pDrCotVal_{suffix}")
                    ),
                    "bid": to_decimal(
                        record.get(f"pMeDem_{suffix}")
                    ),
                    "ask": to_decimal(
                        record.get(f"pMeOf_{suffix}")
                    ),
                    "volume": to_decimal(
                        record.get(f"zTotTran_{suffix}")
                    ),
                    "trade_count": to_decimal(
                        record.get(f"zTotTran5J_{suffix}")
                    ),
                    "open_interest": to_decimal(
                        record.get(f"qTotTran5J_{suffix}")
                    ),
                    "expiry": record.get("endDate"),
                }

        # --------------------------------------------------------------
        # 3. Read contract master; no INSERT/UPDATE/DELETE.
        # --------------------------------------------------------------
        cursor.execute("""
            SELECT
                OptionID,
                TSEInsCode,
                Symbol,
                OptionType,
                StrikePrice,
                ContractSize,
                ExpiryDate
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
        """, UNDERLYING_ID)

        db_contracts = {}
        for row in cursor.fetchall():
            code = str(row[1]).strip()
            db_contracts[code] = {
                "option_id": row[0],
                "symbol": row[2],
                "type": str(row[3]).strip().upper(),
                "strike": to_decimal(row[4]),
                "contract_size": row[5],
                "expiry": row[6],
            }

        matched_codes = sorted(
            set(api_contracts.keys()) & set(db_contracts.keys())
        )
        api_only = sorted(
            set(api_contracts.keys()) - set(db_contracts.keys())
        )
        db_only = sorted(
            set(db_contracts.keys()) - set(api_contracts.keys())
        )

        # --------------------------------------------------------------
        # 4. Compare prices against intrinsic value.
        # Intrinsic is based on underlying closing price for consistency.
        # --------------------------------------------------------------
        results = []
        mismatch_type = Counter()
        price_stats = {
            "close": Counter(),
            "last": Counter(),
            "bid": Counter(),
            "ask": Counter(),
        }

        missing_underlying = 0
        missing_strike = 0
        missing_close = 0
        negative_prices = 0
        side_mismatches = 0
        strike_mismatches = 0

        for code in matched_codes:
            api = api_contracts[code]
            db = db_contracts[code]

            side = api["type"]
            strike = api["strike"]
            underlying_close = api["underlying_close"]

            if underlying_close is None:
                missing_underlying += 1
            if strike is None:
                missing_strike += 1
            if api["close"] is None:
                missing_close += 1

            if db["type"] in ("CALL", "PUT") and db["type"] != side:
                side_mismatches += 1

            if (
                strike is not None
                and db["strike"] is not None
                and strike != db["strike"]
            ):
                strike_mismatches += 1

            intrinsic = get_intrinsic(
                side, underlying_close, strike
            )

            row_result = {
                **api,
                "db_symbol": db["symbol"],
                "intrinsic": intrinsic,
                "prices": {},
            }

            for field in ("close", "last", "bid", "ask"):
                price = api[field]
                difference = (
                    price - intrinsic
                    if price is not None and intrinsic is not None
                    else None
                )

                row_result["prices"][field] = {
                    "price": price,
                    "difference": difference,
                }

                if price is not None and price < 0:
                    negative_prices += 1

                if price is None or intrinsic is None:
                    price_stats[field]["missing"] += 1
                elif price == 0:
                    price_stats[field]["zero"] += 1
                elif difference < -TOLERANCE:
                    price_stats[field]["below"] += 1
                elif difference < Decimal("0"):
                    price_stats[field]["slightly_below"] += 1
                else:
                    price_stats[field]["at_or_above"] += 1

            if intrinsic is not None:
                if intrinsic == 0:
                    row_result["moneyness"] = "OTM_OR_ATM"
                else:
                    row_result["moneyness"] = "ITM"
            else:
                row_result["moneyness"] = "UNKNOWN"

            results.append(row_result)

        # --------------------------------------------------------------
        # 5. Summary.
        # --------------------------------------------------------------
        print()
        print("=" * 86)
        print("SUMMARY")
        print("=" * 86)
        print(f"API records for underlying       : {len(target_records)}")
        print(f"Unique API option contracts     : {len(api_contracts)}")
        print(f"DB option contracts             : {len(db_contracts)}")
        print(f"Matched contracts               : {len(matched_codes)}")
        print(f"API contracts absent from DB    : {len(api_only)}")
        print(f"DB contracts absent from API    : {len(db_only)}")
        print(f"Missing underlying close        : {missing_underlying}")
        print(f"Missing/invalid strike          : {missing_strike}")
        print(f"Missing option close            : {missing_close}")
        print(f"Negative price fields           : {negative_prices}")
        print(f"Option type mismatches          : {side_mismatches}")
        print(f"Strike mismatches               : {strike_mismatches}")

        side_counts = Counter(api_contracts[c]["type"] for c in matched_codes)
        print(f"CALL contracts                  : {side_counts['CALL']}")
        print(f"PUT contracts                   : {side_counts['PUT']}")

        # --------------------------------------------------------------
        # 6. Price-level results.
        # --------------------------------------------------------------
        print()
        print("PRICE VS INTRINSIC DISTRIBUTION")
        print("-" * 86)
        print(
            f"{'PRICE FIELD':<16}"
            f"{'AT/ABOVE':>12}"
            f"{'BELOW > TOL.':>15}"
            f"{'SLIGHTLY BELOW':>17}"
            f"{'ZERO':>10}"
            f"{'MISSING':>10}"
        )

        labels = {
            "close": "Closing price",
            "last": "Last trade",
            "bid": "Best bid",
            "ask": "Best ask",
        }

        for field in ("close", "last", "bid", "ask"):
            stat = price_stats[field]
            print(
                f"{labels[field]:<16}"
                f"{stat['at_or_above']:>12}"
                f"{stat['below']:>15}"
                f"{stat['slightly_below']:>17}"
                f"{stat['zero']:>10}"
                f"{stat['missing']:>10}"
            )

        # --------------------------------------------------------------
        # 7. Detailed comparison table.
        # --------------------------------------------------------------
        print()
        print("=" * 86)
        print("CONTRACT PRICE COMPARISON")
        print("=" * 86)
        print(
            f"{'SYMBOL':<14}"
            f"{'TYPE':<6}"
            f"{'STRIKE':>12}"
            f"{'INTRINSIC':>13}"
            f"{'CLOSE':>12}"
            f"{'LAST':>12}"
            f"{'BID':>12}"
            f"{'ASK':>12}"
        )
        print("-" * 86)

        for item in results:
            prices = item["prices"]
            print(
                f"{item['symbol'][:13]:<14}"
                f"{item['type']:<6}"
                f"{fmt(item['strike']):>12}"
                f"{fmt(item['intrinsic']):>13}"
                f"{fmt(prices['close']['price']):>12}"
                f"{fmt(prices['last']['price']):>12}"
                f"{fmt(prices['bid']['price']):>12}"
                f"{fmt(prices['ask']['price']):>12}"
            )

        # --------------------------------------------------------------
        # 8. Review flags: closing or last price below intrinsic.
        # Bid/ask are included for diagnostic context, not proof of error.
        # --------------------------------------------------------------
        flagged = [
            item for item in results
            if item["intrinsic"] is not None
            and any(
                item["prices"][field]["difference"] is not None
                and item["prices"][field]["difference"] < -TOLERANCE
                for field in ("close", "last")
            )
        ]

        print()
        print("=" * 86)
        print("REVIEW FLAGS: CLOSE OR LAST BELOW INTRINSIC")
        print("=" * 86)
        print(f"Flagged contracts: {len(flagged)}")
        print("-" * 86)

        for item in flagged:
            prices = item["prices"]
            close_diff = prices["close"]["difference"]
            last_diff = prices["last"]["difference"]

            print(
                f"{item['symbol']} | {item['type']} "
                f"| S(close)={fmt(item['underlying_close'])} "
                f"| K={fmt(item['strike'])} "
                f"| Intrinsic={fmt(item['intrinsic'])}"
            )
            print(
                f"    Close={fmt(prices['close']['price'])} "
                f"(diff={fmt(close_diff)})"
            )
            print(
                f"    Last ={fmt(prices['last']['price'])} "
                f"(diff={fmt(last_diff)})"
            )
            print(
                f"    Bid={fmt(prices['bid']['price'])} "
                f"| Ask={fmt(prices['ask']['price'])} "
                f"| Volume={fmt(item['volume'])}"
            )

        print()
        print("=" * 86)
        print("DATA QUALITY NOTES")
        print("=" * 86)
        print(
            "1. Intrinsic value uses the underlying closing price "
            "and API strike price."
        )
        print(
            "2. Closing, last-trade, bid and ask prices are compared "
            "separately."
        )
        print(
            "3. Zero or absent quotes are not treated as executable prices."
        )
        print(
            "4. A below-intrinsic result is a review flag, not proof "
            "of an API defect."
        )
        print(
            "5. Price timestamp differences, stale trades and contract "
            "mapping must be considered before conclusions."
        )
        print("Database writes: NONE")
        print("=" * 86)

    except Exception as exc:
        print()
        print("BR64 FAILED")
        print(f"Error type : {type(exc).__name__}")
        print(f"Error      : {exc}")
        sys.exit(1)

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
