"""L6 辅助统计的**代码正确性**测试（设计文档 §6.7）。

⚠️ 这里测的是**统计代码对不对**（合成面板上有已知答案的情形），
**不是**「因子在 A 股上有没有效」——后者属于 §6.7 的弱参考，且明文不得用来证明实现正确。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("_l6_statistics", ROOT / "tools" / "l6_statistics.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_l6_statistics"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def l6():
    return _tool()


def _panel(values: np.ndarray, days: int | None = None) -> pd.DataFrame:
    days = days or values.shape[0]
    index = pd.date_range("2021-01-04", periods=days, freq="B")
    return pd.DataFrame(values, index=index, columns=[f"S{i}" for i in range(values.shape[1])])


def test_forward_returns_have_no_lookahead(l6):
    """未来 h 日收益：最后 h 行必须是 NaN（否则就是把未来信息混进来了）。"""
    close = _panel(np.arange(1.0, 21.0).reshape(10, 2))
    fwd = l6.forward_returns(close, 3)
    assert fwd.iloc[-3:].isna().all().all()
    assert np.isclose(fwd.iloc[0, 0], close.iloc[3, 0] / close.iloc[0, 0] - 1.0)


def test_spearman_ic_is_exactly_one_when_factor_equals_forward_return(l6):
    """因子 = 未来收益 ⇒ 逐日 IC = 1（排序完全一致）；取负 ⇒ −1。"""
    rng = np.random.default_rng(7)
    future = _panel(rng.normal(size=(30, 12)))
    ic = l6.spearman_ic(future, future)
    assert np.allclose(ic.dropna().to_numpy(), 1.0)
    assert np.allclose(l6.spearman_ic(-future, future).dropna().to_numpy(), -1.0)


def test_spearman_ic_uses_rank_so_monotone_transforms_do_not_change_it(l6):
    """Spearman 只看秩：把因子做严格单调变换（exp）后 IC 不变。"""
    rng = np.random.default_rng(11)
    factor = _panel(rng.normal(size=(25, 20)))
    future = _panel(rng.normal(size=(25, 20)))
    base = l6.spearman_ic(factor, future)
    transformed = l6.spearman_ic(np.exp(factor), future)
    assert np.allclose(base.dropna().to_numpy(), transformed.dropna().to_numpy())


def test_ic_summary_matches_hand_computed_statistics(l6):
    """均值/标准差/IR/t 值/正比例的手算对照。"""
    values = pd.Series([0.1, 0.2, -0.1, 0.3, np.nan])
    summary = l6.ic_summary(values)
    clean = np.array([0.1, 0.2, -0.1, 0.3])
    assert summary["days"] == 4
    assert np.isclose(summary["mean"], clean.mean())
    assert np.isclose(summary["std"], clean.std(ddof=1))
    assert np.isclose(summary["ir"], clean.mean() / clean.std(ddof=1))
    assert np.isclose(summary["t"], clean.mean() / clean.std(ddof=1) * np.sqrt(4))
    assert np.isclose(summary["positive"], 0.75)


def test_vectorized_ic_matches_scipy_day_by_day(l6):
    """★ 向量化实现必须与「逐日 `scipy.stats.spearmanr`」逐点一致。

    这是向量化（换掉十几万次 Python 调用）之后的**等价性证据**——不做这一步，
    提速就等于换了口径。
    """
    from scipy import stats

    rng = np.random.default_rng(3)
    index = pd.date_range("2021-01-04", periods=40, freq="B")
    columns = [f"S{i}" for i in range(25)]
    left = pd.DataFrame(rng.normal(size=(40, 25)), index=index, columns=columns)
    right = pd.DataFrame(rng.normal(size=(40, 25)), index=index, columns=columns)
    # 打洞：制造 NaN 与「有效股票不足 5 只」的日子
    left = left.where(rng.random((40, 25)) > 0.1)
    right = right.where(rng.random((40, 25)) > 0.2)

    fast = l6.spearman_ic(left, right)
    slow = {}
    for day in left.index:
        x, y = left.loc[day], right.loc[day]
        keep = x.notna() & y.notna()
        slow[day] = stats.spearmanr(x[keep], y[keep]).statistic if keep.sum() >= 5 else np.nan
    slow = pd.Series(slow)
    np.testing.assert_allclose(
        fast.to_numpy(dtype=float), slow.to_numpy(dtype=float), rtol=0, atol=1e-12, equal_nan=True
    )


def test_industry_exposure_is_vectorized_but_still_an_anova(l6):
    """行业暴露的向量化实现给出的 sqrt(R²) 必须与逐日手算的 ANOVA 一致。"""
    rng = np.random.default_rng(13)
    index = pd.date_range("2021-01-04", periods=8, freq="B")
    columns = [f"S{i}" for i in range(12)]
    factor = pd.DataFrame(rng.normal(size=(8, 12)), index=index, columns=columns)
    industry = pd.DataFrame([["A"] * 4 + ["B"] * 4 + ["C"] * 4] * 8, index=index, columns=columns)

    fast = l6.industry_exposure(factor, industry)
    manual = {}
    for day in index:
        values, labels = factor.loc[day], industry.loc[day]
        groups = [values[labels == g].to_numpy(dtype=float) for g in ("A", "B", "C")]
        grand = values.to_numpy(dtype=float)
        ss_between = sum(g.size * (g.mean() - grand.mean()) ** 2 for g in groups)
        ss_total = float(((grand - grand.mean()) ** 2).sum())
        manual[day] = float(np.sqrt(ss_between / ss_total))
    np.testing.assert_allclose(
        fast.to_numpy(dtype=float), pd.Series(manual).to_numpy(dtype=float), rtol=1e-12, atol=1e-15
    )


def test_spearman_ic_skips_days_with_too_few_stocks(l6):
    """有效股票少于 5 只的交易日不给 IC（不制造假信号）。"""
    rng = np.random.default_rng(3)
    future = _panel(rng.normal(size=(10, 8)))
    future.iloc[:, 3:] = np.nan
    ic = l6.spearman_ic(future, future)
    assert ic.isna().all()


def test_industry_exposure_is_one_when_factor_is_constant_within_industry(l6):
    """因子在行业内部为常数 ⇒ 变异全部由行业解释 ⇒ sqrt(R²) = 1。

    注意 `industry_exposure` 要求当日至少 10 只有效股票（否则不给值），故这里用 12 只 × 3 行业。
    """
    index = pd.date_range("2021-01-04", periods=6, freq="B")
    columns = [f"S{i}" for i in range(12)]
    industry = pd.DataFrame(
        [["A"] * 4 + ["B"] * 4 + ["C"] * 4] * 6, index=index, columns=columns
    )
    within_constant = pd.DataFrame(
        [[1.0] * 4 + [2.0] * 4 + [3.0] * 4] * 6, index=index, columns=columns
    )
    exposure = l6.industry_exposure(within_constant, industry).dropna()
    assert exposure.size == 6, "行业暴露应在每个交易日都有值"
    assert np.allclose(exposure.to_numpy(), 1.0)

    # 行业之间无差异、行业内部差异很大 ⇒ 行业解释力接近 0
    rng = np.random.default_rng(19)
    scrambled = pd.DataFrame(rng.normal(size=(6, 12)), index=index, columns=columns)
    assert l6.industry_exposure(scrambled, industry).dropna().mean() < 0.6


def test_average_pairwise_pnl_correlation_detects_identical_series(l6):
    """两条完全相同的 PnL 序列 ⇒ 两两相关 = 1（检验相关计算的符号与量级）。"""
    index = pd.date_range("2021-01-04", periods=60, freq="B")
    series = pd.Series(np.linspace(-1.0, 1.0, 60), index=index)
    mean, pairs = l6.average_pairwise_pnl_correlation({"a": series, "b": series})
    assert pairs == 1
    assert np.isclose(mean, 1.0)


def test_factor_pnl_is_cross_sectionally_standardized(l6):
    """PnL 代理用**截面标准化**后的因子：对因子整体加常数或乘正数不改变它。"""
    rng = np.random.default_rng(5)
    factor = _panel(rng.normal(size=(40, 15)))
    future = _panel(rng.normal(size=(40, 15)))
    base = l6.factor_pnl(factor, future)
    shifted = l6.factor_pnl(factor + 100.0, future)
    scaled = l6.factor_pnl(factor * 3.0, future)
    assert np.allclose(base.dropna().to_numpy(), shifted.dropna().to_numpy(), atol=1e-12)
    assert np.allclose(base.dropna().to_numpy(), scaled.dropna().to_numpy(), atol=1e-12)
