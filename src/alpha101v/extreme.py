"""极端值策略：**默认忠实于平台口径（±inf → NaN）**，另提供显式的 winsorize 与研究诊断。

为什么默认是 NaN
----------------
三方口径一致，且都不在库层自动保留 inf：

* **vnpy**（本仓库的差分参照）：`ts_function.py` 里 `pl.when(col.is_infinite() | col.is_nan()).then(None)`
  —— 直接降为 null；
* **BRAIN 官方**：`divide` 文档写「dividing by zero raises an error; to avoid it, use
  `divide(x, add(y, 0.0001))`」⇒ 除零在平台上同样**无定义**；而「压制极端值」在平台上是
  **独立的 `winsorize` 算子**，由作者显式调用，**不会自动发生**；
* 论文公式本身也没有任何 winsorize 步骤。

为什么另给 winsorize
--------------------
如果你的目的是**挖掘因子的全部预测力**（而不是与平台逐位对拍），把 ±inf 变成 NaN 会**丢掉信息** ✗：
NaN 行在排序/分层里被整行剔除，等于「爆表」的标的被扔掉。常见做法是把 ±inf 替换成
**该截面上的最大/最小有限值**（极端形式的 winsorize），保留排序信息。

⚠️ 这**会改变因子数值**，所以：

* 默认行为不变（`extremes="nan"`）；
* 需要时显式开启（`extremes="winsorize"`，或在拿到因子面板后调用 :func:`winsorize_inf`）；
* 与 golden / 差分 / 平台算例对拍时**必须用默认** —— 否则数值不可比。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["count_extremes", "winsorize_inf", "winsorize_std"]


def count_extremes(frame: pd.DataFrame) -> dict[str, int]:
    """统计极端值/缺失数量（**诊断用**，不修改数据）。

    返回 ``{"pos_inf", "neg_inf", "nan", "cells"}`` —— 建议在研究流程里记一笔：
    「这次有多少格的信号爆表」本身就是有用信息（审计意见 E：不要静默抹掉它）。
    """
    values = frame.to_numpy(dtype=float)
    return {
        "pos_inf": int(np.isposinf(values).sum()),
        "neg_inf": int(np.isneginf(values).sum()),
        "nan": int(np.isnan(values).sum()),
        "cells": int(values.size),
    }


def winsorize_inf(frame: pd.DataFrame, *, axis: int = 1) -> pd.DataFrame:
    """把 ±inf 替换为**同一截面上的最大/最小有限值**（不改变其余数值，返回新对象）。

    Parameters
    ----------
    frame:
        因子面板（行 = 日期，列 = 标的）。
    axis:
        ``1``（默认）按**行**（每个交易日的横截面）取极值；``0`` 按列（每个标的的时间序列）。

    Notes
    -----
    * 若某截面**没有任何有限值**，该截面的 inf 仍为 NaN（无值可依）；
    * 只在最后一步做极值替换，**不做**分位数裁剪（那会改变排序，属于更强的 winsorize，
      请另行处理）；
    * 与 :func:`count_extremes` 一起用：先计数、再决定是否替换。
    """
    out = frame.copy()
    values = out.to_numpy(dtype=float)
    if not np.isinf(values).any():
        return out

    finite = np.where(np.isfinite(values), values, np.nan)
    with np.errstate(invalid="ignore"):
        if axis == 1:
            hi = np.nanmax(finite, axis=1, keepdims=True)
            lo = np.nanmin(finite, axis=1, keepdims=True)
        elif axis == 0:
            hi = np.nanmax(finite, axis=0, keepdims=True)
            lo = np.nanmin(finite, axis=0, keepdims=True)
        else:  # pragma: no cover - 参数校验
            raise ValueError("axis 只接受 0 或 1")
    replaced = np.where(np.isposinf(values), hi, np.where(np.isneginf(values), lo, values))
    return pd.DataFrame(replaced, index=out.index, columns=out.columns)


def winsorize_std(frame: pd.DataFrame, *, std: float = 4.0, axis: int = 1) -> pd.DataFrame:
    """**BRAIN 官方口径**的 winsorize：把值 clip 到「均值 ± ``std`` 倍标准差」区间内。

    官方原文（`operator_winsorize`）："The winsorize(x, std=4) operator adjusts all values in the
    input vector x so that they fall within the lower and upper bounds, which are set as multiples
    of the standard deviation from the mean. By default, values beyond ±4 standard deviations are
    replaced with the nearest boundary value."

    与 :func:`winsorize_inf` 的分工：

    * 本函数是**官方语义**：按 σ 定界、**大但有限的值也会被裁剪**（保留极端信息但不让它主导）；
    * ``±inf``（除零/溢出）**本身就是"超出 ±4σ"** ⇒ 会被 clip 到边界（研究口径下"爆表"仍保留排序信息）；
      而**默认口径**（``extremes="nan"``）仍把 ±inf 视为未定义 ⇒ NaN（与 vnpy / BRAIN 的
      「dividing by zero raises an error」一致）。

    Notes
    -----
    * 均值/标准差按**每个截面**（``axis=1``，默认）nan-aware 计算，``ddof=0``（与本库 ``stddev`` 一致）；
    * NaN 保持 NaN（既不参与统计、也不被填充）；某截面无有效值时整行保持 NaN；
    * 只做 clip，**不改排序以外的信息量**：这正是「保留 4σ 信息」的常用做法。
    """
    out = frame.copy()
    values = out.to_numpy(dtype=float)
    if values.size == 0:
        return out

    data = np.where(np.isinf(values), np.nan, values)      # 统计量不能用 inf 算
    with np.errstate(invalid="ignore"):
        if axis == 1:
            mean = np.nanmean(data, axis=1, keepdims=True)
            spread = np.nanstd(data, axis=1, ddof=0, keepdims=True)
        elif axis == 0:
            mean = np.nanmean(data, axis=0, keepdims=True)
            spread = np.nanstd(data, axis=0, ddof=0, keepdims=True)
        else:  # pragma: no cover
            raise ValueError("axis 只接受 0 或 1")
        lower, upper = mean - std * spread, mean + std * spread
        # inf 比任何有限上界都大（-inf 比下界都小）⇒ clip 后自然落到边界；NaN 仍为 NaN
        clipped = np.clip(values, lower, upper)
    return pd.DataFrame(clipped, index=out.index, columns=out.columns)
