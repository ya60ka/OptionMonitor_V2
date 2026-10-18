
# BR65 - Corrected Trade Fields and Dual Underlying Price Audit
# READ ONLY - NO DATABASE WRITES

import json
import sys
from decimal import Decimal, InvalidOperation
from collections import Counter

import pyodbc

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
UNDERLYING_INSCODE = "17914401175772326"
TOLERANCE = Decimal("1.00")


def dec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def fmt(value):
    return "N/A" if value is None else f"{value:,.2f}"


def intrinsic(side, underlying, strike):
    if underlying is None or strike is None:
        return None
    if side == "CALL":
        return max(underlying - strike, Decimal("0"))
    if side == "PUT":
        return max(strike - underlying, Decimal("0"))
    return None


def difference(price, intrinsic_value):
    if price is None or intrinsic_value is None:
        return None
    return price - intrinsic_value


def main():
    connection = None

    print("=" * 90)
    print("BR65 - CORRECTED TRADE FIELDS AND DUAL UNDERLYING PRICE AUDIT")
    print("=" * 90)
    print(f"Server          : {SERVER}")
    print(f"Database        : {DATABASE}")
    print("Mode            : READ ONLY")
    print("Database writes : NONE")
    print()

    try:
        connection_string = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={SERVER};DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
        )
        connection = pyodbc.connect(
            connection_string, timeout=15, autocommit=True
        )
        cursor = connection.cursor()

        cursor.execute("""
            SELECT TOP (1)
                RawDataID, RetrievedAt, APIName, HttpStatusCode,
                ResponseJSON
            FROM dbo.RawApiResponse
            WHERE IsSuccess = 1
              AND APIName = 'GetInstrumentOptionMarketWatch'
              AND ResponseJSON IS NOT NULL
            ORDER BY RetrievedAt DESC, RawDataID DESC
        """)
        raw = cursor.fetchone()

        if raw is None:
            raise RuntimeError("No successful raw API response found.")

        raw_id, retrieved_at, api_name, status, raw_json = raw
        if isinstance(raw_json, bytes):
            raw_json = raw_json.decode("utf-8")

        payload = json.loads(raw_json)
        records = payload.get("instrumentOptMarketWatch")

        if not isinstance(records, list):
            raise RuntimeError("API array instrumentOptMarketWatch is missing.")

        target = [
            r for r in records
            if str(r.get("uaInsCode", "")).strip() == UNDERLYING_INSCODE
        ]

        contracts = {}

        for r in target:
            strike = dec(r.get("strikePrice"))
            for side, suffix in (("CALL", "C"), ("PUT", "P")):
                code = r.get(f"insCode_{suffix}")
                if code is None or str(code).strip() == "":
                    continue

                code = str(code).strip()
                contracts[code] = {
                    "code": code,
                    "symbol": str(
                        r.get(f"lVal18AFC_{suffix}", "")
                    ).strip(),
                    "side": side,
                    "strike": strike,
                    "underlying_close": dec(r.get("pClosing_UA")),
                    "underlying_last": dec(r.get("pDrCotVal_UA")),
                    "option_close": dec(r.get(f"pClosing_{suffix}")),
                    "option_last": dec(r.get(f"pDrCotVal_{suffix}")),
                    "bid": dec(r.get(f"pMeDem_{suffix}")),
                    "ask": dec(r.get(f"pMeOf_{suffix}")),
                    # TSETMC field meanings: volume vs. trade count
                    "volume": dec(r.get(f"qTotTran5J_{suffix}")),
                    "trade_count": dec(r.get(f"zTotTran_{suffix}")),
                    "trade_value": dec(r.get(f"qTotCap_{suffix}")),
                }

        cursor.execute("""
            SELECT TSEInsCode
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
        """, 1)
        db_codes = {
            str(row[0]).strip()
            for row in cursor.fetchall()
            if row[0] is not None
        }

        matched = sorted(set(contracts) & db_codes)
        api_only = sorted(set(contracts) - db_codes)
        db_only = sorted(db_codes - set(contracts))

        print("SOURCE")
        print("-" * 90)
        print(f"RawDataID       : {raw_id}")
        print(f"RetrievedAt     : {retrieved_at}")
        print(f"APIName         : {api_name}")
        print(f"HTTP status     : {status}")
        print(f"Raw array items : {len(records)}")
        print(f"Underlying rows : {len(target)}")
        print(f"API contracts   : {len(contracts)}")
        print(f"DB contracts    : {len(db_codes)}")
        print(f"Matched         : {len(matched)}")
        print(f"API only        : {len(api_only)}")
        print(f"DB only         : {len(db_only)}")

        print()
        print("CORRECTED TRADE-FIELD CHECK")
        print("-" * 90)
        print("Volume field      : qTotTran5J")
        print("Trade-count field : zTotTran")
        print("Trade-value field : qTotCap")

        field_stats = Counter()
        for code in matched:
            c = contracts[code]
            if c["volume"] is None:
                field_stats["missing_volume"] += 1
            elif c["volume"] == 0:
                field_stats["zero_volume"] += 1
            else:
                field_stats["positive_volume"] += 1

            if c["trade_count"] is None:
                field_stats["missing_trade_count"] += 1
            elif c["trade_count"] == 0:
                field_stats["zero_trade_count"] += 1
            else:
                field_stats["positive_trade_count"] += 1

            if c["trade_value"] is None:
                field_stats["missing_trade_value"] += 1
            elif c["trade_value"] == 0:
                field_stats["zero_trade_value"] += 1

        for key, value in sorted(field_stats.items()):
            print(f"{key:<30}: {value}")

        print()
        print("DUAL UNDERLYING-PRICE COMPARISON")
        print("-" * 90)
        print(
            f"{'SYMBOL':<14}{'SIDE':<6}{'STRIKE':>11}"
            f"{'S_CLOSE':>12}{'S_LAST':>12}"
            f"{'INTR_CLOSE':>13}{'INTR_LAST':>13}"
        )

        flagged = []
        stats = {
            "close_basis_below": 0,
            "last_basis_below": 0,
            "both_basis_below": 0,
            "close_basis_above": 0,
            "last_basis_above": 0,
        }

        for code in matched:
            c = contracts[code]
            iv_close = intrinsic(
                c["side"], c["underlying_close"], c["strike"]
            )
            iv_last = intrinsic(
                c["side"], c["underlying_last"], c["strike"]
            )

            close_diff = difference(c["option_close"], iv_close)
            last_diff = difference(c["option_last"], iv_last)

            close_below = (
                close_diff is not None and close_diff < -TOLERANCE
            )
            last_below = (
                last_diff is not None and last_diff < -TOLERANCE
            )

            if close_below:
                stats["close_basis_below"] += 1
            elif close_diff is not None:
                stats["close_basis_above"] += 1

            if last_below:
                stats["last_basis_below"] += 1
            elif last_diff is not None:
                stats["last_basis_above"] += 1

            if close_below and last_below:
                stats["both_basis_below"] += 1

            print(
                f"{c['symbol'][:13]:<14}{c['side']:<6}"
                f"{fmt(c['strike']):>11}"
                f"{fmt(c['underlying_close']):>12}"
                f"{fmt(c['underlying_last']):>12}"
                f"{fmt(iv_close):>13}"
                f"{fmt(iv_last):>13}"
            )

            if close_below or last_below:
                flagged.append({
                    **c,
                    "iv_close": iv_close,
                    "iv_last": iv_last,
                    "close_diff": close_diff,
                    "last_diff": last_diff,
                })

        print()
        print("SUMMARY OF INTRINSIC COMPARISONS")
        print("-" * 90)
        for key, value in stats.items():
            print(f"{key:<30}: {value}")

        print()
        print("FLAGGED CONTRACT DETAILS")
        print("-" * 90)

        for c in flagged:
            print(
                f"{c['symbol']} | {c['side']} | "
                f"K={fmt(c['strike'])}"
            )
            print(
                f"  Underlying close/last: "
                f"{fmt(c['underlying_close'])} / "
                f"{fmt(c['underlying_last'])}"
            )
            print(
                f"  Intrinsic close/last: "
                f"{fmt(c['iv_close'])} / {fmt(c['iv_last'])}"
            )
            print(
                f"  Option close/last: "
                f"{fmt(c['option_close'])} / {fmt(c['option_last'])}"
            )
            print(
                f"  Difference close/last: "
                f"{fmt(c['close_diff'])} / {fmt(c['last_diff'])}"
            )
            print(
                f"  Volume={fmt(c['volume'])}; "
                f"TradeCount={fmt(c['trade_count'])}; "
                f"TradeValue={fmt(c['trade_value'])}"
            )
            print(
                f"  Bid={fmt(c['bid'])}; Ask={fmt(c['ask'])}"
            )

        print()
        print("=" * 90)
        print("INTERPRETATION")
        print("=" * 90)
        print(
            "The comparison uses the same API capture for option and "
            "underlying prices."
        )
        print(
            "The corrected volume and trade-count fields are reported "
            "separately."
        )
        print(
            "A below-intrinsic flag is diagnostic only; it does not "
            "establish a data defect."
        )
        print("Database writes: NONE")
        print("=" * 90)

    except Exception as exc:
        print()
        print("BR65 FAILED")
        print(f"{type(exc).__name__}: {exc}")
        sys.exit(1)

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
