"""alpha101v.operators — 时间序列/截面算子层（M1，共 17 个算子）。

口径的唯一权威说明是 ``docs/operators.md``：本模块的每个歧义点决策都在那里
给出了理由与替代口径。本文件只负责实现，不改口径。

统一契约（frozen contract）
--------------------------
* 面板（panel）= ``DataFrame``，``index`` = 交易日（升序、唯一），``columns`` = 股票代码。
* 时序算子沿 ``axis=0`` 滚动（逐股票一条序列）；截面算子沿 ``axis=1`` 计算（每日一次）。
* 纯函数：**绝不原地修改入参**（对齐设计文档 §6.5「输入不可变性」，专治原始实现
  ``alpha1`` 污染 ``close`` 面板的缺陷）。
* 返回值一律是 ``DataFrame``。传入 ``Series`` 视为「单列面板」的语法糖
  （输出仍是单列 ``DataFrame``，列名保持不变）。
* 预热期策略：``min_periods = window``（严格），窗口内出现 NaN 即结果为 NaN。
  详见 ``docs/operators.md`` §2.1。
* 天数参数：接受整数或实数；**非整数按论文规定取下整 ``floor(d)``**（下文与
  ``docs/operators.md`` §3.8）。下整后小于下限的仍报错。

已冻结的歧义点决策（详见 docs/operators.md §3）
-----------------------------------------------
===== ==========================================================
ddof  ``stddev``/``covariance`` 默认 ``ddof=0``（BRAIN 官方算例口径，L-B 定案），0/1 可选
rank  ``ts_rank``/``rank`` 默认 ``normalization="zero_to_one"`` → (名次−1)/(n−1) ∈ [0,1]（BRAIN 官方）
argmax ``ts_argmax``/``ts_argmin`` 默认 ``basis="days_ago"``（BRAIN 官方口径：今天=0，L-B 定案）
scale ``scale`` 沿 ``axis=1``（每日 ``Σ|x| = k``），``axis=0`` 是错的
floor 非整数天数按论文取下整 ``floor(d)``（58–99 号因子大量使用）
order ``decay_linear`` 权重方向默认「最新最大」，``order="oldest_first"`` 对齐 vnpy
常数序列 ``correlation`` 遇零方差 → ``NaN``（不是 0，也不是 inf）
===== ==========================================================
"""

from __future__ import annotations

import contextlib
import contextvars

from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import rankdata

__all__ = [
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
    "rolling_rank",
]

# ---------------------------------------------------------------------------
# 内部工具（不属于公开算子面）
# ---------------------------------------------------------------------------

#: 允许的 ``ddof`` 取值。只放行 0/1：二者是唯一有明确统计含义的样本/总体口径，
#: 且 ``covariance`` 的 ddof=0/1 换算 (n-1)/n 在此范围内闭式可证。
ALLOWED_DDOF = (0, 1)

#: 允许的 ``ts_argmax``/``ts_argmin`` 基准。
ALLOWED_ARG_BASIS = ("days_ago", "window_start")

#: 允许的 ``rank`` 并列处理策略。
ALLOWED_RANK_METHODS = ("average", "min", "max", "first", "dense")

#: rank 归一化区间（BRAIN 完整文档定案；见 docs/operators.md §3.2）
#: * ``zero_to_one``（默认）= ``(名次−1)/(n−1)`` ∈ [0,1]：官方算例 ``(4,3,6,10,2) → (0.5,0.25,0.75,1,0)``、
#:   ``ts_rank`` 「13 is the 4th of 5 (0-based 3) → 3/(5−1) = 0.75」；n=1 时分母为 0 ⇒ NaN；
#: * ``one_over_n`` = ``名次/n`` ∈ (0,1]：**vnpy 的口径**，差分对拍时用它对齐；
#: * ``ordinal`` = 序号 ``1..n``：参照实现的序号口径。
ALLOWED_NORMALIZATIONS = ("zero_to_one", "one_over_n", "ordinal")

