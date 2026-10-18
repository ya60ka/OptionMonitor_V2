
# BR45 - First Controlled Off-Hours Snapshot Capture
# Uses the latest BR44 response file.
# All database writes are committed in ONE transaction.
# Old database OptionMarketDB is never accessed.

from pathlib import Path
from datetime import datetime, timezone
# Iran Standard Time: UTC+03:30
from datetime import timedelta
from decimal import Decimal
import json
import sys

import pyodbc


PROJECT_DIR = Path(r"E:\PythonProject\OptionMonitor_V2")
DATA_DIR = PROJECT_DIR / "data" / "api_tests"

SERVER = "localhost"
DATABASE = "OptionMarketDB_V2"
DRIVER = "ODBC Driver 17 for SQL Server"

UNDERLYING_CODE = "17914401175772326"
API_URL = (
    "https://cdn.tsetmc.com/api/Instrument/"
    "GetInstrumentOptionMarketWatch/1"
)
API_NAME = "GetInstrumentOptionMarketWatch"




def log(message, lines=None):
    print(message)
    if lines is not None:
        lines.append(str(message))

def normalize_code(value):
    return "" if value is None else str(value).strip()


def to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        raise ValueError(f"Invalid decimal value: {value!r}")


def to_int(value):
    if value is None or value == "":
        return None

    number = Decimal(str(value))
    if number != number.to_integral_value():
        raise ValueError(f"Expected integer, received: {value!r}")

    return int(number)


def find_api_array(payload):
    if not isinstance(payload, dict):
        raise ValueError("API root is not a JSON object.")

    rows = payload.get("instrumentOptMarketWatch")
    if not isinstance(rows, list):
        raise ValueError(
            "API array $.instrumentOptMarketWatch was not found."
        )

    return rows


def get_field(row, name, side=None):
    key = f"{name}_{side}" if side else name
    return row.get(key)


def percent_change(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) * Decimal("100") / previous


def make_market_values(row, side, contract_size, ua_last, ua_close):
    last = to_decimal(get_field(row, "pDrCotVal", side))
    close = to_decimal(get_field(row, "pClosing", side))
    yesterday = to_decimal(get_field(row, "priceYesterday", side))

    change = (
        last - yesterday
        if last is not None and yesterday is not None
        else None
    )

    return {
        "LastPrice": last,
        "ClosingPrice": close,
        "FirstPrice": None,
        "MinPrice": None,
        "MaxPrice": None,
        "YesterdayPrice": yesterday,
        "PriceChange": change,
        "PriceChangePercent": percent_change(last, yesterday),
        "TradeCount": to_int(get_field(row, "zTotTran", side)),
        "Volume": to_int(get_field(row, "qTotTran5J", side)),
        "TradeValue": to_decimal(get_field(row, "qTotCap", side)),
        "BestBuyPrice": to_decimal(get_field(row, "pMeDem", side)),
        "BestBuyVolume": to_int(get_field(row, "qTitMeDem", side)),
        "BestSellPrice": to_decimal(get_field(row, "pMeOf", side)),
        "BestSellVolume": to_int(get_field(row, "qTitMeOf", side)),
        "OpenInterest": to_int(get_field(row, "oP", side)),
        "UnderlyingLastPrice": ua_last,
        "UnderlyingClosePrice": ua_close,
        "ContractSize": contract_size,
    }


def execute_current_upsert(
    cursor, table, key_column, key_value, columns, values
):
    update_columns = [c for c in columns if c != key_column]

    update_sql = (
        f"UPDATE dbo.{table} SET "
        + ", ".join(f"[{c}] = ?" for c in update_columns)
        + f" WHERE [{key_column}] = ?"
    )

    update_values = [
        values[columns.index(c)] for c in update_columns
    ]
    cursor.execute(update_sql, *(update_values + [key_value]))

    if cursor.rowcount == 0:
        insert_sql = (
            f"INSERT INTO dbo.{table} "
            + "(" + ", ".join(f"[{c}]" for c in columns) + ") "
            + "VALUES (" + ", ".join("?" for _ in columns) + ")"
        )
        cursor.execute(insert_sql, values)


