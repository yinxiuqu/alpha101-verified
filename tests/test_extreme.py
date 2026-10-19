"""极端值三原则测试：除零 → NaN（默认）/ 极小分母 → 掩码 + 可见 / 分子溢出 → 显式截断。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v.extreme import bound_inf, count_extremes, mask_small_denominator


def test_default_path_never_emits_inf():
    """★ 原则 ①：默认路径下输出**永不含 ±inf**（库契约）。"""
    from alpha101v import registry

    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-02", periods=30)
    cols = [f"S{i}" for i in range(8)]
    close = pd.DataFrame(rng.uniform(10, 20, (30, 8)), index=idx, columns=cols)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.DataFrame(np.maximum(close.to_numpy(), open_.to_numpy()) * 1.01, index=idx, columns=cols)
    low = pd.DataFrame(np.minimum(close.to_numpy(), open_.to_numpy()) * 0.99, index=idx, columns=cols)
    panel = {
        "close": close, "Open": open_, "high": high, "low": low,
        "volume": pd.DataFrame(rng.uniform(1e5, 2e5, (30, 8)), index=idx, columns=cols),
        "vwap": (high + low + close) / 3.0,
        "returns": close.pct_change().fillna(0.0),
    }
    result = registry.run_factor("alpha42", panel)      # rank 相除，会除零
    assert not np.isinf(result.to_numpy(dtype=float)).any(), "默认输出永不含 ±inf（除零 ⇒ NaN）"


def test_mask_small_denominator_covers_case_one_and_two():
    """原则 ①②：按**分母**掩码——0 与 1e-15 都算不可靠，正常分母照常计算。"""
    numer = pd.DataFrame([[1.0, 1.0, 1.0]], index=[pd.Timestamp("2024-01-02")], columns=list("ABC"))
    denom = pd.DataFrame([[0.0, 1e-15, 2.0]], index=numer.index, columns=numer.columns)
    row = mask_small_denominator(numer, denom, eps=1e-12).iloc[0]
    assert np.isnan(row["A"]), "分母为 0 ⇒ NaN"
    assert np.isnan(row["B"]), "极小分母 ⇒ NaN（巨大有限值不可靠）"
    assert row["C"] == 0.5


def test_bound_inf_is_explicit_for_case_three():
    """原则 ③：只有显式调用才把 ±inf 换成截面有限极值（前提：确认是溢出）。"""
    frame = pd.DataFrame([[1.0, 2.0, np.inf, -np.inf]], index=[pd.Timestamp("2024-01-02")],
                         columns=list("ABCD"))
    row = bound_inf(frame).iloc[0]
    assert row["C"] == 2.0 and row["D"] == 1.0
    assert np.isnan(pd.DataFrame([[np.nan]], index=[pd.Timestamp("2024-01-02")]).iloc[0, 0])


def test_bound_inf_leaves_all_nan_row_alone():
    frame = pd.DataFrame([[1.0, np.inf, np.nan]], index=[pd.Timestamp("2024-01-02")],
                         columns=list("ABC"))
    out = bound_inf(frame)
    assert out.iloc[0]["B"] == 1.0 and np.isnan(out.iloc[0]["C"])


def test_count_extremes_diagnostic():
    frame = pd.DataFrame(
        [[1.0, np.inf, 3.0, -np.inf, np.nan],
         [np.nan, np.nan, np.nan, np.nan, np.nan]],
        index=pd.date_range("2024-01-02", periods=2), columns=list("ABCDE"),
    )
    stats = count_extremes(frame)
    assert stats["pos_inf"] == 1 and stats["neg_inf"] == 1
    assert stats["nan"] == 6 and stats["cells"] == 10
    assert stats["huge_finite"] == 0


def test_count_extremes_flags_huge_finite_values():
    """原则 ②：极小分母产生的巨大**有限**值必须可见（默认路径不处理它，但要看得到）。"""
    frame = pd.DataFrame([[1e15, 2.0, -3e14]], index=[pd.Timestamp("2024-01-02")],
                         columns=list("ABC"))
    stats = count_extremes(frame, huge=1e12)
    assert stats["huge_finite"] == 2
    assert stats["pos_inf"] == 0 and stats["neg_inf"] == 0


def test_decay_linear_zero_observation_is_nan_not_zero():
    """★ P0-1：稀疏模式下「窗口里一个有效值都没有」必须给 NaN，而不是 0.0（伪造数据）。"""
    from alpha101v import operators as op

    n = 6
    frame = pd.DataFrame(
        {"allnan": [np.nan] * n, "live": [1.0, 2, 3, 4, 5, 6]},
        index=pd.date_range("2024-01-02", periods=n),
    )
    sparse = op.decay_linear(frame, 3)            # 官方 sparse 语义
    strict = op.decay_linear(frame, 3, dense=True)

    assert sparse["allnan"].isna().all(), "零观测窗口必须 NaN（原实现返回 0.0 ✗）"
    assert strict["allnan"].isna().all()
    assert not sparse["live"].iloc[2:].isna().any(), "有观测的列从第 3 行起不受影响（前两行是预热期）"
    # 非零观测窗口仍按官方 sparse（NaN 计 0、分母为完整权重和）
    assert np.isfinite(sparse["live"].iloc[-1])


def test_run_factor_raw_is_discoverable():
    """N2：B3 的正式入口必须**可发现** —— 出现在 __all__ 与顶层命名空间（而不只是 registry 模块）。"""
    import alpha101v

    assert hasattr(alpha101v, "run_factor_raw"), "顶层应导出 run_factor_raw"
    assert "run_factor_raw" in alpha101v.__all__
    assert callable(alpha101v.run_factor_raw)


def test_no_duplicate_top_level_definitions():
    """N1：禁止同一模块里重复定义同名函数（曾因补丁重复粘贴，run_factor_raw 被定义两次）。"""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "alpha101v"
    problems = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in seen:
                    problems.append(f"{path.name}:{node.lineno} 重复定义 {node.name}（首次 {seen[node.name]}）")
                seen[node.name] = node.lineno
    assert not problems, "发现重复定义：" + "; ".join(problems)


def test_research_mode_switch_for_decay_dense():
    """B4 方案 A：默认不变；进入 research_mode() 后未显式传 dense 的调用改用严格口径；退出即恢复。"""
    import alpha101v
    from alpha101v import operators as op

    frame = pd.DataFrame(
        {"A": [np.nan, 1.0, np.nan, 3.0, 4.0, 5.0]},
        index=pd.date_range("2024-01-02", periods=6),
    )
    # 默认（官方 sparse）：缺口按 0 计入 ⇒ 有值
    default = op.decay_linear(frame, 3)
    assert default["A"].notna().any()

    with alpha101v.research_mode():
        strict = op.decay_linear(frame, 3)
        # 严格口径：窗口内任一 NaN ⇒ NaN ⇒ 含缺口的窗口全为 NaN
        assert strict["A"].isna().sum() > default["A"].isna().sum()
        # 显式传参优先：不受上下文影响
        explicit = op.decay_linear(frame, 3, dense=False)
        pd.testing.assert_frame_equal(explicit, default)

    # 退出后恢复默认
    after = op.decay_linear(frame, 3)
    pd.testing.assert_frame_equal(after, default)
