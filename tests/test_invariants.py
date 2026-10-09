"""不变量与元测试（设计文档 §6.5 的**算子层**落点，M1）。

⚠️ 逻辑定位（§6.5 原文）：以下是**必要条件，不是充分条件**——
**通不过一定错，通过了不代表对。**

覆盖：
* 输入不可变性（专治 §3.3 缺陷 2 的原地改写入参）
* 时间截断一致性（PIT 金标准：``[0,T]`` 与 ``[0,t]`` 在 t 处必须逐点完全相等）
* 未来扰动（篡改 t 之后的数据，t 及之前不得改变）
* 缩放不变性（排序型算子对正数缩放不变）
* 脏数据（NaN / 0）不崩且不产生 ±inf

本文件不碰因子层（M2 起才有因子）；全部对象都是算子。
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from alpha101v import operators as ops
from alpha101v import panel as panel_contract
from alpha101v.neutralize import ind_neutralize, neu_industry, neutral

# ---------------------------------------------------------------------------
# 夹具：确定性面板（固定种子，任何人重跑都得到同一份数据）
# ---------------------------------------------------------------------------

DAYS = 40
CUT = 25
COLS = list("ABCD")

_RNG = np.random.default_rng(20260101)
BASE = pd.DataFrame(
    _RNG.normal(loc=10.0, scale=2.0, size=(DAYS, len(COLS))),
    index=pd.date_range("2021-01-04", periods=DAYS, freq="B"),
    columns=COLS,
)
EXPOSURE = pd.DataFrame(
    _RNG.normal(size=(DAYS, len(COLS))), index=BASE.index, columns=COLS
)
IND = pd.Series(["银行", "银行", "医药", "医药"], index=COLS)

#: 每个算子在 BASE 上的一次调用（入参用 ``d`` 派生，保证截断测试可直接复用）。
BATTERY: dict[str, Callable[[pd.DataFrame], object]] = {
    "ts_sum": lambda d: ops.ts_sum(d, 5),
    "sma": lambda d: ops.sma(d, 5),
    "stddev": lambda d: ops.stddev(d, 5),
    "correlation": lambda d: ops.correlation(d, EXPOSURE.loc[d.index], 5),
    "covariance": lambda d: ops.covariance(d, EXPOSURE.loc[d.index], 5),
    "ts_rank": lambda d: ops.ts_rank(d, 5),
    "product": lambda d: ops.product(d, 3),
    "ts_min": lambda d: ops.ts_min(d, 5),
    "ts_max": lambda d: ops.ts_max(d, 5),
    "delta": lambda d: ops.delta(d, 2),
    "delay": lambda d: ops.delay(d, 2),
    "rank": lambda d: ops.rank(d),
    "scale": lambda d: ops.scale(d, 2.0),
    "ts_argmax": lambda d: ops.ts_argmax(d, 5),
    "ts_argmin": lambda d: ops.ts_argmin(d, 5),
    "decay_linear": lambda d: ops.decay_linear(d, 5),
    "rolling_rank": lambda d: ops.rolling_rank(d.iloc[0].to_numpy()),
    "ind_neutralize": lambda d: ind_neutralize(d, IND),
    "neu_industry": lambda d: neu_industry(d, IND),
    "neutral": lambda d: neutral(d, EXPOSURE.loc[d.index]),
    "vwap_from_amount": lambda d: panel_contract.vwap_from_amount(d, d.abs() + 1.0),
    "returns_from_close": lambda d: panel_contract.returns_from_close(d),
}

#: 时间序列上「只用过去信息」的算子（可做截断一致性与未来扰动检验）。
PIT_BATTERY: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    name: fn
    for name, fn in BATTERY.items()
    if name not in {"rolling_rank", "vwap_from_amount", "returns_from_close"}
}


# ---------------------------------------------------------------------------
# 1. 输入不可变性（§6.5；也是变异测试 m6 的目标）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(BATTERY))
def test_inputs_are_not_modified(name):
    """调用前后入参面板必须一字未变（纯函数契约）。"""
    snapshot = BASE.copy(deep=True)
    BATTERY[name](BASE)
    pd.testing.assert_frame_equal(BASE, snapshot)


@pytest.mark.parametrize("name", sorted(BATTERY))
def test_operators_do_not_produce_inf_from_finite_inputs(name):
    """有限输入不得产生 ±inf（未定义的比值一律给 NaN）。"""
    out = BATTERY[name](BASE)
    if isinstance(out, pd.DataFrame):
        assert not np.isinf(out.to_numpy(dtype=float)).any(), name


@pytest.mark.parametrize("name", sorted(BATTERY))
def test_dirty_inputs_do_not_crash(name):
    """NaN 与 0 混入时不得抛异常（停牌/缺数据是常态）。"""
    dirty = BASE.copy()
    dirty.iloc[3:6, 0] = np.nan
    dirty.iloc[10, 1] = 0.0
    dirty.iloc[12:14, 2] = 0.0
    out = BATTERY[name](dirty)
    if isinstance(out, pd.DataFrame):
        assert not np.isinf(out.to_numpy(dtype=float)).any(), name


@pytest.mark.parametrize("name", sorted(BATTERY))
def test_no_deprecated_pandas_api_warnings(name):
    """运行时不得触发 pandas 弃用警告（§9 R8 依赖漂移的前置信号）。

    原始实现正是死在这类问题上：``as_matrix()`` 在 pandas ≥1.0 被删除、
    ``fillna(method=)`` 在 2.x 被废弃（设计文档 §3.3 缺陷 1、§3.3 附加环境冲突）。
    把「用了将被删除的 API」变成一条**立刻失败**的测试，比等它某天崩掉便宜得多。
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        warnings.simplefilter("error", DeprecationWarning)
        BATTERY[name](BASE)


