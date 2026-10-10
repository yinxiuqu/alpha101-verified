"""alpha101v.factors — 因子层（M3：全部 101 个因子，论文逐字转写）。

转写纪律（设计文档 §4.5 clean-room）
------------------------------------
* 每个因子的公式**逐字来自论文**（arXiv:1601.00991v3，Appendix A），原文见
  `docs/paper_formulas.md` §5；每个函数 docstring 保留该因子原文一行，便于逐条核对；
* 本文件**不参考任何 GPL 许可实现的代码**（`tests/test_provenance.py` 机械守门）。

契约（与设计文档 §7.5 的自动装配配合）
-------------------------------------
* 因子是**纯函数**：形参名 = 面板字段名（`close` / `Open` / `high` / `low` / `volume` /
  `vwap` / `returns` / `amount` / `cap` / `ind_<level>`），`registry.run_factor` 按名字装配；
* 入参同 (index, columns) 契约并先校验；**绝不原地修改入参**；缺数据 → NaN（不 fillna(0)）。

论文记号的落地映射（消歧决策见 docs/operators.md §3.9–§3.12）
------------------------------------------------------------
====================== ==================================================
`sum`                  → `ts_sum`
`min/max(x, 常数d)`     → `ts_min/ts_max`；`min/max(表达式, 表达式)` → 逐元素 `minimum/maximum`
`adv{d}`               → `_adv(amount, d)` = `sma(amount, d)`（论文：平均每日**美元成交额**）
`^`                    → `_pow(x, a)` = 保号幂 `sign(x)·|x|^a`（消歧见 A20）
`x ? y : z`            → `_if`；比较 → `_lt/_gt/_eq`（**NaN 传播**，非 C 的 False）
`||`                   → `_or`（Kleene 三值：True∨未知=True，False∨未知=未知）
`IndNeutralize(x, IndClass.<level>)` → `ind_neutralize(x, ind_<level>)`
====================== ==================================================

状态（设计文档 §6.8 / §9 R2）
----------------------------
`verified` 需六条门槛全满足（含 L3 因子级差分与 L5 golden 快照）⇒ M3 阶段无人可得；
故只标 `partial`（结构与论文一致）与 `ambiguous`（**规范本身未定**且改变数值）。
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from .elemwise import abs_, log, maximum, minimum, sign, signedpower
from .neutralize import ind_neutralize
from .operators import (
    _as_frame,
    _check_numeric,
    _check_unique_axes,
    correlation,
    covariance,
    decay_linear,
    delta,
    delay,
    product,
    rank,
    scale,
    sma,
    stddev,
    ts_argmax,
    ts_argmin,
    ts_max,
    ts_min,
    ts_rank,
    ts_sum,
)

__all__ = ["ALL_FACTOR_NAMES", "AMBIGUOUS_FACTORS", "PILOT_NAMES", "ambiguous_reason"]


# ---------------------------------------------------------------------------
# 内部工具：面板校验 + 论文记号映射（都不是算子；规范对照器会忽略或映射它们）
# ---------------------------------------------------------------------------


def _panels(**named: object) -> dict[str, pd.DataFrame]:
    """校验一批面板：数值、轴唯一、且彼此同 (index, columns) 契约。

    因子里的原始算术（`close - Open`）不做对齐检查，若两块面板轴不同 pandas 会
    **静默外连接并产出 NaN**，因此因子层必须显式校验。
    """
    numeric = {k: v for k, v in named.items() if not k.startswith("ind")}
    labels = {k: v for k, v in named.items() if k.startswith("ind")}

    frames: dict[str, pd.DataFrame] = {}
    reference: tuple[str, pd.DataFrame] | None = None
    for name, obj in numeric.items():
        frame = _as_frame(obj, name)
        _check_numeric(frame, name)
        _check_unique_axes(frame, name)
        if reference is None:
            reference = (name, frame)
        else:
            ref_name, ref = reference
            if not frame.index.equals(ref.index) or not frame.columns.equals(ref.columns):
                raise ValueError(
                    f"因子入参必须共享同一 (index, columns) 契约：{name!r} 与 {ref_name!r} 不一致"
                )
        frames[name] = frame

    if reference is None:
        raise ValueError("因子至少需要一个数值面板")
    ref_name, ref = reference

    # 行业标签面板（`ind_<level>`）：可以是 `Series`（静态快照，index=股票代码）或
    # `DataFrame`（PIT as-of，index=交易日）——非数值，因此只校验轴对齐，不做数值检查。
    for name, obj in labels.items():
        if isinstance(obj, pd.Series):
            if not obj.index.equals(ref.columns):
                raise ValueError(
                    f"{name!r} 的 index 必须等于面板 columns（股票代码）；"
                    f"收到 {list(obj.index[:3])} vs {list(ref.columns[:3])}"
                )
            frames[name] = obj  # 保留 Series 形态（ind_neutralize 直接支持）
        else:
            frame = _as_frame(obj, name)
            _check_unique_axes(frame, name)
            if not frame.index.equals(ref.index) or not frame.columns.equals(ref.columns):
                raise ValueError(
                    f"{name!r}（PIT 行业面板）必须与数值面板同 (index, columns)；"
                    f"收到 {frame.shape} vs {ref.shape}"
                )
            frames[name] = frame
    return frames


def _adv(amount: pd.DataFrame, window: int) -> pd.DataFrame:
    """论文 ``adv{d}`` = 平均每日**美元成交额**（dollar volume）→ A 股取 ``amount``（元）。

    用 ``volume``（手/股）替代属「近似」（设计文档 §6.3 举的正是这个例子），影响 45 个因子，
    已记入 `docs/deviations.md` §1.2 P2。
    """
    return sma(amount, window)


def _values(obj: object, like: pd.DataFrame) -> float | np.ndarray:
    """把比较/逻辑的右操作数规范成「标量」或「与 like 同形的 float 矩阵」。"""
    if isinstance(obj, bool):
        raise TypeError("布尔字面量不参与因子表达式（请用比较表达式）")
    if isinstance(obj, (int, float, np.integer, np.floating)):
        return float(obj)
    frame = _as_frame(obj)
    if not frame.index.equals(like.index) or not frame.columns.equals(like.columns):
        raise ValueError("比较/逻辑的两侧必须共享同一 (index, columns) 契约")
    return frame.to_numpy(dtype=float)


def _reference_frame(*operands: object) -> pd.DataFrame:
    """从操作数里挑出作为对齐基准的面板（论文里比较的**任一侧**都可能是标量，如 `0 < ts_min(...)`）。"""
    for obj in operands:
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            return _as_frame(obj)
    raise TypeError("比较/逻辑运算至少需要一个 DataFrame/Series 操作数")


def _cmp(left: object, right: object, operator: str) -> pd.DataFrame:
    """逐格比较，**NaN 传播**（任一侧缺失 ⇒ NaN，而不是 C 语义的 False）。

    理由：把「未知」输出成 0 会让下游把缺失当成真实结论（设计文档 §3.3 缺陷 7 的同类批评）。
    """
    reference = _reference_frame(left, right)
    left_values = _values(left, reference)
    right_values = _values(right, reference)
    with np.errstate(invalid="ignore"):
        raw = {"<": left_values < right_values, ">": left_values > right_values,
               "==": left_values == right_values}[operator]
    comparable = np.isfinite(left_values) & np.isfinite(right_values)
    return pd.DataFrame(
        np.where(comparable, raw.astype(float), np.nan),
        index=reference.index, columns=reference.columns,
    )


def _lt(left: object, right: object) -> pd.DataFrame:
    return _cmp(left, right, "<")


def _gt(left: object, right: object) -> pd.DataFrame:
    return _cmp(left, right, ">")


def _eq(left: object, right: object) -> pd.DataFrame:
    return _cmp(left, right, "==")


def _or(left: object, right: object) -> pd.DataFrame:
    """论文 ``||``：Kleene 三值逻辑（True ∨ 未知 = True；False ∨ 未知 = 未知）。"""
    reference = _reference_frame(left, right)
    left_values = _values(left, reference)
    right_values = _values(right, reference)
    return pd.DataFrame(
        np.where(
            (left_values == 1.0) | (right_values == 1.0),
            1.0,
            np.where((left_values == 0.0) & (right_values == 0.0), 0.0, np.nan),
        ),
        index=reference.index, columns=reference.columns,
    )


def _if(condition: pd.DataFrame, yes: object, no: object) -> pd.DataFrame:
    """论文三元 ``cond ? yes : no``（逐格选择；条件为 NaN ⇒ 结果 NaN）。"""
    condition_frame = _as_frame(condition)
    condition_values = condition_frame.to_numpy(dtype=float)
    yes_values = _values(yes, condition_frame)
    no_values = _values(no, condition_frame)
    return pd.DataFrame(
        np.where(
            condition_values == 1.0, yes_values, np.where(condition_values == 0.0, no_values, np.nan)
        ),
        index=condition_frame.index, columns=condition_frame.columns,
    )


def _pow(base: object, exponent: object) -> pd.DataFrame:
    """论文中缀 ``^``：默认取**保号幂** ``sign(x)·|x|^a``（消歧与影响见 ambiguous 原因 A20）。

    切到论文字面 ``x^a`` 只需改成 ``signedpower(..., preserve_sign=False)``；两者只在
    **底数为负**时不同（alpha48 的负收益平方、alpha90 的负离差^分数指数）——这两个因子
    因此被标为 `ambiguous`。
    """
    return signedpower(base, exponent, preserve_sign=True)


# ---------------------------------------------------------------------------
# 因子 1–101（论文逐字转写）
# ---------------------------------------------------------------------------


def alpha1(close, returns):
    r"""Alpha#1: (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)"""
    p = _panels(close=close, returns=returns)
    base = _if(_lt(p["returns"], 0), stddev(p["returns"], 20), p["close"])
    return rank(ts_argmax(signedpower(base, 2.0), 5)) - 0.5


