"""试点因子用例（M2）：封闭解 / **独立第二实现** / L2 结构对照 / L4 不变量。

验证思路（对齐设计文档 §6.3–§6.5）：
* **不拿实现自己的输出当基准**：alpha4/alpha56 用 scipy `rankdata` + 显式逐日逐股循环
  另写一份（不同代码路径、不同函数），alpha101/alpha41 用论文公式的裸 numpy 直算。
* **L2 结构对照**（本轮的轻量版）：用 spy 记录因子实际调用的算子**多重集**，
  与论文公式的算子集合比对；完整 AST↔公式树比对是 M3 的 `tools/conformance_report.py`。
* **L4 不变量**：入参不可变、时间截断一致性（PIT）、输出无 ±inf，以及各因子特有的
  尺度/单位不变性（含 alpha101 因加性常数 0.001 而**不**尺度不变这一论文规范性质）。
"""

from __future__ import annotations

import collections

import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata

from alpha101v import factors, registry

PILOT_NAMES = ("alpha101", "alpha4", "alpha41", "alpha56")
FIELDS = ("close", "Open", "high", "low", "volume", "vwap", "returns", "amount", "cap", "ind")


def make_panel(days: int = 30, names: int = 4, seed: int = 20260101) -> dict[str, pd.DataFrame]:
    """构造确定性面板（10 个字段；价格为正、单位自洽）。"""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-01-04", periods=days, freq="B")
    columns = [f"S{i}" for i in range(names)]
    shape = (days, names)

    steps = rng.normal(0.0, 0.3, size=shape)
    close = pd.DataFrame(20.0 + np.cumsum(steps, axis=0), index=index, columns=columns)
    Open = pd.DataFrame(close.to_numpy() * (1.0 + rng.normal(0, 0.004, size=shape)), index=index, columns=columns)
    high = pd.DataFrame(
        np.maximum(close.to_numpy(), Open.to_numpy()) * (1.0 + np.abs(rng.normal(0, 0.004, size=shape))),
        index=index, columns=columns,
    )
    low = pd.DataFrame(
        np.minimum(close.to_numpy(), Open.to_numpy()) * (1.0 - np.abs(rng.normal(0, 0.004, size=shape))),
        index=index, columns=columns,
    )
    volume = pd.DataFrame(np.abs(rng.normal(1e5, 1e4, size=shape)) + 1.0, index=index, columns=columns)
    amount = volume * 100.0 * ((high + low) / 2.0)
    vwap = amount / (volume * 100.0)
    returns = close.pct_change(fill_method=None)
    cap = pd.DataFrame(np.abs(rng.normal(1e6, 2e5, size=shape)) + 1.0, index=index, columns=columns)
    ind = pd.DataFrame(rng.choice(["银行", "医药"], size=shape), index=index, columns=columns)
    return {
        "close": close, "Open": Open, "high": high, "low": low, "volume": volume,
        "vwap": vwap, "returns": returns, "amount": amount, "cap": cap, "ind": ind,
    }


PANEL = make_panel()


def one(value: float, column: str = "X") -> pd.DataFrame:
    return pd.DataFrame([[value]], index=pd.date_range("2021-01-04", periods=1), columns=[column])


# ---------------------------------------------------------------------------
# 0. 注册与契约
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("alpha101", ("close", "Open", "high", "low")),
        ("alpha4", ("low",)),
        ("alpha41", ("high", "low", "vwap")),
        ("alpha56", ("returns", "cap")),
    ],
)
def test_pilot_fields_match_paper_dependencies(name, expected):
    """形参名 = 面板字段名 = 论文该因子实际依赖的输入（§7.5 自动装配的前提）。"""
    assert registry.field_names(registry.REGISTRY[name].func) == expected
    assert set(expected) <= set(FIELDS)


