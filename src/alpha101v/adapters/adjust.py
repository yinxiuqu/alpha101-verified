"""价格复权（除权除息）——**PIT 安全**版本。

为什么必须有这一层
------------------
``stock_day`` 是**原始价**：除权除息当天价格会「跳空」（送转股/派现），
这不是亏损却会被算成收益率暴跌。实测样例（000153，2024-06-07，每 10 股送 4 股 + 派 1.5 元）::

    前收 7.74 → 当日收 5.61   ⇒ 原始收益率 −27.5%（假信号）

本模块按「除权除息参考价」口径复权，把该跳空抹平（同一例复权收益率 +3.5%）。

口径（实证确定，2026-10-09）
--------------------------
``stock_xdxr`` 的 ``fenhong`` / ``songzhuangu`` / ``peigu`` 是 **每 10 股**口径
（用 6 个真实案例反推参考价，与当日实际收盘的相对误差 0.6%~3.9%；按「每股」解释则偏 44%~85%）::

    R = (C_prev − fenhong/10 + (peigu/10)·peigujia) / (1 + songzhuangu/10 + peigu/10)

累计因子 ``F_t = Π_{e ≤ t} (C_prev,e / R_e)``（≥1，随时间增长）。

**两种模式与它们的关键差别**

* ``hfq``（**本库默认**）：把 ``F`` 归一化到面板**第一行 = 1**（早期价不动、后期价上调）。
  因子只依赖**过去**的除权事件 ⇒ **因果/PIT 安全**，能通过时间截断一致性检验；
* ``qfq``：把 ``F`` 归一化到**最后一行 = 1**（最新价与原始价一致，便于人工核对）。
  它让**全部历史价格**都依赖**未来**的除权事件 ⇒ 全样本 qfq 存在前视
  （``docs/verification.md`` §1.3 的已知限制之一），**仅供展示/回测取价，不用于因子计算**。

两者只差每只股票一个**常数**缩放，因此对 `rank` 型因子无影响，但对跨股**水平型**比较
（如 `alpha41 = sqrt(high·low) − vwap`）会有差异——这正是必须显式选一种口径的原因。

不做什么
--------
* 不改 ``volume`` / ``amount``（成交量额是交易数量，不是价格）；
* 不改 ``cap``（市值口径由调用方声明，见歧义 A19）；
* 不做隐式填充（缺前收的事件跳过并计数，由调用方决定）。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "ADJUST_MODES",
    "PRICE_FIELDS",
    "adjust_price_panels",
    "cumulative_factors",
    "load_xdxr_events",
    "reference_price",
]

#: 允许的复权模式：``none`` 不复权；``hfq`` 后复权（因果，默认）；``qfq`` 前复权（非因果，仅供展示）。
ADJUST_MODES: tuple[str, ...] = ("none", "hfq", "qfq")

#: 需要按同一因子缩放的价格类字段（``vwap`` 是价格，必须一起缩放，否则 `close − vwap` 失去意义）。
PRICE_FIELDS: tuple[str, ...] = ("close", "Open", "high", "low", "vwap")

#: 影响价格连续性的 xdxr 类别（1 = 除权除息）；其余类别（股本变化/送配股上市…）不影响价格。
XDXR_PRICE_CATEGORY = 1

_XDXR_FIELDS = ("fenhong", "songzhuangu", "peigu", "peigujia")


def reference_price(
    prev_close: float, fenhong: float, songzhuangu: float, peigu: float, peigujia: float
) -> float:
    """除权除息参考价 ``R``（字段按**每 10 股**解释）。

    ``R = (C_prev − fenhong/10 + (peigu/10)·peigujia) / (1 + songzhuangu/10 + peigu/10)``

    返回 ``nan`` 表示该事件无法定价（前收非正、R 非正），调用方应跳过。
    """
    if not np.isfinite(prev_close) or prev_close <= 0:
        return float("nan")
    dividend = (0.0 if fenhong is None else float(fenhong)) / 10.0
    bonus = (0.0 if songzhuangu is None else float(songzhuangu)) / 10.0
    rights = (0.0 if peigu is None else float(peigu)) / 10.0
    rights_price = 0.0 if peigujia is None else float(peigujia)
    denominator = 1.0 + bonus + rights
    if denominator <= 0:
        return float("nan")
    ref = (prev_close - dividend + rights * rights_price) / denominator
    return float(ref) if ref > 0 else float("nan")


def load_xdxr_events(
    codes: Iterable[str],
    start: str,
    end: str,
    *,
    uri: str = "mongodb://127.0.0.1:27017",
    database: str = "quantaxis",
    collection: str = "stock_xdxr",
    category: int = XDXR_PRICE_CATEGORY,
    chunk_size: int = 200,
) -> pd.DataFrame:
    """读取区间内的除权除息事件（只读；``pymongo`` 延迟导入）。

    返回列：``code, date, fenhong, songzhuangu, peigu, peigujia``（缺失字段按 0 处理）。
    """
    try:
        import pymongo  # 延迟导入：不进运行时依赖
    except ImportError as exc:  # pragma: no cover
        raise ImportError("读取 xdxr 需要 pymongo：pip install 'alpha101v[mongo]'") from exc

    codes = sorted({str(code) for code in codes})
    if not codes:
        raise ValueError("codes 不能为空")

    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        coll = client[database][collection]
        frames: list[pd.DataFrame] = []
        for offset in range(0, len(codes), chunk_size):
            batch = codes[offset : offset + chunk_size]
            cursor = coll.find(
                {"code": {"$in": batch}, "category": category, "date": {"$gte": start, "$lte": end}},
                {"_id": 0, "code": 1, "date": 1, **{f: 1 for f in _XDXR_FIELDS}},
            )
            frames.append(pd.DataFrame(list(cursor)))
    finally:
        client.close()

    if not frames or all(frame.empty for frame in frames):
        return pd.DataFrame(columns=["code", "date", *_XDXR_FIELDS])

    events = pd.concat(frames, ignore_index=True)
    events["date"] = pd.to_datetime(events["date"])
    for field in _XDXR_FIELDS:
        if field not in events.columns:
            events[field] = np.nan
        events[field] = pd.to_numeric(events[field], errors="coerce")
    return events.sort_values(["date", "code"], ignore_index=True)


def cumulative_factors(
    close: pd.DataFrame, events: pd.DataFrame, *, mode: str = "hfq"
) -> pd.DataFrame:
    """累计复权因子面板（与 ``close`` 同形，逐股票取值）。

    * 事件日若不是交易日，映射到**该日或之后第一个交易日**（用 ``searchsorted``）；
    * 缺少前收（事件在面板首行或之前）的事件**跳过**；
    * ``hfq`` 归一化到首行 = 1（因果）；``qfq`` 归一化到末行 = 1（非因果，仅供展示）。
    """
    if mode not in ADJUST_MODES:
        raise ValueError(f"mode 只接受 {ADJUST_MODES}，收到 {mode!r}")
    if mode == "none":
        return pd.DataFrame(1.0, index=close.index, columns=close.columns)

    factors = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    if events is None or events.empty:
        return factors

    for code, group in events.groupby("code", sort=False):
        if code not in close.columns:
            continue
        series = close[code]
        if series.notna().sum() == 0:
            continue
        multipliers: list[tuple[int, float]] = []
        for row in group.itertuples(index=False):
            position = int(series.index.searchsorted(row.date))
            if position <= 0 or position >= len(series):
                continue  # 面板首行或窗口之外：无前收，跳过
            prev_close = series.iloc[position - 1]
            ref = reference_price(
                prev_close, row.fenhong, row.songzhuangu, row.peigu, row.peigujia
            )
            if not np.isfinite(ref):
                continue
            multipliers.append((position, float(prev_close) / ref))

        if not multipliers:
            continue
        column = np.ones(len(series), dtype=float)
        for position, ratio in multipliers:
            column[position:] *= ratio
        factors[code] = column

    if mode == "qfq":
        tail = factors.iloc[-1].replace(0.0, np.nan)
        factors = factors.div(tail, axis=1).fillna(1.0)
    return factors


def adjust_price_panels(
    panels: dict[str, pd.DataFrame],
    factors: pd.DataFrame,
    *,
    price_fields: Sequence[str] = PRICE_FIELDS,
) -> dict[str, pd.DataFrame]:
    """按累计因子缩放价格类字段，返回**新字典**（不修改入参）。"""
    adjusted = dict(panels)
    for field in price_fields:
        if field in adjusted:
            adjusted[field] = adjusted[field].reindex(
                index=factors.index, columns=factors.columns
            ) * factors
    return adjusted
