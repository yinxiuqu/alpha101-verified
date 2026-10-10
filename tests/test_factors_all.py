"""全量 101 个因子的契约、不变量与规范对照（M3）。

分四层证据（`verified` 仍是 0/101：还缺 M4 因子级差分与 M5 golden 快照）：

1. **注册完整性**：101 个因子全部登记，`paper_ref` 齐全，状态只有 `partial`/`ambiguous`；
2. **可算 + 不产 ±inf**：每个因子在合成面板上跑通（含 250 日长窗口），形状与入参一致；
3. **L4 不变量**：入参不可变、**时间截断一致性**（PIT 金标准，逐点相等）；
4. **L2 规范对照**：调用 `tools/conformance_report.py`（论文公式 ↔ 实现 AST），必须 0 偏离。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from alpha101v import factors, registry

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALL_NAMES = tuple(f"alpha{n}" for n in range(1, 102))
FULL_DAYS = 320          # > 250 日最长窗口，保证长窗口因子也有值
CUT_DAYS = 240

#: 论文公式里出现这些算子的因子 ⇒ 规范本身未定（与 `factors.AMBIGUOUS_FACTORS` 必须一致）。
EXPECTED_DECAY_AMBIGUOUS = {
    31, 39, 57, 58, 59, 63, 66, 71, 72, 73, 76, 77, 82, 87, 88, 89, 91, 92, 93, 96, 97, 98,
}
EXPECTED_ARG_AMBIGUOUS = {1, 57, 60, 96, 98, 100}
EXPECTED_POW_AMBIGUOUS = {48, 90}


def make_panel(days: int = FULL_DAYS, names: int = 5, seed: int = 20261010) -> dict[str, pd.DataFrame]:
    """合成长面板：10 个字段 + 三个行业层级（L1/L2/L3 对应 sector/industry/subindustry）。"""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-01-04", periods=days, freq="B")
    columns = [f"S{i}" for i in range(names)]
    shape = (days, names)

    # 对数正态价格：随机游走 + **每日 5% 异质冲击**。异质冲击必须足够大，才能让
    # 截面排序每天真正打乱——否则短窗口内 rank 序列零方差（相关系数按本库策略给 NaN）
    # 会让 alpha96 这类多层嵌套因子在小夹具上整片为 NaN，掩盖实现本身是否正确。
    walk = np.cumsum(rng.normal(0.0, 0.015, size=shape), axis=0)
    shock = rng.normal(0.0, 0.05, size=shape)
    close = pd.DataFrame(30.0 * np.exp(walk + shock), index=index, columns=columns)
    Open = pd.DataFrame(close.to_numpy() * (1 + rng.normal(0, 0.004, size=shape)), index=index, columns=columns)
    high = pd.DataFrame(
        np.maximum(close.to_numpy(), Open.to_numpy()) * (1 + np.abs(rng.normal(0, 0.004, size=shape))),
        index=index, columns=columns,
    )
    low = pd.DataFrame(
        np.minimum(close.to_numpy(), Open.to_numpy()) * (1 - np.abs(rng.normal(0, 0.004, size=shape))),
        index=index, columns=columns,
    )
    volume = pd.DataFrame(np.abs(rng.normal(2e5, 3e4, size=shape)) + 100.0, index=index, columns=columns)
    amount = volume * 100.0 * (close + Open) / 2.0
    vwap = amount / (volume * 100.0)
    returns = close.pct_change(fill_method=None)
    cap = pd.DataFrame(np.abs(rng.normal(1e6, 2e5, size=shape)) + 1.0, index=index, columns=columns)

    sectors = ["金融", "制造"]
    industries = ["银行", "医药", "电子"]
    subindustries = ["城商行", "创新药", "半导体", "白电"]
    panel = {
        "close": close, "Open": Open, "high": high, "low": low, "volume": volume,
        "amount": amount, "vwap": vwap, "returns": returns, "cap": cap,
        "ind_sector": pd.Series([sectors[i % len(sectors)] for i in range(names)], index=columns),
        "ind_industry": pd.Series([industries[i % len(industries)] for i in range(names)], index=columns),
        "ind_subindustry": pd.Series([subindustries[i % len(subindustries)] for i in range(names)], index=columns),
    }
    return panel


PANEL = make_panel()


# ---------------------------------------------------------------------------
# 1. 注册完整性
# ---------------------------------------------------------------------------


def test_all_101_factors_are_registered():
    assert len(registry.REGISTRY) == 101
    assert set(registry.REGISTRY) == set(ALL_NAMES)
    for number, name in enumerate(ALL_NAMES, start=1):
        meta = registry.REGISTRY[name]
        assert meta.paper_ref.startswith(f"Appendix A, Alpha#{number}"), name
        assert meta.status in {"partial", "ambiguous"}, name
        assert registry.field_names(meta.func) == meta.params


def test_ambiguous_status_follows_the_declared_rules():
    """`ambiguous` 集合必须与论文公式里出现「未定案算子」的因子集合完全一致。"""
    declared = {
        "decay": set(factors.AMBIGUOUS_FACTORS[
            "decay_linear 权重方向未定案（vnpy 取相反方向，BRAIN 文案未取得）"
        ]),
        "arg": set(factors.AMBIGUOUS_FACTORS[
            "ts_argmax/ts_argmin 基准未定案（论文只写 which day，BRAIN 文案未取得）"
        ]),
        "pow": set(factors.AMBIGUOUS_FACTORS[
            "`^` 语义（论文字面 x^a vs 保号幂）在此因子产生实质差异（负底数）"
        ]),
    }
    assert declared["decay"] == EXPECTED_DECAY_AMBIGUOUS
    assert declared["arg"] == EXPECTED_ARG_AMBIGUOUS
    assert declared["pow"] == EXPECTED_POW_AMBIGUOUS

    expected_ambiguous = declared["decay"] | declared["arg"] | declared["pow"]
    actual = {int(name[5:]) for name, meta in registry.REGISTRY.items() if meta.status == "ambiguous"}
    assert actual == expected_ambiguous

    # 其余因子一律 partial（**没有任何 verified**：六条门槛未全满足）
    assert all(meta.status != "verified" for meta in registry.REGISTRY.values())


# ---------------------------------------------------------------------------
# 2. 可算 + 不产 ±inf
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_NAMES)
def test_factor_runs_on_synthetic_panel(name):
    out = registry.run_factor(name, PANEL)
    assert isinstance(out, pd.DataFrame), name
    assert out.index.equals(PANEL["close"].index), name
    assert out.columns.equals(PANEL["close"].columns), name
    values = out.to_numpy(dtype=float)
    assert not np.isinf(values).any(), f"{name} 产生 ±inf"
    assert np.isfinite(values).any(), f"{name} 全为 NaN（合成面板足够长，不该如此）"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_factor_does_not_modify_inputs(name):
    panel = make_panel(days=90, names=3, seed=7)
    snapshot = {key: value.copy(deep=True) for key, value in panel.items()}
    registry.run_factor(name, panel, copy_inputs=False)
    for key, value in panel.items():
        if isinstance(value, pd.Series):
            pd.testing.assert_series_equal(value, snapshot[key], obj=key)
        else:
            pd.testing.assert_frame_equal(value, snapshot[key], obj=key)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_factor_is_pit_safe_truncation_consistency(name):
    """PIT 金标准：`[0,T]` 与 `[0,t]` 在 t 处必须**逐点完全相等**（无前视）。"""
    full = registry.run_factor(name, PANEL)
    truncated = registry.run_factor(name, {k: v.iloc[:CUT_DAYS] for k, v in PANEL.items()})
    pd.testing.assert_frame_equal(truncated, full.iloc[:CUT_DAYS])


# ---------------------------------------------------------------------------
# 3. L2 规范对照（外部工具即门禁）
# ---------------------------------------------------------------------------


def test_l2_conformance_report_has_no_deviation():
    """论文公式 ↔ 实现 AST 的规范对照必须 0 偏离（等价 / 已声明差异）。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "conformance_report.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"规范对照存在偏离：\n{output}"
    assert "等价 101" in output, output
