"""alpha101v.elemwise — 逐元素函数层（M2）。

**为什么单列一层**：论文把 `abs` / `log` / `sign` / `signedpower` 列在
「Functions（一元函数）」而不是「Operators（时序/截面算子）」下。
设计文档 §7.3 的 **20 算子面**是算子层的正确边界，因此这些函数**不进** `OPERATORS`，
单独成层（`tests/test_operators.py::test_api_surface_is_exactly_twenty` 继续守着 20 这个数）。

论文里这 4 个函数覆盖 **15 个因子**（`docs/paper_formulas.md` §7.6）：
`abs` 5 个、`log` 3 个、`sign` 6 个、`signedpower` 2 个。缺了它们，这 15 个因子无法转写。

统一契约与算子层一致：输入 ``DataFrame``（``Series`` 视为单列面板）→ 输出 ``DataFrame``，
**绝不原地修改入参**；非数值输入报 ``TypeError``。

口径决策（三条，全部显式；见 ``docs/operators.md`` §3.9 与 ``docs/ambiguities.md`` A13/A15）
----------------------------------------------------------------------------------------
1. **`log(x)`：`x <= 0` → `NaN`，不是 `-inf`。** 论文写「standard definitions」，
   数学上 `log(0) = -inf`；但 ±inf 会污染下游全部算子，本库一律用 NaN 表示「未定义」
   （与 `panel.returns_from_close` 对非正价格的处理一致）。这是**有意偏离字面定义**：
   NaN 可被安全传播，inf 不能。
2. **`sign(0) = 0`**（标准定义）。
3. **`signedpower(x, a)` 默认保号**：`sign(x)·|x|^a`；`preserve_sign=False` 给出论文字面的 `x^a`。
   ⚠️ **两种模式在负底数上不同，且与指数是否为整数无关**：
   `preserve_sign=True` 时 `x = -4, a = 2` 给 **−16**（`sign(-4)·|−4|²`），
   字面模式给 **+16**。因此「保号与否」只在**底数为负**时才产生差异。
   论文两处用法的**底数都非负**——Alpha#1 的底数是 `((returns < 0) ? stddev(returns, 20) : close)`
   （stddev ≥ 0、close > 0），Alpha#84 的底数是 `Ts_Rank(...)` ∈ (0, 1]——
   所以这个歧义**不阻塞这两个因子的转写**，但仍记入 A13，待 BRAIN 文档或 vnpy 定案。
4. **指数 `a` 可以是标量，也可以是同形面板**：论文 Alpha#84 逐字为
   `SignedPower(Ts_Rank((vwap - ts_max(vwap, 15.3217)), 20.7127), delta(close, 4.96796))`
   —— 指数是 `delta(close, …)`，**是一个面板**，不是常数。
5. **结果非有限（如 `0` 的负次幂 → inf）一律置 NaN**，绝不把 ±inf 交给下游。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .operators import _as_frame, _prep

__all__ = ["ELEMWISE", "abs_", "log", "maximum", "minimum", "power", "sign", "signedpower"]

#: 逐元素层的公开函数面（**与 20 算子面互不相交**，见模块文档串）。
ELEMWISE: tuple[str, ...] = ("abs_", "log", "maximum", "minimum", "power", "sign", "signedpower")

_NONFINITE_RESULT_POLICY = "结果非有限（含 0 的负次幂）→ NaN，不产生 ±inf"


def _values(df: object, name: str = "input") -> tuple[pd.DataFrame, np.ndarray]:
    """校验并取出 float64 数值矩阵（保留 index/columns 用于回填）。"""
    frame = _prep(df, name=name)
    return frame, frame.to_numpy(dtype=float)


def _wrap(values: np.ndarray, like: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(values, index=like.index, columns=like.columns)


def _mask_nonfinite(values: np.ndarray) -> np.ndarray:
    """把 ±inf 一律降级为 NaN（NaN 原样保留）。"""
    return np.where(np.isfinite(values), values, np.nan)


def _exponents(a: object, like: pd.DataFrame) -> float | np.ndarray:
    """把指数参数规范成「标量 float」或「与 like 同形的 float64 矩阵」。"""
    if isinstance(a, bool):
        raise TypeError("指数 a 不能是布尔值")
    if isinstance(a, (int, float, np.integer, np.floating)):
        exponent = float(a)
        if not np.isfinite(exponent):
            raise ValueError(f"指数 a 必须是有限实数，收到 {a}")
        return exponent
    if isinstance(a, (pd.DataFrame, pd.Series)):
        panel = _prep(a, name="a")
        if not panel.index.equals(like.index) or not panel.columns.equals(like.columns):
            raise ValueError(
                "指数面板必须与被幂面板同 index/columns（论文 Alpha#84 的指数是面板 delta(close, d)）；"
                f"收到 {panel.shape} vs {like.shape}"
            )
        values = panel.to_numpy(dtype=float)
        if np.isinf(values).any():
            raise ValueError("指数面板含 ±inf（面板契约要求先清洗）")
        return values
    raise TypeError(f"指数 a 必须是实数或同形面板，收到 {type(a).__name__}")


def minimum(left: object, right: object) -> pd.DataFrame:
    """逐元素最小（论文里 `min(表达式, 表达式)` 的落地；第二参数是常数时走 `ts_min`）。

    ★ 口径决策：**NaN 视为缺失**（``np.fmin`` 语义）——一侧缺失时返回另一侧，
    两侧皆缺失才给 NaN。理由（见 docs/operators.md §3.12）：

    1. 论文只定义了 ``min(x, d) = ts_min(x, d)``，对「逐元素 min/max」的缺失语义**未作规定**；
    2. 若取 NaN 传播，形如 ``alpha96 = max(分支A, 分支B)`` 的因子会在某一分支系统性为 NaN 时
       **整片退化为 NaN**（实测：3 日窗口内 rank 序列零方差 ⇒ 相关系数 NaN ⇒ 长链断裂）；
    3. ``min/max`` 在 pandas/polars 里的通行语义本就跳过缺失（na.rm），取 fmin/fmax 与之一致。
    """
    return _pairwise(left, right, np.fmin)


def maximum(left: object, right: object) -> pd.DataFrame:
    """逐元素最大（论文里 `max(表达式, 表达式)` 的落地）；NaN 视为缺失，见 :func:`minimum`。"""
    return _pairwise(left, right, np.fmax)


def _operand_values(obj: object, like: pd.DataFrame, name: str):
    """取操作数数值：标量直接广播，面板则要求与 ``like`` 同 (index, columns) 契约。"""
    if isinstance(obj, bool):
        raise TypeError(f"{name} 不能是布尔值")
    if isinstance(obj, (int, float, np.integer, np.floating)):
        return float(obj)
    frame, values = _values(obj, name)
    if not frame.index.equals(like.index) or not frame.columns.equals(like.columns):
        raise ValueError(f"{name} 必须与另一侧共享同一 (index, columns) 契约")
    return values


def _pairwise(left: object, right: object, operation) -> pd.DataFrame:
    reference = None
    for candidate in (left, right):
        if isinstance(candidate, (pd.DataFrame, pd.Series)):
            reference = _as_frame(candidate)
            break
    if reference is None:
        raise TypeError("逐元素 min/max 至少需要一个 DataFrame/Series 操作数")
    left_values = _operand_values(left, reference, "left")
    right_values = _operand_values(right, reference, "right")
    with np.errstate(invalid="ignore"):
        result = operation(left_values, right_values)
    return _wrap(result, reference)


def abs_(df: pd.DataFrame) -> pd.DataFrame:
    """``|x|``（论文记法 `abs(x)`；用下划线避开内置 `abs`）。"""
    frame, values = _values(df)
    return _wrap(np.abs(values), frame)


def log(df: pd.DataFrame) -> pd.DataFrame:
    """自然对数 ``ln x``；**x <= 0 → NaN**（不产生 -inf，见模块文档串决策 1）。"""
    frame, values = _values(df)
    safe = np.where(values > 0.0, values, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return _wrap(np.log(safe), frame)


def sign(df: pd.DataFrame) -> pd.DataFrame:
    """符号函数：``-1 / 0 / +1``，``sign(0) = 0``；NaN 保持 NaN。"""
    frame, values = _values(df)
    return _wrap(np.sign(values), frame)


def power(df: pd.DataFrame, a: object) -> pd.DataFrame:
    """BRAIN ``power(x, y) = x^y`` —— **论文中缀 `^` 的对应算子**（L-B 定案，见 §3.13）。

    BRAIN 原文：*"Returns x raised to the power of y (x ^ y). Note: power(x, y) can drop the
    sign of x when y is non-integer; use signed_power(x, y) to preserve"* ⇒ 落地规则：

    * ``x >= 0`` → ``x^y``；
    * ``x < 0`` 且 ``y`` 为**整数** → 数学结果（奇数次幂为负，如 ``power(-0.05, 2) = +0.0025``）；
    * ``x < 0`` 且 ``y`` **非整数** → **丢符号**（取 ``|x|^y``）。

    与 :func:`signedpower`（BRAIN 的 ``signed_power``）的差别**只在负底数**：
    ``signedpower(-0.05, 2) = -0.0025``。这直接决定 Alpha#48 分母 ``Σ((Δclose/delay)^2, 250)`` 的符号，
    因此论文用 `^` 的地方一律走本函数，只有论文显式写 ``SignedPower(...)`` 的地方（Alpha#1、#84）才用
    :func:`signedpower`。``x = 0`` 与 :func:`signedpower` 保持一致返回 0（BRAIN 未规定 ``0^0``）。
    """
    frame, values = _values(df)
    exponent = _exponents(a, frame)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        odd_integer = (np.floor(exponent) == exponent) & (np.mod(exponent, 2.0) != 0.0)
        magnitude = np.power(np.abs(values), exponent) * np.where(odd_integer, -1.0, 1.0)
        result = np.where(
            values >= 0.0, np.power(np.where(values >= 0.0, values, 0.0), exponent), magnitude
        )
        result = np.where(values == 0.0, 0.0, result)
    return _wrap(_mask_nonfinite(result), frame)


def signedpower(df: pd.DataFrame, a: object, *, preserve_sign: bool = True) -> pd.DataFrame:
    """幂函数，默认**保号**：``sign(x)·|x|^a``；``preserve_sign=False`` 为论文字面 ``x^a``。

    ``a`` 可以是标量（如 Alpha#1 的 `2.`）或同形面板（如 Alpha#84 的 `delta(close, 4.96796)`）。
    非有限结果（例如 `0` 的负次幂）一律置 NaN（见模块文档串决策 5）。
    """
    frame, values = _values(df)
    exponent = _exponents(a, frame)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        if preserve_sign:
            result = np.sign(values) * np.abs(values) ** exponent
        else:
            result = np.power(values, exponent)
    return _wrap(_mask_nonfinite(result), frame)
