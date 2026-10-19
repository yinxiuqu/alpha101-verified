"""`decay_linear` 向量化实现的**等价性边界**（方案 ①：数学等价，末位按求和顺序可差 ≤1 ulp）。

守三件事：
1. **NaN 掩码逐位相同**（稀疏的零观测掩码、dense 的整窗有效、预热期）；
2. 数值差 ``max|Δ| <= 1e-13`` 且相对差 ``<= 1e-15``（实测约 3 ulp / 3e-16）；
3. 两种 order、dense/sparse、含大量 NaN 与整列全 NaN 的面板都要过。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v import operators as op


def _apply_reference(df: pd.DataFrame, period, *, order="recent_first", dense=False) -> pd.DataFrame:
    """原 ``rolling().apply`` 实现（保留作对照基准，不入生产代码）。"""
    frame, w = op._prep_win(df, period)
    weights = np.arange(1, w + 1, dtype=float) if order == "recent_first" else np.arange(w, 0, -1, dtype=float)
    weights /= weights.sum()
    values = frame if dense else frame.fillna(0.0)
    out = values.rolling(window=w, min_periods=w).apply(lambda win: float(np.sum(win * weights)), raw=True)
    if not dense:
        out = out.mask(frame.notna().rolling(window=w, min_periods=w).sum() == 0)
    return out


def _panel(seed=0, n=200, m=30, nan_frac=0.05, ties=False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    data = rng.normal(size=(n, m)).cumsum(axis=0) + 50
    data[rng.random(data.shape) < nan_frac] = np.nan
    if ties:
        data = np.round(data, 0)
    frame = pd.DataFrame(data, index=idx, columns=[f"S{i}" for i in range(m)])
    frame.iloc[:, 5] = np.nan          # 整列全 NaN（P0-1 场景）
    return frame


@pytest.mark.parametrize("order", ["recent_first", "oldest_first"])
@pytest.mark.parametrize("dense", [False, True])
@pytest.mark.parametrize("window", [3, 5, 10, 20])
@pytest.mark.parametrize("panel_kwargs", [dict(), dict(nan_frac=0.3), dict(ties=True)])
def test_vectorized_matches_apply_reference(order, dense, window, panel_kwargs):
    frame = _panel(**panel_kwargs)
    fast = op.decay_linear(frame, window, order=order, dense=dense).to_numpy()
    ref = _apply_reference(frame, window, order=order, dense=dense).to_numpy()

    assert np.array_equal(np.isnan(fast), np.isnan(ref)), "NaN 掩码必须逐位相同"
    both = ~np.isnan(fast) & ~np.isnan(ref)
    if both.any():
        delta = np.abs(fast[both] - ref[both])
        assert delta.max() <= 1e-13, f"绝对差超界：{delta.max():.3e}"
        rel = delta / np.maximum(np.abs(ref[both]), 1e-300)
        assert rel.max() <= 1e-15, f"相对差超界：{rel.max():.3e}"


def test_zero_observation_still_nan():
    """P0-1 的守护：全 NaN 列在稀疏模式下必须是 NaN（不能是 0.0）。"""
    frame = _panel()
    frame["ALLNAN"] = np.nan
    out = op.decay_linear(frame, 5)
    assert out["ALLNAN"].isna().all()
