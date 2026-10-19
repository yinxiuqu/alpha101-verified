"""`ts_argmax` / `ts_argmin` 向量化的**逐位精确**等价（整数索引 ⇒ 应完全相等）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v import operators as op


def _reference(df: pd.DataFrame, window, *, which: str, basis="days_ago") -> pd.DataFrame:
    kernel = op._argmax_1based if which == "max" else op._argmin_1based
    frame, w = op._prep_win(df, window)
    pos = frame.rolling(window=w, min_periods=w).apply(kernel, raw=True)
    return op._shift_arg_basis(pos, w, basis)


def _panel(seed=0, n=120, m=20, nan_frac=0.0, ties=False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    data = rng.normal(size=(n, m))
    if ties:
        data = np.round(data, 0)          # 制造大量并列（考验「取最早」规则）
    if nan_frac:
        data[rng.random(data.shape) < nan_frac] = np.nan
    return pd.DataFrame(data, index=idx, columns=[f"S{i}" for i in range(m)])


@pytest.mark.parametrize("which", ["max", "min"])
@pytest.mark.parametrize("basis", ["days_ago", "window_start"])
@pytest.mark.parametrize("window", [2, 3, 5, 10])
@pytest.mark.parametrize("panel_kwargs", [dict(), dict(ties=True), dict(nan_frac=0.1)])
def test_exact_equality(which, basis, window, panel_kwargs):
    frame = _panel(**panel_kwargs)
    fast = getattr(op, "ts_argmax" if which == "max" else "ts_argmin")(frame, window, basis=basis).to_numpy()
    ref = _reference(frame, window, which=which, basis=basis).to_numpy()
    assert np.array_equal(np.isnan(fast), np.isnan(ref)), "NaN 掩码必须逐位相同"
    both = ~np.isnan(fast) & ~np.isnan(ref)
    assert np.array_equal(fast[both], ref[both]), "整数索引必须逐位相等（含并列取最早的规则）"


def test_ties_take_earliest():
    """并列时取**最早出现**（与 np.argmax 一致）：全等窗口 ⇒ days_ago = window-1（最老）。"""
    frame = pd.DataFrame({"A": [5.0, 5.0, 5.0, 5.0]}, index=pd.date_range("2024-01-01", periods=4))
    out = op.ts_argmax(frame, 3)
    assert out["A"].iloc[-1] == 2.0, "3 期窗口全等 ⇒ 最老的那期（days_ago=2）"
