"""逐元素层用例（M2；论文 Functions 的 4 个函数，覆盖 15 个因子）。

对应论文 Appendix A「Functions and Operators」逐字定义，见 `docs/paper_formulas.md` §7.6。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import alpha101v
from alpha101v import elemwise

IDX = pd.date_range("2021-01-04", periods=3, freq="B")
COLS = list("AB")


def frame(values, cols=COLS) -> pd.DataFrame:
    array = np.asarray(values, dtype=float).reshape(len(IDX), -1)
    return pd.DataFrame(array, index=IDX, columns=cols[: array.shape[1]])


def test_elemwise_surface_is_separate_from_the_twenty_operators():
    """逐元素层与 20 算子面互不相交，且都从包命名空间导出。"""
    assert set(elemwise.ELEMWISE) == {"abs_", "log", "sign", "signedpower"}
    assert not set(elemwise.ELEMWISE) & set(alpha101v.OPERATORS)
    assert len(alpha101v.OPERATORS) == 20
    for name in elemwise.ELEMWISE:
        assert callable(getattr(alpha101v, name)), name


def test_abs_matches_numpy():
    data = frame([[-1.5, 2.0], [np.nan, -0.0], [-3.25, 4.0]])
    out = elemwise.abs_(data)
    assert isinstance(out, pd.DataFrame)
    np.testing.assert_allclose(out.to_numpy(), np.abs(data.to_numpy()), equal_nan=True)
    pd.testing.assert_index_equal(out.index, data.index)
    pd.testing.assert_index_equal(out.columns, data.columns)


def test_log_is_natural_log_and_nonpositive_is_nan_not_inf():
    """★ 口径决策 1：x <= 0 → NaN（不是 -inf）。"""
    data = frame([[1.0, np.e], [0.0, -1.0], [np.nan, 10.0]])
    out = elemwise.log(data)
    values = out.to_numpy()
    assert values[0, 0] == pytest.approx(0.0)
    assert values[0, 1] == pytest.approx(1.0)          # ln e = 1
    assert np.isnan(values[1, 0]) and np.isnan(values[1, 1])   # 0 与负值
    assert np.isnan(values[2, 0])
    assert values[2, 1] == pytest.approx(np.log(10.0))
    assert not np.isinf(out.to_numpy(dtype=float)).any()


def test_sign_zero_is_zero_and_nan_stays_nan():
    data = frame([[-5.0, 0.0], [3.0, np.nan], [0.0, -0.5]])
    out = elemwise.sign(data)
    np.testing.assert_allclose(
        out.to_numpy(), [[-1.0, 0.0], [1.0, np.nan], [0.0, -1.0]], equal_nan=True
    )


def test_signedpower_default_preserves_sign():
    """★ 口径决策 3：默认 `sign(x)·|x|^a`，负底数也能算。"""
    data = frame([[-4.0, 4.0], [-1.0, 1.0], [0.0, 9.0]])
    out = elemwise.signedpower(data, 0.5)
    np.testing.assert_allclose(out.to_numpy(), [[-2.0, 2.0], [-1.0, 1.0], [0.0, 3.0]], rtol=1e-15)


def test_signedpower_literal_mode_matches_paper_text():
    """`preserve_sign=False` = 论文字面 `x^a`：负底数 + 非整数指数 → NaN。"""
    data = frame([[-4.0, 4.0], [-1.0, 1.0], [0.0, 9.0]])
    out = elemwise.signedpower(data, 0.5, preserve_sign=False)
    values = out.to_numpy()
    assert np.isnan(values[0, 0]) and np.isnan(values[1, 0])   # 负底数 + 0.5
    assert values[0, 1] == pytest.approx(2.0)
    assert values[2, 0] == pytest.approx(0.0)


def test_signedpower_modes_differ_on_negative_base_even_for_integer_exponent():
    """★ 更正：两种模式的差异**只取决于底数是否为负**，与指数是否整数无关。

    `x = -4, a = 2`：保号模式给 `sign(-4)·|−4|² = −16`，字面模式给 `(−4)² = +16`。
    （本条曾被我误判为「a=2 时无差异」，是实现 + 测试 + 论文原文三方核对的直接产物。）
    """
    data = frame([[-4.0, 4.0], [-1.0, 1.0], [0.0, 9.0]])
    keep = elemwise.signedpower(data, 2.0)
    literal = elemwise.signedpower(data, 2.0, preserve_sign=False)
    np.testing.assert_allclose(keep.to_numpy(), [[-16.0, 16.0], [-1.0, 1.0], [0.0, 81.0]])
    np.testing.assert_allclose(literal.to_numpy(), [[16.0, 16.0], [1.0, 1.0], [0.0, 81.0]])


def test_signedpower_modes_agree_when_base_is_non_negative_as_in_the_paper():
    """论文两处用法的**底数都非负**（#1：stddev/close；#84：Ts_Rank ∈ (0,1]）→ 两模式一致。

    这才是「该歧义不阻塞这两个因子转写」的**真正理由**（不是「a=2」）。
    """
    base = frame([[0.0, 0.25], [0.5, 0.75], [1.0, 0.1]])
    for exponent in (2.0, 0.5, -1.0):   # 注：a=0 且 x=0 是唯一的例外，见下一条测试
        pd.testing.assert_frame_equal(
            elemwise.signedpower(base, exponent),
            elemwise.signedpower(base, exponent, preserve_sign=False),
        )


def test_signedpower_zero_base_zero_exponent_is_the_only_disagreement():
    """边角（显式记录）：`x=0, a=0` 时保号给 `0·1 = 0`，字面给 `0^0 = 1`——非零底数两者都 =1。"""
    data = frame([[0.0, 2.0], [1.0, 3.0], [4.0, 5.0]])
    keep = elemwise.signedpower(data, 0.0)
    literal = elemwise.signedpower(data, 0.0, preserve_sign=False)
    assert keep.iloc[0, 0] == 0.0
    assert literal.iloc[0, 0] == 1.0
    pd.testing.assert_frame_equal(keep.iloc[1:], literal.iloc[1:])


def test_signedpower_accepts_a_panel_exponent_as_in_alpha84():
    """★ 论文 Alpha#84 逐字：`SignedPower(Ts_Rank(...), delta(close, 4.96796))` —— 指数是**面板**。"""
    base = frame([[0.2, 0.4], [0.6, 0.8], [1.0, 0.5]])
    exponent = frame([[2.0, 0.5], [-1.0, 3.0], [0.0, 1.0]])
    out = elemwise.signedpower(base, exponent)
    expected = np.sign(base.to_numpy()) * np.abs(base.to_numpy()) ** exponent.to_numpy()
    np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-15)
    # 底数非负 ⇒ 与字面模式一致（论文用法）
    pd.testing.assert_frame_equal(out, elemwise.signedpower(base, exponent, preserve_sign=False))
    # 指数面板必须同 index/columns
    with pytest.raises(ValueError):
        elemwise.signedpower(base, exponent.iloc[:2])


