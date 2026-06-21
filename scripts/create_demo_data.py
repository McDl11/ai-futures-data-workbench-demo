from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "futures.db"


DATES = ["20260612", "20260615", "20260616", "20260617", "20260618"]
EXCHANGES = ["SHFE", "DCE", "CZCE", "INE", "CFFEX"]
PRODUCTS = [
    ("CU.SHF", "CU", "CU", "沪铜主力", "SHFE", 78500, 1.25, 128000, 214000),
    ("RB.SHF", "RB", "RB", "螺纹钢主力", "SHFE", 3360, -0.72, 980000, 1560000),
    ("AU.SHF", "AU", "AU", "沪金主力", "SHFE", 563, 0.38, 152000, 388000),
    ("SC.INE", "SC", "SC", "原油主力", "INE", 612, -1.15, 94000, 122000),
    ("M.DCE", "M", "M", "豆粕主力", "DCE", 3290, 0.82, 760000, 1180000),
    ("TA.CZC", "TA", "TA", "PTA主力", "CZCE", 5860, 1.68, 690000, 1040000),
    ("IF.CFX", "IF", "IF", "沪深300股指主力", "CFFEX", 3620, 0.45, 78000, 92000),
]


def exec_many(conn: sqlite3.Connection, statements: list[str]) -> None:
    for statement in statements:
        conn.execute(statement)


def reset_schema(conn: sqlite3.Connection) -> None:
    tables = [
        "trade_cal",
        "fut_basic",
        "fut_daily",
        "fut_mapping",
        "ft_limit",
        "fut_settle",
        "fut_holding",
        "fut_wsr",
        "index_daily",
        "shibor",
        "fx_daily",
        "sge_daily",
        "cn_cpi",
        "cn_ppi",
        "cn_pmi",
        "report_generation_history",
        "report_send_history",
        "report_recipient_send_history",
        "task_run_history",
    ]
    for table in tables:
        conn.execute(f'drop table if exists "{table}"')


def create_schema(conn: sqlite3.Connection) -> None:
    exec_many(
        conn,
        [
            """
            create table trade_cal (
                exchange text,
                cal_date text,
                is_open text,
                pretrade_date text,
                unique(exchange, cal_date)
            )
            """,
            """
            create table fut_basic (
                ts_code text primary key,
                symbol text,
                exchange text,
                name text,
                fut_code text,
                fut_type text,
                list_date text,
                delist_date text
            )
            """,
            """
            create table fut_daily (
                ts_code text,
                trade_date text,
                pre_close real,
                pre_settle real,
                open real,
                high real,
                low real,
                close real,
                settle real,
                change1 real,
                change2 real,
                vol real,
                amount real,
                oi real,
                oi_chg real
            )
            """,
            """
            create table fut_mapping (
                ts_code text,
                trade_date text,
                mapping_ts_code text
            )
            """,
            """
            create table ft_limit (
                ts_code text,
                trade_date text,
                name text,
                up_limit real,
                down_limit real,
                m_ratio real,
                cont text,
                exchange text
            )
            """,
            """
            create table fut_settle (
                ts_code text,
                trade_date text,
                settle real,
                trading_fee_rate real,
                trading_fee real,
                long_margin_rate real,
                short_margin_rate real
            )
            """,
            """
            create table fut_holding (
                trade_date text,
                symbol text,
                broker text,
                vol real,
                vol_chg real,
                long_hld real,
                long_chg real,
                short_hld real,
                short_chg real
            )
            """,
            """
            create table fut_wsr (
                trade_date text,
                symbol text,
                fut_name text,
                warehouse text,
                vol real,
                vol_chg real,
                unit text
            )
            """,
            """
            create table index_daily (
                ts_code text,
                trade_date text,
                close real,
                change real,
                pct_chg real,
                vol real,
                amount real
            )
            """,
            """
            create table shibor (
                date text,
                "on" real,
                one_w real,
                two_w real,
                one_m real,
                three_m real
            )
            """,
            """
            create table fx_daily (
                ts_code text,
                trade_date text,
                bid_close real,
                ask_close real
            )
            """,
            """
            create table sge_daily (
                ts_code text,
                trade_date text,
                close real,
                pct_change real,
                amount real
            )
            """,
            """
            create table cn_cpi (
                month text,
                nt_yoy real,
                nt_mom real
            )
            """,
            """
            create table cn_ppi (
                month text,
                ppi_yoy real,
                ppi_mp_yoy real
            )
            """,
            """
            create table cn_pmi (
                month text,
                pmi010000 real,
                pmi010100 real,
                pmi010200 real
            )
            """,
            """
            create table report_generation_history (
                id integer primary key autoincrement,
                trade_date text not null,
                report_type text not null,
                generation_status text not null,
                html_path text,
                pdf_path text,
                md_path text,
                report_dir text,
                quality_status text not null,
                quality_detail text,
                generated_at text not null,
                recorded_at text not null,
                output text,
                error text
            )
            """,
            """
            create table report_send_history (
                id integer primary key autoincrement,
                trade_date text not null,
                report_type text not null,
                recipients_key text not null,
                recipients text not null,
                cc text not null,
                status text not null,
                sent_at text not null,
                error text,
                html_path text,
                md_path text,
                pdf_path text
            )
            """,
            """
            create table report_recipient_send_history (
                id integer primary key autoincrement,
                trade_date text not null,
                report_type text not null,
                recipient text not null,
                cc text not null,
                status text not null,
                sent_at text not null,
                error text,
                html_path text,
                md_path text,
                pdf_path text
            )
            """,
            """
            create table task_run_history (
                id integer primary key autoincrement,
                task_type text not null,
                task_name text not null,
                status text not null,
                target_date text,
                detail text,
                started_at text,
                finished_at text not null,
                duration_seconds real,
                output text,
                error text
            )
            """,
        ],
    )