#: 允许的 ``decay_linear`` 权重方向（★ 论文歧义点，见 docs/operators.md §3.7）：
#: ``recent_first`` = 最新值权重最大（本库默认；设计文档 §8.1 + WMA 惯例）；
#: ``oldest_first`` = 论文权重列表按时间正序读（＝ vnpy ``ts_decay_linear`` 的实现方式）。
ALLOWED_DECAY_ORDERS = ("recent_first", "oldest_first")


def _as_frame(obj: object, name: str = "input") -> pd.DataFrame:
    """把 Series 视为单列面板；DataFrame 原样返回（不复制，因为算子不写入）。"""
    if isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, pd.Series):
        return obj.to_frame()
    raise TypeError(
        f"{name} 必须是 DataFrame（index=交易日, columns=股票代码）；"
        f"Series 会被视为单列面板，但收到的是 {type(obj).__name__}。"
    )


def _check_numeric(df: pd.DataFrame, name: str = "input") -> None:
    if df.shape[1] == 0:
        return
    bad = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    if bad:
        raise TypeError(f"{name} 含非数值列：{bad[:5]}（面板值必须是数值）")


def _floor_days(value: object, *, name: str, minimum: int) -> int:
    """天数参数规范化：**非整数按论文规定取下整 floor(d)**（依据 docs/operators.md §3.8）。

    论文（arXiv:1601.00991v3，Appendix A「Functions and Operators」）逐字：
    *"non-integer number of days d is converted to floor(d)"*。
    论文自身在 58–99 号因子中大量使用非整数窗口（229 处，最多 8 位小数），
    故本库接受实数天数并取下整；**下整后**小于 ``minimum`` 的一律报错（不静默夹逼）。
    必须是 floor 而非四舍五入：``3.65459`` 取 3，取整会得 4，结果不同。
    """
    if isinstance(value, bool):
        raise TypeError(f"{name} 不能是布尔值")
    if isinstance(value, (int, np.integer)):
        days = int(value)
    elif isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            raise ValueError(f"{name} 必须是有限天数，收到 {value}")
        days = int(np.floor(value))
    else:
        raise TypeError(f"{name} 必须是整数或实数天数，收到 {type(value).__name__}")
    if days < minimum:
        raise ValueError(
            f"{name} 必须 >= {minimum}（论文规定非整数取下整，收到 {value} → floor 后为 {days}）"
        )
    return days


def _check_window(window: object) -> int:
    return _floor_days(window, name="window", minimum=1)


def _check_period(period: object, name: str = "period") -> int:
    return _floor_days(period, name=name, minimum=0)


def _check_unique_axes(df: pd.DataFrame, name: str = "input") -> None:
    if not df.index.is_unique:
        raise ValueError(f"{name} 的 index 必须唯一（重复交易日会让 stack/unstack 语义不明）")
    if not df.columns.is_unique:
        raise ValueError(f"{name} 的 columns 必须唯一（重复股票代码会污染截面算子）")


def _prep(obj: object, window: int | float | None = None, name: str = "input") -> pd.DataFrame:
    """统一入口校验：类型 → 数值 → 窗口 → 轴向唯一性。"""
    df = _as_frame(obj, name)
    _check_numeric(df, name)
    _check_unique_axes(df, name)
    if window is not None:
        _check_window(window)
    return df


def _prep_win(obj: object, window: object, name: str = "input") -> tuple[pd.DataFrame, int]:
    """校验面板，并按论文 floor 规则规范化天数参数，返回 ``(面板, 整型天数)``。

    算子内部一律使用**规范化后的整型天数**（pandas 的 rolling 不接受实数窗口），
    因此凡接受天数参数的算子都必须经由此函数，不得直接使用入参原值。
    """
    frame = _prep(obj, name=name)
    return frame, _check_window(window)


