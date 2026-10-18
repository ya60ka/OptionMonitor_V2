
# BR66 - OPTION QUOTE CONSISTENCY AUDIT
# READ ONLY - NO DATABASE WRITES

import json
import pyodbc
from decimal import Decimal, InvalidOperation

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
UNDERLYING_CODE = "17914401175772326"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
)


def number(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            return None
        return result
    except (InvalidOperation, ValueError, TypeError):
        return None


def fmt(value):
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def intrinsic(side, underlying, strike):
    if underlying is None or strike is None:
        return None
    if side == "CALL":
        return max(Decimal("0"), underlying - strike)
    return max(Decimal("0"), strike - underlying)


def main():
    print("=" * 100)
    print("BR66 - OPTION QUOTE CONSISTENCY AUDIT")
    print("=" * 100)
    print("Database mode : READ ONLY")
    print("Database writes: NONE")

    connection = pyodbc.connect(CONNECTION_STRING, timeout=15)

    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT TOP (1)
                RawDataID, RetrievedAt, APIName,
                HttpStatusCode, ResponseJSON
            FROM dbo.RawApiResponse
            WHERE IsSuccess = 1
              AND APIName = 'GetInstrumentOptionMarketWatch'
              AND ResponseJSON IS NOT NULL
            ORDER BY RetrievedAt DESC, RawDataID DESC
        """)

        row = cursor.fetchone()
        if not row:
            raise RuntimeError("No successful raw API response found.")

        raw_id, retrieved_at, api_name, http_status, response_json = row

        if isinstance(response_json, bytes):
            response_json = response_json.decode("utf-8")

        payload = json.loads(response_json)
        records = payload.get("instrumentOptMarketWatch", [])

        target = [
            r for r in records
            if str(r.get("uaInsCode", "")) == UNDERLYING_CODE
        ]

        contracts = []

        for record in target:
            underlying_close = number(record.get("pClosing_UA"))
            underlying_last = number(record.get("pDrCotVal_UA"))

            for suffix, side in (("C", "CALL"), ("P", "PUT")):
                code = record.get(f"insCode_{suffix}")
                if code is None:
                    continue

                strike = number(record.get("strikePrice"))
                option_close = number(record.get(f"pClosing_{suffix}"))
                option_last = number(record.get(f"pDrCotVal_{suffix}"))
                bid = number(record.get(f"pMeDem_{suffix}"))
                ask = number(record.get(f"pMeOf_{suffix}"))
                volume = number(record.get(f"qTotTran5J_{suffix}"))
                trade_count = number(record.get(f"zTotTran_{suffix}"))
                trade_value = number(record.get(f"qTotCap_{suffix}"))

                intrinsic_close = intrinsic(
                    side, underlying_close, strike
                )
                intrinsic_last = intrinsic(
                    side, underlying_last, strike
                )

                flags = []

                if bid is not None and ask is not None:
                    if bid > 0 and ask > 0 and bid > ask:
                        flags.append("CROSSED_MARKET")

                if bid is not None and bid > 0 and ask is not None and ask > 0:
                    if option_last is not None and option_last > 0:
                        if option_last < bid or option_last > ask:
                            flags.append("LAST_OUTSIDE_BID_ASK")

                if ask == 0:
                    flags.append("ZERO_ASK")

                if bid == 0:
                    flags.append("ZERO_BID")

                if (
                    option_last is not None
                    and intrinsic_last is not None
                    and option_last < intrinsic_last
                ):
                    flags.append("LAST_BELOW_INTRINSIC_LAST_BASIS")

                if (
                    option_close is not None
                    and intrinsic_close is not None
                    and option_close < intrinsic_close
                ):
                    flags.append("CLOSE_BELOW_INTRINSIC_CLOSE_BASIS")

                if (
                    volume is not None
                    and volume > 0
                    and option_last is not None
                    and intrinsic_last is not None
                    and option_last < intrinsic_last
                ):
                    flags.append("TRADED_BUT_LAST_BELOW_INTRINSIC")

                if (
                    trade_value is not None
                    and volume is not None
                    and volume > 0
                ):
                    implied_average = trade_value / volume / Decimal("1000")
                else:
                    implied_average = None

                contracts.append({
                    "symbol": record.get(f"insCode_{suffix}"),
                    "name": record.get(f"lVal18AFC_{suffix}")
                             or record.get(f"lVal18AFC{suffix}")
                             or str(code),
                    "side": side,
                    "strike": strike,
                    "underlying_close": underlying_close,
                    "underlying_last": underlying_last,
                    "intrinsic_close": intrinsic_close,
                    "intrinsic_last": intrinsic_last,
                    "option_close": option_close,
                    "option_last": option_last,
                    "bid": bid,
                    "ask": ask,
                    "volume": volume,
                    "trade_count": trade_count,
                    "trade_value": trade_value,
                    "implied_average": implied_average,
                    "flags": flags,
                })

        print("\nSOURCE")
        print("-" * 100)
        print(f"RawDataID       : {raw_id}")
        print(f"RetrievedAt     : {retrieved_at}")
        print(f"APIName         : {api_name}")
        print(f"HTTP status     : {http_status}")
        print(f"Underlying rows : {len(target)}")
        print(f"Contracts       : {len(contracts)}")

        checks = {
            "CROSSED_MARKET": 0,
            "LAST_OUTSIDE_BID_ASK": 0,
            "ZERO_BID": 0,
            "ZERO_ASK": 0,
            "LAST_BELOW_INTRINSIC_LAST_BASIS": 0,
            "CLOSE_BELOW_INTRINSIC_CLOSE_BASIS": 0,
            "TRADED_BUT_LAST_BELOW_INTRINSIC": 0,
        }

        for contract in contracts:
            for flag in set(contract["flags"]):
                if flag in checks:
                    checks[flag] += 1

        print("\nSUMMARY")
        print("-" * 100)
        for label, count in checks.items():
            print(f"{label:44}: {count}")

        flagged = [c for c in contracts if c["flags"]]

        print("\nFLAGGED CONTRACTS")
        print("-" * 100)

        for c in sorted(flagged, key=lambda x: str(x["name"])):
            print(
                f"\n{c['name']} | {c['side']} | "
                f"K={fmt(c['strike'])}"
            )
            print(
                f"Underlying close/last : "
                f"{fmt(c['underlying_close'])} / "
                f"{fmt(c['underlying_last'])}"
            )
            print(
                f"Intrinsic close/last  : "
                f"{fmt(c['intrinsic_close'])} / "
                f"{fmt(c['intrinsic_last'])}"
            )
            print(
                f"Option close/last     : "
                f"{fmt(c['option_close'])} / "
                f"{fmt(c['option_last'])}"
            )
            print(
                f"Bid / Ask             : "
                f"{fmt(c['bid'])} / {fmt(c['ask'])}"
            )
            print(
                f"Volume / TradeCount   : "
                f"{fmt(c['volume'])} / {fmt(c['trade_count'])}"
            )
            print(
                f"TradeValue            : {fmt(c['trade_value'])}"
            )
            print(
                f"TradeValue/Volume/1000: {fmt(c['implied_average'])}"
            )
            print("Flags                 : " + ", ".join(c["flags"]))

        print("\n" + "=" * 100)
        print("Interpretation:")
        print("- A last price outside bid/ask is a review flag, not proof of bad data.")
        print("- Zero bid/ask can occur in an illiquid or inactive contract.")
        print("- Intrinsic-value violations require checking timestamps, price units,")
        print("  and market conventions before concluding that the API is defective.")
        print("Database writes: NONE")
        print("=" * 100)

    finally:
        connection.close()


if __name__ == "__main__":
    main()
