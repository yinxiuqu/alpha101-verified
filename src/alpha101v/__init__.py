"""alpha101v — 一份「可验证的 Alpha101」实现（M0/M1：算子层）。

设计依据：``docs/Alpha101_修复发布决策与验证协议_v0.1.md``（内容版本 v0.2）。
口径唯一权威：``docs/operators.md``。

公开算子面恰好 20 个（16 个时序/截面算子 + ``rolling_rank`` 构件 + 3 个中性化算子），
见 :data:`OPERATORS`；另有**不属于算子面**的逐元素函数层见 :data:`ELEMWISE`
（论文把它们列为 Functions，见 ``docs/operators.md`` §3.9）。

因子层（M3）交付 **全部 101 个因子**（:data:`ALL_FACTOR_NAMES`），导入本包即自动登记进
``registry.REGISTRY``；状态只有 ``partial``（结构对照等价）与 ``ambiguous``
（规范未定，见 ``factors.AMBIGUOUS_FACTORS``）——``verified`` 需六条门槛，见设计文档 §6.8。因子层（``factors.py``）已含全部 101 个因子（论文逐字转写）。
本包**不含任何来自 GPL 实现的代码**（clean-room，见 ``docs/paper_formulas.md`` 与
``tests/test_provenance.py``）。
"""

from __future__ import annotations

from . import elemwise, factors, neutralize, operators, panel, registry
from .elemwise import ELEMWISE, abs_, log, maximum, minimum, sign, signedpower
from .factors import ALL_FACTOR_NAMES, PILOT_NAMES, alpha4, alpha41, alpha5, alpha56, alpha101
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

def _resolve_version() -> str:
    """版本号**单一来源**：优先读安装元数据（`pyproject.toml` 里的 version），
    源码树直接 import（未安装）时回退。硬编码版本号曾与 pyproject 漂移过
    （`__init__` 写 0.1.0、dist 是 0.1.1），因此有 tests/test_version.py 专门守这条。
    """
    try:
        from importlib.metadata import version as _v

        return _v("alpha101v")
    except Exception:  # noqa: BLE001 - 未安装/元数据缺失时回退
        return "0.1.4"


__version__ = _resolve_version()

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
    "ALL_FACTOR_NAMES",
    "ELEMWISE",
    "OPERATORS",
    "PILOT_NAMES",
    "__version__",
    "alpha4",
    "alpha41",
    "alpha56",
    "alpha101",
    "factors",
    "panel",
    "registry",
    "abs_",
    "elemwise",
    "log",
    "maximum",
    "minimum",
    "sign",
    "signedpower",
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