def _finite_or_nan(frame: pd.DataFrame) -> pd.DataFrame:
    """把 ±inf 一律降级为 NaN。

    ★ 为什么需要它：`pandas.rolling().corr()` 在**近乎零方差**的窗口里会给出 ±inf
    （方差是 1e-18 级别的非零值 ⇒ 0/0 变成有限值/极小值），这违反本库
    「分母为 0 ⇒ NaN」的显式承诺（详见 docs/operators.md §3.5）。
    该问题由 M3 的 101 因子全量跑（alpha3/44/55）暴露出来。
    """
    values = frame.to_numpy(dtype=float)
    if np.isfinite(values).all():
        return frame
    return pd.DataFrame(
        np.where(np.isfinite(values), values, np.nan), index=frame.index, columns=frame.columns
    )


def _check_aligned(x: pd.DataFrame, y: pd.DataFrame, op: str) -> None:
    """二元算子要求两块面板共享同一 (index, columns) 契约。"""
    if x.shape != y.shape or not x.index.equals(y.index) or not x.columns.equals(y.columns):
        raise ValueError(
            f"{op} 要求两块面板的 index 与 columns 完全一致（逐元素配对计算）；"
            f"收到 {x.shape}/{list(x.columns)[:3]} 与 {y.shape}/{list(y.columns)[:3]}。"
            "Series 语法糖要求两者列名相同，否则请显式 to_frame(name=...) 统一列名。"
        )


# ---------------------------------------------------------------------------
# A 组：时间序列算子（沿 axis=0）
# ---------------------------------------------------------------------------


def ts_sum(df: pd.DataFrame, window: int | float) -> pd.DataFrame:
    """滚动求和。前 ``window-1`` 行为 NaN（严格预热）。"""
    df, window = _prep_win(df, window)
    return df.rolling(window=window, min_periods=window).sum()


def sma(df: pd.DataFrame, window: int | float) -> pd.DataFrame:
    """滚动等权均值（不是指数加权）。"""
    df, window = _prep_win(df, window)
    return df.rolling(window=window, min_periods=window).mean()


def stddev(df: pd.DataFrame, window: int | float, ddof: int = 0) -> pd.DataFrame:
    """滚动标准差。

    ★ 歧义点 ``ddof`` —— **已由 BRAIN 官方文档（L-B）定案为默认 0**：官方 ``ts_std_dev`` 算例
    明确「Average the squared deviations: (0 + 0.0001 + 0.0004 + 0.0001 + 0.0004) / **5** = 0.0002」
    即**总体口径**（``docs/operators.md`` §3.1/§3.13.3）。``ddof=1``（样本口径）仍可选——
    vnpy 的 ``ts_std`` 同为 0，但其 ``cs_std`` 用 1（自身不一致）；其余取值直接报错，避免静默漂移。
    """
    df, window = _prep_win(df, window)
    if ddof not in ALLOWED_DDOF:
        raise ValueError(f"ddof 只接受 {ALLOWED_DDOF}（显式口径），收到 {ddof}")
    return df.rolling(window=window, min_periods=window).std(ddof=ddof)


def correlation(x: pd.DataFrame, y: pd.DataFrame, window: int | float) -> pd.DataFrame:
    """滚动 Pearson 相关系数，与 ``pandas.rolling().corr()`` 逐点一致。

    ★ 歧义点：任一侧在窗口内**零方差**（常数序列、或全 0 序列）→ ``NaN``，
    绝不返回 0 或 ±inf。实测 pandas 的 0/0 行为即为 NaN，本库显式依赖并测试它。
    """
    x, window = _prep_win(x, window, "x")
    y, _ = _prep_win(y, window, "y")
    _check_aligned(x, y, "correlation")
    return _finite_or_nan(x.rolling(window=window, min_periods=window).corr(y))