def alpha2(close, Open, volume):
    r"""Alpha#2: (-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))"""
    p = _panels(close=close, Open=Open, volume=volume)
    return -1.0 * correlation(
        rank(delta(log(p["volume"]), 2)), rank((p["close"] - p["Open"]) / p["Open"]), 6
    )


def alpha3(Open, volume):
    r"""Alpha#3: (-1 * correlation(rank(open), rank(volume), 10))"""
    p = _panels(Open=Open, volume=volume)
    return -1.0 * correlation(rank(p["Open"]), rank(p["volume"]), 10)


def alpha4(low):
    r"""Alpha#4: (-1 * Ts_Rank(rank(low), 9))"""
    p = _panels(low=low)
    return -1.0 * ts_rank(rank(p["low"]), 9)


def alpha5(close, Open, vwap):
    r"""Alpha#5: (rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))"""
    p = _panels(close=close, Open=Open, vwap=vwap)
    return rank(p["Open"] - (ts_sum(p["vwap"], 10) / 10)) * (-1.0 * abs_(rank(p["close"] - p["vwap"])))


def alpha6(Open, volume):
    r"""Alpha#6: (-1 * correlation(open, volume, 10))"""
    p = _panels(Open=Open, volume=volume)
    return -1.0 * correlation(p["Open"], p["volume"], 10)


def alpha7(close, amount, volume):
    r"""Alpha#7: ((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))"""
    p = _panels(close=close, amount=amount, volume=volume)
    adv20 = _adv(p["amount"], 20)
    return _if(
        _lt(adv20, p["volume"]),
        (-1.0 * ts_rank(abs_(delta(p["close"], 7)), 60)) * sign(delta(p["close"], 7)),
        -1.0 * 1,
    )


def alpha8(Open, returns):
    r"""Alpha#8: (-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10))))"""
    p = _panels(Open=Open, returns=returns)
    combined = ts_sum(p["Open"], 5) * ts_sum(p["returns"], 5)
    return -1.0 * rank(combined - delay(combined, 10))


def alpha9(close):
    r"""Alpha#9: ((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : (-1 * delta(close, 1))))"""
    p = _panels(close=close)
    change = delta(p["close"], 1)
    return _if(
        _lt(0, ts_min(change, 5)), change, _if(_lt(ts_max(change, 5), 0), change, -1.0 * change)
    )


def alpha10(close):
    r"""Alpha#10: rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close, 1) : (-1 * delta(close, 1)))))"""
    p = _panels(close=close)
    change = delta(p["close"], 1)
    return rank(
        _if(_lt(0, ts_min(change, 4)), change, _if(_lt(ts_max(change, 4), 0), change, -1.0 * change))
    )


def alpha11(close, vwap, volume):
    r"""Alpha#11: ((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))"""
    p = _panels(close=close, vwap=vwap, volume=volume)
    spread = p["vwap"] - p["close"]
    return (rank(ts_max(spread, 3)) + rank(ts_min(spread, 3))) * rank(delta(p["volume"], 3))


def alpha12(close, volume):
    r"""Alpha#12: (sign(delta(volume, 1)) * (-1 * delta(close, 1)))"""
    p = _panels(close=close, volume=volume)
    return sign(delta(p["volume"], 1)) * (-1.0 * delta(p["close"], 1))


def alpha13(close, volume):
    r"""Alpha#13: (-1 * rank(covariance(rank(close), rank(volume), 5)))"""
    p = _panels(close=close, volume=volume)
    return -1.0 * rank(covariance(rank(p["close"]), rank(p["volume"]), 5))


def alpha14(Open, volume, returns):
    r"""Alpha#14: ((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))"""
    p = _panels(Open=Open, volume=volume, returns=returns)
    return (-1.0 * rank(delta(p["returns"], 3))) * correlation(p["Open"], p["volume"], 10)


def alpha15(high, volume):
    r"""Alpha#15: (-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))"""
    p = _panels(high=high, volume=volume)
    return -1.0 * ts_sum(rank(correlation(rank(p["high"]), rank(p["volume"]), 3)), 3)


def alpha16(high, volume):
    r"""Alpha#16: (-1 * rank(covariance(rank(high), rank(volume), 5)))"""
    p = _panels(high=high, volume=volume)
    return -1.0 * rank(covariance(rank(p["high"]), rank(p["volume"]), 5))


def alpha17(close, amount, volume):
    r"""Alpha#17: (((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))"""
    p = _panels(close=close, amount=amount, volume=volume)
    adv20 = _adv(p["amount"], 20)
    return (
        (-1.0 * rank(ts_rank(p["close"], 10)))
        * rank(delta(delta(p["close"], 1), 1))
        * rank(ts_rank(p["volume"] / adv20, 5))
    )


def alpha18(close, Open):
    r"""Alpha#18: (-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open, 10))))"""
    p = _panels(close=close, Open=Open)
    return -1.0 * rank(
        stddev(abs_(p["close"] - p["Open"]), 5)
        + (p["close"] - p["Open"])
        + correlation(p["close"], p["Open"], 10)
    )


def alpha19(close, returns):
    r"""Alpha#19: ((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250)))))"""
    p = _panels(close=close, returns=returns)
    return (-1.0 * sign((p["close"] - delay(p["close"], 7)) + delta(p["close"], 7))) * (
        1 + rank(1 + ts_sum(p["returns"], 250))
    )


def alpha20(close, Open, high, low):
    r"""Alpha#20: (((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open - delay(low, 1))))"""
    p = _panels(close=close, Open=Open, high=high, low=low)
    return (
        (-1.0 * rank(p["Open"] - delay(p["high"], 1)))
        * rank(p["Open"] - delay(p["close"], 1))
        * rank(p["Open"] - delay(p["low"], 1))
    )


def alpha21(close, amount, volume):
    r"""Alpha#21: ((((sum(close, 8) / 8) + stddev(close, 8)) < (sum(close, 2) / 2)) ? (-1 * 1) : (((sum(close, 2) / 2) < ((sum(close, 8) / 8) - stddev(close, 8))) ? 1 : (((1 < (volume / adv20)) || ((volume / adv20) == 1)) ? 1 : (-1 * 1))))"""
    p = _panels(close=close, amount=amount, volume=volume)
    adv20 = _adv(p["amount"], 20)
    ratio = p["volume"] / adv20
    return _if(
        _lt((ts_sum(p["close"], 8) / 8) + stddev(p["close"], 8), ts_sum(p["close"], 2) / 2),
        -1.0 * 1,
        _if(
            _lt(ts_sum(p["close"], 2) / 2, (ts_sum(p["close"], 8) / 8) - stddev(p["close"], 8)),
            1,
            _if(_or(_lt(1, ratio), _eq(ratio, 1)), 1, -1.0 * 1),
        ),
    )


