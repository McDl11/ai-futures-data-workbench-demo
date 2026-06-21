from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductAlias:
    name: str
    code: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class TableDictionaryEntry:
    table: str
    label: str
    purpose: str
    key_fields: tuple[str, ...]
    notes: tuple[str, ...] = ()


PRODUCT_ALIASES = [
    ProductAlias("鸡蛋", "JD", ("鸡蛋", "jd")),
    ProductAlias("黄金", "AU", ("黄金", "沪金", "au")),
    ProductAlias("白银", "AG", ("白银", "沪银", "ag")),
    ProductAlias("螺纹钢", "RB", ("螺纹", "螺纹钢", "rb")),
    ProductAlias("豆粕", "M", ("豆粕", "m")),
    ProductAlias("玉米", "C", ("玉米", "c")),
    ProductAlias("生猪", "LH", ("生猪", "lh")),
]


TABLE_DICTIONARY = [
    TableDictionaryEntry(
        table="fut_daily",
        label="期货日线行情",
        purpose="查询具体期货合约的历史开高低收、结算价、成交量和持仓量。",
        key_fields=("ts_code", "trade_date", "open", "high", "low", "close", "settle", "vol", "oi"),
        notes=("查某个品种历史行情时，通常先用品种代码筛选合约代码。",),
    ),
    TableDictionaryEntry(
        table="fut_mapping",
        label="主力映射",
        purpose="查询某个品种每天对应的主力或连续合约映射。",
        key_fields=("ts_code", "trade_date", "mapping_ts_code"),
        notes=("查主力连续行情时，先用这里找到 mapping_ts_code，再去 fut_daily 查行情。",),
    ),
    TableDictionaryEntry(
        table="fut_basic",
        label="合约基础信息",
        purpose="查询期货合约名称、交易所、品种代码、上市日期、到期日期和合约乘数。",
        key_fields=("ts_code", "symbol", "exchange", "name", "fut_code", "list_date", "delist_date"),
    ),
    TableDictionaryEntry(
        table="trade_cal",
        label="交易日历",
        purpose="判断某天是不是交易日，查询上一交易日或下一交易日。",
        key_fields=("exchange", "cal_date", "is_open", "pretrade_date"),
    ),
    TableDictionaryEntry(
        table="fut_holding",
        label="持仓排名",
        purpose="查询期货公司成交量、多空持仓排名及变化。",
        key_fields=("trade_date", "symbol", "broker", "vol", "long_hld", "short_hld"),
    ),
    TableDictionaryEntry(
        table="fut_wsr",
        label="仓单日报",
        purpose="查询交易所仓单数量、仓库和仓单变化。",
        key_fields=("trade_date", "symbol", "fut_name", "warehouse", "vol", "vol_chg"),
    ),
    TableDictionaryEntry(
        table="fut_settle",
        label="结算参数",
        purpose="查询手续费、保证金、结算价等合约结算相关参数。",
        key_fields=("ts_code", "trade_date", "settle", "trading_fee", "long_margin_rate", "short_margin_rate"),
    ),
    TableDictionaryEntry(
        table="ft_limit",
        label="涨跌停板",
        purpose="查询期货合约每日涨停价、跌停价和相关比例。",
        key_fields=("trade_date", "ts_code", "name", "up_limit", "down_limit"),
    ),
    TableDictionaryEntry(
        table="index_daily",
        label="期货指数日线",
        purpose="查询期货指数级别的日线行情。",
        key_fields=("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"),
    ),
    TableDictionaryEntry(
        table="shibor",
        label="SHIBOR",
        purpose="查询银行间拆借利率。",
        key_fields=("date", "on", "1w", "2w", "1m", "3m", "6m", "9m", "1y"),
    ),
    TableDictionaryEntry(
        table="fx_daily",
        label="汇率日线",
        purpose="查询外汇买卖报价日线。",
        key_fields=("ts_code", "trade_date", "bid_open", "bid_close", "ask_open", "ask_close"),
    ),
    TableDictionaryEntry(
        table="sge_daily",
        label="黄金现货日线",
        purpose="查询上海黄金交易所现货行情。",
        key_fields=("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"),
    ),
    TableDictionaryEntry(
        table="cn_cpi",
        label="CPI",
        purpose="查询居民消费价格指数。",
        key_fields=("month", "nt_val", "nt_yoy", "nt_mom"),
    ),
    TableDictionaryEntry(
        table="cn_ppi",
        label="PPI",
        purpose="查询工业生产者出厂价格指数。",
        key_fields=("month", "ppi_yoy", "ppi_mom"),
    ),
    TableDictionaryEntry(
        table="cn_pmi",
        label="PMI",
        purpose="查询采购经理指数。",
        key_fields=("month", "pmi010000", "pmi010100"),
    ),
]


def answer_data_dictionary_question(question: str) -> str | None:
    normalized = str(question or "").strip().lower()
    if not normalized:
        return None

    product = _match_product(normalized)
    if product and _wants_history_market(normalized):
        return _product_history_answer(product)

    table = _match_table(normalized)
    if table:
        return _table_answer(table)

    if _wants_table_lookup(normalized):
        return _general_table_lookup_answer()

    return None


def _product_history_answer(product: ProductAlias) -> str:
    return (
        f"{product.name}历史行情主要查 fut_daily 表。\n"
        f"- 品种代码：{product.code}\n"
        "- 关键字段：ts_code、trade_date、open、high、low、close、settle、vol、oi\n"
        "- 如果你要查主力连续行情，先用 fut_mapping 找每天的 mapping_ts_code，再回到 fut_daily 查行情。"
    )


def _table_answer(entry: TableDictionaryEntry) -> str:
    notes = "".join(f"\n- {note}" for note in entry.notes)
    return (
        f"{entry.table} 是{entry.label}表。\n"
        f"- 用途：{entry.purpose}\n"
        f"- 关键字段：{', '.join(entry.key_fields)}"
        f"{notes}"
    )


def _general_table_lookup_answer() -> str:
    entries = [
        "历史日线行情：fut_daily",
        "主力映射：fut_mapping",
        "合约基础信息：fut_basic",
        "交易日历：trade_cal",
        "持仓排名：fut_holding",
        "仓单日报：fut_wsr",
        "涨跌停板：ft_limit",
        "期货指数：index_daily",
    ]
    return "常用查询表：\n- " + "\n- ".join(entries)


def _match_product(question: str) -> ProductAlias | None:
    for product in PRODUCT_ALIASES:
        if any(alias.lower() in question for alias in product.aliases):
            return product
    return None


def _match_table(question: str) -> TableDictionaryEntry | None:
    for entry in TABLE_DICTIONARY:
        if entry.table.lower() in question or entry.label.lower() in question:
            return entry
    return None


def _wants_history_market(question: str) -> bool:
    return any(word in question for word in ("历史行情", "日线", "行情", "价格", "k线", "k 线"))


def _wants_table_lookup(question: str) -> bool:
    return any(word in question for word in ("哪个表", "哪张表", "什么表", "表查", "字段", "数据字典"))