def covariance(x: pd.DataFrame, y: pd.DataFrame, window: int | float, ddof: int = 0) -> pd.DataFrame:
    """滚动协方差。

    ★ 歧义点：与 :func:`stddev` 共用 ``ddof`` 口径，默认 **0**（BRAIN 官方总体口径，L-B 定案）。
    ddof=0 由样本协方差按 ``(n-1)/n`` 闭式换算，n = window（严格预热 ⇒ 窗口内无 NaN）。
    """
    x, window = _prep_win(x, window, "x")
    y, _ = _prep_win(y, window, "y")
    _check_aligned(x, y, "covariance")
    if ddof not in ALLOWED_DDOF:
        raise ValueError(f"ddof 只接受 {ALLOWED_DDOF}（显式口径），收到 {ddof}")
    cov = _finite_or_nan(x.rolling(window=window, min_periods=window).cov(y))
    if ddof == 1:
        return cov
    return cov * (window - 1) / window


def _normalize_ranks(ranks, counts, normalization: str):
    """把「已处理并列的名次」按请求的区间归一化（``ranks``/``counts`` 均为数值或 Series）。"""
    if normalization not in ALLOWED_NORMALIZATIONS:
        raise ValueError(f"normalization 只接受 {ALLOWED_NORMALIZATIONS}，收到 {normalization!r}")
    if normalization == "ordinal":
        return ranks
    # BRAIN 官方 zero_to_one：最低 → 0.0、最高 → 1.0（n = 1 时分母为 0 ⇒ NaN，显式声明）
    zero_to_one = normalization == "zero_to_one"
    divisor = (counts - 1.0) if zero_to_one else counts
    if isinstance(ranks, pd.DataFrame):
        numerator = (ranks - 1.0) if zero_to_one else ranks
        with np.errstate(invalid="ignore", divide="ignore"):
            return _finite_or_nan(numerator.div(divisor, axis=0))
    if not divisor:
        return float("nan")
    value = (float(ranks) - 1.0 if zero_to_one else float(ranks)) / float(divisor)
    return value if np.isfinite(value) else float("nan")


def _ordinal_rank(window_values: np.ndarray) -> float:
    """单窗口辅助函数：窗口**末值**的序号名次（1..n，并列取 average），不归一化。

    供 :func:`ts_rank` 作为 rolling 内核使用（归一化在算子层只做一次，避免二次归一化）。
    """
    values = np.asarray(window_values, dtype=float)
    if values.size == 0 or not np.isfinite(values).all():
        return float("nan")
    return float(np.asarray(rankdata(values))[-1])


