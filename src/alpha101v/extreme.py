"""极端值策略：三类情形分开处理（除零 / 极小分母 / 分子溢出），默认取最保守的口径。

为什么默认是 NaN
----------------
三方口径一致、且都不在库层自动保留 inf：

* **vnpy**（本仓库差分参照）：`ts_function.py` 里 ``pl.when(col.is_infinite() | col.is_nan()).then(None)``
  —— 直接降为 null；
* **BRAIN 官方**：``divide`` 文档写「dividing by zero raises an error; to avoid it, use
  ``divide(x, add(y, 0.0001))``」⇒ 除零在平台上同样**无定义**；而「压制极端值」是**独立的
  ``winsorize(x, std=4)`` 算子**（clip 到 mean ± 4σ），由作者显式调用，**不会自动发生**；
* 论文公式本身也没有任何 winsorize 步骤。

三分类原则（**不能只凭 inf 本身判断该保留还是剔除**）
----------------------------------------------------
=====================================================================  ================================  ==========================================
情形                                                                  判断依据                          处理
=====================================================================  ================================  ==========================================
① **除以 0** 得到 ±inf                                                分母为 0（不能从 inf 反推）       显式 **NaN/屏蔽**；**不要**用截面极值
                                                                                                        替换（会把无意义的计算爆炸伪装成
                                                                                                        极端信号，扭曲 IC/分层/ML）
② **极小分母**导致的**巨大有限值**                                   分母 ``|d| <= eps``（值有限）      分母阈值掩码，或截面 winsorize
③ **分子溢出**导致 ±inf                                              分子极大、**非**除零               可截断保留：替换为截面最大/最小有限值
=====================================================================  ================================  ==========================================

本库入口：
* ① ② 的正确解法是**计算层**按分母掩码 → :func:`mask_small_denominator`
  （事后只能看到 inf，无法区分 ① 与 ③，所以「查分母」才是对的）；
* ② 的替代解 → :func:`winsorize_std`（只裁剪**有限**值到 ±std σ）；
* ③ 的显式方案 → :func:`bound_inf`（**前提**：已确认 inf 来自溢出而非除零）。

默认策略 ``extremes="nan"``：±inf 一律 NaN（保守，对应 ① 与「来源不明」）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["bound_inf", "count_extremes", "mask_small_denominator", "winsorize_inf", "winsorize_std"]


def count_extremes(frame: pd.DataFrame) -> dict[str, int]:
    """统计极端值/缺失数量（**诊断用**，不修改数据）。

    返回 ``{"pos_inf", "neg_inf", "nan", "cells"}``。建议在研究流程里记一笔：
    「这次有多少格信号爆表」本身就是有用信息，不要让它静默消失。
    """
    values = frame.to_numpy(dtype=float)
    return {
        "pos_inf": int(np.isposinf(values).sum()),
        "neg_inf": int(np.isneginf(values).sum()),
        "nan": int(np.isnan(values).sum()),
        "cells": int(values.size),
    }


def mask_small_denominator(
    numer: pd.DataFrame, denom: pd.DataFrame, *, eps: float = 1e-12
) -> pd.DataFrame:
    """**计算层**的正确做法：分母绝对值 ``<= eps`` 时结果置 NaN（对应三分类 ① ②）。

    这比「事后把 inf 变 NaN」更准：**除零与溢出无法从 inf 本身区分**，但分母是可查的。
    ``eps`` 要按因子量纲自定（示例值只适用于 O(1) 量级的分母）。

    用法::

        factor = mask_small_denominator(numer, denom, eps=1e-12)
    """
    if not np.isfinite(eps) or eps < 0:
        raise ValueError("eps 必须是非负有限数")
    small = denom.abs().to_numpy(dtype=float) <= eps
    values = (numer / denom).to_numpy(dtype=float)
    values = np.where(small, np.nan, values)
    return pd.DataFrame(values, index=numer.index, columns=numer.columns)


def bound_inf(frame: pd.DataFrame, *, axis: int = 1) -> pd.DataFrame:
    """三分类 ③：把 ±inf 替换为同一截面最大/最小**有限**值（保留尾部信息）。

    **前提**：你已确认这些 inf 来自**分子溢出**而不是**除零**。若无法确认，请用默认口径
    （±inf ⇒ NaN）—— 把除零爆炸伪装成极端信号会扭曲 IC/分层/ML。
    """
    out = frame.copy()
    values = out.to_numpy(dtype=float)
    if not np.isinf(values).any():
        return out

    finite = np.where(np.isfinite(values), values, np.nan)
    with np.errstate(invalid="ignore"):
        if axis == 1:
            high = np.nanmax(finite, axis=1, keepdims=True)
            low = np.nanmin(finite, axis=1, keepdims=True)
        elif axis == 0:
            high = np.nanmax(finite, axis=0, keepdims=True)
            low = np.nanmin(finite, axis=0, keepdims=True)
        else:
            raise ValueError("axis 只接受 0 或 1")
    replaced = np.where(np.isposinf(values), high, np.where(np.isneginf(values), low, values))
    return pd.DataFrame(replaced, index=out.index, columns=out.columns)


def winsorize_inf(frame: pd.DataFrame, *, axis: int = 1) -> pd.DataFrame:
    """:func:`bound_inf` 的旧名（保留兼容）。仅用于**已确认是溢出**的 inf。"""
    return bound_inf(frame, axis=axis)


def winsorize_std(
    frame: pd.DataFrame, *, std: float = 4.0, axis: int = 1, keep_inf_bound: bool = False
) -> pd.DataFrame:
    """**BRAIN 官方口径**的 winsorize：把（有限）值 clip 到「均值 ± ``std`` 倍标准差」。

    官方原文（``operator_winsorize``）："The winsorize(x, std=4) operator adjusts all values in the
    input vector x so that they fall within the lower and upper bounds, which are set as multiples
    of the standard deviation from the mean. By default, values beyond ±4 standard deviations are
    replaced with the nearest boundary value."

    行为
    ----
    * 均值/标准差按**每个截面**（``axis=1``，默认）nan-aware 计算，``ddof=0``（与本库 ``stddev`` 一致）；
    * **±inf 默认仍为 NaN**（三分类 ① 保守：无法区分除零与溢出）；若已确认是**溢出**且想保留尾部，
      传 ``keep_inf_bound=True``（等价于先 :func:`bound_inf` 再 clip）；
    * NaN 保持 NaN；某截面无有效值时整行保持 NaN；
    * 只做 clip，不引入新信息 —— 这正是「保留 4σ 信息」的常用做法。
    """
    out = frame.copy()
    values = out.to_numpy(dtype=float)
    if values.size == 0:
        return out

    if keep_inf_bound:
        values = bound_inf(out, axis=axis).to_numpy(dtype=float)
    else:
        values = np.where(np.isinf(values), np.nan, values)

    finite_only = np.where(np.isfinite(values), values, np.nan)
    with np.errstate(invalid="ignore"):
        if axis == 1:
            mean = np.nanmean(finite_only, axis=1, keepdims=True)
            spread = np.nanstd(finite_only, axis=1, ddof=0, keepdims=True)
        elif axis == 0:
            mean = np.nanmean(finite_only, axis=0, keepdims=True)
            spread = np.nanstd(finite_only, axis=0, ddof=0, keepdims=True)
        else:
            raise ValueError("axis 只接受 0 或 1")
        clipped = np.clip(values, mean - std * spread, mean + std * spread)
    return pd.DataFrame(clipped, index=out.index, columns=out.columns)