def main():
    lines = []
    connection = None
    report_path = None

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    report_path = DATA_DIR / f"BR45_capture_report_{stamp}.txt"

    log("=" * 78, lines)
    log("BR45 - First Controlled Off-Hours Snapshot Capture", lines)
    log("=" * 78, lines)
    log(f"Database         : {DATABASE}", lines)
    log(f"Underlying code  : {UNDERLYING_CODE}", lines)
    log("Transaction mode : ALL OR NOTHING", lines)
    log("", lines)

    try:
        # ----------------------------------------------------------
        # 1. Locate and validate the newest BR44 response
        # ----------------------------------------------------------
        candidates = sorted(
            DATA_DIR.glob("BR44_live_response_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not candidates:
            raise FileNotFoundError(
                "No BR44_live_response_*.json file was found."
            )

        source_path = candidates[0]
        raw_text = source_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        rows = find_api_array(payload)

        selected_rows = [
            row for row in rows
            if isinstance(row, dict)
            and normalize_code(row.get("uaInsCode")) == UNDERLYING_CODE
            and (
                row.get("insCode_C") is not None
                or row.get("insCode_P") is not None
            )
        ]

        if len(selected_rows) != 42:
            raise ValueError(
                f"Expected 42 underlying rows, found {len(selected_rows)}."
            )

        source_contracts = []
        seen_ids = set()

        for row in selected_rows:
            for side in ("C", "P"):
                code = normalize_code(row.get(f"insCode_{side}"))
                if not code:
                    continue
                if code in seen_ids:
                    raise ValueError(f"Duplicate API contract ID: {code}")
                seen_ids.add(code)
                source_contracts.append((code, side, row))

        if len(source_contracts) != 84:
            raise ValueError(
                f"Expected 84 contracts, found {len(source_contracts)}."
            )

        retrieved_utc = datetime.now(timezone.utc).replace(tzinfo=None)


        retrieved_local = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
        retrieved_local = retrieved_local.replace(tzinfo=None)

        data_date = retrieved_local.date()
        data_time = retrieved_local.time()


        log(f"Source file      : {source_path}", lines)
        log(f"Source rows      : {len(rows)}", lines)
        log(f"Underlying rows  : {len(selected_rows)}", lines)
        log(f"Contracts        : {len(source_contracts)}", lines)
        log(f"Retrieved UTC    : {retrieved_utc}", lines)
        log(f"Data date Tehran : {data_date}", lines)
        log(f"Data time Tehran : {data_time}", lines)

        # ----------------------------------------------------------
        # 2. Connect only to OptionMarketDB_V2
        # ----------------------------------------------------------
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
            autocommit=False,
            timeout=15,
        )
        cursor = connection.cursor()

        cursor.execute("SET XACT_ABORT ON;")

        cursor.execute("""
            SELECT UnderlyingID
            FROM dbo.Underlying
            WHERE TSEInsCode = ?
        """, UNDERLYING_CODE)

        underlying_matches = cursor.fetchall()
        if len(underlying_matches) != 1:
            raise ValueError(
                "Expected exactly one matching underlying in the database."
            )

        underlying_id = underlying_matches[0][0]

        cursor.execute("""
            SELECT OptionID, TSEInsCode, ContractSize
            FROM dbo.OptionContract
            WHERE UnderlyingID = ?
        """, underlying_id)

        db_contracts = {
            normalize_code(r.TSEInsCode): {
                "OptionID": r.OptionID,
                "ContractSize": r.ContractSize,
            }
            for r in cursor.fetchall()
        }

        api_ids = {code for code, _, _ in source_contracts}
        db_ids = set(db_contracts)

        if api_ids != db_ids:
            missing_db = sorted(api_ids - db_ids)
            missing_api = sorted(db_ids - api_ids)
            raise ValueError(
                "API/database contract mismatch. "
                f"Missing in DB={missing_db[:5]}, "
                f"missing in API={missing_api[:5]}"
            )

        log(f"UnderlyingID     : {underlying_id}", lines)
        log(f"DB contract match: PASS ({len(db_contracts)}/84)", lines)

        # ----------------------------------------------------------
        # 3. Validate underlying source values
        # ----------------------------------------------------------
        base_row = selected_rows[0]

        ua_last = to_decimal(base_row.get("pDrCotVal_UA"))
        ua_close = to_decimal(base_row.get("pClosing_UA"))
        ua_yesterday = to_decimal(base_row.get("priceYesterday_UA"))

        if ua_last is None or ua_close is None or ua_yesterday is None:
            raise ValueError(
                "One or more required underlying prices are missing."
            )

        for row in selected_rows:
            if (
                to_decimal(row.get("pDrCotVal_UA")) != ua_last
                or to_decimal(row.get("pClosing_UA")) != ua_close
                or to_decimal(row.get("priceYesterday_UA")) != ua_yesterday
            ):
                raise ValueError(
                    "Underlying price fields are inconsistent between rows."
                )

        ua_change = ua_last - ua_yesterday

        log(f"Underlying last  : {ua_last}", lines)
        log(f"Underlying close : {ua_close}", lines)
        log(f"Underlying prev  : {ua_yesterday}", lines)

        # ----------------------------------------------------------
        # 4. Build and validate snapshot payloads before writing
        # ----------------------------------------------------------
        option_payloads = []

        for code, side, row in source_contracts:
            db_info = db_contracts[code]
            contract_size = to_int(row.get("contractSize"))

            if contract_size is None:
                contract_size = db_info["ContractSize"]

            values = make_market_values(
                row, side, contract_size, ua_last, ua_close
            )

            # Core prices must be present and positive.
            for field in ("LastPrice", "ClosingPrice", "YesterdayPrice"):
                value = values[field]
                if value is None or value <= 0:
                    raise ValueError(
                        f"{code}: invalid {field}={value!r}"
                    )

            option_payloads.append({
                "OptionID": db_info["OptionID"],
                "TSEInsCode": code,
                "values": values,
            })

        log(f"Validated options: {len(option_payloads)}", lines)
        log("Unmapped price extrema: First/Min/Max remain NULL.", lines)
        log("")

        # ----------------------------------------------------------
        # 5. Begin transaction and create collection run
        # ----------------------------------------------------------
        cursor.execute("""
            INSERT INTO dbo.CollectionRun
                (JobName, Status, ItemsRequested, ItemsSucceeded,
                 ItemsFailed, Summary)
            OUTPUT INSERTED.CollectionRunID
            VALUES (?, 'RUNNING', ?, 0, 0, ?)
        """, (
            "BR45_OffHoursCapture",
            86,
            "First off-hours capture from saved BR44 API response.",
        ))

        collection_run_id = cursor.fetchone()[0]
        log(f"CollectionRunID  : {collection_run_id}", lines)

        # Save the complete API response once, not 84 duplicate copies.
        cursor.execute("""
            INSERT INTO dbo.RawApiResponse
                (CollectionRunID, UnderlyingID, OptionID, InsCode,
                 APIName, RequestURL, RetrievedAt, HttpStatusCode,
                 IsSuccess, ErrorMessage, ResponseJSON)
            VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?, NULL, ?)
        """, (
            collection_run_id,
            underlying_id,
            API_NAME,
            API_URL,
            retrieved_utc,
            200,
            True,
            raw_text,
        ))

        # ----------------------------------------------------------
        # 6. Insert option snapshots and update current records
        # ----------------------------------------------------------
        snapshot_columns = [
            "OptionID", "DataDate", "DataTime", "LastPrice",
            "ClosingPrice", "FirstPrice", "MinPrice", "MaxPrice",
            "YesterdayPrice", "PriceChange", "PriceChangePercent",
            "TradeCount", "Volume", "TradeValue", "BestBuyPrice",
            "BestBuyVolume", "BestSellPrice", "BestSellVolume",
            "OpenInterest", "UnderlyingLastPrice",
            "UnderlyingClosePrice", "ContractSize", "SourceRetrievedAt",
        ]

        snapshot_sql = (
            "INSERT INTO dbo.OptionLiveSnapshot ("
            + ", ".join(f"[{c}]" for c in snapshot_columns)
            + ") VALUES ("
            + ", ".join("?" for _ in snapshot_columns)
            + ")"
        )

        current_columns = snapshot_columns + ["UpdatedAt"]

        snapshot_count = 0
        current_count = 0

        for item in option_payloads:
            values = item["values"]

            ordered = [
                item["OptionID"],
                data_date,
                data_time,
                values["LastPrice"],
                values["ClosingPrice"],
                values["FirstPrice"],
                values["MinPrice"],
                values["MaxPrice"],
                values["YesterdayPrice"],
                values["PriceChange"],
                values["PriceChangePercent"],
                values["TradeCount"],
                values["Volume"],
                values["TradeValue"],
                values["BestBuyPrice"],
                values["BestBuyVolume"],
                values["BestSellPrice"],
                values["BestSellVolume"],
                values["OpenInterest"],
                values["UnderlyingLastPrice"],
                values["UnderlyingClosePrice"],
                values["ContractSize"],
                retrieved_utc,
            ]

            cursor.execute(snapshot_sql, ordered)
            snapshot_count += 1

            current_values = ordered + [retrieved_utc]
            execute_current_upsert(
                cursor,
                "OptionLiveCurrent",
                "OptionID",
                item["OptionID"],
                current_columns,
                current_values,
            )
            current_count += 1

        # ----------------------------------------------------------
        # 7. Insert underlying snapshot and update current
        # ----------------------------------------------------------
        ua_trade_count = to_int(base_row.get("zTotTran_UA"))
        ua_volume = to_int(base_row.get("qTotTran5J_UA"))
        ua_trade_value = to_decimal(base_row.get("qTotCap_UA"))

        ua_columns = [
            "UnderlyingID", "DataDate", "DataTime", "LastPrice",
            "ClosingPrice", "YesterdayPrice", "PriceChange",
            "PriceChangePercent", "TradeCount", "Volume",
            "TradeValue", "SourceRetrievedAt",
        ]

        ua_values = [
            underlying_id,
            data_date,
            data_time,
            ua_last,
            ua_close,
            ua_yesterday,
            ua_change,
            percent_change(ua_last, ua_yesterday),
            ua_trade_count,
            ua_volume,
            ua_trade_value,
            retrieved_utc,
        ]

        cursor.execute(
            "INSERT INTO dbo.UnderlyingLiveSnapshot ("
            + ", ".join(f"[{c}]" for c in ua_columns)
            + ") VALUES ("
            + ", ".join("?" for _ in ua_columns)
            + ")",
            ua_values,
        )

        ua_current_columns = ua_columns + ["UpdatedAt"]
        ua_current_values = ua_values + [retrieved_utc]

        execute_current_upsert(
            cursor,
            "UnderlyingLiveCurrent",
            "UnderlyingID",
            underlying_id,
            ua_current_columns,
            ua_current_values,
        )

        # ----------------------------------------------------------
        # 8. Mark the run successful and commit everything
        # ----------------------------------------------------------
        cursor.execute("""
            UPDATE dbo.CollectionRun
            SET FinishedAt = SYSUTCDATETIME(),
                Status = 'SUCCESS',
                ItemsSucceeded = ?,
                ItemsFailed = 0,
                Summary = ?
            WHERE CollectionRunID = ?
        """, (
            snapshot_count + 1,
            (
                f"Captured {snapshot_count} option snapshots and "
                "1 underlying snapshot. Current tables updated."
            ),
            collection_run_id,
        ))

        connection.commit()

        log("")
        log("=" * 78, lines)
        log("BR45 CAPTURE SUCCESS", lines)
        log("=" * 78, lines)
        log(f"CollectionRunID        : {collection_run_id}", lines)
        log("Raw API responses      : 1", lines)
        log(f"Option snapshots       : {snapshot_count}", lines)
        log("Underlying snapshots   : 1", lines)
        log(f"Option current records : {current_count}", lines)
        log("Underlying current     : 1", lines)
        log("Database transaction   : COMMITTED", lines)
        log("Old database touched   : NO", lines)

    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass

        log("", lines)
        log("=" * 78, lines)
        log("BR45 CAPTURE FAILED", lines)
        log(f"Error: {type(exc).__name__}: {exc}", lines)
        log("Database transaction: ROLLED BACK", lines)
        log("No partial transaction changes should remain.", lines)
        raise

    finally:
        if connection is not None:
            connection.close()

        if report_path is not None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "\n".join(lines),
                encoding="utf-8",
            )
            print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