def _ordinal_rank_matrix(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    """``ts_rank`` 的**向量化内核**：每个窗口末值的 average 名次（1..n，未归一化）。

    数学恒等：窗口末值 x 的 average 名次 = ``1 + #{< x} + (#{== x} − 1) / 2``
    （与 ``scipy.stats.rankdata(win)[-1]`` 逐位相同）。用 ``window`` 次**整列**比较即可算出，
    完全避开 ``rolling().apply`` 的逐窗口 Python 回调 —— 这是全市场构建的主要算力瓶颈
    （``ts_rank`` 被 57 个因子使用）。

    等价性由三层证据守着：``tests/test_operators.py`` 的 ts_rank 用例、golden 快照的**位级**
    比对、以及算子层差分（对 vnpy）。``valid`` 掩码保证「窗口内任一元素非有限 ⇒ NaN」，
    与 :func:`_ordinal_rank` 的原语义一致（``inf`` 同样视为无效）。
    """
    arr = frame.to_numpy(dtype=float)
    rows, cols = arr.shape
    out = np.full((rows, cols), np.nan, dtype=float)
    if window < 1 or rows < window:
        return pd.DataFrame(out, index=frame.index, columns=frame.columns)

    last = arr[window - 1:]
    less = np.zeros_like(last)
    equal = np.zeros_like(last)
    valid = np.ones(last.shape, dtype=bool)
    for offset in range(window):
        current = arr[offset:rows - window + 1 + offset]
        valid &= np.isfinite(current)
        less += current < last
        equal += current == last

    with np.errstate(invalid="ignore"):
        rank = 1.0 + less + (equal - 1.0) / 2.0
    rank[~valid] = np.nan
    computed = pd.DataFrame(rank, index=frame.index[window - 1:], columns=frame.columns)
    return computed.reindex(frame.index)


def rolling_rank(window_values: np.ndarray, normalization: str = "zero_to_one") -> float:
    """单窗口辅助函数：返回窗口**末值**的名次（并列取 average），按 ``normalization`` 归一化。

    这是 :func:`ts_rank` 的构件，也是设计文档 §8.1 明确要求逐窗口对拍的对象：
    ``scipy.stats.rankdata(w)[-1]``。默认区间 ``zero_to_one`` = 官方 ``(名次−1)/(n−1) ∈ [0,1]``。
    """
    values = np.asarray(window_values, dtype=float)
    result = _normalize_ranks(_ordinal_rank(values), float(values.size), normalization)
    return float(result)


def ts_rank(df: pd.DataFrame, window: int | float, normalization: str = "zero_to_one") -> pd.DataFrame:
    """滚动时序 rank（窗口**末值**在窗口内的名次）。

    ★ 歧义点 ``normalization`` —— **已由 BRAIN 官方文档（L-B）定案为默认 `zero_to_one`**：
    官方 ``ts_rank`` 算例「Suppose [10, 12, 11, 15, 13] … 13 is the 4th value out of 5 (0-based
    index 3) ⇒ **Normalized rank: 3 / (5 − 1) = 0.75**」⇒ ``(名次−1)/(n−1) ∈ [0,1]``。
    ``one_over_n``（``名次/n`` ∈ (0,1]，vnpy 口径，差分对拍用）与 ``ordinal``（序号 1..n）仍可选；
    严格预热（``min_periods=window``）不变 ⇒ 窗口内无 NaN。
    """
    df, window = _prep_win(df, window)
    ordinal = _ordinal_rank_matrix(df, window)
    return _normalize_ranks(ordinal, float(window), normalization)


def product(df: pd.DataFrame, window: int | float) -> pd.DataFrame:
    """滚动连乘。"""
    df, window = _prep_win(df, window)
    return df.rolling(window=window, min_periods=window).apply(np.prod, raw=True)


def ts_min(df: pd.DataFrame, window: int | float) -> pd.DataFrame:
    """滚动最小值。"""
    df, window = _prep_win(df, window)
    return df.rolling(window=window, min_periods=window).min()


def ts_max(df: pd.DataFrame, window: int | float) -> pd.DataFrame:
    """滚动最大值。"""
    df, window = _prep_win(df, window)
    return df.rolling(window=window, min_periods=window).max()


def delta(df: pd.DataFrame, period: int | float = 1) -> pd.DataFrame:
    """一阶差分 ``x_t - x_{t-period}``（period 可为 0 ⇒ 全 0）。"""
    df = _prep(df)
    period = _check_period(period)
    return df - df.shift(period)


def delay(df: pd.DataFrame, period: int | float = 1) -> pd.DataFrame:
    """滞后 ``period`` 期（无前视）。"""
    df = _prep(df)
    period = _check_period(period)
    return df.shift(period)


def _decay_linear_core(
    df: pd.DataFrame, period: int | float, *, order: str = "recent_first", dense: bool = False
) -> pd.DataFrame:
    """线性衰减加权平均（**向量化实现**：``period`` 次整列 shift+乘加，不逐窗口回调）。

    语义与原 ``rolling().apply`` 实现相同：权重归一、``dense=False`` 时窗口内 NaN 计 0
    （分母仍为完整权重和）、``dense=True`` 时整窗必须有效。

    ⚠️ **与 apply 实现的差异只有浮点求和顺序**（两者数学等价）：实测 ``max|Δ| = 4.26e-14``
    （因子值约 100 时约 3 ulp、相对差 3e-16），NaN 掩码逐位相同。
    ``tests/test_decay_equivalence.py`` 把这条边界钉成断言（掩码逐位 + ``max|Δ| <= 1e-13``）。
    速度：60 只 × 300 天、``w=20`` 时 204 ms → 49 ms（≈4.2×）。
    """
    df, period = _prep_win(df, period)
    if order not in ALLOWED_DECAY_ORDERS:
        raise ValueError(f"order 只接受 {ALLOWED_DECAY_ORDERS}，收到 {order!r}")

    window = period
    # 系数按**年龄**索引：coef[k] 配 t-k 这一期。原实现用 chronological 窗口 weights[j]，
    # recent_first ⇒ weights = 1..w（最新权重最大）⇒ 年龄 k 的系数 = w-k；oldest_first ⇒ k+1。
    if order == "recent_first":
        coefficients = np.array([window - k for k in range(window)], dtype=float)
    else:
        coefficients = np.array([k + 1 for k in range(window)], dtype=float)
    coefficients /= coefficients.sum()

    base = df if dense else df.fillna(0.0)
    result: pd.DataFrame | None = None
    for age in range(window):
        term = base.shift(age) * coefficients[age]
        result = term if result is None else result + term
    assert result is not None

    if dense:
        full = base.notna().rolling(window=window, min_periods=window).sum() == window
        return result.where(full)
    # 稀疏语义保留，但「窗口内零观测」必须 NaN（P0-1 修复）
    observed = df.notna().rolling(window=window, min_periods=window).sum() == 0
    return result.mask(observed)



#: 研究口径开关（B4）：``None`` ⇒ 保持官方默认（稀疏）；被 :func:`research_mode` 设为 ``True`` 时，
#: **未显式传 `dense`** 的 ``decay_linear`` 调用改用严格口径。默认值恒为 ``None`` ⇒ 行为与 0.1.4 完全一致。
_DECAY_DENSE: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "alpha101v_decay_dense", default=None
)