# ---------------------------------------------------------------------------
# 2. 时间截断一致性（PIT 金标准，§6.5「一条顶十条」）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(PIT_BATTERY))
def test_time_truncation_consistency(name):
    """``[0,T]`` 全量算 vs ``[0,t]`` 截断算，在 t 及之前必须**完全相等**。"""
    full = PIT_BATTERY[name](BASE)
    truncated = PIT_BATTERY[name](BASE.iloc[:CUT])
    pd.testing.assert_frame_equal(truncated, full.iloc[:CUT])


def _centered_lookahead(df: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    """故意前视的对照算子（居中滚动窗口会用到期之后的数据）。"""
    return df.rolling(window, center=True, min_periods=1).mean()


def test_truncation_consistency_has_teeth_lookahead_operator_fails():
    """控制实验：把前视算子喂给上面的判据，必须判失败——否则该判据是摆设。"""
    full = _centered_lookahead(BASE)
    truncated = _centered_lookahead(BASE.iloc[:CUT])
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(truncated, full.iloc[:CUT])


# ---------------------------------------------------------------------------
# 3. 未来扰动（§6.5）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PIT_BATTERY))
def test_future_perturbation_does_not_change_past(name):
    """随机篡改 t 之后的数据，t 及之前的结果必须逐点不变。"""
    perturbed = BASE.copy()
    perturbed.iloc[CUT:] = perturbed.iloc[CUT:] * -7.5 + 1000.0
    full = PIT_BATTERY[name](BASE)
    after = PIT_BATTERY[name](perturbed)
    pd.testing.assert_frame_equal(after.iloc[:CUT], full.iloc[:CUT])


# ---------------------------------------------------------------------------
# 4. 缩放不变性（§6.5）
# ---------------------------------------------------------------------------


def test_rank_ts_rank_and_scale_are_invariant_under_positive_scaling():
    """价格整体 ×k（k>0）后，排序型算子与截面缩放结果必须不变。"""
    k = 3.5
    scaled = BASE * k
    for name, fn in (
        ("rank", lambda d: ops.rank(d)),
        ("ts_rank", lambda d: ops.ts_rank(d, 5)),
        ("scale", lambda d: ops.scale(d, 2.0)),
    ):
        np.testing.assert_allclose(
            fn(scaled).to_numpy(dtype=float),
            fn(BASE).to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
            err_msg=name,
        )


def test_translation_is_not_guaranteed_but_documented_rank_behaviour():
    """价格整体 +c：**截面 rank 不变**（单调平移），而水平型算子会变。

    设计文档 §6.5 把「平移不变性」列为「多数因子排序应不变」——本测试只钉死
    算子层的可判定部分：``rank`` 在正平移下不变，其余算子不作承诺（见 operators.md §3.6）。
    """
    shifted = BASE + 1000.0
    pd.testing.assert_frame_equal(ops.rank(BASE), ops.rank(shifted))
