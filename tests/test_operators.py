"""算子层用例：覆盖设计文档 §8 的 A 组（时序）、B 组（截面）、中性化组。

判据（§6.2）：20/20 通过，数值对拍容差 ``rtol = 1e-10``；这一层没有「大概对」。

本文件同时是「口径即测试」的落地处：``docs/operators.md`` 里每一处歧义点决策
在下面都有对应断言（ddof / pct / argmax 基准 / scale 轴向 / 常数序列相关系数 /
并列策略 / 严格预热）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata

import alpha101v
from alpha101v import operators as ops
from alpha101v.neutralize import ind_neutralize, neu_industry, neutral

# ---------------------------------------------------------------------------
# 公共夹具与断言工具
# ---------------------------------------------------------------------------

#: §8.1 的单序列样例 ``[1,2,3,4,5]``
X5 = pd.DataFrame({"s": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=pd.date_range("2020-01-06", periods=5, freq="B"))

#: §8.2 的单日截面样例 ``[10,20,30,40]``
ROW = pd.DataFrame([[10.0, 20.0, 30.0, 40.0]], index=[pd.Timestamp("2021-01-04")], columns=list("ABCD"))

#: 中性化组样例：4 个交易日 × 6 只股票（3 个行业 × 2 只），数值固定以保证可复现
C_PANEL = pd.DataFrame(
    [
        [0.5, -1.2, 2.0, 0.3, -0.7, 1.1],
        [1.0, 0.4, -0.5, 2.2, 0.9, -1.3],
        [-0.2, 1.7, 0.8, -1.5, 0.6, 0.1],
        [2.4, -0.6, 1.3, 0.7, -1.9, 0.5],
    ],
    index=pd.date_range("2021-01-04", periods=4, freq="B"),
    columns=list("ABCDEF"),
)
C_IND = pd.Series(["银行", "银行", "医药", "医药", "白酒", "白酒"], index=list("ABCDEF"))


def seq(values, name: str = "s", start: str = "2020-01-06") -> pd.DataFrame:
    """把列表包成单列面板（index = 连续交易日）。"""
    return pd.DataFrame(
        {name: [float(v) for v in values]},
        index=pd.date_range(start, periods=len(values), freq="B"),
    )


def values(result: pd.DataFrame) -> np.ndarray:
    """取单列算子的数值结果。"""
    assert isinstance(result, pd.DataFrame), f"算子必须返回 DataFrame，收到 {type(result).__name__}"
    assert result.shape[1] == 1
    return result.to_numpy(dtype=float).ravel()


def assert_allclose(actual, expected, rtol: float = 1e-10, atol: float = 0.0) -> None:
    np.testing.assert_allclose(
        np.asarray(actual, dtype=float), np.asarray(expected, dtype=float),
        rtol=rtol, atol=atol, equal_nan=True,
    )


# ---------------------------------------------------------------------------
# 0. 公开算子面（§7.3 + §8.1 + §8.3 = 恰好 20 个）
# ---------------------------------------------------------------------------


def test_api_surface_is_exactly_twenty():
    """公开算子面恰好 20 个，且与设计文档 §7.3/§8 一一对应。"""
    expected = {
        "ts_sum", "sma", "stddev", "correlation", "covariance", "ts_rank", "product",
        "ts_min", "ts_max", "delta", "delay", "rank", "scale", "ts_argmax", "ts_argmin",
        "decay_linear", "rolling_rank", "ind_neutralize", "neu_industry", "neutral",
    }
    assert len(alpha101v.OPERATORS) == 20, alpha101v.OPERATORS
    assert set(alpha101v.OPERATORS) == expected
    for name in alpha101v.OPERATORS:
        assert callable(getattr(alpha101v, name)), f"{name} 未在包命名空间导出或不可调用"


def test_operators_return_dataframe_and_preserve_axes():
    """契约：输入 DataFrame → 输出 DataFrame，且 index/columns 原样保留。"""
    panel = C_PANEL.copy()
    calls = {
        "ts_sum": lambda: ops.ts_sum(panel, 3),
        "sma": lambda: ops.sma(panel, 3),
        "stddev": lambda: ops.stddev(panel, 3),
        "correlation": lambda: ops.correlation(panel, panel.shift(1).fillna(0.0), 3),
        "covariance": lambda: ops.covariance(panel, panel.shift(1).fillna(0.0), 3),
        "ts_rank": lambda: ops.ts_rank(panel, 3),
        "product": lambda: ops.product(panel, 2),
        "ts_min": lambda: ops.ts_min(panel, 3),
        "ts_max": lambda: ops.ts_max(panel, 3),
        "delta": lambda: ops.delta(panel, 1),
        "delay": lambda: ops.delay(panel, 1),
        "rank": lambda: ops.rank(panel),
        "scale": lambda: ops.scale(panel),
        "ts_argmax": lambda: ops.ts_argmax(panel, 3),
        "ts_argmin": lambda: ops.ts_argmin(panel, 3),
        "decay_linear": lambda: ops.decay_linear(panel, 3),
        "ind_neutralize": lambda: ind_neutralize(panel, C_IND),
        "neu_industry": lambda: neu_industry(panel, C_IND),
        "neutral": lambda: neutral(panel, panel.shift(1).fillna(0.0)),
    }
    for name, call in calls.items():
        out = call()
        assert isinstance(out, pd.DataFrame), name
        assert out.index.equals(panel.index), name
        assert out.columns.equals(panel.columns), name


def test_series_input_is_treated_as_single_column_panel():
    """Series 语法糖：视为单列面板，输出仍是 DataFrame（契约单一）。"""
    series = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2020-01-06", periods=3, freq="B"), name="px")
    out = ops.ts_sum(series, 2)
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == ["px"]
    assert_allclose(values(out), [np.nan, 3.0, 5.0])


# ---------------------------------------------------------------------------
# A 组：时间序列算子（§8.1）
# ---------------------------------------------------------------------------


def test_a01_ts_sum():
    """``ts_sum(x, 3)`` → ``[NaN, NaN, 6, 9, 12]``（前 window-1 为 NaN）。"""
    assert_allclose(values(ops.ts_sum(X5, 3)), [np.nan, np.nan, 6.0, 9.0, 12.0])


def test_a02_sma():
    """``sma(x, 3)`` → ``[NaN, NaN, 2, 3, 4]``（等权）。"""
    assert_allclose(values(ops.sma(X5, 3)), [np.nan, np.nan, 2.0, 3.0, 4.0])


def test_a03_stddev_default_is_ddof1():
    """★ 歧义点 ddof：默认 ``ddof=1`` → ``[NaN, NaN, 1, 1, 1]``。"""
    assert_allclose(values(ops.stddev(X5, 3)), [np.nan, np.nan, 1.0, 1.0, 1.0])


def test_a04_stddev_ddof0():
    """``ddof=0``（总体口径）→ ``0.81649658...``，与 numpy ``std(ddof=0)`` 对拍。"""
    expected = np.sqrt(2.0 / 3.0)
    assert_allclose(values(ops.stddev(X5, 3, ddof=0)), [np.nan, np.nan, expected, expected, expected])
    for i in range(2, 5):
        window = X5["s"].to_numpy()[i - 2 : i + 1]
        assert np.isclose(np.std(window, ddof=0), expected, rtol=1e-12)


def test_a05_stddev_rejects_undefined_ddof():
    """ddof 只放行 0/1，其余显式报错（防止静默口径漂移）。"""
    with pytest.raises(ValueError, match="ddof"):
        ops.stddev(X5, 3, ddof=2)


def test_a06_delta_period1_and_period2():
    """``delta(x, 1)`` → ``[NaN, 1, 1, 1, 1]``；``delta(x, 2)`` → ``[NaN, NaN, 2, 2, 2]``。"""
    assert_allclose(values(ops.delta(X5, 1)), [np.nan, 1.0, 1.0, 1.0, 1.0])
    assert_allclose(values(ops.delta(X5, 2)), [np.nan, np.nan, 2.0, 2.0, 2.0])


def test_a07_delay():
    """``delay(x, 2)`` → ``[NaN, NaN, 1, 2, 3]``。"""
    assert_allclose(values(ops.delay(X5, 2)), [np.nan, np.nan, 1.0, 2.0, 3.0])


def test_a08_ts_min_and_ts_max():
    """``ts_min(x, 3)`` → ``[NaN, NaN, 1, 2, 3]``；``ts_max(x, 3)`` → ``[NaN, NaN, 3, 4, 5]``。"""
    assert_allclose(values(ops.ts_min(X5, 3)), [np.nan, np.nan, 1.0, 2.0, 3.0])
    assert_allclose(values(ops.ts_max(X5, 3)), [np.nan, np.nan, 3.0, 4.0, 5.0])


def test_a09_product():
    """``product(x, 2)`` → ``[NaN, 2, 6, 12, 20]``。"""
    assert_allclose(values(ops.product(X5, 2)), [np.nan, 2.0, 6.0, 12.0, 20.0])


def test_a10_ts_rank_ordinal_and_pct():
    """★ 歧义点 pct：``ts_rank([1,2,3], 3)`` 末值 → 序号口径 3；pct 口径 1.0。

    默认口径是 ``pct=True``（与截面 rank 同量纲）。
    """
    x3 = seq([1, 2, 3])
    assert_allclose(values(ops.ts_rank(x3, 3)), [np.nan, np.nan, 1.0])  # 默认 pct=True
    assert_allclose(values(ops.ts_rank(x3, 3, pct=True)), [np.nan, np.nan, 1.0])
    assert_allclose(values(ops.ts_rank(x3, 3, pct=False)), [np.nan, np.nan, 3.0])


def test_a11_ts_rank_pct_range_and_midrank():
    """pct 口径值域 ⊆ (0, 1]，中间值的名次为 ``序号/窗口``。"""
    x5 = seq([5, 1, 4, 2, 3])
    pct = values(ops.ts_rank(x5, 5))
    # 窗口末值 = 3，在 [5,1,4,2,3] 中名次为 3（average 法无并列）→ 3/5
    assert_allclose(pct[-1], 3.0 / 5.0)
    assert np.all((pct[4:] > 0) & (pct[4:] <= 1))


def test_a12_ts_argmax_default_basis_is_window_start():
    """★ 歧义点 argmax 基准：默认自窗口起点 1-based，``[1,3,2]`` → 2。"""
    x3 = seq([1, 3, 2])
    assert_allclose(values(ops.ts_argmax(x3, 3)), [np.nan, np.nan, 2.0])


def test_a13_ts_argmax_days_ago_basis():
    """``basis="days_ago"``（官方 BRAIN 口径：今天=0）→ ``[1,3,2]`` → 1。"""
    x3 = seq([1, 3, 2])
    assert_allclose(values(ops.ts_argmax(x3, 3, basis="days_ago")), [np.nan, np.nan, 1.0])


def test_a14_ts_argmax_direction_and_ties():
    """方向覆盖：最新值是最大值 → 3 / 0；最旧值是最大值 → 1 / 2；并列取最早出现。"""
    assert_allclose(values(ops.ts_argmax(seq([1, 2, 3]), 3)), [np.nan, np.nan, 3.0])
    assert_allclose(values(ops.ts_argmax(seq([1, 2, 3]), 3, basis="days_ago")), [np.nan, np.nan, 0.0])
    assert_allclose(values(ops.ts_argmax(seq([3, 2, 1]), 3)), [np.nan, np.nan, 1.0])
    assert_allclose(values(ops.ts_argmax(seq([3, 2, 1]), 3, basis="days_ago")), [np.nan, np.nan, 2.0])
    assert_allclose(values(ops.ts_argmax(seq([2, 2, 1]), 3)), [np.nan, np.nan, 1.0])


def test_a15_ts_argmax_rejects_unknown_basis():
    with pytest.raises(ValueError, match="basis"):
        ops.ts_argmax(seq([1, 2, 3]), 3, basis="midpoint")


def test_a16_ts_argmin():
    """``ts_argmin([3,1,2], 3)`` → 自起点 2 / 距今 1。"""
    x3 = seq([3, 1, 2])
    assert_allclose(values(ops.ts_argmin(x3, 3)), [np.nan, np.nan, 2.0])
    assert_allclose(values(ops.ts_argmin(x3, 3, basis="days_ago")), [np.nan, np.nan, 1.0])
    assert_allclose(values(ops.ts_argmin(seq([2, 2, 3]), 3)), [np.nan, np.nan, 1.0])


def test_a17_decay_linear_weights():
    """``decay_linear([1,2,3], 3)`` = ``(1·1+2·2+3·3)/6 = 14/6``，末值权重最大。"""
    assert_allclose(values(ops.decay_linear(seq([1, 2, 3]), 3)), [np.nan, np.nan, 14.0 / 6.0])


def test_a18_decay_linear_matches_np_average():
    """逐窗口与 ``np.average(w, weights=1..d)`` 对拍（权重恰为 1..d / (d(d+1)/2)）。"""
    rng = np.random.default_rng(20261009)
    x = pd.DataFrame(rng.normal(size=(12, 2)), index=pd.date_range("2020-01-06", periods=12, freq="B"))
    period = 5
    out = ops.decay_linear(x, period)
    weights = np.arange(1, period + 1, dtype=float)
    arr = x.to_numpy()
    for t in range(period - 1, len(x)):
        for c in range(x.shape[1]):
            window = arr[t - period + 1 : t + 1, c]
            assert np.isclose(out.iloc[t, c], np.average(window, weights=weights), rtol=1e-12)


def test_a19_correlation_perfect_linear():
    """``correlation([1..5],[2,4,6,8,10],3)`` → ``[NaN, NaN, 1, 1, 1]``。"""
    x = seq([1, 2, 3, 4, 5])
    y = seq([2, 4, 6, 8, 10])
    assert_allclose(values(ops.correlation(x, y, 3)), [np.nan, np.nan, 1.0, 1.0, 1.0])


def test_a20_correlation_constant_series_is_nan_not_zero_or_inf():
    """★ 歧义点：常数序列（零方差）→ NaN，**不是 0、也不是 inf**。"""
    x = seq([1, 1, 1])
    y = seq([1, 2, 3])
    out = values(ops.correlation(x, y, 3))
    assert np.isnan(out[-1])
    assert not np.isinf(out[-1])
    assert out[-1] != 0.0


def test_a21_correlation_matches_pandas():
    """与 ``pandas.rolling().corr()`` 逐点 allclose（容差 rtol=1e-10）。"""
    rng = np.random.default_rng(7)
    x = pd.DataFrame(rng.normal(size=(20, 3)), index=pd.date_range("2020-01-06", periods=20, freq="B"))
    y = pd.DataFrame(rng.normal(size=(20, 3)), index=x.index)
    assert_allclose(
        ops.correlation(x, y, 6).to_numpy(),
        x.rolling(6, min_periods=6).corr(y).to_numpy(),
        rtol=1e-10, atol=1e-12,
    )


def test_a22_covariance_matches_pandas_ddof1():
    """``covariance`` 默认 ddof=1，与 ``pandas.rolling().cov()`` 逐点一致。

    注意（文档勘误，见 docs/operators.md §5）：设计文档 §8.1 把该用例的期望写成
    ``1``，实测/推导应为 ``2``：cov([1,2,3],[2,4,6]) = 4 / (3-1) = 2。
    文档同时要求「与 pandas ``rolling().cov()`` 对拍」，此处以后者为准。
    """
    x = seq([1, 2, 3, 4, 5])
    y = seq([2, 4, 6, 8, 10])
    out = values(ops.covariance(x, y, 3))
    assert_allclose(out, [np.nan, np.nan, 2.0, 2.0, 2.0])
    assert_allclose(
        ops.covariance(x, y, 3).to_numpy(),
        x.rolling(3, min_periods=3).cov(y).to_numpy(),
        rtol=1e-10, atol=1e-12,
    )


def test_a23_covariance_ddof0_is_population_identity():
    """ddof=0 由样本协方差按 ``(n-1)/n`` 换算（n = window）。"""
    x = seq([1, 2, 3, 4, 5])
    y = seq([2, 4, 6, 8, 10])
    assert_allclose(values(ops.covariance(x, y, 3, ddof=0)), [np.nan, np.nan, 4.0 / 3.0, 4.0 / 3.0, 4.0 / 3.0])


def test_a24_rolling_rank_matches_scipy_per_window():
    """``rolling_rank`` 与 ``scipy.stats.rankdata(w)[-1]`` 逐窗口一致（§8.1 要求）。"""
    rng = np.random.default_rng(101)
    x = pd.DataFrame(rng.normal(size=(15, 2)), index=pd.date_range("2020-01-06", periods=15, freq="B"))
    assert ops.rolling_rank(np.array([1.0, 3.0, 2.0])) == rankdata([1.0, 3.0, 2.0])[-1]
    # 末值并列 → average 名次（[1,2,2] 的末值名次 = 2.5），与 scipy 默认一致
    assert ops.rolling_rank(np.array([1.0, 2.0, 2.0])) == rankdata([1.0, 2.0, 2.0])[-1] == 2.5
    arr = x.to_numpy()
    for t in range(4, len(x)):
        for c in range(x.shape[1]):
            assert ops.rolling_rank(arr[t - 4 : t + 1, c]) == rankdata(arr[t - 4 : t + 1, c])[-1]


def test_a25_min_periods_strict_warmup_for_every_rolling_operator():
    """★ min_periods 策略：``min_periods = window`` —— 预热期必须是 NaN，不许填值。

    这是变异测试 m7（把 ``ts_sum`` 的 ``min_periods`` 放宽成 1）必须失败的地方；
    也修正了设计文档 §8.4 最后一行的归因（见 docs/operators.md §5）。
    """
    window = 4
    rolling_calls = {
        "ts_sum": lambda d: ops.ts_sum(d, window),
        "sma": lambda d: ops.sma(d, window),
        "stddev": lambda d: ops.stddev(d, window),
        "ts_rank": lambda d: ops.ts_rank(d, window),
        "product": lambda d: ops.product(d, window),
        "ts_min": lambda d: ops.ts_min(d, window),
        "ts_max": lambda d: ops.ts_max(d, window),
        "decay_linear": lambda d: ops.decay_linear(d, window),
        "ts_argmax": lambda d: ops.ts_argmax(d, window),
        "ts_argmin": lambda d: ops.ts_argmin(d, window),
        "correlation": lambda d: ops.correlation(d, d + 1.0, window),
        "covariance": lambda d: ops.covariance(d, d + 1.0, window),
    }
    for name, call in rolling_calls.items():
        out = call(X5)
        assert out.iloc[: window - 1].isna().all().all(), f"{name} 预热期必须为 NaN"
        assert out.iloc[window - 1 :].notna().all().all(), f"{name} 预热期之后应有值"


def test_a26_nan_inside_window_propagates():
    """窗口内出现 NaN → 该点结果为 NaN（严格预热 ⇒ 不做部分窗口近似）。"""
    x = seq([1, 2, np.nan, 4, 5])
    assert_allclose(values(ops.ts_sum(x, 3)), [np.nan, np.nan, np.nan, np.nan, np.nan])
    assert_allclose(values(ops.sma(x, 3)), [np.nan, np.nan, np.nan, np.nan, np.nan])
    assert_allclose(values(ops.ts_rank(x, 3)), [np.nan, np.nan, np.nan, np.nan, np.nan])
    # 窗口滑出 NaN 之后应恢复出值，证明是「窗口内 NaN 传播」而不是整列报废
    x2 = seq([np.nan, 2, 3, 4, 5])
    assert_allclose(values(ops.ts_sum(x2, 3)), [np.nan, np.nan, np.nan, 9.0, 12.0])


def test_a27_window_and_period_validation():
    """窗口/周期参数显式校验（负数、0 窗口、非整数一律报错）。"""
    with pytest.raises(ValueError):
        ops.ts_sum(X5, 0)
    with pytest.raises(TypeError):
        ops.ts_sum(X5, 2.5)
    with pytest.raises(ValueError):
        ops.delta(X5, -1)
    with pytest.raises(ValueError):
        ops.decay_linear(X5, 0)


def test_a28_binary_operators_require_aligned_panels():
    """二元算子要求两块面板 (index, columns) 完全一致，否则显式报错。"""
    x = seq([1, 2, 3])
    y = seq([1, 2, 3], name="other")
    with pytest.raises(ValueError, match="完全一致"):
        ops.correlation(x, y, 2)
    with pytest.raises(ValueError, match="完全一致"):
        ops.covariance(x, y.shift(1), 2)


# ---------------------------------------------------------------------------
# B 组：截面算子（§8.2）
# ---------------------------------------------------------------------------


def test_b01_rank_pct_matches_rankdata_over_n():
    """``rank([10,20,30,40])`` → ``[0.25, 0.5, 0.75, 1.0]``，值域 ⊆ (0, 1]。"""
    out = ops.rank(ROW)
    assert_allclose(out.to_numpy().ravel(), [0.25, 0.5, 0.75, 1.0])
    assert_allclose(out.to_numpy().ravel(), rankdata([10, 20, 30, 40], "average") / 4.0)
    assert np.all((out.to_numpy() > 0) & (out.to_numpy() <= 1))


def test_b02_rank_ties_policy_is_average():
    """★ 歧义点：并列策略默认 ``average`` → ``[10,10,30]`` 得 ``[0.5, 0.5, 1.0]``。

    设计文档 §8.2 把该行期望写成 ``[1/3, 1/3, 1.0]``（标注「average 法」），
    但 ``[1/3, 1/3, 1]`` 实际是 ``min`` 法的结果（文档勘误，见 docs/operators.md §5）。
    本库以「与 ``scipy.stats.rankdata(row, 'average')/n`` 逐点相等」这一条
    文字判据为准（该判据与 §8.2 第一行样例一致），并同时提供 ``method="min"``
    以复现文档字面数值。
    """
    ties = pd.DataFrame([[10.0, 10.0, 30.0]], index=ROW.index, columns=list("ABC"))
    average = ops.rank(ties)
    assert_allclose(average.to_numpy().ravel(), rankdata([10, 10, 30], "average") / 3.0)
    assert_allclose(average.to_numpy().ravel(), [0.5, 0.5, 1.0])
    assert_allclose(ops.rank(ties, method="min").to_numpy().ravel(), [1 / 3, 1 / 3, 1.0])


def test_b03_rank_pct_false_returns_ordinal():
    """``pct=False`` → 序号 1..n（对齐序号口径的参照实现所需）。"""
    assert_allclose(ops.rank(ROW, pct=False).to_numpy().ravel(), [1.0, 2.0, 3.0, 4.0])


def test_b04_rank_keeps_nan_and_ranks_remainder():
    """NaN 不参与排序且保持 NaN；分母是当日有效股票数。"""
    row = pd.DataFrame([[10.0, np.nan, 30.0, 40.0]], index=ROW.index, columns=list("ABCD"))
    out = ops.rank(row).to_numpy().ravel()
    assert np.isnan(out[1])
    assert_allclose(out[[0, 2, 3]], rankdata([10, 30, 40], "average") / 3.0)
    all_nan = pd.DataFrame([[np.nan, np.nan]], index=ROW.index, columns=list("AB"))
    assert ops.rank(all_nan).isna().all().all()


def test_b05_scale_sum_abs_equals_k_per_row():
    """★ 歧义点 scale 轴向：``scale(row, k=1)`` → ``[0.1,0.2,0.3,0.4]``，逐日 Σ|x| == k。

    这正是原始实现按列求和（缺陷 3）必失败的断言。
    """
    out = ops.scale(ROW, k=1)
    assert_allclose(out.to_numpy().ravel(), [0.1, 0.2, 0.3, 0.4])
    assert_allclose(out.abs().sum(axis=1).to_numpy(), [1.0])


def test_b06_scale_k3_and_multi_row():
    """``scale(row, k=3)`` → 每行 ``Σ|x| == 3``（多行多列的每日截面缩放）。"""
    panel = C_PANEL.copy()
    out = ops.scale(panel, k=3)
    assert_allclose(out.abs().sum(axis=1).to_numpy(), [3.0] * len(panel))
    # 缩放不改变符号与相对比例
    assert_allclose(np.sign(out.to_numpy()), np.sign(panel.to_numpy()))
    assert_allclose(out.to_numpy() / out.to_numpy()[:, :1], panel.to_numpy() / panel.to_numpy()[:, :1])


def test_b07_scale_zero_row_is_nan():
    """边界：某日 Σ|x| == 0（全 0 / 全 NaN 行）→ 该日 NaN（0/0 未定义），不抛异常。"""
    panel = pd.DataFrame(
        [[0.0, 0.0, 0.0], [np.nan, np.nan, np.nan], [1.0, -1.0, 2.0]],
        index=pd.date_range("2021-01-04", periods=3, freq="B"),
        columns=list("ABC"),
    )
    out = ops.scale(panel, k=1)
    assert out.iloc[0].isna().all()
    assert out.iloc[1].isna().all()
    assert_allclose(out.iloc[2].abs().sum(), 1.0)


def test_b08_scale_rejects_nonpositive_k():
    with pytest.raises(ValueError, match="k"):
        ops.scale(ROW, k=0)
    with pytest.raises(ValueError, match="k"):
        ops.scale(ROW, k=-1)


# ---------------------------------------------------------------------------
# 中性化组（§8.3）
# ---------------------------------------------------------------------------


def _dummy_panels(labels: pd.Series, like: pd.DataFrame) -> list[pd.DataFrame]:
    """把行业标签展开成「每个行业一个 0/1 面板」的回归元列表。"""
    return [
        pd.DataFrame(
            np.broadcast_to((labels.reindex(like.columns) == g).to_numpy(), like.shape),
            index=like.index, columns=like.columns,
        ).astype(float)
        for g in sorted(labels.dropna().unique())
    ]


def _labels_frame(labels: pd.Series, like: pd.DataFrame) -> pd.DataFrame:
    """把静态行业标签铺成可写的逐日面板（PIT 形态的测试夹具）。"""
    return pd.DataFrame(
        np.tile(labels.to_numpy(), (len(like), 1)), index=like.index, columns=like.columns
    )


def test_c01_ind_neutralize_residual_is_orthogonal_to_industry_dummies():
    """残差在每个行业内求和 ≈ 0，且与行业哑变量内积 ≈ 0（正交性断言）。"""
    resid = ind_neutralize(C_PANEL, C_IND)
    grouped = resid.T.groupby(C_IND).sum().T
    assert_allclose(grouped.to_numpy(), np.zeros_like(grouped.to_numpy()), atol=1e-12)

    dummies = pd.get_dummies(C_IND).astype(float)
    inner = resid.to_numpy() @ dummies.to_numpy()
    assert_allclose(inner, np.zeros_like(inner), atol=1e-12)
    # 每个行业残差均值亦为 0
    means = resid.T.groupby(C_IND).mean().T
    assert_allclose(means.to_numpy(), np.zeros_like(means.to_numpy()), atol=1e-12)


def test_c02_ind_neutralize_matches_statsmodels_residual():
    """与 ``statsmodels.OLS(y, dummies).resid`` 对拍 ``rtol=1e-10``（§8.3 判据）。"""
    sm = pytest.importorskip("statsmodels.api")
    dummies = pd.get_dummies(C_IND).astype(float).to_numpy()
    resid = ind_neutralize(C_PANEL, C_IND)
    for i in range(len(C_PANEL)):
        expected = sm.OLS(C_PANEL.iloc[i].to_numpy(), dummies).fit().resid
        assert_allclose(resid.iloc[i].to_numpy(), expected, rtol=1e-10, atol=1e-12)


def test_c03_ind_neutralize_all_nan_industry_does_not_crash():
    """某行业全部为 NaN → 不崩；残差按显式策略给 NaN（**不得** LinAlgError）。"""
    all_nan = pd.Series([np.nan] * C_PANEL.shape[1], index=C_PANEL.columns)
    out = ind_neutralize(C_PANEL, all_nan)
    assert out.isna().all().all()

    partial = C_IND.copy()
    partial.loc["C"] = np.nan
    out2 = ind_neutralize(C_PANEL, partial)
    assert out2["C"].isna().all()
    assert out2[["A", "B", "D", "E", "F"]].notna().all().all()

    # 某一天整个截面都拿不到行业 → 该日全 NaN，其余日正常
    labels = _labels_frame(C_IND, C_PANEL)
    labels.iloc[1] = np.nan
    out3 = ind_neutralize(C_PANEL, labels)
    assert out3.iloc[1].isna().all()
    assert out3.drop(index=out3.index[1]).notna().all().all()


def test_c04_ind_neutralize_single_member_industry_residuals_are_zero():
    """共线性边界：某行业只有 1 只股票 → 残差恒为 0（行为文档化）。"""
    labels = C_IND.copy()
    labels.loc["A"] = "独苗"
    resid = ind_neutralize(C_PANEL, labels)
    assert_allclose(resid["A"].to_numpy(), np.zeros(len(C_PANEL)), atol=1e-15)


def test_c05_ind_neutralize_pit_industry_panel_matches_manual_daily_grouping():
    """PIT 形态（``industry`` 为逐日 as-of 面板）：逐日标签不同 → 逐日分组计算。"""
    labels = _labels_frame(C_IND, C_PANEL)
    labels.iloc[2, 0] = "医药"  # 第 3 天 A 的行业口径变更（as-of 生效）

    out = ind_neutralize(C_PANEL, labels)
    static = ind_neutralize(C_PANEL, C_IND)
    assert not out.equals(static), "PIT 标签变化必须影响结果（否则说明标签没被逐日使用）"

    manual = C_PANEL.copy().astype(float)
    for i in range(len(C_PANEL)):
        row = C_PANEL.iloc[i]
        groups = labels.iloc[i]
        manual.iloc[i] = (row - row.groupby(groups).transform("mean")).to_numpy()
    assert_allclose(out.to_numpy(), manual.to_numpy(), rtol=1e-12, atol=1e-15)


def test_c06_ind_neutralize_static_series_and_pit_frame_agree_when_labels_constant():
    """静态 Series 与「逐日相同的 DataFrame」必须给出同一结果（两条路径互证）。"""
    labels = _labels_frame(C_IND, C_PANEL)
    assert_allclose(
        ind_neutralize(C_PANEL, labels).to_numpy(),
        ind_neutralize(C_PANEL, C_IND).to_numpy(),
        rtol=1e-12, atol=1e-15,
    )


def test_c07_ind_neutralize_rejects_bad_industry_type():
    with pytest.raises(TypeError, match="Series"):
        ind_neutralize(C_PANEL, ["银行"] * 6)


def test_c08_neu_industry_matches_groupby_transform():
    """``neu_industry`` = ``a / 行业内均值``，与 ``groupby.transform('mean')`` 对拍。"""
    out = neu_industry(C_PANEL, C_IND)
    expected = C_PANEL.div(C_PANEL.T.groupby(C_IND).transform("mean").T)
    assert_allclose(out.to_numpy(), expected.to_numpy(), rtol=1e-12, atol=1e-15)


def test_c09_neu_industry_zero_mean_is_nan():
    """行业均值为 0 → 该格 NaN（比例未定义），不得产生 ±inf。"""
    panel = pd.DataFrame([[1.0, -1.0, 2.0]], index=ROW.index, columns=list("ABC"))
    labels = pd.Series(["x", "x", "y"], index=list("ABC"))
    out = neu_industry(panel, labels)
    assert out.iloc[0, 0] != out.iloc[0, 0]  # 用 x != x 捕获 NaN
    assert np.isnan(out.iloc[0, 0]) and np.isnan(out.iloc[0, 1])
    assert not np.isinf(out.to_numpy()).any()
    assert_allclose(out.iloc[0, 2], 1.0)


def test_c10_neutral_matches_statsmodels_no_intercept():
    """``neutral`` 逐日 OLS 残差（**无隐式截距**），与 statsmodels 对拍 rtol=1e-10。"""
    sm = pytest.importorskip("statsmodels.api")
    dummies = _dummy_panels(C_IND, C_PANEL)
    out = neutral(C_PANEL, dummies)
    design = pd.get_dummies(C_IND).astype(float).to_numpy()
    for i in range(len(C_PANEL)):
        expected = sm.OLS(C_PANEL.iloc[i].to_numpy(), design).fit().resid
        assert_allclose(out.iloc[i].to_numpy(), expected, rtol=1e-10, atol=1e-12)


def test_c11_neutral_equals_ind_neutralize_on_dummies():
    """对哑变量回归的残差 ≡ ``ind_neutralize``（同一数学对象的两种实现，互证）。"""
    dummies = _dummy_panels(C_IND, C_PANEL)
    assert_allclose(
        neutral(C_PANEL, dummies).to_numpy(),
        ind_neutralize(C_PANEL, C_IND).to_numpy(),
        rtol=1e-10, atol=1e-12,
    )


def test_c12_neutral_collinear_dummies_do_not_raise_linalgerror():
    """回归元共线（重复列 + 全 0 列）→ SVD 最小范数解，不抛 LinAlgError，残差不变。

    这是原始实现逐日 ``la.inv`` 会崩的场景（设计文档 §3.3 缺陷 4）。
    """
    dummies = _dummy_panels(C_IND, C_PANEL)
    duplicated = dummies + [dummies[0], pd.DataFrame(0.0, index=C_PANEL.index, columns=C_PANEL.columns)]
    out = neutral(C_PANEL, duplicated)
    assert_allclose(
        out.to_numpy(), ind_neutralize(C_PANEL, C_IND).to_numpy(), rtol=1e-10, atol=1e-12
    )


def test_c13_neutral_single_exposure_matches_formula():
    """单回归元（如市值暴露）情形：残差 = ``y - x·(xᵀy)/(xᵀx)``（无截距）。"""
    exposure = pd.DataFrame(
        [[1.0, 2.0, 4.0, 8.0], [1.0, 1.0, 2.0, 3.0]],
        index=C_PANEL.index[:2], columns=list("ABCD"),
    )
    y = C_PANEL.iloc[:2][["A", "B", "C", "D"]]
    out = neutral(y, exposure)
    for i in range(2):
        x = exposure.iloc[i].to_numpy()
        yy = y.iloc[i].to_numpy()
        expected = yy - x * (x @ yy) / (x @ x)
        assert_allclose(out.iloc[i].to_numpy(), expected, rtol=1e-12, atol=1e-15)


def test_c14_neutral_nan_rows_are_excluded_and_kept_nan():
    """``y`` 或回归元非有限的股票当日不进入回归，其残差为 NaN。"""
    exposure = pd.DataFrame(
        [[1.0, np.nan, 4.0, 8.0]], index=ROW.index, columns=list("ABCD")
    )
    y = pd.DataFrame([[1.0, 2.0, 3.0, np.nan]], index=ROW.index, columns=list("ABCD"))
    out = neutral(y, exposure)
    assert np.isnan(out.iloc[0, 1]) and np.isnan(out.iloc[0, 3])
    x = exposure.iloc[0, [0, 2]].to_numpy()
    yy = y.iloc[0, [0, 2]].to_numpy()
    assert_allclose(out.iloc[0, [0, 2]].to_numpy(), yy - x * (x @ yy) / (x @ x), rtol=1e-12)


def test_c15_neutral_rejects_label_series():
    """把行业标签直接喂给 ``neutral`` 是常见误用 → 显式报错并指路。"""
    with pytest.raises(TypeError, match="ind_neutralize"):
        neutral(C_PANEL, C_IND)
    with pytest.raises(ValueError, match="至少需要一个回归元面板"):
        neutral(C_PANEL, [])
    mismatched = pd.DataFrame(1.0, index=C_PANEL.index[:2], columns=C_PANEL.columns)
    with pytest.raises(ValueError, match="完全一致"):
        neutral(C_PANEL, mismatched)
