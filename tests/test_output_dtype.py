"""补丁测试：run_factor 出口 float32 / 无 inf；run_factor_raw 保留 float64。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from alpha101v import FACTOR_DTYPE, run_factor, run_factor_raw


def _panel(days: int = 320, n: int = 5) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2021-01-04", periods=days, freq="B")
    cols = [f"S{i}" for i in range(n)]
    close = pd.DataFrame(30 * np.exp(np.cumsum(rng.normal(0, 0.02, (days, n)), 0)), index=idx, columns=cols)
    op = close * (1 + rng.normal(0, 0.004, (days, n)))
    high = np.maximum(close, op) * 1.004
    low = np.minimum(close, op) * 0.996
    vol = pd.DataFrame(np.abs(rng.normal(2e5, 3e4, (days, n))) + 100, index=idx, columns=cols)
    amt = vol * 100 * (close + op) / 2
    return {
        "close": close, "Open": op, "high": high, "low": low, "volume": vol,
        "amount": amt, "vwap": amt / (vol * 100),
        "returns": close.pct_change(fill_method=None),
        "cap": pd.DataFrame(1e6, index=idx, columns=cols),
        "ind_sector": pd.Series(["A", "A", "B", "B", "B"], index=cols),
        "ind_industry": pd.Series(["A1", "A1", "B1", "B1", "B2"], index=cols),
        "ind_subindustry": pd.Series(["x", "y", "x", "y", "z"], index=cols),
    }


def test_run_factor_is_float32_and_no_inf():
    panel = _panel()
    out = run_factor("alpha84", panel)
    assert out.dtypes.iloc[0] == FACTOR_DTYPE
    assert not np.isinf(out.to_numpy(dtype=np.float64)).any()
    assert out.attrs["factor_dtype"] == "float32"


def test_raw_keeps_float64():
    panel = _panel()
    raw = run_factor_raw("alpha84", panel)
    assert raw.dtypes.iloc[0] == np.dtype(np.float64)


def test_explicit_float64_override():
    panel = _panel()
    out = run_factor("alpha84", panel, dtype=np.float64)
    assert out.dtypes.iloc[0] == np.dtype(np.float64)
