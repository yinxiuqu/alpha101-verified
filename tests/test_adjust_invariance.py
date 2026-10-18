"""L7 调用方式不变性 + 复权层最小复现（**不需要 MongoDB**，纯合成数据）。

这一层专门挡两个真实 bug（用户审计 2026-10-18 的 A 与 B）：

* **A**：`prev_close = series.iloc[position-1]` 在停牌日取到 NaN ⇒ 除权事件被静默当 1.0
  ⇒ 同一股票「单独请求」与「和别的股票一起请求」得到不同的复权价；
* **B**：hfq 锚在**面板首行** ⇒ 同一日期的复权价随窗口起点变化。

现有 L1–L6 都在「单次调用、固定窗口」下验证，测不到这两类问题——所以单独补这一层。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v.adapters.adjust import cumulative_factors


def _close(codes=("A", "B"), days=8, suspend: dict[str, list[int]] | None = None) -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=days, freq="B")
    frame = pd.DataFrame(
        {code: np.linspace(100.0, 107.0, days) for code in codes}, index=index
    )
    for code, positions in (suspend or {}).items():
        frame.loc[frame.index[positions], code] = np.nan
    return frame


def _event(date: str, code: str = "A", songzhuangu: float = 10.0) -> pd.DataFrame:
    """一条 10 送 10 的 xdxr 事件（送转 10 股 ⇒ 参考价 = prev_close / 2）。"""
    return pd.DataFrame({
        "date": [pd.Timestamp(date)], "code": [code],
        "fenhong": [0.0], "songzhuangu": [songzhuangu],
        "peigu": [0.0], "peigujia": [0.0],
    })


def test_prev_close_skips_suspension_days():
    """★ bug A：除权日前几天停牌时，前收必须取「之前最后一个非 NaN 收盘」，不能丢弃该事件。"""
    days = 8
    close = _close(days=days, suspend={"A": [3, 4]})   # A 在第 4/5 行停牌（NaN）
    # 事件落在停牌之后的第一天（第 6 行）⇒ 前收应取第 3 行（最后有效）
    events = _event(close.index[5].strftime("%Y-%m-%d"))
    factors = cumulative_factors(close, events, mode="hfq")

    affected = factors["A"].iloc[5]
    assert not np.isclose(affected, 1.0), (
        "除权事件被静默丢弃了（factors 仍为 1.0）—— 说明 prev_close 取到了 NaN"
    )
    # 10 送 10 ⇒ 参考价 = 前收 / 2 ⇒ 因子 = 前收 / 参考价 = 2.0（此后各行都 ×2）
    assert np.allclose(factors["A"].iloc[5:].to_numpy(), 2.0)


def test_batch_invariance():
    """★ L7：同一只股票「单独请求」与「与其它股票一起请求」的复权因子必须逐位相同。"""
    close_all = _close(codes=("A", "B"), suspend={"A": [3, 4]})
    close_solo = close_all[["A"]]
    events = _event(close_all.index[5].strftime("%Y-%m-%d"))

    solo = cumulative_factors(close_solo, events, mode="hfq", anchor_date=close_all.index[-1])
    multi = cumulative_factors(close_all, events, mode="hfq", anchor_date=close_all.index[-1])
    np.testing.assert_array_equal(solo["A"].to_numpy(), multi["A"].to_numpy())


def test_anchor_invariance_across_windows():
    """★ L7：给定同一 anchor_date，长窗口与短窗口在重叠区间的复权因子必须逐位相同。"""
    close = _close(days=12)
    events = _event(close.index[6].strftime("%Y-%m-%d"))
    anchor = close.index[-1]

    full = cumulative_factors(close, events, mode="hfq", anchor_date=anchor)
    short = cumulative_factors(close.iloc[4:], events, mode="hfq", anchor_date=anchor)
    overlap = short.index.intersection(full.index)
    np.testing.assert_allclose(
        full.loc[overlap, "A"].to_numpy(), short.loc[overlap, "A"].to_numpy(),
        rtol=0, atol=1e-12, equal_nan=True,
    )


def test_without_anchor_is_window_dependent_but_documented():
    """不给 anchor_date 时保留历史语义（hfq 锚面板首行）⇒ **窗口依赖**，这是有意的兼容行为。"""
    close = _close(days=12)
    events = _event(close.index[6].strftime("%Y-%m-%d"))
    # 关键：窗口起点必须**晚于事件**，才会暴露「锚首行」的窗口依赖
    # （若窗口仍包含该事件，hfq 的值在重叠区间恰好一致，测试就测不出问题）
    full = cumulative_factors(close, events, mode="hfq")
    short = cumulative_factors(close.iloc[8:], events, mode="hfq")
    overlap = short.index.intersection(full.index)
    differs = not np.allclose(
        full.loc[overlap, "A"].to_numpy(), short.loc[overlap, "A"].to_numpy(), equal_nan=True
    )
    assert differs, "不传 anchor 时应保留『锚面板首行』的历史语义（窗口依赖）"
    # 但显式 anchor 后就必须一致 —— 这条区分是 API 契约的一部分
    a = cumulative_factors(close, events, mode="hfq", anchor_date=close.index[-1])
    b = cumulative_factors(close.iloc[8:], events, mode="hfq", anchor_date=close.index[-1])
    np.testing.assert_allclose(
        a.loc[overlap, "A"].to_numpy(), b.loc[overlap, "A"].to_numpy(), rtol=0, atol=1e-12
    )