@contextlib.contextmanager
def research_mode(*, decay_dense: bool = True):
    """研究口径上下文：块内**未显式传** `dense` 的 ``decay_linear`` 使用 ``dense=decay_dense``。

    为什么需要它（审计 B4）：``factors.py`` 里有 62 处 ``decay_linear(...)`` 调用**都没传** ``dense``
    （忠实官方 sparse 默认），而 ``run_factor`` 没有口径参数 ⇒ 想用严格口径只能 monkeypatch
    ``alpha101v.factors.decay_linear``（且必须是 ``factors.`` 前缀，改 ``operators.`` 无效）。

    用法::

        with alpha101v.research_mode():          # 研究口径：窗口必须完整，缺数据 ⇒ NaN
            run_factor("alpha31", panel)

    * **默认行为不变**：不进这个上下文 ⇒ 与 0.1.4 完全一致（golden / 差分 / 平台对拍口径不动）；
    * **线程/任务安全**：用 ``ContextVar`` 而不是模块级全局变量；
    * 显式传 ``dense=True/False`` 的调用**不受影响**（显式优先）。
    """
    token = _DECAY_DENSE.set(bool(decay_dense))
    try:
        yield
    finally:
        _DECAY_DENSE.reset(token)

def decay_linear(
    df: pd.DataFrame,
    period: int | float,
    *,
    order: str = "recent_first",
    dense: bool | None = None,
) -> pd.DataFrame:
    """:func:`_decay_linear_core` 的公开包装：**稀疏模式下补一道「零观测掩码」**。

    为什么需要：稀疏语义（官方默认）把窗口内的 NaN 当 0 计入，但**「窗口里一个有效值都没有」**
    时它是「没数据」而不是「数据为 0」⇒ 必须给 NaN。原实现直接 fillna(0) 后 rolling，
    ``min_periods`` 被满足 ⇒ 输出 0.0 ✗（伪造观测：新股上市前的全 NaN 列会在截面 rank 里拿到名次，
    挤动全市场排名，实测污染 16/101 个因子）。

    修法只堵「零观测」这一种情况：``valid_count == 0`` 的位置置 NaN；
    其余窗口仍是官方 sparse 语义（NaN 计 0、分母为完整权重和）⇒ golden / 差分口径不变。
    """
    if dense is None:                        # 未显式指定 ⇒ 查研究口径上下文（默认仍为 False）
        context_value = _DECAY_DENSE.get()
        dense = False if context_value is None else bool(context_value)
    out = _decay_linear_core(df, period, order=order, dense=dense)
    if not dense:
        frame, window = _prep_win(df, period)
        valid_count = frame.notna().rolling(window=window, min_periods=window).sum()
        out = out.mask(valid_count == 0)
    return out

