"""复权模块用例（**不需要数据库**，纯合成数据）。

复权是 M3 的正确性前置：`returns` 在除权除息日会出现假跳空，直接影响使用 `returns` 的因子。
本文件钉死三件事：参考价公式与「每 10 股」口径、``hfq`` 的**因果性**（``qfq`` 不具备）、
以及价格缩放的字段范围（只动价格，不动量额）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v.adapters.adjust import (
    ADJUST_MODES,
    adjust_price_panels,
    cumulative_factors,
    reference_price,
)

IDX = pd.date_range("2024-01-02", periods=6, freq="B")


def events(code: str, date: pd.Timestamp, **kwargs) -> pd.DataFrame:
    row = {"code": code, "date": date, "fenhong": 0.0, "songzhuangu": 0.0, "peigu": 0.0, "peigujia": 0.0}
    row.update(kwargs)
    return pd.DataFrame([row])


def flat_panel(value: float = 10.0, codes=("S", "T")) -> pd.DataFrame:
    return pd.DataFrame(value, index=IDX, columns=list(codes))


# ---------------------------------------------------------------------------
# 1. 参考价公式（口径即契约）
# ---------------------------------------------------------------------------


def test_reference_price_cash_dividend_uses_per_ten_shares():
    """每 10 股派 10 元 = 1 元/股 ⇒ 前收 10 的参考价 = 9（若误按「每股」会得 0）。"""
    assert reference_price(10.0, 10.0, 0.0, 0.0, 0.0) == pytest.approx(9.0)
    # 用真实案例校验口径：000153 2024-06-07（每10股送4股+派1.5元，前收 7.74）
    assert reference_price(7.74, 1.5, 4.0, 0.0, 0.0) == pytest.approx((7.74 - 0.15) / 1.4, rel=1e-12)


def test_reference_price_bonus_and_rights_issue():
    """送转与配股同时进入分子分母：``R = (C − div + (peigu/10)·配价) / (1 + bonus + peigu)``。"""
    assert reference_price(20.0, 0.0, 10.0, 0.0, 0.0) == pytest.approx(10.0)      # 10 送 10
    assert reference_price(10.0, 0.0, 0.0, 3.0, 5.0) == pytest.approx((10.0 + 0.3 * 5.0) / 1.3)


def test_reference_price_rejects_unpricable_events():
    assert np.isnan(reference_price(0.0, 1.0, 0.0, 0.0, 0.0))
    assert np.isnan(reference_price(np.nan, 1.0, 0.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# 2. 累计因子：口径、归一化、事件定位
# ---------------------------------------------------------------------------


def test_cumulative_factors_hfq_scales_from_event_onwards():
    close = flat_panel()
    factors = cumulative_factors(close, events("S", IDX[2], fenhong=10.0), mode="hfq")
    expected = pd.Series([1, 1, 10 / 9, 10 / 9, 10 / 9, 10 / 9], index=IDX, dtype=float)
    np.testing.assert_allclose(factors["S"].to_numpy(), expected.to_numpy(), rtol=1e-15)
    np.testing.assert_allclose(factors["T"].to_numpy(), np.ones(len(IDX)))  # 无事件股票不受影响


def test_cumulative_factors_qfq_normalizes_to_last_row():
    close = flat_panel()
    hfq = cumulative_factors(close, events("S", IDX[2], fenhong=10.0), mode="hfq")
    qfq = cumulative_factors(close, events("S", IDX[2], fenhong=10.0), mode="qfq")
    assert qfq["S"].iloc[-1] == pytest.approx(1.0)          # 末行 = 1：与原始价一致（展示口径）
    assert hfq["S"].iloc[0] == pytest.approx(1.0)           # 首行 = 1：早期价不动（因果口径）
    ratio = (hfq["S"] / qfq["S"]).to_numpy()
    np.testing.assert_allclose(ratio, np.full(len(IDX), ratio[0]), rtol=1e-15)  # 只差一个常数


def test_event_on_non_trading_day_maps_to_next_trading_day():
    """除权日常落在非交易日（周末）——事件必须映射到**该日或之后第一个交易日**。

    IDX = 2024-01-02(二) … 01-05(五)、01-08(一)、01-09(二)；2024-01-06 是周六，
    因此事件应作用到 **01-08**（``IDX[4]``）那一行。
    """
    close = flat_panel()
    saturday = pd.Timestamp("2024-01-06")
    assert saturday not in IDX
    factors = cumulative_factors(close, events("S", saturday, fenhong=10.0), mode="hfq")
    assert factors["S"].iloc[3] == pytest.approx(1.0)      # 01-05 之前不受影响
    assert factors["S"].iloc[4] == pytest.approx(10 / 9)   # 01-08 起生效


def test_events_before_panel_or_without_prev_close_are_skipped():
    close = flat_panel()
    before = cumulative_factors(close, events("S", IDX[0], fenhong=10.0), mode="hfq")
    np.testing.assert_allclose(before["S"].to_numpy(), np.ones(len(IDX)))  # 首行事件：无前收 ⇒ 跳过
    out_of_range = cumulative_factors(close, events("S", IDX[-1] + pd.Timedelta(days=400)), mode="hfq")
    np.testing.assert_allclose(out_of_range["S"].to_numpy(), np.ones(len(IDX)))


def test_cumulative_factors_validates_mode():
    close = flat_panel()
    assert cumulative_factors(close, None, mode="hfq")["S"].iloc[-1] == 1.0
    with pytest.raises(ValueError, match="mode"):
        cumulative_factors(close, None, mode="split")


def test_hfq_is_causal_qfq_is_not():
    """★ 关键性质：``hfq`` 因子只依赖过去 ⇒ 截断后不变；``qfq`` 依赖未来 ⇒ 截断后改变。

    这正是「默认 hfq、qfq 仅供展示」的理由（设计文档 §9 R3 反前视）。
    """
    close = flat_panel()
    ev = pd.concat([events("S", IDX[2], fenhong=10.0), events("S", IDX[4], songzhuangu=5.0)], ignore_index=True)
    cut = 4
    for mode, should_match in (("hfq", True), ("qfq", False)):
        full = cumulative_factors(close, ev, mode=mode)
        truncated = cumulative_factors(close.iloc[:cut], ev[ev["date"] < IDX[cut]], mode=mode)
        same = np.allclose(
            truncated["S"].to_numpy(), full["S"].iloc[:cut].to_numpy(), rtol=1e-12
        )
        assert same is should_match, f"mode={mode} 的因果性判定不符预期（same={same}）"


# ---------------------------------------------------------------------------
# 3. 价格缩放：只动价格，不动量额；不修改入参
# ---------------------------------------------------------------------------


def test_adjust_price_panels_scales_only_price_fields_and_keeps_inputs():
    panels = {
        "close": flat_panel(10.0), "Open": flat_panel(11.0), "high": flat_panel(12.0),
        "low": flat_panel(9.0), "vwap": flat_panel(10.5), "volume": flat_panel(1000.0),
        "amount": flat_panel(1_000_000.0), "cap": flat_panel(5e5),
    }
    snapshot = {k: v.copy(deep=True) for k, v in panels.items()}
    factors = cumulative_factors(panels["close"], events("S", IDX[2], fenhong=10.0), mode="hfq")
    out = adjust_price_panels(panels, factors)

    for field in ("close", "Open", "high", "low", "vwap"):
        np.testing.assert_allclose(out[field]["S"].to_numpy(), panels[field]["S"].to_numpy() * factors["S"].to_numpy())
    for field in ("volume", "amount", "cap"):
        np.testing.assert_allclose(out[field].to_numpy(), panels[field].to_numpy())  # 量/额/市值不动
    for field, original in snapshot.items():
        pd.testing.assert_frame_equal(panels[field], original)  # 入参一字未改


def test_adjust_modes_are_documented():
    assert ADJUST_MODES == ("none", "hfq", "qfq")