def alpha22(close, high, volume):
    r"""Alpha#22: (-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))"""
    p = _panels(close=close, high=high, volume=volume)
    return -1.0 * (delta(correlation(p["high"], p["volume"], 5), 5) * rank(stddev(p["close"], 20)))


def alpha23(high):
    r"""Alpha#23: (((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)"""
    p = _panels(high=high)
    return _if(_lt(ts_sum(p["high"], 20) / 20, p["high"]), -1.0 * delta(p["high"], 2), 0)


def alpha24(close):
    r"""Alpha#24: ((((delta((sum(close, 100) / 100), 100) / delay(close, 100)) < 0.05) || ((delta((sum(close, 100) / 100), 100) / delay(close, 100)) == 0.05)) ? (-1 * (close - ts_min(close, 100))) : (-1 * delta(close, 3)))"""
    p = _panels(close=close)
    ratio = delta(ts_sum(p["close"], 100) / 100, 100) / delay(p["close"], 100)
    return _if(
        _or(_lt(ratio, 0.05), _eq(ratio, 0.05)),
        -1.0 * (p["close"] - ts_min(p["close"], 100)),
        -1.0 * delta(p["close"], 3),
    )


def alpha25(close, high, vwap, returns, amount):
    r"""Alpha#25: rank(((((-1 * returns) * adv20) * vwap) * (high - close)))"""
    p = _panels(close=close, high=high, vwap=vwap, returns=returns, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return rank((((-1.0 * p["returns"]) * adv20) * p["vwap"]) * (p["high"] - p["close"]))


def alpha26(high, volume):
    r"""Alpha#26: (-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))"""
    p = _panels(high=high, volume=volume)
    return -1.0 * ts_max(correlation(ts_rank(p["volume"], 5), ts_rank(p["high"], 5), 5), 3)


def alpha27(vwap, volume):
    r"""Alpha#27: ((0.5 < rank((sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0))) ? (-1 * 1) : 1)"""
    p = _panels(vwap=vwap, volume=volume)
    value = rank(ts_sum(correlation(rank(p["volume"]), rank(p["vwap"]), 6), 2) / 2.0)
    return _if(_lt(0.5, value), -1.0 * 1, 1)


def alpha28(close, high, low, amount):
    r"""Alpha#28: scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))"""
    p = _panels(close=close, high=high, low=low, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return scale(correlation(adv20, p["low"], 5) + ((p["high"] + p["low"]) / 2) - p["close"])


def alpha29(close, returns):
    r"""Alpha#29: (min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1), 5))))), 2), 1))))), 1), 5) + ts_rank(delay((-1 * returns), 6), 5))"""
    p = _panels(close=close, returns=returns)
    inner = ts_min(rank(rank((-1.0 * rank(delta(p["close"] - 1, 5))))), 2)
    smoothed = product(rank(rank(scale(log(ts_sum(inner, 1))))), 1)
    return ts_min(smoothed, 5) + ts_rank(delay(-1.0 * p["returns"], 6), 5)


def alpha30(close, volume):
    r"""Alpha#30: (((1.0 - rank(((sign((close - delay(close, 1))) + sign((delay(close, 1) - delay(close, 2)))) + sign((delay(close, 2) - delay(close, 3)))))) * sum(volume, 5)) / sum(volume, 20))"""
    p = _panels(close=close, volume=volume)
    signs = (
        sign(p["close"] - delay(p["close"], 1))
        + sign(delay(p["close"], 1) - delay(p["close"], 2))
    ) + sign(delay(p["close"], 2) - delay(p["close"], 3))
    return ((1.0 - rank(signs)) * ts_sum(p["volume"], 5)) / ts_sum(p["volume"], 20)


def alpha31(close, low, amount):
    r"""Alpha#31: ((rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10)))) + rank((-1 * delta(close, 3)))) + sign(scale(correlation(adv20, low, 12))))"""
    p = _panels(close=close, low=low, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return (
        rank(rank(rank(decay_linear(-1.0 * rank(rank(delta(p["close"], 10))), 10))))
        + rank(-1.0 * delta(p["close"], 3))
    ) + sign(scale(correlation(adv20, p["low"], 12)))


def alpha32(close, vwap):
    r"""Alpha#32: (scale(((sum(close, 7) / 7) - close)) + (20 * scale(correlation(vwap, delay(close, 5), 230))))"""
    p = _panels(close=close, vwap=vwap)
    return scale((ts_sum(p["close"], 7) / 7) - p["close"]) + (
        20 * scale(correlation(p["vwap"], delay(p["close"], 5), 230))
    )


def alpha33(close, Open):
    r"""Alpha#33: rank((-1 * ((1 - (open / close))^1)))"""
    p = _panels(close=close, Open=Open)
    return rank(-1.0 * _pow(1 - (p["Open"] / p["close"]), 1))


def alpha34(close, returns):
    r"""Alpha#34: rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + (1 - rank(delta(close, 1)))))"""
    p = _panels(close=close, returns=returns)
    return rank(
        (1 - rank(stddev(p["returns"], 2) / stddev(p["returns"], 5))) + (1 - rank(delta(p["close"], 1)))
    )


def alpha35(close, high, low, volume, returns):
    r"""Alpha#35: ((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * (1 - Ts_Rank(returns, 32)))"""
    p = _panels(close=close, high=high, low=low, volume=volume, returns=returns)
    return (ts_rank(p["volume"], 32) * (1 - ts_rank((p["close"] + p["high"]) - p["low"], 16))) * (
        1 - ts_rank(p["returns"], 32)
    )


def alpha36(close, Open, vwap, volume, returns, amount):
    r"""Alpha#36: (((((2.21 * rank(correlation((close - open), delay(volume, 1), 15))) + (0.7 * rank((open - close)))) + (0.73 * rank(Ts_Rank(delay((-1 * returns), 6), 5)))) + rank(abs(correlation(vwap, adv20, 6)))) + (0.6 * rank((((sum(close, 200) / 200) - open) * (close - open)))))"""
    p = _panels(close=close, Open=Open, vwap=vwap, volume=volume, returns=returns, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return (
        (
            (
                (2.21 * rank(correlation(p["close"] - p["Open"], delay(p["volume"], 1), 15)))
                + (0.7 * rank(p["Open"] - p["close"]))
            )
            + (0.73 * rank(ts_rank(delay(-1.0 * p["returns"], 6), 5)))
        )
        + rank(abs_(correlation(p["vwap"], adv20, 6)))
    ) + (0.6 * rank(((ts_sum(p["close"], 200) / 200) - p["Open"]) * (p["close"] - p["Open"])))


def alpha37(close, Open):
    r"""Alpha#37: (rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))"""
    p = _panels(close=close, Open=Open)
    return rank(correlation(delay(p["Open"] - p["close"], 1), p["close"], 200)) + rank(
        p["Open"] - p["close"]
    )


def alpha38(close, Open):
    r"""Alpha#38: ((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))"""
    p = _panels(close=close, Open=Open)
    return (-1.0 * rank(ts_rank(p["close"], 10))) * rank(p["close"] / p["Open"])


def alpha39(close, volume, returns, amount):
    r"""Alpha#39: ((-1 * rank((delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))))) * (1 + rank(sum(returns, 250))))"""
    p = _panels(close=close, volume=volume, returns=returns, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return (
        -1.0 * rank(delta(p["close"], 7) * (1 - rank(decay_linear(p["volume"] / adv20, 9))))
    ) * (1 + rank(ts_sum(p["returns"], 250)))


def alpha40(high, volume):
    r"""Alpha#40: ((-1 * rank(stddev(high, 10))) * correlation(high, volume, 10))"""
    p = _panels(high=high, volume=volume)
    return (-1.0 * rank(stddev(p["high"], 10))) * correlation(p["high"], p["volume"], 10)


def alpha41(high, low, vwap):
    r"""Alpha#41: (((high * low)^0.5) - vwap)"""
    p = _panels(high=high, low=low, vwap=vwap)
    return _pow(p["high"] * p["low"], 0.5) - p["vwap"]


def alpha42(close, vwap):
    r"""Alpha#42: (rank((vwap - close)) / rank((vwap + close)))"""
    p = _panels(close=close, vwap=vwap)
    return rank(p["vwap"] - p["close"]) / rank(p["vwap"] + p["close"])


def alpha43(close, volume, amount):
    r"""Alpha#43: (ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, 7)), 8))"""
    p = _panels(close=close, volume=volume, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return ts_rank(p["volume"] / adv20, 20) * ts_rank(-1.0 * delta(p["close"], 7), 8)


def alpha44(high, volume):
    r"""Alpha#44: (-1 * correlation(high, rank(volume), 5))"""
    p = _panels(high=high, volume=volume)
    return -1.0 * correlation(p["high"], rank(p["volume"]), 5)


def alpha45(close, volume):
    r"""Alpha#45: (-1 * ((rank((sum(delay(close, 5), 20) / 20)) * correlation(close, volume, 2)) * rank(correlation(sum(close, 5), sum(close, 20), 2))))"""
    p = _panels(close=close, volume=volume)
    return -1.0 * (
        rank(ts_sum(delay(p["close"], 5), 20) / 20)
        * correlation(p["close"], p["volume"], 2)
        * rank(correlation(ts_sum(p["close"], 5), ts_sum(p["close"], 20), 2))
    )


def alpha46(close):
    r"""Alpha#46: ((0.25 < (((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10))) ? (-1 * 1) : (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < 0) ? 1 : ((-1 * 1) * (close - delay(close, 1)))))"""
    p = _panels(close=close)
    inner = ((delay(p["close"], 20) - delay(p["close"], 10)) / 10) - (
        (delay(p["close"], 10) - p["close"]) / 10
    )
    return _if(
        _lt(0.25, inner),
        -1.0 * 1,
        _if(_lt(inner, 0), 1, (-1.0 * 1) * (p["close"] - delay(p["close"], 1))),
    )


def alpha47(close, high, vwap, volume, amount):
    r"""Alpha#47: ((((rank((1 / close)) * volume) / adv20) * ((high * rank((high - close))) / (sum(high, 5) / 5))) - rank((vwap - delay(vwap, 5))))"""
    p = _panels(close=close, high=high, vwap=vwap, volume=volume, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return (
        ((rank(1 / p["close"]) * p["volume"]) / adv20)
        * ((p["high"] * rank(p["high"] - p["close"])) / (ts_sum(p["high"], 5) / 5))
    ) - rank(p["vwap"] - delay(p["vwap"], 5))


def alpha48(close, ind_subindustry):
    r"""Alpha#48: (indneutralize(((correlation(delta(close, 1), delta(delay(close, 1), 1), 250) * delta(close, 1)) / close), IndClass.subindustry) / sum(((delta(close, 1) / delay(close, 1))^2), 250))"""
    p = _panels(close=close, ind_subindustry=ind_subindustry)
    numerator = (
        correlation(delta(p["close"], 1), delta(delay(p["close"], 1), 1), 250) * delta(p["close"], 1)
    ) / p["close"]
    return ind_neutralize(numerator, p["ind_subindustry"]) / ts_sum(
        _pow(delta(p["close"], 1) / delay(p["close"], 1), 2), 250
    )


def alpha49(close):
    r"""Alpha#49: (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.1)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))"""
    p = _panels(close=close)
    inner = ((delay(p["close"], 20) - delay(p["close"], 10)) / 10) - (
        (delay(p["close"], 10) - p["close"]) / 10
    )
    return _if(_lt(inner, -1.0 * 0.1), 1, (-1.0 * 1) * (p["close"] - delay(p["close"], 1)))


def alpha50(vwap, volume):
    r"""Alpha#50: (-1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)), 5))"""
    p = _panels(vwap=vwap, volume=volume)
    return -1.0 * ts_max(rank(correlation(rank(p["volume"]), rank(p["vwap"]), 5)), 5)


def alpha51(close):
    r"""Alpha#51: (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.05)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))"""
    p = _panels(close=close)
    inner = ((delay(p["close"], 20) - delay(p["close"], 10)) / 10) - (
        (delay(p["close"], 10) - p["close"]) / 10
    )
    return _if(_lt(inner, -1.0 * 0.05), 1, (-1.0 * 1) * (p["close"] - delay(p["close"], 1)))


def alpha52(low, volume, returns):
    r"""Alpha#52: ((((-1 * ts_min(low, 5)) + delay(ts_min(low, 5), 5)) * rank(((sum(returns, 240) - sum(returns, 20)) / 220))) * ts_rank(volume, 5))"""
    p = _panels(low=low, volume=volume, returns=returns)
    return (
        ((-1.0 * ts_min(p["low"], 5)) + delay(ts_min(p["low"], 5), 5))
        * rank((ts_sum(p["returns"], 240) - ts_sum(p["returns"], 20)) / 220)
    ) * ts_rank(p["volume"], 5)


def alpha53(close, high, low):
    r"""Alpha#53: (-1 * delta((((close - low) - (high - close)) / (close - low)), 9))"""
    p = _panels(close=close, high=high, low=low)
    return -1.0 * delta(((p["close"] - p["low"]) - (p["high"] - p["close"])) / (p["close"] - p["low"]), 9)


def alpha54(close, Open, high, low):
    r"""Alpha#54: ((-1 * ((low - close) * (open^5))) / ((low - high) * (close^5)))"""
    p = _panels(close=close, Open=Open, high=high, low=low)
    return (-1.0 * ((p["low"] - p["close"]) * _pow(p["Open"], 5))) / (
        (p["low"] - p["high"]) * _pow(p["close"], 5)
    )


def alpha55(close, high, low, volume):
    r"""Alpha#55: (-1 * correlation(rank(((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12)))), rank(volume), 6))"""
    p = _panels(close=close, high=high, low=low, volume=volume)
    return -1.0 * correlation(
        rank((p["close"] - ts_min(p["low"], 12)) / (ts_max(p["high"], 12) - ts_min(p["low"], 12))),
        rank(p["volume"]),
        6,
    )


def alpha56(returns, cap):
    r"""Alpha#56: (0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))"""
    p = _panels(returns=returns, cap=cap)
    return 0 - (
        1
        * (
            rank(ts_sum(p["returns"], 10) / ts_sum(ts_sum(p["returns"], 2), 3))
            * rank(p["returns"] * p["cap"])
        )
    )


def alpha57(close, vwap):
    r"""Alpha#57: (0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2))))"""
    p = _panels(close=close, vwap=vwap)
    return 0 - (1 * ((p["close"] - p["vwap"]) / decay_linear(rank(ts_argmax(p["close"], 30)), 2)))


def alpha58(vwap, volume, ind_sector):
    r"""Alpha#58: (-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.sector), volume, 3.92795), 7.89291), 5.50322))"""
    p = _panels(vwap=vwap, volume=volume, ind_sector=ind_sector)
    return -1.0 * ts_rank(
        decay_linear(
            correlation(ind_neutralize(p["vwap"], p["ind_sector"]), p["volume"], 3.92795), 7.89291
        ),
        5.50322,
    )


def alpha59(vwap, volume, ind_industry):
    r"""Alpha#59: (-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(((vwap * 0.728317) + (vwap * (1 - 0.728317))), IndClass.industry), volume, 4.25197), 16.2289), 8.19648))"""
    p = _panels(vwap=vwap, volume=volume, ind_industry=ind_industry)
    blended = (p["vwap"] * 0.728317) + (p["vwap"] * (1 - 0.728317))
    return -1.0 * ts_rank(
        decay_linear(
            correlation(ind_neutralize(blended, p["ind_industry"]), p["volume"], 4.25197), 16.2289
        ),
        8.19648,
    )


def alpha60(close, high, low, volume):
    r"""Alpha#60: (0 - (1 * ((2 * scale(rank(((((close - low) - (high - close)) / (high - low)) * volume)))) - scale(rank(ts_argmax(close, 10))))))"""
    p = _panels(close=close, high=high, low=low, volume=volume)
    return 0 - (
        1
        * (
            (
                2
                * scale(
                    rank(
                        (((p["close"] - p["low"]) - (p["high"] - p["close"]))
                         / (p["high"] - p["low"]))
                        * p["volume"]
                    )
                )
            )
            - scale(rank(ts_argmax(p["close"], 10)))
        )
    )


def alpha61(vwap, amount):
    r"""Alpha#61: (rank((vwap - ts_min(vwap, 16.1219))) < rank(correlation(vwap, adv180, 17.9282)))"""
    p = _panels(vwap=vwap, amount=amount)
    adv180 = _adv(p["amount"], 180)
    return _lt(
        rank(p["vwap"] - ts_min(p["vwap"], 16.1219)),
        rank(correlation(p["vwap"], adv180, 17.9282)),
    )


def alpha62(Open, high, low, vwap, amount):
    r"""Alpha#62: ((rank(correlation(vwap, sum(adv20, 22.4101), 9.91009)) < rank(((rank(open) + rank(open)) < (rank(((high + low) / 2)) + rank(high))))) * -1)"""
    p = _panels(Open=Open, high=high, low=low, vwap=vwap, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return (
        _lt(
            rank(correlation(p["vwap"], ts_sum(adv20, 22.4101), 9.91009)),
            rank(
                _lt(
                    rank(p["Open"]) + rank(p["Open"]),
                    rank((p["high"] + p["low"]) / 2) + rank(p["high"]),
                )
            ),
        )
        * -1
    )


def alpha63(close, Open, vwap, amount, ind_industry):
    r"""Alpha#63: ((rank(decay_linear(delta(IndNeutralize(close, IndClass.industry), 2.25164), 8.22237)) - rank(decay_linear(correlation(((vwap * 0.318108) + (open * (1 - 0.318108))), sum(adv180, 37.2467), 13.557), 12.2883))) * -1)"""
    p = _panels(close=close, Open=Open, vwap=vwap, amount=amount, ind_industry=ind_industry)
    adv180 = _adv(p["amount"], 180)
    blended = (p["vwap"] * 0.318108) + (p["Open"] * (1 - 0.318108))
    left = rank(decay_linear(delta(ind_neutralize(p["close"], p["ind_industry"]), 2.25164), 8.22237))
    right = rank(decay_linear(correlation(blended, ts_sum(adv180, 37.2467), 13.557), 12.2883))
    return (left - right) * -1


def alpha64(Open, high, low, vwap, amount):
    r"""Alpha#64: ((rank(correlation(sum(((open * 0.178404) + (low * (1 - 0.178404))), 12.7054), sum(adv120, 12.7054), 16.6208)) < rank(delta(((((high + low) / 2) * 0.178404) + (vwap * (1 - 0.178404))), 3.69741))) * -1)"""
    p = _panels(Open=Open, high=high, low=low, vwap=vwap, amount=amount)
    adv120 = _adv(p["amount"], 120)
    blended_open_low = (p["Open"] * 0.178404) + (p["low"] * (1 - 0.178404))
    blended_mid = (((p["high"] + p["low"]) / 2) * 0.178404) + (p["vwap"] * (1 - 0.178404))
    return (
        _lt(
            rank(correlation(ts_sum(blended_open_low, 12.7054), ts_sum(adv120, 12.7054), 16.6208)),
            rank(delta(blended_mid, 3.69741)),
        )
        * -1
    )


def alpha65(Open, vwap, amount):
    r"""Alpha#65: ((rank(correlation(((open * 0.00817205) + (vwap * (1 - 0.00817205))), sum(adv60, 8.6911), 6.40374)) < rank((open - ts_min(open, 13.635)))) * -1)"""
    p = _panels(Open=Open, vwap=vwap, amount=amount)
    adv60 = _adv(p["amount"], 60)
    blended = (p["Open"] * 0.00817205) + (p["vwap"] * (1 - 0.00817205))
    return (
        _lt(
            rank(correlation(blended, ts_sum(adv60, 8.6911), 6.40374)),
            rank(p["Open"] - ts_min(p["Open"], 13.635)),
        )
        * -1
    )


def alpha66(Open, high, low, vwap):
    r"""Alpha#66: ((rank(decay_linear(delta(vwap, 3.51013), 7.23052)) + Ts_Rank(decay_linear(((((low * 0.96633) + (low * (1 - 0.96633))) - vwap) / (open - ((high + low) / 2))), 11.4157), 6.72611)) * -1)"""
    p = _panels(Open=Open, high=high, low=low, vwap=vwap)
    blended_low = (p["low"] * 0.96633) + (p["low"] * (1 - 0.96633))
    ratio = (blended_low - p["vwap"]) / (p["Open"] - ((p["high"] + p["low"]) / 2))
    return (
        rank(decay_linear(delta(p["vwap"], 3.51013), 7.23052))
        + ts_rank(decay_linear(ratio, 11.4157), 6.72611)
    ) * -1


def alpha67(high, vwap, amount, ind_sector, ind_subindustry):
    r"""Alpha#67: ((rank((high - ts_min(high, 2.14593)))^rank(correlation(IndNeutralize(vwap, IndClass.sector), IndNeutralize(adv20, IndClass.subindustry), 6.02936))) * -1)"""
    p = _panels(
        high=high, vwap=vwap, amount=amount, ind_sector=ind_sector, ind_subindustry=ind_subindustry
    )
    adv20 = _adv(p["amount"], 20)
    base = rank(p["high"] - ts_min(p["high"], 2.14593))
    exponent = rank(
        correlation(
            ind_neutralize(p["vwap"], p["ind_sector"]),
            ind_neutralize(adv20, p["ind_subindustry"]),
            6.02936,
        )
    )
    return _pow(base, exponent) * -1


def alpha68(close, high, low, amount):
    r"""Alpha#68: ((Ts_Rank(correlation(rank(high), rank(adv15), 8.91644), 13.9333) < rank(delta(((close * 0.518371) + (low * (1 - 0.518371))), 1.06157))) * -1)"""
    p = _panels(close=close, high=high, low=low, amount=amount)
    adv15 = _adv(p["amount"], 15)
    blended = (p["close"] * 0.518371) + (p["low"] * (1 - 0.518371))
    return (
        _lt(
            ts_rank(correlation(rank(p["high"]), rank(adv15), 8.91644), 13.9333),
            rank(delta(blended, 1.06157)),
        )
        * -1
    )


def alpha69(close, vwap, amount, ind_industry):
    r"""Alpha#69: ((rank(ts_max(delta(IndNeutralize(vwap, IndClass.industry), 2.72412), 4.79344))^Ts_Rank(correlation(((close * 0.490655) + (vwap * (1 - 0.490655))), adv20, 4.92416), 9.0615)) * -1)"""
    p = _panels(close=close, vwap=vwap, amount=amount, ind_industry=ind_industry)
    adv20 = _adv(p["amount"], 20)
    blended = (p["close"] * 0.490655) + (p["vwap"] * (1 - 0.490655))
    base = rank(ts_max(delta(ind_neutralize(p["vwap"], p["ind_industry"]), 2.72412), 4.79344))
    exponent = ts_rank(correlation(blended, adv20, 4.92416), 9.0615)
    return _pow(base, exponent) * -1


def alpha70(close, vwap, amount, ind_industry):
    r"""Alpha#70: ((rank(delta(vwap, 1.29456))^Ts_Rank(correlation(IndNeutralize(close, IndClass.industry), adv50, 17.8256), 17.9171)) * -1)"""
    p = _panels(close=close, vwap=vwap, amount=amount, ind_industry=ind_industry)
    adv50 = _adv(p["amount"], 50)
    base = rank(delta(p["vwap"], 1.29456))
    exponent = ts_rank(
        correlation(ind_neutralize(p["close"], p["ind_industry"]), adv50, 17.8256), 17.9171
    )
    return _pow(base, exponent) * -1


def alpha71(close, Open, low, vwap, amount):
    r"""Alpha#71: max(Ts_Rank(decay_linear(correlation(Ts_Rank(close, 3.43976), Ts_Rank(adv180, 12.0647), 18.0175), 4.20501), 15.6948), Ts_Rank(decay_linear((rank(((low + open) - (vwap + vwap)))^2), 16.4662), 4.4388))"""
    p = _panels(close=close, Open=Open, low=low, vwap=vwap, amount=amount)
    adv180 = _adv(p["amount"], 180)
    left = ts_rank(
        decay_linear(
            correlation(ts_rank(p["close"], 3.43976), ts_rank(adv180, 12.0647), 18.0175), 4.20501
        ),
        15.6948,
    )
    right = ts_rank(
        decay_linear(_pow(rank((p["low"] + p["Open"]) - (p["vwap"] + p["vwap"])), 2), 16.4662), 4.4388
    )
    return maximum(left, right)


def alpha72(high, low, vwap, volume, amount):
    r"""Alpha#72: (rank(decay_linear(correlation(((high + low) / 2), adv40, 8.93345), 10.1519)) / rank(decay_linear(correlation(Ts_Rank(vwap, 3.72469), Ts_Rank(volume, 18.5188), 6.86671), 2.95011)))"""
    p = _panels(high=high, low=low, vwap=vwap, volume=volume, amount=amount)
    adv40 = _adv(p["amount"], 40)
    return rank(
        decay_linear(correlation((p["high"] + p["low"]) / 2, adv40, 8.93345), 10.1519)
    ) / rank(
        decay_linear(
            correlation(ts_rank(p["vwap"], 3.72469), ts_rank(p["volume"], 18.5188), 6.86671), 2.95011
        )
    )


def alpha73(Open, low, vwap):
    r"""Alpha#73: (max(rank(decay_linear(delta(vwap, 4.72775), 2.91864)), Ts_Rank(decay_linear(((delta(((open * 0.147155) + (low * (1 - 0.147155))), 2.03608) / ((open * 0.147155) + (low * (1 - 0.147155)))) * -1), 3.33829), 16.7411)) * -1)"""
    p = _panels(Open=Open, low=low, vwap=vwap)
    blended = (p["Open"] * 0.147155) + (p["low"] * (1 - 0.147155))
    left = rank(decay_linear(delta(p["vwap"], 4.72775), 2.91864))
    right = ts_rank(decay_linear((delta(blended, 2.03608) / blended) * -1, 3.33829), 16.7411)
    return maximum(left, right) * -1


def alpha74(close, high, vwap, volume, amount):
    r"""Alpha#74: ((rank(correlation(close, sum(adv30, 37.4843), 15.1365)) < rank(correlation(rank(((high * 0.0261661) + (vwap * (1 - 0.0261661)))), rank(volume), 11.4791))) * -1)"""
    p = _panels(close=close, high=high, vwap=vwap, volume=volume, amount=amount)
    adv30 = _adv(p["amount"], 30)
    blended = (p["high"] * 0.0261661) + (p["vwap"] * (1 - 0.0261661))
    return (
        _lt(
            rank(correlation(p["close"], ts_sum(adv30, 37.4843), 15.1365)),
            rank(correlation(rank(blended), rank(p["volume"]), 11.4791)),
        )
        * -1
    )


def alpha75(low, vwap, volume, amount):
    r"""Alpha#75: (rank(correlation(vwap, volume, 4.24304)) < rank(correlation(rank(low), rank(adv50), 12.4413)))"""
    p = _panels(low=low, vwap=vwap, volume=volume, amount=amount)
    adv50 = _adv(p["amount"], 50)
    return _lt(
        rank(correlation(p["vwap"], p["volume"], 4.24304)),
        rank(correlation(rank(p["low"]), rank(adv50), 12.4413)),
    )


def alpha76(low, vwap, amount, ind_sector):
    r"""Alpha#76: (max(rank(decay_linear(delta(vwap, 1.24383), 11.8259)), Ts_Rank(decay_linear(Ts_Rank(correlation(IndNeutralize(low, IndClass.sector), adv81, 8.14941), 19.569), 17.1543), 19.383)) * -1)"""
    p = _panels(low=low, vwap=vwap, amount=amount, ind_sector=ind_sector)
    adv81 = _adv(p["amount"], 81)
    left = rank(decay_linear(delta(p["vwap"], 1.24383), 11.8259))
    right = ts_rank(
        decay_linear(
            ts_rank(correlation(ind_neutralize(p["low"], p["ind_sector"]), adv81, 8.14941), 19.569),
            17.1543,
        ),
        19.383,
    )
    return maximum(left, right) * -1


def alpha77(high, low, vwap, amount):
    r"""Alpha#77: min(rank(decay_linear(((((high + low) / 2) + high) - (vwap + high)), 20.0451)), rank(decay_linear(correlation(((high + low) / 2), adv40, 3.1614), 5.64125)))"""
    p = _panels(high=high, low=low, vwap=vwap, amount=amount)
    adv40 = _adv(p["amount"], 40)
    left = rank(
        decay_linear((((p["high"] + p["low"]) / 2) + p["high"]) - (p["vwap"] + p["high"]), 20.0451)
    )
    right = rank(decay_linear(correlation((p["high"] + p["low"]) / 2, adv40, 3.1614), 5.64125))
    return minimum(left, right)


def alpha78(low, vwap, volume, amount):
    r"""Alpha#78: (rank(correlation(sum(((low * 0.352233) + (vwap * (1 - 0.352233))), 19.7428), sum(adv40, 19.7428), 6.83313))^rank(correlation(rank(vwap), rank(volume), 5.77492)))"""
    p = _panels(low=low, vwap=vwap, volume=volume, amount=amount)
    adv40 = _adv(p["amount"], 40)
    blended = (p["low"] * 0.352233) + (p["vwap"] * (1 - 0.352233))
    base = rank(correlation(ts_sum(blended, 19.7428), ts_sum(adv40, 19.7428), 6.83313))
    exponent = rank(correlation(rank(p["vwap"]), rank(p["volume"]), 5.77492))
    return _pow(base, exponent)


def alpha79(Open, close, vwap, amount, ind_sector):
    r"""Alpha#79: (rank(delta(IndNeutralize(((close * 0.60733) + (open * (1 - 0.60733))), IndClass.sector), 1.23438)) < rank(correlation(Ts_Rank(vwap, 3.60973), Ts_Rank(adv150, 9.18637), 14.6644)))"""
    p = _panels(Open=Open, close=close, vwap=vwap, amount=amount, ind_sector=ind_sector)
    adv150 = _adv(p["amount"], 150)
    blended = (p["close"] * 0.60733) + (p["Open"] * (1 - 0.60733))
    return _lt(
        rank(delta(ind_neutralize(blended, p["ind_sector"]), 1.23438)),
        rank(correlation(ts_rank(p["vwap"], 3.60973), ts_rank(adv150, 9.18637), 14.6644)),
    )


def alpha80(Open, high, amount, ind_industry):
    r"""Alpha#80: ((rank(Sign(delta(IndNeutralize(((open * 0.868128) + (high * (1 - 0.868128))), IndClass.industry), 4.04545)))^Ts_Rank(correlation(high, adv10, 5.11456), 5.53756)) * -1)"""
    p = _panels(Open=Open, high=high, amount=amount, ind_industry=ind_industry)
    adv10 = _adv(p["amount"], 10)
    blended = (p["Open"] * 0.868128) + (p["high"] * (1 - 0.868128))
    base = rank(sign(delta(ind_neutralize(blended, p["ind_industry"]), 4.04545)))
    exponent = ts_rank(correlation(p["high"], adv10, 5.11456), 5.53756)
    return _pow(base, exponent) * -1


def alpha81(vwap, volume, amount):
    r"""Alpha#81: ((rank(Log(product(rank((rank(correlation(vwap, sum(adv10, 49.6054), 8.47743))^4)), 14.9655))) < rank(correlation(rank(vwap), rank(volume), 5.07914))) * -1)"""
    p = _panels(vwap=vwap, volume=volume, amount=amount)
    adv10 = _adv(p["amount"], 10)
    inner = _pow(rank(correlation(p["vwap"], ts_sum(adv10, 49.6054), 8.47743)), 4)
    return (
        _lt(
            rank(log(product(rank(inner), 14.9655))),
            rank(correlation(rank(p["vwap"]), rank(p["volume"]), 5.07914)),
        )
        * -1
    )


def alpha82(Open, volume, ind_sector):
    r"""Alpha#82: (min(rank(decay_linear(delta(open, 1.46063), 14.8717)), Ts_Rank(decay_linear(correlation(IndNeutralize(volume, IndClass.sector), ((open * 0.634196) + (open * (1 - 0.634196))), 17.4842), 6.92131), 13.4283)) * -1)"""
    p = _panels(Open=Open, volume=volume, ind_sector=ind_sector)
    blended = (p["Open"] * 0.634196) + (p["Open"] * (1 - 0.634196))
    left = rank(decay_linear(delta(p["Open"], 1.46063), 14.8717))
    right = ts_rank(
        decay_linear(
            correlation(ind_neutralize(p["volume"], p["ind_sector"]), blended, 17.4842), 6.92131
        ),
        13.4283,
    )
    return minimum(left, right) * -1


def alpha83(close, high, low, vwap, volume):
    r"""Alpha#83: ((rank(delay(((high - low) / (sum(close, 5) / 5)), 2)) * rank(rank(volume))) / (((high - low) / (sum(close, 5) / 5)) / (vwap - close)))"""
    p = _panels(close=close, high=high, low=low, vwap=vwap, volume=volume)
    spread = (p["high"] - p["low"]) / (ts_sum(p["close"], 5) / 5)
    return (rank(delay(spread, 2)) * rank(rank(p["volume"]))) / (spread / (p["vwap"] - p["close"]))


def alpha84(close, vwap):
    r"""Alpha#84: SignedPower(Ts_Rank((vwap - ts_max(vwap, 15.3217)), 20.7127), delta(close, 4.96796))"""
    p = _panels(close=close, vwap=vwap)
    return signedpower(
        ts_rank(p["vwap"] - ts_max(p["vwap"], 15.3217), 20.7127), delta(p["close"], 4.96796)
    )


def alpha85(close, high, low, volume, amount):
    r"""Alpha#85: (rank(correlation(((high * 0.876703) + (close * (1 - 0.876703))), adv30, 9.61331))^rank(correlation(Ts_Rank(((high + low) / 2), 3.70596), Ts_Rank(volume, 10.1595), 7.11408)))"""
    p = _panels(close=close, high=high, low=low, volume=volume, amount=amount)
    adv30 = _adv(p["amount"], 30)
    blended = (p["high"] * 0.876703) + (p["close"] * (1 - 0.876703))
    base = rank(correlation(blended, adv30, 9.61331))
    exponent = rank(
        correlation(
            ts_rank((p["high"] + p["low"]) / 2, 3.70596), ts_rank(p["volume"], 10.1595), 7.11408
        )
    )
    return _pow(base, exponent)


def alpha86(Open, close, vwap, amount):
    r"""Alpha#86: ((Ts_Rank(correlation(close, sum(adv20, 14.7444), 6.00049), 20.4195) < rank(((open + close) - (vwap + open)))) * -1)"""
    p = _panels(Open=Open, close=close, vwap=vwap, amount=amount)
    adv20 = _adv(p["amount"], 20)
    return (
        _lt(
            ts_rank(correlation(p["close"], ts_sum(adv20, 14.7444), 6.00049), 20.4195),
            rank((p["Open"] + p["close"]) - (p["vwap"] + p["Open"])),
        )
        * -1
    )


def alpha87(close, vwap, amount, ind_industry):
    r"""Alpha#87: (max(rank(decay_linear(delta(((close * 0.369701) + (vwap * (1 - 0.369701))), 1.91233), 2.65461)), Ts_Rank(decay_linear(abs(correlation(IndNeutralize(adv81, IndClass.industry), close, 13.4132)), 4.89768), 14.4535)) * -1)"""
    p = _panels(close=close, vwap=vwap, amount=amount, ind_industry=ind_industry)
    adv81 = _adv(p["amount"], 81)
    blended = (p["close"] * 0.369701) + (p["vwap"] * (1 - 0.369701))
    left = rank(decay_linear(delta(blended, 1.91233), 2.65461))
    right = ts_rank(
        decay_linear(
            abs_(correlation(ind_neutralize(adv81, p["ind_industry"]), p["close"], 13.4132)), 4.89768
        ),
        14.4535,
    )
    return maximum(left, right) * -1


def alpha88(Open, close, high, low, amount):
    r"""Alpha#88: min(rank(decay_linear(((rank(open) + rank(low)) - (rank(high) + rank(close))), 8.06882)), Ts_Rank(decay_linear(correlation(Ts_Rank(close, 8.44728), Ts_Rank(adv60, 20.6966), 8.01266), 6.65053), 2.61957))"""
    p = _panels(Open=Open, close=close, high=high, low=low, amount=amount)
    adv60 = _adv(p["amount"], 60)
    left = rank(
        decay_linear((rank(p["Open"]) + rank(p["low"])) - (rank(p["high"]) + rank(p["close"])), 8.06882)
    )
    right = ts_rank(
        decay_linear(
            correlation(ts_rank(p["close"], 8.44728), ts_rank(adv60, 20.6966), 8.01266), 6.65053
        ),
        2.61957,
    )
    return minimum(left, right)


def alpha89(low, vwap, amount, ind_industry):
    r"""Alpha#89: (Ts_Rank(decay_linear(correlation(((low * 0.967285) + (low * (1 - 0.967285))), adv10, 6.94279), 5.51607), 3.79744) - Ts_Rank(decay_linear(delta(IndNeutralize(vwap, IndClass.industry), 3.48158), 10.1466), 15.3012))"""
    p = _panels(low=low, vwap=vwap, amount=amount, ind_industry=ind_industry)
    adv10 = _adv(p["amount"], 10)
    blended = (p["low"] * 0.967285) + (p["low"] * (1 - 0.967285))
    left = ts_rank(decay_linear(correlation(blended, adv10, 6.94279), 5.51607), 3.79744)
    right = ts_rank(
        decay_linear(delta(ind_neutralize(p["vwap"], p["ind_industry"]), 3.48158), 10.1466), 15.3012
    )
    return left - right


def alpha90(close, low, amount, ind_subindustry):
    r"""Alpha#90: ((rank((close - ts_max(close, 4.66719)))^Ts_Rank(correlation(IndNeutralize(adv40, IndClass.subindustry), low, 5.38375), 3.21856)) * -1)"""
    p = _panels(close=close, low=low, amount=amount, ind_subindustry=ind_subindustry)
    adv40 = _adv(p["amount"], 40)
    base = rank(p["close"] - ts_max(p["close"], 4.66719))
    exponent = ts_rank(
        correlation(ind_neutralize(adv40, p["ind_subindustry"]), p["low"], 5.38375), 3.21856
    )
    return _pow(base, exponent) * -1


def alpha91(close, vwap, volume, amount, ind_industry):
    r"""Alpha#91: ((Ts_Rank(decay_linear(decay_linear(correlation(IndNeutralize(close, IndClass.industry), volume, 9.74928), 16.398), 3.83219), 4.8667) - rank(decay_linear(correlation(vwap, adv30, 4.01303), 2.6809))) * -1)"""
    p = _panels(close=close, vwap=vwap, volume=volume, amount=amount, ind_industry=ind_industry)
    adv30 = _adv(p["amount"], 30)
    left = ts_rank(
        decay_linear(
            decay_linear(
                correlation(ind_neutralize(p["close"], p["ind_industry"]), p["volume"], 9.74928),
                16.398,
            ),
            3.83219,
        ),
        4.8667,
    )
    right = rank(decay_linear(correlation(p["vwap"], adv30, 4.01303), 2.6809))
    return (left - right) * -1


def alpha92(Open, close, high, low, amount):
    r"""Alpha#92: min(Ts_Rank(decay_linear(((((high + low) / 2) + close) < (low + open)), 14.7221), 18.8683), Ts_Rank(decay_linear(correlation(rank(low), rank(adv30), 7.58555), 6.94024), 6.80584))"""
    p = _panels(Open=Open, close=close, high=high, low=low, amount=amount)
    adv30 = _adv(p["amount"], 30)
    condition = _lt(((p["high"] + p["low"]) / 2) + p["close"], p["low"] + p["Open"])
    left = ts_rank(decay_linear(condition, 14.7221), 18.8683)
    right = ts_rank(
        decay_linear(correlation(rank(p["low"]), rank(adv30), 7.58555), 6.94024), 6.80584
    )
    return minimum(left, right)


def alpha93(close, vwap, amount, ind_industry):
    r"""Alpha#93: (Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.industry), adv81, 17.4193), 19.848), 7.54455) / rank(decay_linear(delta(((close * 0.524434) + (vwap * (1 - 0.524434))), 2.77377), 16.2664)))"""
    p = _panels(close=close, vwap=vwap, amount=amount, ind_industry=ind_industry)
    adv81 = _adv(p["amount"], 81)
    blended = (p["close"] * 0.524434) + (p["vwap"] * (1 - 0.524434))
    return ts_rank(
        decay_linear(
            correlation(ind_neutralize(p["vwap"], p["ind_industry"]), adv81, 17.4193), 19.848
        ),
        7.54455,
    ) / rank(decay_linear(delta(blended, 2.77377), 16.2664))


def alpha94(vwap, amount):
    r"""Alpha#94: ((rank((vwap - ts_min(vwap, 11.5783)))^Ts_Rank(correlation(Ts_Rank(vwap, 19.6462), Ts_Rank(adv60, 4.02992), 18.0926), 2.70756)) * -1)"""
    p = _panels(vwap=vwap, amount=amount)
    adv60 = _adv(p["amount"], 60)
    base = rank(p["vwap"] - ts_min(p["vwap"], 11.5783))
    exponent = ts_rank(
        correlation(ts_rank(p["vwap"], 19.6462), ts_rank(adv60, 4.02992), 18.0926), 2.70756
    )
    return _pow(base, exponent) * -1


def alpha95(Open, high, low, amount):
    r"""Alpha#95: (rank((open - ts_min(open, 12.4105))) < Ts_Rank((rank(correlation(sum(((high + low) / 2), 19.1351), sum(adv40, 19.1351), 12.8742))^5), 11.7584))"""
    p = _panels(Open=Open, high=high, low=low, amount=amount)
    adv40 = _adv(p["amount"], 40)
    inner = _pow(
        rank(
            correlation(
                ts_sum((p["high"] + p["low"]) / 2, 19.1351), ts_sum(adv40, 19.1351), 12.8742
            )
        ),
        5,
    )
    return _lt(rank(p["Open"] - ts_min(p["Open"], 12.4105)), ts_rank(inner, 11.7584))


def alpha96(close, vwap, volume, amount):
    r"""Alpha#96: (max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume), 3.83878), 4.16783), 8.38151), Ts_Rank(decay_linear(Ts_ArgMax(correlation(Ts_Rank(close, 7.45404), Ts_Rank(adv60, 4.13242), 3.65459), 12.6556), 14.0365), 13.4143)) * -1)"""
    p = _panels(close=close, vwap=vwap, volume=volume, amount=amount)
    adv60 = _adv(p["amount"], 60)
    left = ts_rank(
        decay_linear(correlation(rank(p["vwap"]), rank(p["volume"]), 3.83878), 4.16783), 8.38151
    )
    right = ts_rank(
        decay_linear(
            ts_argmax(
                correlation(ts_rank(p["close"], 7.45404), ts_rank(adv60, 4.13242), 3.65459), 12.6556
            ),
            14.0365,
        ),
        13.4143,
    )
    return maximum(left, right) * -1


def alpha97(low, vwap, amount, ind_industry):
    r"""Alpha#97: ((rank(decay_linear(delta(IndNeutralize(((low * 0.721001) + (vwap * (1 - 0.721001))), IndClass.industry), 3.3705), 20.4523)) - Ts_Rank(decay_linear(Ts_Rank(correlation(Ts_Rank(low, 7.87871), Ts_Rank(adv60, 17.255), 4.97547), 18.5925), 15.7152), 6.71659)) * -1)"""
    p = _panels(low=low, vwap=vwap, amount=amount, ind_industry=ind_industry)
    adv60 = _adv(p["amount"], 60)
    blended = (p["low"] * 0.721001) + (p["vwap"] * (1 - 0.721001))
    left = rank(decay_linear(delta(ind_neutralize(blended, p["ind_industry"]), 3.3705), 20.4523))
    right = ts_rank(
        decay_linear(
            ts_rank(
                correlation(ts_rank(p["low"], 7.87871), ts_rank(adv60, 17.255), 4.97547), 18.5925
            ),
            15.7152,
        ),
        6.71659,
    )
    return (left - right) * -1


def alpha98(Open, vwap, amount):
    r"""Alpha#98: (rank(decay_linear(correlation(vwap, sum(adv5, 26.4719), 4.58418), 7.18088)) - rank(decay_linear(Ts_Rank(Ts_ArgMin(correlation(rank(open), rank(adv15), 20.8187), 8.62571), 6.95668), 8.07206)))"""
    p = _panels(Open=Open, vwap=vwap, amount=amount)
    adv5 = _adv(p["amount"], 5)
    adv15 = _adv(p["amount"], 15)
    left = rank(decay_linear(correlation(p["vwap"], ts_sum(adv5, 26.4719), 4.58418), 7.18088))
    right = rank(
        decay_linear(
            ts_rank(ts_argmin(correlation(rank(p["Open"]), rank(adv15), 20.8187), 8.62571), 6.95668),
            8.07206,
        )
    )
    return left - right


def alpha99(high, low, volume, amount):
    r"""Alpha#99: ((rank(correlation(sum(((high + low) / 2), 19.8975), sum(adv60, 19.8975), 8.8136)) < rank(correlation(low, volume, 6.28259))) * -1)"""
    p = _panels(high=high, low=low, volume=volume, amount=amount)
    adv60 = _adv(p["amount"], 60)
    return (
        _lt(
            rank(
                correlation(
                    ts_sum((p["high"] + p["low"]) / 2, 19.8975), ts_sum(adv60, 19.8975), 8.8136
                )
            ),
            rank(correlation(p["low"], p["volume"], 6.28259)),
        )
        * -1
    )


def alpha100(close, high, low, volume, amount, ind_subindustry):
    r"""Alpha#100: (0 - (1 * (((1.5 * scale(indneutralize(indneutralize(rank(((((close - low) - (high - close)) / (high - low)) * volume)), IndClass.subindustry), IndClass.subindustry))) - scale(indneutralize((correlation(close, rank(adv20), 5) - rank(ts_argmin(close, 30))), IndClass.subindustry))) * (volume / adv20))))"""
    p = _panels(
        close=close, high=high, low=low, volume=volume, amount=amount, ind_subindustry=ind_subindustry
    )
    adv20 = _adv(p["amount"], 20)
    label = p["ind_subindustry"]
    ratio = (
        ((p["close"] - p["low"]) - (p["high"] - p["close"])) / (p["high"] - p["low"])
    ) * p["volume"]
    left = 1.5 * scale(ind_neutralize(ind_neutralize(rank(ratio), label), label))
    right = scale(
        ind_neutralize(
            correlation(p["close"], rank(adv20), 5) - rank(ts_argmin(p["close"], 30)), label
        )
    )
    return 0 - (1 * ((left - right) * (p["volume"] / adv20)))


def alpha101(close, Open, high, low):
    r"""Alpha#101: ((close - open) / ((high - low) + .001))"""
    p = _panels(close=close, Open=Open, high=high, low=low)
    return (p["close"] - p["Open"]) / ((p["high"] - p["low"]) + 0.001)


# ---------------------------------------------------------------------------
# 注册：全部 101 个因子 + 状态判定规则
# ---------------------------------------------------------------------------

#: ``ambiguous`` 判定：**规范本身未定**且会改变数值的因子（设计文档 §9 R2：不得标 verified）。
#: 每条原因都列出因子清单，可由 `tools/conformance_report.py` 从论文公式复算核对。
AMBIGUOUS_FACTORS: dict[str, tuple[int, ...]] = {
    "decay_linear 权重方向未定案（vnpy 取相反方向，BRAIN 文案未取得）": (
        31, 39, 57, 58, 59, 63, 66, 71, 72, 73, 76, 77, 82, 87, 88, 89, 91, 92, 93, 96, 97, 98,
    ),
    "ts_argmax/ts_argmin 基准未定案（论文只写 which day，BRAIN 文案未取得）": (1, 57, 60, 96, 98, 100),
    "`^` 语义（论文字面 x^a vs 保号幂）在此因子产生实质差异（负底数）": (48, 90),
}

#: 设计文档 §7.7 的 5 个试点因子（M2 交付，测试单独覆盖）。
PILOT_NAMES: tuple[str, ...] = ("alpha101", "alpha4", "alpha5", "alpha41", "alpha56")

ALL_FACTOR_NAMES: tuple[str, ...] = tuple(f"alpha{n}" for n in range(1, 102))


def ambiguous_reason(number: int) -> str | None:
    """返回该因子的 ``ambiguous`` 原因（无则 ``None``）。"""
    for reason, numbers in AMBIGUOUS_FACTORS.items():
        if number in numbers:
            return reason
    return None


def _register_all() -> None:
    """把 101 个因子登记进 `registry`（幂等：重复导入不报错）。"""
    from . import registry

    for number in range(1, 102):
        name = f"alpha{number}"
        if name in registry.REGISTRY:
            continue
        function: Callable[..., pd.DataFrame] = globals()[name]
        reason = ambiguous_reason(number)
        registry.register(
            name,
            function,
            paper_ref=f"Appendix A, Alpha#{number}（逐字公式见 docs/paper_formulas.md §5）",
            status="ambiguous" if reason else "partial",
            notes=reason or "结构与论文一致（算子级对照等价）；待 M4 因子级差分与 M5 golden 快照",
        )


_register_all()
