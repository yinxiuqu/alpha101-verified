"""真实 A 股数据端到端用例（设计文档 §7.4 面板契约 + §10.2 数据源）。

**这些是"真数据"测试**：本地 MongoDB（``quantaxis``）+ 申万 as-of 成员 parquet。
缺少任一前置条件时整文件跳过（CI 不应因为本机没有数据库而变红），
因此它是**本地/发布前**的证据层，与 `tests/test_differential.py` 同一性质。

断言的重点不是数值大小，而是**契约与不变量在真实数据上成立**：
面板契约、单位口径自洽（``vwap ∈ [low, high]``）、因子不产生 ±inf、
PIT 行业面板上的 `ind_neutralize` 逐日行业内残差和 ≈ 0、以及真实数据上的时间截断一致性。
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
import pytest

from alpha101v import panel as panel_contract
from alpha101v import registry
from alpha101v.neutralize import ind_neutralize

MEMBERS = pathlib.Path("/home/yinxiuqu/quantming/data/sw_industry/members.parquet")
MONGO_URI = "mongodb://127.0.0.1:27017"
WINDOW = ("2024-01-02", "2024-03-29")  # 58 个交易日，够跑 10 日窗口因子
N_CODES = 60


def _mongo_available() -> bool:
    try:
        import pymongo  # noqa: PLC0415
    except ImportError:
        return False
    try:
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_mongo_available() and MEMBERS.exists()),
    reason="需要本地 MongoDB(quantaxis) 与申万成员 parquet（本地/发布前证据层，CI 自动跳过）",
)


@pytest.fixture(scope="module")
def real() -> dict:
    """真实面板 + PIT 行业标签（模块级缓存，避免重复查库）。"""
    from alpha101v.adapters.industry import load_sw_industry
    from alpha101v.adapters.mongo import load_panel

    import pymongo

    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        pool = sorted(
            {str(doc["code"]) for doc in client["quantaxis"]["stock_daily_basic"].find({"date": WINDOW[1]}, {"code": 1})}
        )
    finally:
        client.close()
    assert pool, "取样日没有市值数据"
    rng = np.random.default_rng(20261009)
    codes = sorted(rng.choice(pool, size=min(N_CODES, len(pool)), replace=False).tolist())

    panel = load_panel(codes, *WINDOW, uri=MONGO_URI)
    industry = load_sw_industry(panel["close"].index, panel["close"].columns, level="L1")
    panel["ind"] = industry
    return {"panel": panel, "industry": industry, "codes": codes}


def test_real_panel_satisfies_contract(real):
    """面板契约在真实数据上通过；同时确认「最小历史长度」这道闸门确实有效。"""
    panel = real["panel"]
    assert panel_contract.validate_panel(panel, min_history=None) == []
    short = panel_contract.validate_panel(panel, min_history=250)
    assert any("最小历史长度" in problem for problem in short)


def test_real_vwap_unit_convention_is_self_consistent(real):
    """★ 单位口径的真实验证：``vwap = amount/(vol*100)`` 必须落在当日 ``[low, high]`` 内。

    若把「手」当「股」（少乘 100），vwap 会整体偏小 100 倍，本断言立刻失败。
    """
    panel = real["panel"]
    low, high, vwap = panel["low"], panel["high"], panel["vwap"]
    valid = vwap.notna() & low.notna() & high.notna()
    inside = (vwap >= low) & (vwap <= high) & valid
    ratio = float(inside.to_numpy().sum() / valid.to_numpy().sum())
    assert ratio > 0.99, f"vwap 落在 [low, high] 的比例过低：{ratio:.4%}"


def test_real_prices_volumes_and_cap_are_sane(real):
    """真实数据的量纲体检：价格为正、成交量非负、市值为正、收益量级合理。"""
    panel = real["panel"]
    assert (panel["close"].dropna() > 0).all().all()
    assert (panel["volume"].dropna() >= 0).all().all()
    assert (panel["amount"].dropna() >= 0).all().all()
    cap = panel["cap"].dropna()
    assert cap.size > 0 and (cap > 0).all().all()
    returns = panel["returns"].dropna()
    assert returns.abs().max().max() < 0.5  # A 股无涨跌幅限制前的极端值也不应超过 50%


@pytest.mark.parametrize("name", ["alpha101", "alpha4", "alpha5", "alpha41", "alpha56"])
def test_pilot_factors_run_on_real_data(name, real):
    """5 个试点因子在真实面板上算得出、不产生 ±inf、形状与覆盖面合理。"""
    panel = real["panel"]
    out = registry.run_factor(name, panel)
    assert out.index.equals(panel["close"].index)
    assert out.columns.equals(panel["close"].columns)
    values = out.to_numpy(dtype=float)
    assert not np.isinf(values).any(), f"{name} 产生 ±inf"
    finite_ratio = float(np.isfinite(values).mean())
    assert finite_ratio > 0.5, f"{name} 有效值过少：{finite_ratio:.2%}"


def test_real_pit_industry_panel_coverage(real):
    """申万 L1 as-of 行业面板在真实样本上的覆盖率与形态。"""
    industry = real["industry"]
    panel = real["panel"]
    assert industry.shape == panel["close"].shape
    assert float(industry.notna().to_numpy().mean()) > 0.9
    assert industry.attrs.get("level") == "L1"


def test_ind_neutralize_on_real_pit_panel_is_orthogonal(real):
    """★ 真实数据上的硬验证：``ind_neutralize`` 逐日按**当日**行业标签去均值后，行业内残差和 ≈ 0。"""
    panel, industry = real["panel"], real["industry"]
    factor = registry.run_factor("alpha4", panel)
    resid = ind_neutralize(factor, industry)
    worst = 0.0
    for day in resid.index:
        sums = resid.loc[day].groupby(industry.loc[day]).sum()
        if sums.size:
            worst = max(worst, float(np.nanmax(np.abs(sums.to_numpy()))))
    assert worst < 1e-9, f"行业内残差和未归零：{worst:.3e}"


def test_real_data_time_truncation_consistency(real):
    """真实数据上的 PIT 金标准：全量与截断在 t 处必须逐点完全相等。"""
    panel = real["panel"]
    cut = 40
    full = registry.run_factor("alpha5", panel)
    truncated = registry.run_factor("alpha5", {k: v.iloc[:cut] for k, v in panel.items()})
    pd.testing.assert_frame_equal(truncated, full.iloc[:cut])