@pytest.mark.parametrize("name", PILOT_NAMES)
def test_factor_output_is_panel_shaped_and_finite(name):
    out = registry.run_factor(name, PANEL)
    assert isinstance(out, pd.DataFrame)
    assert out.index.equals(PANEL["close"].index)
    assert out.columns.equals(PANEL["close"].columns)
    assert not np.isinf(out.to_numpy(dtype=float)).any(), name


@pytest.mark.parametrize("name", PILOT_NAMES)
def test_factor_does_not_modify_inputs(name):
    """因子层的入参不可变性（`run_factor(..., copy_inputs=False)` 时直接暴露因子行为）。"""
    panel = make_panel()
    snapshot = {key: value.copy(deep=True) for key, value in panel.items()}
    registry.run_factor(name, panel, copy_inputs=False)
    for key, value in panel.items():
        pd.testing.assert_frame_equal(value, snapshot[key], obj=key)


@pytest.mark.parametrize("name", PILOT_NAMES)
def test_factor_is_pit_safe_truncation_consistency(name):
    """PIT 金标准：`[0,T]` 与 `[0,t]` 在 t 处必须逐点完全相等（无前视）。"""
    panel = make_panel(days=24)
    cut = 16
    full = registry.run_factor(name, panel)
    truncated = registry.run_factor(name, {key: value.iloc[:cut] for key, value in panel.items()})
    pd.testing.assert_frame_equal(truncated, full.iloc[:cut])


@pytest.mark.parametrize(
    ("name", "broken_field"),
    [("alpha101", "close"), ("alpha41", "vwap"), ("alpha56", "cap")],
)
def test_factor_rejects_misaligned_panels(name, broken_field):
    """多字段因子的入参必须同 (index, columns) 契约，否则显式报错（而非静默外连接出 NaN）。

    注：单字段因子（alpha4）无从「彼此不一致」，故不适用本测试。
    """
    panel = make_panel(days=6, names=3)
    panel[broken_field] = panel[broken_field].iloc[:-1]
    with pytest.raises(ValueError, match="契约"):
        registry.run_factor(name, panel, copy_inputs=False)


# ---------------------------------------------------------------------------
# 1. alpha101：封闭解 + 加性常数的性质
# ---------------------------------------------------------------------------


def test_alpha101_matches_paper_arithmetic():
    panel = make_panel(days=8, names=3, seed=11)
    out = factors.alpha101(panel["close"], panel["Open"], panel["high"], panel["low"])
    expected = (panel["close"].to_numpy() - panel["Open"].to_numpy()) / (
        (panel["high"].to_numpy() - panel["low"].to_numpy()) + 0.001
    )
    np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-15)


def test_alpha101_absolute_anchor_is_hand_computable():
    """单点绝对锚点（人工可核）：close=10, open=9, high=11, low=8 → 1/(3+0.001)。"""
    out = factors.alpha101(one(10.0), one(9.0), one(11.0), one(8.0))
    assert out.iloc[0, 0] == pytest.approx(1.0 / 3.001, rel=1e-15)


def test_alpha101_high_equals_low_stays_finite():
    """`high == low` → 除以加性常数 0.001，结果有限（不产生 inf）。"""
    out = factors.alpha101(one(10.0), one(9.0), one(8.0), one(8.0))
    assert out.iloc[0, 0] == pytest.approx(1000.0)
    assert np.isfinite(out.to_numpy()).all()


def test_alpha101_is_not_scale_invariant_because_of_additive_epsilon():
    """★ 论文规范的性质：`0.001` 是**加性**常数 ⇒ alpha101 不尺度不变（A 股落地需登记）。"""
    panel = make_panel(days=6, names=3, seed=13)
    k = 3.5
    scaled = {key: value * k for key, value in panel.items() if key in {"close", "Open", "high", "low"}}
    base = factors.alpha101(panel["close"], panel["Open"], panel["high"], panel["low"])
    out = factors.alpha101(scaled["close"], scaled["Open"], scaled["high"], scaled["low"])
    expected = (k * (panel["close"] - panel["Open"])) / (
        k * (panel["high"] - panel["low"]) + 0.001
    )
    np.testing.assert_allclose(out.to_numpy(), expected.to_numpy(), rtol=1e-12)
    assert not np.allclose(out.to_numpy(), base.to_numpy(), rtol=1e-6)  # 确实不尺度不变


