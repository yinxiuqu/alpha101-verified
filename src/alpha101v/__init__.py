"""alpha101v — 一份「可验证的 Alpha101」实现（M0/M1：算子层）。

设计依据：``docs/Alpha101_修复发布决策与验证协议_v0.1.md``（内容版本 v0.2）。
口径唯一权威：``docs/operators.md``。

公开算子面恰好 20 个（16 个时序/截面算子 + ``rolling_rank`` 构件 + 3 个中性化算子），
见 :data:`OPERATORS`。因子层（``factors.py`` / ``registry.REGISTRY``）是 M2/M3 的工作，
本包当前**不含任何因子实现**，也不含任何来自 GPL 实现的代码（clean-room）。
"""

from __future__ import annotations

from . import neutralize, operators
from .neutralize import ind_neutralize, neu_industry, neutral
from .operators import (
    correlation,
    covariance,
    decay_linear,
    delta,
    delay,
    product,
    rank,
    rolling_rank,
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

__version__ = "0.1.0"

#: 20 个算子的名字（设计文档 §7.3 的 17 个 API + §8.1 的 rolling_rank + §8.3 的两个中性化变体）。
#: ``tests/test_operators.py::test_api_surface_is_exactly_twenty`` 会守住这个清单。
OPERATORS: tuple[str, ...] = (
    # A 组 / 时序与截面（§7.3）
    "ts_sum",
    "sma",
    "stddev",
    "correlation",
    "covariance",
    "ts_rank",
    "product",
    "ts_min",
    "ts_max",
    "delta",
    "delay",
    "rank",
    "scale",
    "ts_argmax",
    "ts_argmin",
    "decay_linear",
    # §8.1 明确要求对拍的构件
    "rolling_rank",
    # §8.3 中性化组
    "ind_neutralize",
    "neu_industry",
    "neutral",
)

__all__ = [
    "OPERATORS",
    "__version__",
    "correlation",
    "covariance",
    "decay_linear",
    "delta",
    "delay",
    "ind_neutralize",
    "neu_industry",
    "neutral",
    "neutralize",
    "operators",
    "product",
    "rank",
    "rolling_rank",
    "scale",
    "sma",
    "stddev",
    "ts_argmax",
    "ts_argmin",
    "ts_max",
    "ts_min",
    "ts_rank",
    "ts_sum",
]