def insert_calendar(conn: sqlite3.Connection) -> None:
    previous = "20260611"
    for date in DATES:
        for exchange in EXCHANGES:
            conn.execute(
                "insert into trade_cal (exchange, cal_date, is_open, pretrade_date) values (?, ?, ?, ?)",
                (exchange, date, "1", previous),
            )
        previous = date


def insert_products(conn: sqlite3.Connection) -> None:
    for ts_code, symbol, fut_code, name, exchange, *_ in PRODUCTS:
        conn.execute(
            """
            insert into fut_basic (ts_code, symbol, exchange, name, fut_code, fut_type, list_date, delist_date)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts_code, symbol, exchange, name, fut_code, "商品期货" if exchange != "CFFEX" else "金融期货", "20240101", "20991231"),
        )


def insert_market_data(conn: sqlite3.Connection) -> None:
    for day_index, date in enumerate(DATES):
        for item_index, (ts_code, symbol, fut_code, name, exchange, base, pct, vol, oi) in enumerate(PRODUCTS):
            drift = (day_index - 2) * (0.004 + item_index * 0.0007)
            close = round(base * (1 + drift + pct / 100 * (0.45 + day_index * 0.08)), 2)
            pre_settle = round(close / (1 + pct / 100), 2)
            open_price = round(pre_settle * (1 + pct / 100 * 0.25), 2)
            high = round(max(open_price, close) * 1.012, 2)
            low = round(min(open_price, close) * 0.988, 2)
            settle = round((high + low + close) / 3, 2)
            day_vol = int(vol * (0.72 + day_index * 0.11 + item_index * 0.025))
            day_oi = int(oi * (0.94 + day_index * 0.018))
            oi_chg = int(day_oi * (pct / 100) * 0.18 + (item_index - 3) * 280)
            amount = round(day_vol * close * 10 / 10000, 2)
            conn.execute(
                """
                insert into fut_daily (
                    ts_code, trade_date, pre_close, pre_settle, open, high, low, close, settle,
                    change1, change2, vol, amount, oi, oi_chg
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_code,
                    date,
                    pre_settle,
                    pre_settle,
                    open_price,
                    high,
                    low,
                    close,
                    settle,
                    round(close - pre_settle, 2),
                    round(settle - pre_settle, 2),
                    day_vol,
                    amount,
                    day_oi,
                    oi_chg,
                ),
            )
            conn.execute(
                "insert into fut_mapping (ts_code, trade_date, mapping_ts_code) values (?, ?, ?)",
                (symbol, date, ts_code),
            )
            conn.execute(
                """
                insert into ft_limit (ts_code, trade_date, name, up_limit, down_limit, m_ratio, cont, exchange)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts_code, date, name, round(pre_settle * 1.08, 2), round(pre_settle * 0.92, 2), 0.08, fut_code, exchange),
            )
            conn.execute(
                """
                insert into fut_settle (
                    ts_code, trade_date, settle, trading_fee_rate, trading_fee, long_margin_rate, short_margin_rate
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts_code, date, settle, 0.0001, 3.0 + item_index, 0.10, 0.10),
            )


