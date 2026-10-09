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


# ---------------------------------------------------------------------------
# 复权（除权除息）——真实数据上的正确性前置
# ---------------------------------------------------------------------------

ADJ_CODES = ["000001", "000028", "000100", "000153", "000567", "000657"]
ADJ_WINDOW = ("2023-01-03", "2024-06-28")


@pytest.fixture(scope="module")
def adjusted_pair() -> tuple[dict, dict, pd.DataFrame]:
    """同一区间的**不复权**与 **hfq 复权**面板，外加区间内的除权除息事件。"""
    from alpha101v.adapters.adjust import load_xdxr_events
    from alpha101v.adapters.mongo import load_panel

    raw = load_panel(ADJ_CODES, *ADJ_WINDOW, adjust="none")
    hfq = load_panel(ADJ_CODES, *ADJ_WINDOW, adjust="hfq")
    events = load_xdxr_events(ADJ_CODES, *ADJ_WINDOW)
    return raw, hfq, events


def _ex_date_returns(raw: dict, panel: dict, events: pd.DataFrame) -> tuple[float, float, int]:
    worst_raw = worst_adj = 0.0
    count = 0
    for row in events.itertuples(index=False):
        day = pd.Timestamp(row.date)
        if row.code not in panel["returns"].columns or day not in panel["returns"].index:
            continue
        raw_value = raw["returns"][row.code].loc[day]
        adj_value = panel["returns"][row.code].loc[day]
        if np.isfinite(adj_value):
            count += 1
            worst_adj = max(worst_adj, abs(float(adj_value)))
        if np.isfinite(raw_value):
            worst_raw = max(worst_raw, abs(float(raw_value)))
    return worst_raw, worst_adj, count


def test_real_ex_dividend_gaps_are_removed_by_hfq(adjusted_pair):
    """★ 复权的目的：把除权除息日的**假跳空**抹平，回到 A 股涨跌幅上限之内。

    实测（000153，2024-06-07，每 10 股送 4 股 + 派 1.5 元）：原始 −27.5% → 复权 +3.5%。
    """
    raw, hfq, events = adjusted_pair
    assert len(events) >= 5, "样本内除权事件过少，该用例失去意义"
    worst_raw, worst_adj, count = _ex_date_returns(raw, hfq, events)
    assert count >= 5
    assert worst_raw > 0.25, f"样本内未出现明显除权跳空（最大 {worst_raw:.2%}）"
    assert worst_adj < 0.21, (
        f"复权后除权日收益率仍达 {worst_adj:.2%}，超出 A 股涨跌幅上限（20%）——复权可能失效"
    )


def test_real_hfq_preserves_returns_after_the_last_event(adjusted_pair):
    """除权日**之后**（不含事件当日）原始与复权收益率必须逐点一致：复权只差一个常数缩放。"""
    raw, hfq, events, = adjusted_pair
    for code in ADJ_CODES:
        if code not in raw["returns"].columns:
            continue
        last = events.loc[events["code"] == code, "date"]
        if last.empty:
            continue
        tail = raw["returns"][code].loc[last.max():].iloc[1:]
        other = hfq["returns"][code].loc[last.max():].iloc[1:]
        np.testing.assert_allclose(
            tail.to_numpy(), other.to_numpy(), rtol=1e-12, atol=1e-15, equal_nan=True,
            err_msg=f"{code} 在最后一个除权日之后的收益率被复权改变了",
        )


def _overlap(adjust: str, field: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """同一 ``start``、截断到 ``mid`` 的窗口 vs 完整窗口，取重叠区间的某个字段。"""
    from alpha101v.adapters.mongo import load_panel

    start, end = ADJ_WINDOW
    mid = "2023-12-29"
    full = load_panel(ADJ_CODES, start, end, adjust=adjust)
    part = load_panel(ADJ_CODES, start, mid, adjust=adjust)
    return full[field].loc[:mid], part[field], pd.Timestamp(mid)


def test_real_hfq_levels_are_pit_consistent_but_qfq_levels_are_not():
    """★ 因果性对照（实测细化）：前视体现在**价格水平**上，不在收益率上。

    * ``hfq`` 以窗口首行为基准，只依赖**过去**事件 ⇒ 窗口拉长后重叠区间的**价格水平逐点不变**；
    * ``qfq`` 以窗口末行为基准 ⇒ 一旦窗口向后延长（出现新的除权事件），
      **全部历史价格水平都会改变**（整只股票乘上一个新常数）——这就是它的前视；
    * 两者的差是「每股一个常数缩放」，因此**收益率在两种模式下都一致**——
      这也解释了为什么纯收益类因子对复权模式不敏感，而**水平型**因子
      （如 `alpha41 = sqrt(high·low) − vwap`）必须显式选定口径。
    """
    full_hfq, part_hfq, mid = _overlap("hfq", "close")
    pd.testing.assert_frame_equal(part_hfq.loc[:mid], full_hfq.loc[:mid])

    full_qfq, part_qfq, mid = _overlap("qfq", "close")
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(part_qfq.loc[:mid], full_qfq.loc[:mid])

    # 收益率对两种模式都不变（差一个每股常数）
    for adjust in ("hfq", "qfq"):
        full_ret, part_ret, mid = _overlap(adjust, "returns")
        pd.testing.assert_frame_equal(part_ret.loc[:mid], full_ret.loc[:mid], check_exact=False)


def test_real_data_time_truncation_consistency(real):
    """真实数据上的 PIT 金标准：全量与截断在 t 处必须逐点完全相等。"""
    panel = real["panel"]
    cut = 40
    full = registry.run_factor("alpha5", panel)
    truncated = registry.run_factor("alpha5", {k: v.iloc[:cut] for k, v in panel.items()})
    pd.testing.assert_frame_equal(truncated, full.iloc[:cut])
