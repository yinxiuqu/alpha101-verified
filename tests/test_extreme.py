"""极端值策略测试：默认 NaN（平台口径）vs 显式 winsorize（保留排序信息）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v.extreme import (
    bound_inf,
    count_extremes,
    mask_small_denominator,
    winsorize_inf,
    winsorize_std,
)


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
    assert stats["pos_inf"] == 1 and stats["neg_inf"] == 1
    assert stats["nan"] == 6 and stats["cells"] == 10
    assert stats["huge_finite"] == 0


def test_count_extremes_flags_huge_finite_values():
    """★ 三分类 ②：极小分母产生的巨大**有限**值要被计数（默认路径不处理它，但必须可见）。"""
    frame = pd.DataFrame([[1e15, 2.0, -3e14]], index=[pd.Timestamp("2024-01-02")],
                         columns=list("ABC"))
    stats = count_extremes(frame, huge=1e12)
    assert stats["huge_finite"] == 2
    assert stats["pos_inf"] == 0 and stats["neg_inf"] == 0


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


def test_winsorize_std_clips_to_four_sigma():
    """★ BRAIN 官方口径：clip 到 mean ± 4σ；大但有限的值也会被裁，inf 落到边界，NaN 不动。"""
    normal = pd.DataFrame([[1.0, 2.0, 3.0, 4.0, 5.0]], index=[pd.Timestamp("2024-01-02")],
                          columns=list("ABCDE"))
    mean, spread = 3.0, float(np.std([1, 2, 3, 4, 5]))     # σ = sqrt(2)
    out = winsorize_std(normal, std=1.0)                   # 用 1σ 便于观察裁剪
    row = out.iloc[0]
    assert row["A"] == pytest.approx(mean - 1.0 * spread)
    assert row["E"] == pytest.approx(mean + 1.0 * spread)
    assert row["C"] == pytest.approx(3.0), "区间内的值不得改动"


def test_winsorize_std_keeps_inf_as_nan_by_default():
    """★ 三分类原则 ①：默认口径下 ±inf ⇒ NaN（无法从 inf 区分除零与溢出）。"""
    frame = pd.DataFrame([[1.0, 2.0, np.inf, -np.inf, np.nan]],
                         index=[pd.Timestamp("2024-01-02")], columns=list("ABCDE"))
    row = winsorize_std(frame, std=4.0).iloc[0]
    assert np.isnan(row["C"]) and np.isnan(row["D"]), "默认：±inf 必须变 NaN（不得伪装成极端信号）"
    assert np.isnan(row["E"]), "NaN 不得被填充"


def test_winsorize_std_keep_inf_bound_is_opt_in_for_overflow():
    """★ 三分类原则 ③：显式开启后，inf 才落到截面边界（前提：已确认是溢出）。"""
    frame = pd.DataFrame([[1.0, 2.0, np.inf, -np.inf, np.nan]],
                         index=[pd.Timestamp("2024-01-02")], columns=list("ABCDE"))
    row = winsorize_std(frame, std=4.0, keep_inf_bound=True).iloc[0]
    assert np.isfinite(row["C"]) and np.isfinite(row["D"]), "显式开启后 inf 落到边界"
    assert row["C"] > row["D"], "上界 > 下界"
    assert np.isnan(row["E"])


def test_bound_inf_replaces_with_finite_extremes():
    frame = pd.DataFrame([[1.0, 2.0, np.inf, -np.inf]], index=[pd.Timestamp("2024-01-02")],
                         columns=list("ABCD"))
    row = bound_inf(frame).iloc[0]
    assert row["C"] == 2.0 and row["D"] == 1.0


def test_mask_small_denominator_is_the_compute_layer_fix():
    """★ 三分类原则 ①②：按**分母**掩码，而不是事后猜 inf。"""
    numer = pd.DataFrame([[1.0, 1.0, 1.0]], index=[pd.Timestamp("2024-01-02")], columns=list("ABC"))
    denom = pd.DataFrame([[0.0, 1e-15, 2.0]], index=numer.index, columns=numer.columns)
    out = mask_small_denominator(numer, denom, eps=1e-12)
    row = out.iloc[0]
    assert np.isnan(row["A"]), "分母为 0 ⇒ NaN"
    assert np.isnan(row["B"]), "极小分母（1e-15 ≤ eps）⇒ NaN（巨大有限值不可靠）"
    assert row["C"] == 0.5, "正常分母照常计算"
