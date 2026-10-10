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
ddof  ``stddev``/``covariance`` 默认 ``ddof=1``（样本口径），仅接受 0/1
pct   ``ts_rank`` 默认 ``pct=True`` → ``rankdata(window)[-1] / window`` ∈ (0, 1]
argmax ``ts_argmax``/``ts_argmin`` 默认 ``basis="window_start"``（自窗口起点 1-based）
scale ``scale`` 沿 ``axis=1``（每日 ``Σ|x| = k``），``axis=0`` 是错的
floor 非整数天数按论文取下整 ``floor(d)``（58–99 号因子大量使用）
order ``decay_linear`` 权重方向默认「最新最大」，``order="oldest_first"`` 对齐 vnpy
常数序列 ``correlation`` 遇零方差 → ``NaN``（不是 0，也不是 inf）
===== ==========================================================
"""

from __future__ import annotations

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
ALLOWED_ARG_BASIS = ("window_start", "days_ago")

#: 允许的 ``rank`` 并列处理策略。
ALLOWED_RANK_METHODS = ("average", "min", "max", "first", "dense")

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


def stddev(df: pd.DataFrame, window: int | float, ddof: int = 1) -> pd.DataFrame:
    """滚动标准差。

    ★ 歧义点：``ddof`` 显式化，默认 **1**（样本口径，与 pandas/polars 默认一致）。
    ``ddof=0`` 为总体口径；其余取值直接报错，避免静默的口径漂移。
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


def covariance(x: pd.DataFrame, y: pd.DataFrame, window: int | float, ddof: int = 1) -> pd.DataFrame:
    """滚动样本协方差。

    ★ 歧义点：与 :func:`stddev` 共用 ``ddof`` 口径（默认 1）。
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


def rolling_rank(window_values: np.ndarray) -> float:
    """单窗口辅助函数：返回窗口**末值**的序号 rank（1..n，并列取 average）。

    这是 :func:`ts_rank` 的构件，也是设计文档 §8.1 明确要求逐窗口对拍的对象：
    ``scipy.stats.rankdata(w)[-1]``。
    """
    values = np.asarray(window_values, dtype=float)
    return float(rankdata(values)[-1])


def ts_rank(df: pd.DataFrame, window: int | float, pct: bool = True) -> pd.DataFrame:
    """滚动时序 rank。

    ★ 歧义点：``pct`` 显式化，默认 **True** → ``rankdata(window 末值) / window`` ∈ (0, 1]，
    与截面 :func:`rank` 同量纲（原始实现返回序号 1..n，与截面 pct 混用量纲，见
    设计文档 §3.3 缺陷 6）。``pct=False`` 返回序号 1..n，可用于对齐序号口径的参照实现。
    """
    df, window = _prep_win(df, window)
    ordinal = df.rolling(window=window, min_periods=window).apply(rolling_rank, raw=True)
    if pct:
        return ordinal / float(window)
    return ordinal


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


def decay_linear(
    df: pd.DataFrame, period: int | float, *, order: str = "recent_first"
) -> pd.DataFrame:
    """线性衰减加权平均，权重归一（和为 1）。

    ★ 歧义点 ``order``（论文只写权重列表 ``d, d–1, …, 1``，**未写枚举方向**）：

    * ``"recent_first"``（**默认**）：最新值权重最大，权重 ``1..d`` ⇒ 权重随**年龄**衰减，
      与算子名 ``decay`` 自洽，也与设计文档 §8.1 的期望值 ``14/6`` 一致；
    * ``"oldest_first"``：把论文的权重列表按**时间正序**读（最老权重 ``d``），
      这正是 vnpy ``ts_decay_linear`` 的实现方式（2026-10-09 差分实测确认），
      供 M4 对齐参照实现使用。

    原实现用 numpy ``as_matrix()``（pandas>=1.0 已删除）必崩，见设计文档 §3.3 缺陷 1。
    """
    df, period = _prep_win(df, period)
    if order not in ALLOWED_DECAY_ORDERS:
        raise ValueError(f"order 只接受 {ALLOWED_DECAY_ORDERS}，收到 {order!r}")
    if order == "recent_first":
        weights = np.arange(1, period + 1, dtype=float)
    else:
        weights = np.arange(period, 0, -1, dtype=float)
    weights /= weights.sum()
    return df.rolling(window=period, min_periods=period).apply(
        lambda w: float(np.dot(w, weights)), raw=True
    )


def _argmax_1based(window_values: np.ndarray) -> float:
    """窗口内最大值的位置，**自窗口起点 1-based**（最新值为 window）。并列取最早出现。"""
    return float(np.argmax(window_values) + 1)


def _argmin_1based(window_values: np.ndarray) -> float:
    """窗口内最小值的位置，**自窗口起点 1-based**。并列取最早出现。"""
    return float(np.argmin(window_values) + 1)


def _shift_arg_basis(pos: pd.DataFrame, window: int | float, basis: str) -> pd.DataFrame:
    """把「自窗口起点 1-based」的位置换算成所请求的基准。"""
    if basis == "window_start":
        return pos
    if basis == "days_ago":
        # 官方（BRAIN）口径：今天是 0，昨天是 1 …… 等价换算 = window - 自起点位置
        return float(window) - pos
    raise ValueError(f"basis 只接受 {ALLOWED_ARG_BASIS}，收到 {basis!r}")


def ts_argmax(df: pd.DataFrame, window: int | float, basis: str = "window_start") -> pd.DataFrame:
    """最大值在最近 ``window`` 期中的位置。

    ★ 歧义点：``basis`` 显式化。
    ``"window_start"``（默认）= 自窗口起点 1-based ∈ [1, window]；
    ``"days_ago"`` = 官方 BRAIN 口径「距今几天」，今天是 0 ∈ [0, window-1]。
    两者关系：``days_ago = window - window_start``，本库同时提供并测试，避免歧义沉默。
    并列时取**最早出现**（与 ``np.argmax`` 一致）。
    """
    df, window = _prep_win(df, window)
    pos = df.rolling(window=window, min_periods=window).apply(_argmax_1based, raw=True)
    return _shift_arg_basis(pos, window, basis)


def ts_argmin(df: pd.DataFrame, window: int | float, basis: str = "window_start") -> pd.DataFrame:
    """最小值在最近 ``window`` 期中的位置（``basis`` 语义同 :func:`ts_argmax`）。"""
    df, window = _prep_win(df, window)
    pos = df.rolling(window=window, min_periods=window).apply(_argmin_1based, raw=True)
    return _shift_arg_basis(pos, window, basis)


# ---------------------------------------------------------------------------
# B 组：截面算子（沿 axis=1）
# ---------------------------------------------------------------------------


def rank(df: pd.DataFrame, pct: bool = True, method: str = "average") -> pd.DataFrame:
    """每日截面 rank。

    ★ 歧义点：``pct`` 显式化，默认 **True** → ``scipy.stats.rankdata(row,'average')/n``，
    值域 ⊆ (0, 1]，与设计文档 §8.2 逐点一致。
    ★ 歧义点：并列策略 ``method`` 显式化，默认 **"average"**（pandas/scipy 默认）。
    NaN 不参与排序且保持 NaN（``na_option="keep"``）。
    """
    df = _prep(df)
    if method not in ALLOWED_RANK_METHODS:
        raise ValueError(f"method 只接受 {ALLOWED_RANK_METHODS}，收到 {method!r}")
    return df.rank(axis=1, method=method, pct=pct, na_option="keep")


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
