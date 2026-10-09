"""MongoDB 面板适配（可选层；``pymongo`` 延迟导入，不进运行时依赖）。

数据源口径（设计文档 §10.2 的实测事实，2026-10-09 再次核对一致）
----------------------------------------------------------------
``stock_day``（本地库 ``quantaxis``）::

    {code: "000001", date: "2024-01-02", date_stamp: 1704124800.0,
     open, high, low, close, vol, amount}

* 原始字段名是 **``vol``**（单位 **手**），**没有 ``vwap`` 字段** ⇒ 按 §7.4 计算：
  ``vwap = amount / (vol * 100)``（amount 单位 **元**）；
* ``date`` 是 ``"YYYY-MM-DD"`` 字符串；``stock_day`` 的索引是 ``(code, date_stamp)``，
  因此本模块按 ``code`` 前缀 + ``date`` 字符串过滤（正确性优先；超大范围查询建议改用
  ``date_stamp`` 区间以完全命中索引）。

``stock_daily_basic``::

    {code, ts_code, date, close, turnover_rate, total_share, float_share,
     free_share, total_mv, circ_mv, limit_status, ...}

* ``total_mv`` / ``circ_mv`` 单位 **万元** ⇒ 作为面板契约里的 ``cap``（单位需显式声明）；
* 索引为 ``(code, date)`` 与 ``(date, code)``，查询较快。

⚠️ 本模块**只读取**，不写入任何集合；也不触碰 QUANTAXIS（设计文档 §10.2 的沙箱陷阱）。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pandas as pd

from ..panel import returns_from_close, vwap_from_amount
from .adjust import ADJUST_MODES, adjust_price_panels, cumulative_factors, load_xdxr_events

__all__ = ["load_cap_panel", "load_panel", "load_price_panels"]

DEFAULT_URI = "mongodb://127.0.0.1:27017"
DEFAULT_DATABASE = "quantaxis"
DEFAULT_DAY_COLLECTION = "stock_day"
DEFAULT_BASIC_COLLECTION = "stock_daily_basic"

#: 复权缓冲：为「除权事件日前收」多取一段历史，再由 load_panel 切回 [start, end]。
_ADJUST_BUFFER_DAYS = 30

#: MongoDB 原始字段名 → 面板字段名（``vol`` → ``volume``，单位仍是「手」）。
DAY_FIELD_MAP: dict[str, str] = {
    "open": "Open",
    "close": "close",
    "high": "high",
    "low": "low",
    "vol": "volume",
    "amount": "amount",
}


def _connect(uri: str):
    try:
        import pymongo  # 延迟导入：适配层不污染运行时依赖
    except ImportError as exc:  # pragma: no cover - 取决于本机环境
        raise ImportError(
            "使用 MongoDB 适配需要 pymongo：pip install 'alpha101v[mongo]'（或 pip install pymongo）"
        ) from exc
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")  # 尽早失败，给出明确错误
    return client


def _fetch_long(
    codes: Sequence[str],
    start: str,
    end: str,
    *,
    uri: str,
    database: str,
    collection: str,
    projection: dict[str, int],
    chunk_size: int,
) -> pd.DataFrame:
    """按 code 分批抓取，返回长表 ``[code, date, ...]``（空结果会显式报错）。"""
    client = _connect(uri)
    try:
        coll = client[database][collection]
        frames: list[pd.DataFrame] = []
        codes = list(codes)
        for offset in range(0, len(codes), chunk_size):
            batch = codes[offset : offset + chunk_size]
            cursor = coll.find(
                {"code": {"$in": batch}, "date": {"$gte": start, "$lte": end}},
                {"_id": 0, **projection},
            )
            frames.append(pd.DataFrame(list(cursor)))
    finally:
        client.close()

    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if raw.empty:
        raise ValueError(
            f"{database}.{collection} 在 {start}~{end} 与给定代码集合上没有数据"
            f"（{len(codes)} 只代码）"
        )
    raw["date"] = pd.to_datetime(raw["date"])
    duplicates = int(raw.duplicated(["date", "code"]).sum())
    if duplicates:
        raw = raw.drop_duplicates(["date", "code"], keep="last")
    return raw.sort_values(["date", "code"], ignore_index=True)


def _to_panels(
    raw: pd.DataFrame, field_map: dict[str, str], dates: pd.DatetimeIndex, codes: list[str]
) -> dict[str, pd.DataFrame]:
    panels: dict[str, pd.DataFrame] = {}
    for source, target in field_map.items():
        if source not in raw.columns:
            raise KeyError(f"数据源缺少字段 {source!r}；实际字段：{sorted(raw.columns)}")
        wide = raw.pivot_table(index="date", columns="code", values=source, aggfunc="last")
        panels[target] = wide.reindex(index=dates, columns=codes)
    return panels


def load_price_panels(
    codes: Iterable[str],
    start: str,
    end: str,
    *,
    uri: str = DEFAULT_URI,
    database: str = DEFAULT_DATABASE,
    collection: str = DEFAULT_DAY_COLLECTION,
    chunk_size: int = 100,
) -> dict[str, pd.DataFrame]:
    """抓取 6 个原始字段面板：``Open/close/high/low/volume(手)/amount(元)``。

    返回的面板共享同一 ``DatetimeIndex``（升序、唯一）与同一列顺序（``codes`` 排序后的列表）。
    """
    codes = sorted({str(code) for code in codes})
    if not codes:
        raise ValueError("codes 不能为空")
    raw = _fetch_long(
        codes, start, end,
        uri=uri, database=database, collection=collection,
        projection={"code": 1, "date": 1, **{f: 1 for f in DAY_FIELD_MAP}},
        chunk_size=chunk_size,
    )
    dates = pd.DatetimeIndex(sorted(raw["date"].unique()))
    return _to_panels(raw, DAY_FIELD_MAP, dates, codes)


def load_cap_panel(
    codes: Iterable[str],
    start: str,
    end: str,
    *,
    field: str = "total_mv",
    uri: str = DEFAULT_URI,
    database: str = DEFAULT_DATABASE,
    collection: str = DEFAULT_BASIC_COLLECTION,
    chunk_size: int = 100,
) -> pd.DataFrame:
    """市值面板（``total_mv`` 万元 / ``circ_mv`` 万元），单位必须由调用方显式声明。"""
    codes = sorted({str(code) for code in codes})
    if not codes:
        raise ValueError("codes 不能为空")
    raw = _fetch_long(
        codes, start, end,
        uri=uri, database=database, collection=collection,
        projection={"code": 1, "date": 1, field: 1},
        chunk_size=chunk_size,
    )
    dates = pd.DatetimeIndex(sorted(raw["date"].unique()))
    return _to_panels(raw, {field: field}, dates, codes)[field]


def load_panel(
    codes: Iterable[str],
    start: str,
    end: str,
    *,
    industry: pd.DataFrame | None = None,
    cap_field: str = "total_mv",
    ffill_cap: bool = False,
    adjust: str = "hfq",
    uri: str = DEFAULT_URI,
    database: str = DEFAULT_DATABASE,
) -> dict[str, pd.DataFrame]:
    """组装符合设计文档 §7.4 契约的面板（9~10 个字段）。

    参数
    ----
    industry : 逐日 **PIT** 行业标签面板（``index``=交易日, ``columns``=股票代码），
        由 :func:`alpha101v.adapters.industry.load_sw_industry` 生成；传入则附带 ``ind``。
    ffill_cap : 是否对 ``cap`` 做**前向填充**。默认 ``False``（缺就是 NaN）。
        置 ``True`` 是**允许的**：市值是「当日已知量」，前向填充只用过去的信息，
        不构成前视（设计文档 §9 R3 针对的是未来信息）；但这是调用方的显式选择。
    adjust : ``"hfq"``（默认，**因果/PIT 安全**）/ ``"qfq"``（仅供展示，全样本使用时含前视）/
        ``"none"``（不做复权，除权日会出现假跳空）。见 :mod:`alpha101v.adapters.adjust`。

    复权流程：为了算「除权日前收」，内部会**多取 30 个自然日**的缓冲，
    复权后再切回 ``[start, end]``，因此返回面板的日期区间严格等于请求区间。
    复权只作用于价格类字段（``close/Open/high/low/vwap``）；``volume/amount/cap`` 保持原值，
    ``returns`` 由**复权后**的 ``close`` 计算（这正是复权的目的）。
    """
    codes = sorted({str(code) for code in codes})
    if adjust not in ADJUST_MODES:
        raise ValueError(f"adjust 只接受 {ADJUST_MODES}，收到 {adjust!r}")

    buffer_start = (pd.Timestamp(start) - pd.Timedelta(days=_ADJUST_BUFFER_DAYS)).strftime("%Y-%m-%d")
    panels = load_price_panels(codes, buffer_start, end, uri=uri, database=database)
    panels["vwap"] = vwap_from_amount(panels["amount"], panels["volume"])

    if adjust == "none":
        factors = cumulative_factors(panels["close"], None, mode="none")
    else:
        events = load_xdxr_events(codes, buffer_start, end, uri=uri, database=database)
        factors = cumulative_factors(panels["close"], events, mode=adjust)
    panels = adjust_price_panels(panels, factors)

    keep = panels["close"].index >= pd.Timestamp(start)
    if not keep.any():
        raise ValueError(f"{start}~{end} 区间内没有交易日数据")
    panels = {name: frame.loc[keep] for name, frame in panels.items()}
    panels["returns"] = returns_from_close(panels["close"])

    index, columns = panels["close"].index, panels["close"].columns
    cap = load_cap_panel(codes, start, end, field=cap_field, uri=uri, database=database)
    cap = cap.reindex(index=index, columns=columns)
    if ffill_cap:
        cap = cap.ffill()
    panels["cap"] = cap

    if industry is not None:
        panels["ind"] = industry.reindex(index=index, columns=columns)

    # 统一 index/columns（各面板必须共享同一契约；由 panel.validate_panel 再复核）
    return {name: frame.reindex(index=index, columns=columns) for name, frame in panels.items()}
