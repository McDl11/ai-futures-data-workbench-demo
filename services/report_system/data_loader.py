import sqlite3
from pathlib import Path

import pandas as pd

from config import DB_PATH, DEFAULT_EXCHANGES


class FuturesDataLoader:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f'Database not found: {self.db_path}')

    def connect(self):
        return sqlite3.connect(self.db_path)

    def read_sql(self, sql, params=None):
        with self.connect() as conn:
            return pd.read_sql_query(sql, conn, params=params or {})

    def scalar(self, sql, params=None):
        with self.connect() as conn:
            row = conn.execute(sql, params or {}).fetchone()
            return row[0] if row else None

    def is_trading_day(self, date_str):
        rows = self.read_sql(
            """
            select is_open
            from trade_cal
            where cal_date = :date
              and exchange in ({})
            """.format(','.join(f"'{ex}'" for ex in DEFAULT_EXCHANGES)),
            {'date': date_str},
        )
        if rows.empty:
            return False

        return rows['is_open'].astype(str).eq('1').any()

    def latest_trade_date(self, up_to=None):
        if up_to:
            return self.scalar(
                """
                select max(trade_date)
                from fut_daily
                where trade_date <= :up_to
                """,
                {'up_to': up_to},
            )
        return self.scalar('select max(trade_date) from fut_daily')

    def previous_trade_date(self, trade_date):
        return self.scalar(
            """
            select max(trade_date)
            from fut_daily
            where trade_date < :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_fut_basic(self):
        return self.read_sql(
            """
            select ts_code, symbol, name, fut_code, exchange, fut_type
            from fut_basic
            """
        )

    def get_daily(self, trade_date):
        return self.read_sql(
            """
            select *
            from fut_daily
            where trade_date = :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_mapping(self, trade_date):
        return self.read_sql(
            """
            select ts_code, trade_date, mapping_ts_code
            from fut_mapping
            where trade_date = :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_ft_limit(self, trade_date):
        return self.read_sql(
            """
            select *
            from ft_limit
            where trade_date = :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_settle(self, trade_date):
        return self.read_sql(
            """
            select *
            from fut_settle
            where trade_date = :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_holding(self, trade_date):
        return self.read_sql(
            """
            select *
            from fut_holding
            where trade_date = :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_wsr(self, trade_date):
        return self.read_sql(
            """
            select *
            from fut_wsr
            where trade_date = :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_index_daily(self, trade_date):
        return self.read_sql(
            """
            select *
            from index_daily
            where trade_date = :trade_date
            """,
            {'trade_date': trade_date},
        )

    def get_latest_shibor(self, up_to):
        return self.read_sql(
            """
            select *
            from shibor
            where date <= :date
            order by date desc
            limit 2
            """,
            {'date': up_to},
        )

    def get_latest_fx(self, up_to):
        return self.read_sql(
            """
            select *
            from fx_daily
            where trade_date <= :date
            order by trade_date desc
            limit 2
            """,
            {'date': up_to},
        )

    def get_latest_sge(self, up_to, codes=None):
        if codes:
            placeholders = ','.join(f"'{code}'" for code in codes)
            code_filter = f'and ts_code in ({placeholders})'
        else:
            code_filter = ''
        return self.read_sql(
            f"""
            select *
            from sge_daily
            where trade_date = (
                select max(trade_date) from sge_daily where trade_date <= :date
            )
            {code_filter}
            """,
            {'date': up_to},
        )

    def get_latest_macro(self):
        cpi = self.read_sql('select * from cn_cpi order by month desc limit 1')
        ppi = self.read_sql('select * from cn_ppi order by month desc limit 1')
        pmi = self.read_sql('select * from cn_pmi order by month desc limit 1')
        return {'cpi': cpi, 'ppi': ppi, 'pmi': pmi}