def _argmax_1based(window_values: np.ndarray) -> float:
    """窗口内最大值的位置，**自窗口起点 1-based**（最新值为 window）。并列取最早出现。"""
    return float(np.argmax(window_values) + 1)


def _argmin_1based(window_values: np.ndarray) -> float:
    """窗口内最小值的位置，**自窗口起点 1-based**。并列取最早出现。"""
    return float(np.argmin(window_values) + 1)


def _shift_arg_basis(pos: pd.DataFrame, window: int | float, basis: str) -> pd.DataFrame:
    """把「自窗口起点 1-based」的位置换算成所请求的基准。

    ``days_ago``（**默认**）= BRAIN 官方口径（今天=0）；``window_start`` = 自窗口起点 1-based
    （vnpy 的口径，因子级差分对拍时用它对齐）。
    """
    if basis == "days_ago":
        # BRAIN 原文：today's value is the maximum → 0；yesterday → 1 ⇒ days_ago = window - 自起点位置
        return float(window) - pos
    if basis == "window_start":
        return pos
    raise ValueError(f"basis 只接受 {ALLOWED_ARG_BASIS}，收到 {basis!r}")



def _arg_position_matrix(frame: pd.DataFrame, window: int, *, which: str) -> pd.DataFrame:
    """``ts_argmax``/``ts_argmin`` 的向量化内核：返回 **1-based、自窗口起点** 的位置。

    做法：先取 ``rolling.max/min``（向量化），再自新到老扫一遍、**命中即覆盖** ——
    这样「最老的那个命中者」胜出，与 ``np.argmax``/``np.argmin`` 的**并列取最早**一致。
    ``min_periods=window`` ⇒ 窗口内含 NaN 时极值为 NaN ⇒ 全部不命中 ⇒ 结果 NaN
    （与原 ``rolling.apply`` 的 NaN 语义相同）。
    """
    reduced = (
        frame.rolling(window=window, min_periods=window).max()
        if which == "max"
        else frame.rolling(window=window, min_periods=window).min()
    )
    target = reduced.to_numpy(dtype=float)
    position = np.full(target.shape, np.nan, dtype=float)
    for age in range(window):                     # age 0 = 最新；越往后越老 ⇒ 覆盖后留下最老的
        value = frame.shift(age).to_numpy(dtype=float)
        hit = np.isfinite(target) & (value == target) & np.isfinite(value)
        position = np.where(hit, float(window - age), position)   # 1-based 自窗口起点
    return pd.DataFrame(position, index=frame.index, columns=frame.columns)

