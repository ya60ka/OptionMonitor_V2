
# BR89 - Read-only market data quality audit
# Database: OptionMarketDB_V2
# No INSERT / UPDATE / DELETE

import pyodbc
from collections import Counter

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

OPTION_FIELDS = [
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

NONNEGATIVE_FIELDS = [
    "LastPrice", "ClosingPrice", "FirstPrice", "MinPrice",
    "MaxPrice", "YesterdayPrice", "TradeCount", "Volume",
    "TradeValue", "BestBuyPrice", "BestBuyVolume",
    "BestSellPrice", "BestSellVolume", "OpenInterest",
    "UnderlyingLastPrice", "UnderlyingClosePrice", "ContractSize",
]


def show(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def fmt_ids(rows, limit=15):
    ids = [str(row[0]) for row in rows]
    if not ids:
        return "None"
    result = ", ".join(ids[:limit])
    if len(ids) > limit:
        result += f", ... (+{len(ids) - limit} more)"
    return result


def main():
    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
    )

    show("BR89 - MARKET DATA QUALITY AUDIT")
    print(f"Database: {DATABASE}")
    print("Mode: READ ONLY")
    print("No database data will be modified.")

    conn = pyodbc.connect(connection_string, timeout=15)
    conn.autocommit = True

    try:
        cur = conn.cursor()

        # A. Option current data
        columns = [
            "OptionID", "DataDate", "DataTime", "SourceRetrievedAt",
        ] + OPTION_FIELDS

        select_sql = ", ".join(f"[{name}]" for name in columns)
        cur.execute(
            f"SELECT {select_sql} FROM dbo.OptionLiveCurrent"
        )
        rows = cur.fetchall()
        names = [col[0] for col in cur.description]
        data = [dict(zip(names, row)) for row in rows]

        show("A. CURRENT OPTION DATA")
        print(f"Option rows: {len(data)}")
        print(f"Distinct OptionIDs: {len(set(r['OptionID'] for r in data))}")

        if not data:
            print("ERROR: OptionLiveCurrent is empty.")
            return

        # B. Missing values and zeros
        show("B. NULL AND ZERO COUNTS")

        for field in OPTION_FIELDS:
            null_count = sum(r[field] is None for r in data)
            zero_count = sum(
                r[field] is not None and r[field] == 0
                for r in data
            )
            print(
                f"{field:25} NULL={null_count:3}  ZERO={zero_count:3}"
            )

        # C. Negative values in fields expected to be nonnegative
        show("C. NEGATIVE VALUES")

        negative_total = 0
        for field in NONNEGATIVE_FIELDS:
            bad = [
                r for r in data
                if r[field] is not None and r[field] < 0
            ]
            if bad:
                negative_total += len(bad)
                print(
                    f"{field}: {len(bad)} row(s); "
                    f"OptionIDs: {fmt_ids([(r['OptionID'],) for r in bad])}"
                )

        if negative_total == 0:
            print("No negative values found in checked nonnegative fields.")

        # D. Price relationships
        show("D. PRICE CONSISTENCY")

        invalid_minmax = [
            r for r in data
            if r["MinPrice"] is not None
            and r["MaxPrice"] is not None
            and r["MinPrice"] > 0
            and r["MaxPrice"] > 0
            and r["MinPrice"] > r["MaxPrice"]
        ]
        print(f"MinPrice > MaxPrice: {len(invalid_minmax)}")
        if invalid_minmax:
            print("  OptionIDs:", fmt_ids(
                [(r["OptionID"],) for r in invalid_minmax]
            ))

        last_outside_range = [
            r for r in data
            if r["LastPrice"] is not None
            and r["MinPrice"] is not None
            and r["MaxPrice"] is not None
            and r["LastPrice"] > 0
            and r["MinPrice"] > 0
            and r["MaxPrice"] > 0
            and not (r["MinPrice"] <= r["LastPrice"] <= r["MaxPrice"])
        ]
        print(
            "LastPrice outside [MinPrice, MaxPrice]: "
            f"{len(last_outside_range)}"
        )
        if last_outside_range:
            print("  OptionIDs:", fmt_ids(
                [(r["OptionID"],) for r in last_outside_range]
            ))

        crossed_book = [
            r for r in data
            if r["BestBuyPrice"] is not None
            and r["BestSellPrice"] is not None
            and r["BestBuyPrice"] > 0
            and r["BestSellPrice"] > 0
            and r["BestBuyPrice"] > r["BestSellPrice"]
        ]
        print(
            "BestBuyPrice > BestSellPrice (both positive): "
            f"{len(crossed_book)}"
        )
        if crossed_book:
            print("  OptionIDs:", fmt_ids(
                [(r["OptionID"],) for r in crossed_book]
            ))

        missing_bid = [
            r for r in data
            if r["BestBuyPrice"] is None or r["BestBuyPrice"] == 0
        ]
        missing_ask = [
            r for r in data
            if r["BestSellPrice"] is None or r["BestSellPrice"] == 0
        ]
        print(f"Missing/zero best-buy price: {len(missing_bid)}")
        print(f"Missing/zero best-sell price: {len(missing_ask)}")

        # E. Timestamps and contract metadata
        show("E. TIMESTAMPS AND CONTRACT METADATA")

        source_times = Counter(str(r["SourceRetrievedAt"]) for r in data)
        data_dates = Counter(str(r["DataDate"]) for r in data)
        data_times = Counter(str(r["DataTime"]) for r in data)

        print(f"Distinct SourceRetrievedAt values: {len(source_times)}")
        print(f"Distinct DataDate values: {len(data_dates)}")
        print(f"Distinct DataTime values: {len(data_times)}")
        print(f"Missing SourceRetrievedAt: {sum(r['SourceRetrievedAt'] is None for r in data)}")
        print(f"Missing DataDate: {sum(r['DataDate'] is None for r in data)}")
        print(f"Missing DataTime: {sum(r['DataTime'] is None for r in data)}")
        print(f"Missing/zero ContractSize: {sum(r['ContractSize'] is None or r['ContractSize'] == 0 for r in data)}")

        if source_times:
            print("SourceRetrievedAt values:")
            for value, count in source_times.most_common(5):
                print(f"  {value}: {count} row(s)")

        # F. Underlying current data
        show("F. UNDERLYING CURRENT DATA")

        cur.execute("""
            SELECT UnderlyingID, DataDate, DataTime,
                   LastPrice, ClosingPrice, YesterdayPrice,
                   PriceChange, PriceChangePercent,
                   TradeCount, Volume, TradeValue,
                   SourceRetrievedAt, UpdatedAt
            FROM dbo.UnderlyingLiveCurrent
        """)

        underlying_rows = cur.fetchall()
        underlying_names = [col[0] for col in cur.description]
        underlying_data = [
            dict(zip(underlying_names, row))
            for row in underlying_rows
        ]

        print(f"Underlying rows: {len(underlying_data)}")

        for r in underlying_data:
            for field, value in r.items():
                print(f"{field}: {value}")

        # G. Summary, without treating valid zeros as errors
        show("G. AUDIT SUMMARY")

        checks = [
            ("Exactly 84 option rows", len(data) == 84),
            ("84 distinct OptionIDs", len(set(r["OptionID"] for r in data)) == 84),
            ("Exactly one underlying current row", len(underlying_data) == 1),
            ("No negative values in checked fields", negative_total == 0),
            ("No MinPrice/MaxPrice inversions", len(invalid_minmax) == 0),
            ("No LastPrice outside reported range", len(last_outside_range) == 0),
        ]

        for label, passed in checks:
            print(f"[{'PASS' if passed else 'REVIEW'}] {label}")

        print("\nInterpretation:")
        print("- NULL and zero values are reported, not automatically treated as errors.")
        print("- Crossed bid/ask prices are flagged for review, not auto-corrected.")
        print("- This audit checks consistency, not whether every API field is mapped correctly.")
        print("\nBR89 FINISHED - READ ONLY")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
