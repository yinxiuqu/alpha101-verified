"""alpha101v.neutralize — 行业中性化算子（M1，共 3 个算子）。

设计要点（对齐设计文档 §8.3 与 §10.3 的重点预告）
------------------------------------------------
两个主流实现都栽在 ``IndNeutralize`` 上：一个整个算子缺失（vnpy），一个逐日
``numpy.linalg.inv`` 求逆、遇空行业即 ``LinAlgError``（原始仓库 §3.3 缺陷 4）。
本模块的做法：

1. **向量化**：``ind_neutralize`` 不做逐日 Python 循环，也不用矩阵求逆；
   用「(交易日, 行业) 组合编码 + ``np.bincount`` 分组求和」一次算完整个面板。
2. **等价于 OLS 残差**：仅有行业哑变量、无截距的 OLS，其投影就是组内均值，
   故残差 = ``y - 组内均值``（逐点等价于 ``statsmodels.OLS(y, dummies).resid``，
   由 ``tests/test_operators.py`` 以 rtol=1e-10 对拍）。
3. **共线性/空行业不崩**：组内无观测 → 该组均值 NaN（残差 NaN）；
   单成员行业 → 残差恒为 0；行业标签为 NaN → 不参与分组，残差 NaN。
4. **PIT 友好**：``industry`` 既可以是**静态快照** (``Series``，index=股票代码)，
   也可以是**逐日 as-of 面板** (``DataFrame``，index=交易日, columns=股票代码)，
   后者是 PIT 形态，前视检验（设计文档 §6.5）用之。

``neutral`` 是**一般截面 OLS 参考实现**（逐日 ``np.linalg.lstsq``，SVD 求解，
对共线回归元安全），用于给 ``ind_neutralize`` 的快速路径提供第二条独立证据链。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from .operators import _as_frame, _check_aligned, _check_numeric, _check_unique_axes, _prep

__all__ = ["ind_neutralize", "neu_industry", "neutral"]


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _industry_labels(df: pd.DataFrame, industry: object, name: str = "industry") -> pd.DataFrame:
    """把行业输入对齐成与 ``df`` 同形的标签面板。

    * ``Series``（静态快照）→ 按股票代码广播到每个交易日（可写副本；T×N 的内存
      代价换掉「只读视图」这一隐患，M2 若需要可用 one-hot 矩阵乘法做快路径）；
    * ``DataFrame``（PIT as-of）→ 按 (交易日, 股票代码) 对齐，缺失即 NaN。

    对不上的组合留 NaN，由下游显式处理（残差 NaN），不静默填充。
    """
    if isinstance(industry, pd.Series):
        labels = industry.reindex(df.columns)
        return pd.DataFrame(
            np.tile(labels.to_numpy(), (len(df), 1)),
            index=df.index,
            columns=df.columns,
        )
    if isinstance(industry, pd.DataFrame):
        _check_unique_axes(industry, name)
        return industry.reindex(index=df.index, columns=df.columns)
    raise TypeError(
        f"{name} 必须是 Series（静态快照，index=股票代码）或 DataFrame（PIT as-of 面板，"
        f"index=交易日, columns=股票代码），收到 {type(industry).__name__}。"
    )


def _group_mean(y: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """逐 (交易日, 行业) 分组均值，向量化实现（无逐日循环、无矩阵求逆）。

    语义（与 ``pandas.groupby(...).transform("mean")`` 一致）：
    NaN 值不参与求和与计数（skipna）；标签为 NaN 的格子不参与分组，均值为 NaN；
    组内全为 NaN 或组内无观测 → 均值 NaN；±inf 会污染该组均值（与 pandas 同）。
    """
    if y.shape != labels.shape:
        raise ValueError("标签面板与因子面板形状不一致（内部错误）")

    t_len, n_col = y.shape
    y_flat = y.to_numpy(dtype=float).ravel()
    lab_flat = np.asarray(labels.to_numpy(), dtype=object).ravel()

    labelled = ~pd.isna(lab_flat)
    means_flat = np.full(t_len * n_col, np.nan, dtype=float)

    if labelled.any():
        # 全局只做一次标签编码，保证「求和」与「回填」用同一套组编号
        codes_all = np.full(lab_flat.shape, -1, dtype=np.int64)
        codes_all[labelled], _ = pd.factorize(lab_flat[labelled])
        n_codes = int(codes_all.max()) + 1

        counted = labelled & ~np.isnan(y_flat)
        t_idx = np.repeat(np.arange(t_len), n_col)
        size = t_len * n_codes

        group_means = np.full(size, np.nan, dtype=float)
        if counted.any():
            combo = t_idx[counted] * n_codes + codes_all[counted]
            sums = np.bincount(combo, weights=y_flat[counted], minlength=size)
            counts = np.bincount(combo, minlength=size).astype(float)
            with np.errstate(invalid="ignore", divide="ignore"):
                group_means = sums / counts  # 组内 0 个有效观测 → NaN

        means_flat[labelled] = group_means[t_idx[labelled] * n_codes + codes_all[labelled]]

    return pd.DataFrame(means_flat.reshape(t_len, n_col), index=y.index, columns=y.columns)


def _as_exposure_panels(x: object, like: pd.DataFrame) -> list[pd.DataFrame]:
    """把 ``neutral`` 的回归元输入规范成「同形面板列表」。"""
    if isinstance(x, Mapping):
        panels = list(x.values())
    elif isinstance(x, pd.DataFrame):
        panels = [x]
    elif isinstance(x, Sequence) and not isinstance(x, (str, bytes)):
        panels = list(x)
    else:
        raise TypeError(
            "neutral 的回归元必须是同形面板：单个 DataFrame（单回归元，如市值），"
            "或 DataFrame 的序列/映射（多回归元，如行业哑变量逐列一个面板）。"
            f"收到 {type(x).__name__}。若你手上是行业标签，请用 ind_neutralize。"
        )
    if not panels:
        raise ValueError("neutral 至少需要一个回归元面板")

    out: list[pd.DataFrame] = []
    for i, panel in enumerate(panels):
        p = _as_frame(panel, f"x[{i}]")
        _check_numeric(p, f"x[{i}]")
        _check_unique_axes(p, f"x[{i}]")
        _check_aligned(like, p, "neutral")
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# 公开算子
# ---------------------------------------------------------------------------


def ind_neutralize(df: pd.DataFrame, industry: object) -> pd.DataFrame:
    """行业中性化：逐日对行业哑变量做 OLS 后的残差（组内去均值）。

    ``resid = y - mean(y | 交易日, 行业)``，与「仅含行业哑变量、无截距」的 OLS
    残差逐点等价，故残差在每个行业内求和 ≈ 0、与行业哑变量内积 ≈ 0。

    边界策略（显式，全部有测试）：
    * 行业标签 NaN → 该格残差 NaN（无法定义所属组）；
    * 某行业在某日只有 1 只股票 → 残差恒为 0（共线性边界，非错误）；
    * 某行业在某日的值全为 NaN → 残差 NaN，**不抛 LinAlgError**；
    * 入参一字不改（纯函数）。
    """
    y = _prep(df, name="df")
    labels = _industry_labels(y, industry)
    return y - _group_mean(y, labels)


def neu_industry(df: pd.DataFrame, industry: object) -> pd.DataFrame:
    """按行业做**比例**中性化：``a / 行业内均值``（逐日、逐行业）。

    与 ``df.T.groupby(industry).transform("mean").T`` 对拍（见测试）。
    边界：行业均值为 0 → 该格 NaN（比例未定义），不产生 ±inf。
    """
    y = _prep(df, name="df")
    labels = _industry_labels(y, industry)
    means = _group_mean(y, labels)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = y.div(means.where(means != 0))
    return out


def neutral(y: pd.DataFrame, x: object) -> pd.DataFrame:
    """一般截面 OLS 中性化：逐日 ``y - X·pinv(X)·y``（``np.linalg.lstsq``，SVD）。

    与原始实现的关键差别：**不使用 ``linalg.inv``**。回归元列共线（如某行业哑变量
    全 0、或重复列）时 SVD 给出最小范数解，投影唯一 → 残差仍然正确且**不抛
    LinAlgError**（设计文档 §3.3 缺陷 4）。

    调用契约
    --------
    ``y`` : 因子面板 (交易日 × 股票代码)。
    ``x`` : 回归元面板，单个 DataFrame（单回归元，如对数市值）或 DataFrame 的
        序列/映射（多回归元，如每个行业哑变量一个 0/1 面板）。**不含隐式截距**——
        需要截距请显式加一个全 1 面板（口径与论文公式 ``X(XᵀX)⁻¹Xᵀ`` 一致）。

    边界：``y`` 或任一回归元为非有限值的股票，当日不进入回归，其残差为 NaN。
    """
    y = _prep(y, name="y")
    panels = _as_exposure_panels(x, y)

    t_len = len(y)
    y_arr = y.to_numpy(dtype=float)
    x_arr = np.stack([p.to_numpy(dtype=float) for p in panels], axis=-1)  # (T, N, K)

    out = np.full(y_arr.shape, np.nan, dtype=float)
    for t in range(t_len):
        y_row = y_arr[t]
        x_row = x_arr[t]
        mask = np.isfinite(y_row) & np.all(np.isfinite(x_row), axis=1)
        if not mask.any():
            continue
        x_fit = x_row[mask]
        y_fit = y_row[mask]
        beta, *_ = np.linalg.lstsq(x_fit, y_fit, rcond=None)
        out[t, mask] = y_fit - x_fit @ beta

    return pd.DataFrame(out, index=y.index, columns=y.columns)
