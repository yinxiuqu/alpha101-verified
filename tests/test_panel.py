"""面板契约用例（设计文档 §7.4，M0）。

契约校验本身也要有证据：单位口径（手/元/万元）、前复权配对、PIT 前提
（index 单调递增）都要有断言，否则「显式声明」只是口号。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v import panel as pc

_IDX = pd.date_range("2020-01-06", periods=pc.MIN_HISTORY_DAYS, freq="B")
_COLS = list("ABC")


def good_panel(n: int = pc.MIN_HISTORY_DAYS, m: int = 3) -> dict[str, pd.DataFrame]:
    """构造一份合规面板（250 日 × 3 只，含全部 10 个字段）。"""
    idx = _IDX[:n]
    cols = _COLS[:m]
    rng = np.random.default_rng(4242)
    close = pd.DataFrame(np.abs(rng.normal(10.0, 1.0, size=(n, m))) + 1.0, index=idx, columns=cols)
    volume = pd.DataFrame(np.abs(rng.normal(1e5, 1e4, size=(n, m))), index=idx, columns=cols)
    amount = volume * 100.0 * close
    return {
        "close": close,
        "Open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "volume": volume,
        "vwap": pc.vwap_from_amount(amount, volume),
        "returns": pc.returns_from_close(close),
        "amount": amount,
        "cap": pd.DataFrame(np.abs(rng.normal(1e6, 1e5, size=(n, m))), index=idx, columns=cols),
        "ind": pd.DataFrame("银行", index=idx, columns=cols),
    }


def test_units_declared_for_every_field():
    """每个契约字段都必须有显式单位声明（§7.4、§9 R4）。"""
    assert set(pc.UNITS) == set(pc.ALL_FIELDS)
    assert set(pc.REQUIRED_FIELDS) | set(pc.OPTIONAL_FIELDS) == set(pc.ALL_FIELDS)


def test_industry_level_fields_are_accepted_and_exempt_from_numeric_checks():
    """论文三个 IndClass 层级（`ind_sector/ind_industry/ind_subindustry`）是契约内的非数值字段。"""
    fields = good_panel(n=30)
    for name in ("ind_sector", "ind_industry", "ind_subindustry"):
        fields[name] = pd.DataFrame("银行", index=fields["close"].index, columns=fields["close"].columns)
    assert pc.validate_panel(fields, min_history=None) == []
    assert pc.is_non_numeric_field("ind") and pc.is_non_numeric_field("ind_subindustry")
    assert not pc.is_non_numeric_field("close")


def test_good_panel_passes_contract():
    assert pc.validate_panel(good_panel()) == []
    pc.assert_valid_panel(good_panel())


def test_missing_required_field_is_reported():
    fields = good_panel()
    del fields["vwap"]
    problems = pc.validate_panel(fields)
    assert any("缺少必需字段" in p and "vwap" in p for p in problems)


def test_min_history_is_enforced_and_can_be_skipped():
    fields = good_panel(n=20)
    assert any("最小历史长度" in p for p in pc.validate_panel(fields))
    assert pc.validate_panel(fields, min_history=None) == []


def test_non_monotonic_and_duplicate_index_are_reported():
    fields = good_panel(n=30)
    reversed_index = fields["close"].iloc[::-1]
    for name in fields:
        fields[name] = fields[name].iloc[::-1]
    assert any("未单调递增" in p for p in pc.validate_panel(fields, min_history=None))

    fields2 = good_panel(n=30)
    dup = fields2["close"].copy()
    dup.index = [dup.index[0]] * len(dup)
    fields2["close"] = dup
    problems = pc.validate_panel(fields2, min_history=None)
    assert any("重复值" in p for p in problems)
    assert reversed_index is not None


def test_misaligned_index_and_columns_are_reported():
    fields = good_panel(n=30)
    fields["volume"] = fields["volume"].iloc[:-1]
    assert any("index 与" in p for p in pc.validate_panel(fields, min_history=None))

    fields2 = good_panel(n=30)
    fields2["volume"] = fields2["volume"].rename(columns={"A": "Z"})
    assert any("columns 与" in p for p in pc.validate_panel(fields2, min_history=None))


def test_non_numeric_field_and_inf_are_reported():
    fields = good_panel(n=30)
    fields["close"] = fields["close"].astype(str)
    assert any("非数值列" in p for p in pc.validate_panel(fields, min_history=None))

    fields2 = good_panel(n=30)
    dirty = fields2["high"].copy()
    dirty.iloc[0, 0] = np.inf
    fields2["high"] = dirty
    assert any("inf" in p for p in pc.validate_panel(fields2, min_history=None))


def test_unknown_field_requires_explicit_optin():
    fields = good_panel(n=30)
    fields["mystery"] = fields["close"].copy()
    problems = pc.validate_panel(fields, min_history=None)
    assert any("白名单之外" in p for p in problems)
    assert pc.validate_panel(fields, min_history=None, allow_extra=True) == []


def test_assert_valid_panel_raises_with_all_problems():
    fields = good_panel(n=5)
    del fields["returns"]
    with pytest.raises(pc.PanelContractError) as excinfo:
        pc.assert_valid_panel(fields)
    message = str(excinfo.value)
    assert "缺少必需字段" in message and "最小历史长度" in message


def test_vwap_matches_documented_unit_convention():
    """``vwap = amount / (volume × 100)``：用设计文档 §10.2 的实测样本验证。

    样本：000001 @2026-09-04 vol=814372（手）amount=969948416（元）→ vwap ≈ 11.9104 ∈ [low, high]。
    """
    amount = pd.DataFrame([[969948416.0]], index=_IDX[:1], columns=["000001"])
    volume = pd.DataFrame([[814372.0]], index=_IDX[:1], columns=["000001"])
    vwap = pc.vwap_from_amount(amount, volume)
    assert vwap.iloc[0, 0] == pytest.approx(11.9104, abs=1e-4)
    assert 11.89 <= vwap.iloc[0, 0] <= 11.94


def test_vwap_zero_volume_is_nan_not_inf():
    """停牌/零成交 → vwap 无定义，必须 NaN。"""
    amount = pd.DataFrame([[100.0]], index=_IDX[:1], columns=["A"])
    volume = pd.DataFrame([[0.0]], index=_IDX[:1], columns=["A"])
    out = pc.vwap_from_amount(amount, volume)
    assert np.isnan(out.iloc[0, 0])


def test_returns_from_close_treats_nonpositive_price_as_nan():
    """非正价格是脏数据 → NaN，绝不产生 ±inf（停牌是「价格不变」，自然 0 收益）。"""
    close = pd.DataFrame([[10.0], [0.0], [12.0]], index=_IDX[:3], columns=["A"])
    out = pc.returns_from_close(close)
    assert np.isnan(out.iloc[1, 0])
    assert not np.isinf(out.to_numpy(dtype=float)).any()
    flat = pd.DataFrame([[10.0], [10.0]], index=_IDX[:2], columns=["A"])
    assert pc.returns_from_close(flat).iloc[1, 0] == 0.0


def test_returns_from_close_leaves_first_row_nan_by_default():
    """收益率由前复权 close 计算；首日 NaN（不 fillna(0)，见 §3.3 缺陷 7）。"""
    close = pd.DataFrame([[10.0], [11.0], [12.1]], index=_IDX[:3], columns=["A"])
    out = pc.returns_from_close(close)
    assert np.isnan(out.iloc[0, 0])
    assert out.iloc[1, 0] == pytest.approx(0.1)
    assert out.iloc[2, 0] == pytest.approx(0.1)
    assert pc.returns_from_close(close, fill_first=True).iloc[0, 0] == 0.0