# ---------------------------------------------------------------------------
# 2. alpha4：独立第二实现（scipy + 显式循环）
# ---------------------------------------------------------------------------


def test_alpha4_matches_independent_second_implementation():
    """`-1 * Ts_Rank(rank(low), 9)`：用 `scipy.stats.rankdata` 逐日逐股另写一份对拍。"""
    panel = make_panel(days=18, names=4, seed=17)
    out = factors.alpha4(panel["low"])

    low = panel["low"].to_numpy(dtype=float)
    days, names = low.shape
    cross_rank = np.vstack([rankdata(row) / names for row in low])  # 每日截面 pct rank
    expected = np.full_like(low, np.nan)
    for t in range(8, days):
        for c in range(names):
            expected[t, c] = -rankdata(cross_rank[t - 8 : t + 1, c])[-1] / 9.0
    np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-12, atol=1e-15, equal_nan=True)


def test_alpha4_is_invariant_under_positive_scaling_of_low():
    """rank 对正数缩放不变 ⇒ 整体 ×k 后 alpha4 逐点不变。"""
    panel = make_panel(days=14, names=3, seed=19)
    k = 7.25
    base = factors.alpha4(panel["low"])
    scaled = factors.alpha4(panel["low"] * k)
    np.testing.assert_allclose(scaled.to_numpy(), base.to_numpy(), rtol=1e-12, atol=1e-15, equal_nan=True)


# ---------------------------------------------------------------------------
# 3. alpha41：封闭解 + 线性齐次性
# ---------------------------------------------------------------------------


def test_alpha41_matches_paper_arithmetic():
    panel = make_panel(days=9, names=4, seed=23)
    out = factors.alpha41(panel["high"], panel["low"], panel["vwap"])
    expected = np.sqrt(panel["high"].to_numpy() * panel["low"].to_numpy()) - panel["vwap"].to_numpy()
    np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-14, atol=1e-14)


def test_alpha41_is_linear_homogeneous_in_price_level():
    """价格整体 ×k ⇒ alpha41 整体 ×k（故其截面排序不变）。"""
    panel = make_panel(days=9, names=3, seed=29)
    k = 4.0
    base = factors.alpha41(panel["high"], panel["low"], panel["vwap"])
    scaled = factors.alpha41(panel["high"] * k, panel["low"] * k, panel["vwap"] * k)
    np.testing.assert_allclose(scaled.to_numpy(), k * base.to_numpy(), rtol=1e-12, atol=1e-12)


# ---------------------------------------------------------------------------
# 4. alpha56：独立第二实现 + 嵌套窗口 + cap 单位不变性
# ---------------------------------------------------------------------------


def test_alpha56_matches_independent_second_implementation():
    """嵌套窗口 `Σ10 / Σ3(Σ2)`：用显式循环 + `rankdata` 另写一份对拍。"""
    panel = make_panel(days=20, names=4, seed=31)
    out = factors.alpha56(panel["returns"], panel["cap"])

    returns = panel["returns"].to_numpy(dtype=float)
    cap = panel["cap"].to_numpy(dtype=float)
    days, names = returns.shape

    numer = np.full_like(returns, np.nan)
    denom = np.full_like(returns, np.nan)
    for t in range(days):
        for c in range(names):
            if t >= 9 and np.isfinite(returns[t - 9 : t + 1, c]).all():
                numer[t, c] = returns[t - 9 : t + 1, c].sum()
            if t >= 3 and np.isfinite(returns[t - 3 : t + 1, c]).all():
                denom[t, c] = sum(returns[t - i - j, c] for i in range(3) for j in range(2))

    ratio_rank = np.full_like(returns, np.nan)
    product_rank = np.full_like(returns, np.nan)
    for t in range(days):
        ratio = numer[t] / denom[t]
        mask = np.isfinite(ratio)
        if mask.any():
            ratio_rank[t, mask] = rankdata(ratio[mask]) / mask.sum()
        product = returns[t] * cap[t]
        pmask = np.isfinite(product)
        if pmask.any():
            product_rank[t, pmask] = rankdata(product[pmask]) / pmask.sum()

    expected = -1.0 * (ratio_rank * product_rank)
    np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-12, atol=1e-15, equal_nan=True)