def insert_auxiliary_data(conn: sqlite3.Connection) -> None:
    brokers = ["华东期货", "中原期货", "海通期货"]
    warehouses = ["上海库", "广东库", "江苏库"]
    for date in DATES:
        for item_index, (ts_code, symbol, fut_code, name, exchange, base, pct, vol, oi) in enumerate(PRODUCTS):
            for broker_index, broker in enumerate(brokers):
                conn.execute(
                    """
                    insert into fut_holding (
                        trade_date, symbol, broker, vol, vol_chg, long_hld, long_chg, short_hld, short_chg
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        date,
                        symbol,
                        broker,
                        int(vol * (0.08 + broker_index * 0.02)),
                        int((broker_index + 1) * 1200 * (1 if pct >= 0 else -1)),
                        int(oi * (0.06 + broker_index * 0.015)),
                        int((pct * 300) + broker_index * 180),
                        int(oi * (0.055 + broker_index * 0.012)),
                        int((-pct * 260) + broker_index * 140),
                    ),
                )
            for warehouse_index, warehouse in enumerate(warehouses[:2]):
                conn.execute(
                    """
                    insert into fut_wsr (trade_date, symbol, fut_name, warehouse, vol, vol_chg, unit)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        date,
                        fut_code,
                        name.replace("主力", ""),
                        warehouse,
                        int(3000 + item_index * 800 + warehouse_index * 450),
                        int((pct * 90) + warehouse_index * 30),
                        "吨",
                    ),
                )

    for day_index, date in enumerate(DATES):
        conn.execute(
            "insert into index_daily (ts_code, trade_date, close, change, pct_chg, vol, amount) values (?, ?, ?, ?, ?, ?, ?)",
            ("NHCI.NH", date, 1840 + day_index * 7, 7, 0.38 + day_index * 0.04, 1200000 + day_index * 60000, 860000000 + day_index * 25000000),
        )
        conn.execute(
            'insert into shibor (date, "on", one_w, two_w, one_m, three_m) values (?, ?, ?, ?, ?, ?)',
            (date, 1.72 + day_index * 0.01, 1.83, 1.91, 2.03, 2.12),
        )
        conn.execute(
            "insert into fx_daily (ts_code, trade_date, bid_close, ask_close) values (?, ?, ?, ?)",
            ("USDCNH.FX", date, 7.185 + day_index * 0.006, 7.19 + day_index * 0.006),
        )
        conn.execute(
            "insert into sge_daily (ts_code, trade_date, close, pct_change, amount) values (?, ?, ?, ?, ?)",
            ("Au9999.SGE", date, 558 + day_index * 1.8, 0.18 + day_index * 0.03, 220000 + day_index * 8000),
        )

    conn.execute("insert into cn_cpi (month, nt_yoy, nt_mom) values (?, ?, ?)", ("202605", 0.3, -0.1))
    conn.execute("insert into cn_ppi (month, ppi_yoy, ppi_mp_yoy) values (?, ?, ?)", ("202605", -1.4, -1.1))
    conn.execute("insert into cn_pmi (month, pmi010000, pmi010100, pmi010200) values (?, ?, ?, ?)", ("202605", 50.2, 51.1, 49.7))


def insert_demo_history(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        insert into report_generation_history (
            trade_date, report_type, generation_status, html_path, pdf_path, md_path, report_dir,
            quality_status, quality_detail, generated_at, recorded_at, output, error
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "20260618",
            "white",
            "success",
            "services/report_system/reports/20260618/white/demo.html",
            "services/report_system/reports/20260618/white/demo.pdf",
            "services/report_system/reports/20260618/white/demo.md",
            "services/report_system/reports/20260618/white",
            "passed",
            "Demo seed record.",
            "2026-06-18 16:30:00",
            "2026-06-18 16:30:00",
            "",
            "",
        ),
    )
    conn.execute(
        """
        insert into report_send_history (
            trade_date, report_type, recipients_key, recipients, cc, status, sent_at, error, html_path, md_path, pdf_path
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "20260618",
            "white",
            "demo",
            "demo-recipient@example.com",
            "",
            "dry_run",
            "2026-06-18 16:31:00",
            "",
            "services/report_system/reports/20260618/white/demo.html",
            "services/report_system/reports/20260618/white/demo.md",
            "services/report_system/reports/20260618/white/demo.pdf",
        ),
    )
    conn.execute(
        """
        insert into report_recipient_send_history (
            trade_date, report_type, recipient, cc, status, sent_at, error, html_path, md_path, pdf_path
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "20260618",
            "white",
            "demo-recipient@example.com",
            "",
            "dry_run",
            "2026-06-18 16:31:00",
            "",
            "services/report_system/reports/20260618/white/demo.html",
            "services/report_system/reports/20260618/white/demo.md",
            "services/report_system/reports/20260618/white/demo.pdf",
        ),
    )
    conn.execute(
        """
        insert into task_run_history (
            task_type, task_name, status, target_date, detail, started_at, finished_at, duration_seconds, output, error
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "report_generate",
            "自动报告",
            "success",
            "20260618",
            "white demo dry-run",
            "2026-06-18 16:30:00",
            "2026-06-18 16:31:00",
            60,
            "Demo seed task record.",
            "",
        ),
    )


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    with sqlite3.connect(DB_PATH) as conn:
        reset_schema(conn)
        create_schema(conn)
        insert_calendar(conn)
        insert_products(conn)
        insert_market_data(conn)
        insert_auxiliary_data(conn)
        insert_demo_history(conn)
        conn.commit()
    print(f"Created demo database: {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