def ts_argmax(df: pd.DataFrame, window: int | float, basis: str = "days_ago") -> pd.DataFrame:
    """最大值在最近 ``window`` 期中的位置。

    ★ 歧义点 ``basis`` —— **已由 BRAIN 官方文档（L-B）定案**：``"days_ago"``（默认）=
    距今几天，**今天最大返回 0**、昨天返回 1；即 BRAIN 原文
    *"Returns the number of days since the maximum value occurred in the last d days of a time
    series. If today's value is the maximum, returns 0; if it was yesterday, returns 1, and so on."*
    （`docs/operators.md` §3.13，一手依据 `refs/WorldQuant_BRAIN.pdf`）。

    另一口径 ``"window_start"``（自窗口起点 1-based ∈ [1, window]）保留可选：**vnpy 用的是它**
    （`ts_function.py`: ``series.arg_max() + 1``），因子级差分对拍时用它对齐。两者关系
    ``days_ago = window − window_start``（**序反转**，不是平移）。
    并列时取**最早出现**（与 ``np.argmax`` 一致；BRAIN 未规定）。
    """
    df, window = _prep_win(df, window)
    pos = _arg_position_matrix(df, window, which="max")
    return _shift_arg_basis(pos, window, basis)


def ts_argmin(df: pd.DataFrame, window: int | float, basis: str = "days_ago") -> pd.DataFrame:
    """最小值在最近 ``window`` 期中的位置（``basis`` 语义同 :func:`ts_argmax`，BRAIN 同样「今天=0」）。"""
    df, window = _prep_win(df, window)
    pos = _arg_position_matrix(df, window, which="min")
    return _shift_arg_basis(pos, window, basis)


# ---------------------------------------------------------------------------
# B 组：截面算子（沿 axis=1）
# ---------------------------------------------------------------------------


def rank(df: pd.DataFrame, normalization: str = "zero_to_one", method: str = "average") -> pd.DataFrame:
    """每日截面 rank。

    ★ 歧义点 ``normalization`` —— **已由 BRAIN 官方文档（L-B）定案为默认 `zero_to_one`**：
    官方 ``rank`` 原文「mapping the **lowest value to 0.0** and the **highest to 1.0**」，
    算例 ``x = (4, 3, 6, 10, 2) → (0.5, 0.25, 0.75, 1, 0)`` ⇒ ``(名次−1)/(n−1) ∈ [0,1]``。
    ``one_over_n`` = ``名次/n`` ∈ (0,1]（vnpy 口径，差分对拍用）；``ordinal`` = 序号 1..n。
    n = 1（当日只有一个有效标的）时 ``zero_to_one`` 分母为 0 ⇒ **NaN**（显式声明）。
    ★ 歧义点：并列策略 ``method`` 显式化，默认 **"average"**（pandas/scipy 默认）。
    NaN 不参与排序且保持 NaN（``na_option="keep"``）。
    """
    df = _prep(df)
    if method not in ALLOWED_RANK_METHODS:
        raise ValueError(f"method 只接受 {ALLOWED_RANK_METHODS}，收到 {method!r}")
    counts = df.notna().sum(axis=1).astype(float)
    ordinal = df.rank(axis=1, method=method, pct=False, na_option="keep")
    return _normalize_ranks(ordinal, counts, normalization)


def scale(df: pd.DataFrame, k: float = 1.0) -> pd.DataFrame:
    """每日截面缩放：``Σ|x| = k``（**沿 axis=1**）。

    原实现 ``df.div(df.abs().sum())`` 按列（axis=0）求和，是设计文档 §3.3 缺陷 3；
    此处显式 ``axis=1`` 并由测试断言逐日 ``Σ|x| == k``。

    边界（显式策略）：某日 ``Σ|x| == 0``（全 0 或全 NaN 行）→ 该日结果为 ``NaN``
    （$$0/0$$ 未定义），不返回 0、不抛异常。行内个别 NaN 不参与求和不参与缩放，保持 NaN。
    """
    df = _prep(df)
    k = float(k)
    if not np.isfinite(k) or k <= 0:
        raise ValueError(f"k 必须是有限正数（口径 Σ|x| = k），收到 {k}")
    total = df.abs().sum(axis=1)
    return _finite_or_nan(df.div(total, axis=0) * k)