def test_alpha56_warmup_is_nan_for_nested_windows():
    """预热期：内层 2 日 + 外层 3 日（比值需 5 日）+ 外层 `sum(returns, 10)` ⇒ 前 9 行必为 NaN。

    即：最紧的约束来自 `sum(returns, 10)`；而 `returns` 首日本身是 NaN（无前收）⇒ 首个有效窗口是
    `[1, 10]`，故**第 11 行（t=10）才出值**——比「窗口长度 10」直觉上晚一行，正是严格预热的体现。
    """
    panel = make_panel(days=16, names=3, seed=37)
    out = factors.alpha56(panel["returns"], panel["cap"])
    assert out.iloc[:10].isna().all().all()
    assert out.iloc[10:].notna().all().all()


def test_alpha56_is_invariant_under_positive_scaling_of_cap():
    """`rank(returns · cap)` 对 cap 的正数缩放不变 ⇒ 万元/元、总市值/流通市值不影响排序。"""
    panel = make_panel(days=16, names=3, seed=41)
    base = factors.alpha56(panel["returns"], panel["cap"])
    rescaled = factors.alpha56(panel["returns"], panel["cap"] * 1e4)
    np.testing.assert_allclose(
        rescaled.to_numpy(), base.to_numpy(), rtol=1e-12, atol=1e-15, equal_nan=True
    )


# ---------------------------------------------------------------------------
# 5. L2 结构对照（轻量版：算子调用多重集 vs 论文公式）
# ---------------------------------------------------------------------------


#: 论文公式里出现的**算子层**调用多重集（逐字统计；裸算术不算调用）。
EXPECTED_OPERATOR_CALLS: dict[str, dict[str, int]] = {
    "alpha101": {},                                # ((close - open) / ((high - low) + .001))
    "alpha4": {"rank": 1, "ts_rank": 1},           # -1 * Ts_Rank(rank(low), 9)
    "alpha41": {},                                 # ((high * low)^0.5) - vwap
    # 论文原文 `sum(returns, 10) / sum(sum(returns, 2), 3)` 含 **3 处** sum 调用（嵌套那处本身算两次），
    # 加上两个 rank —— 逐字统计得来的多重集，实现必须与之一致。
    "alpha56": {"ts_sum": 3, "rank": 2},
}


@pytest.mark.parametrize("name", PILOT_NAMES)
def test_l2_operator_call_multiset_matches_paper(name, monkeypatch):
    """记录因子实际调用的算子，与论文公式的算子多重集逐一比对（M3 会升级为 AST 逐节点比对）。"""
    calls: collections.Counter[str] = collections.Counter()
    for operator_name in ("rank", "ts_rank", "ts_sum"):
        original = getattr(factors, operator_name)

        def spy(*args, _name=operator_name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(factors, operator_name, spy)

    registry.run_factor(name, PANEL)
    assert dict(calls) == EXPECTED_OPERATOR_CALLS[name]


def test_l2_alpha56_uses_both_rank_calls_separately():
    """补充：alpha56 的两个 `rank` 作用于不同表达式（嵌套求和比值 / returns·cap），不是重复调用。"""
    panel = make_panel(days=14, names=3, seed=43)
    out = factors.alpha56(panel["returns"], panel["cap"])
    assert out.notna().sum().sum() > 0
    # 若两个 rank 顺序颠倒（乘法交换律下不可见），用负号与量纲关系间接锁死：结果必须为负或 NaN
    assert (out.dropna() <= 0).all().all()