def test_signedpower_zero_base_with_negative_exponent_is_nan_not_inf():
    """决策 5：`0` 的负次幂 → NaN，不产生 ±inf（否则会污染全部下游算子）。"""
    data = frame([[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]])
    for preserve_sign in (True, False):
        out = elemwise.signedpower(data, -1.0, preserve_sign=preserve_sign)
        assert np.isnan(out.iloc[0, 0])
        assert not np.isinf(out.to_numpy(dtype=float)).any()


def test_elemwise_series_sugar_returns_dataframe():
    series = pd.Series([-2.0, 0.0, 3.0], index=IDX, name="px")
    out = elemwise.abs_(series)
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == ["px"]
    np.testing.assert_allclose(out.to_numpy().ravel(), [2.0, 0.0, 3.0])


@pytest.mark.parametrize("name", sorted(elemwise.ELEMWISE))
def test_elemwise_does_not_modify_inputs(name):
    data = frame([[-1.5, 2.0], [0.5, -3.0], [np.nan, 4.0]])
    snapshot = data.copy(deep=True)
    call = {
        "abs_": lambda: elemwise.abs_(data),
        "log": lambda: elemwise.log(data),
        "sign": lambda: elemwise.sign(data),
        "signedpower": lambda: elemwise.signedpower(data, 2.0),
    }[name]
    call()
    pd.testing.assert_frame_equal(data, snapshot)


def test_elemwise_rejects_bad_inputs():
    data = frame([[-1.5, 2.0], [0.5, -3.0], [np.nan, 4.0]])
    with pytest.raises(TypeError):
        elemwise.abs_([1.0, 2.0])
    with pytest.raises(TypeError):
        elemwise.log(pd.DataFrame({"a": ["x", "y", "z"]}, index=IDX))
    with pytest.raises(TypeError):
        elemwise.signedpower(data, True)
    with pytest.raises(TypeError):
        elemwise.signedpower(data, "2")
    with pytest.raises(ValueError):
        elemwise.signedpower(data, np.nan)
    with pytest.raises(ValueError):
        elemwise.signedpower(data, pd.DataFrame(np.inf, index=IDX, columns=COLS))
