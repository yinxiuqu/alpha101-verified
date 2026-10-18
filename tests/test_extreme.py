"""极端值策略测试：默认 NaN（平台口径）vs 显式 winsorize（保留排序信息）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v.extreme import count_extremes, winsorize_inf


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [[1.0, np.inf, 3.0, -np.inf, np.nan],
         [np.nan, np.nan, np.nan, np.nan, np.nan]],
        index=pd.date_range("2024-01-02", periods=2),
        columns=list("ABCDE"),
    )


def test_winsorize_replaces_inf_with_cross_sectional_extremes():
    out = winsorize_inf(_frame())
    row = out.iloc[0]
    assert row["B"] == 3.0, "+inf 应替换为该截面最大有限值"
    assert row["D"] == 1.0, "-inf 应替换为该截面最小有限值"
    assert row["A"] == 1.0 and row["C"] == 3.0, "有限值不得改动"
    assert np.isnan(row["E"]), "NaN 保持 NaN"


def test_winsorize_leaves_all_nan_row_alone():
    out = winsorize_inf(_frame())
    assert out.iloc[1].isna().all(), "整行无有限值时，无值可依 ⇒ 保持 NaN"


def test_count_extremes_diagnostic():
    stats = count_extremes(_frame())
    assert stats == {"pos_inf": 1, "neg_inf": 1, "nan": 6, "cells": 10}


def test_run_factor_default_is_nan_and_winsorize_is_opt_in():
    """★ 契约：默认不输出 inf（NaN）；显式 winsorize 后 inf 消失但 NaN 数减少。"""
    from alpha101v import registry

    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-02", periods=30)
    cols = [f"S{i}" for i in range(8)]
    close = pd.DataFrame(rng.uniform(10, 20, (30, 8)), index=idx, columns=cols)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.DataFrame(np.maximum(close.to_numpy(), open_.to_numpy()) * 1.01, index=idx, columns=cols)
    low = pd.DataFrame(np.minimum(close.to_numpy(), open_.to_numpy()) * 0.99, index=idx, columns=cols)
    panel = {
        "close": close,
        "Open": open_,
        "high": high,
        "low": low,
        "volume": pd.DataFrame(rng.uniform(1e5, 2e5, (30, 8)), index=idx, columns=cols),
        "vwap": (high + low + close) / 3.0,
        "returns": close.pct_change().fillna(0.0),
    }

    default = registry.run_factor("alpha42", panel)          # rank 相除，会除零
    explicit = registry.run_factor("alpha42", panel, extremes="winsorize")

    assert not np.isinf(default.to_numpy(dtype=float)).any(), "默认输出永不含 ±inf"
    assert not np.isinf(explicit.to_numpy(dtype=float)).any(), "winsorize 后也不含 ±inf"
    assert count_extremes(default)["nan"] >= count_extremes(explicit)["nan"], (
        "winsorize 应把原本因 inf 变成的 NaN 补回有限值（NaN 数不增加）"
    )
