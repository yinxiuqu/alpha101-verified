"""极端值策略：严格按「三原则」处理（除零 / 极小分母 / 分子溢出）。

默认路径（``registry.run_factor``）只有一种行为
---------------------------------------------
因子按论文原式计算，**输出永不含 ±inf**：``registry._sanitize`` 把 ±inf 一律降为 **NaN**。
这对应三原则的 ①（除零 = 无定义 ⇒ 显式 NaN/屏蔽），也是 vnpy
（``pl.when(col.is_infinite() | col.is_nan()).then(None)``）与 BRAIN 官方
（``divide`` 文档：dividing by zero raises an error）的共同口径。

**本库不提供「把 inf/winsorize 当默认流程」的开关**——那会把「无意义的计算爆炸」
伪装成「极端有效信号」，扭曲 IC、分层回测与机器学习训练。

三原则与对应工具
----------------
===========================================================  =========================================  ======================================
原则                                                        判断依据                                   本库工具
===========================================================  =========================================  ======================================
① 除以 0 ⇒ ±inf                                             分母为 0（**不能从 inf 反推**）           计算层：:func:`mask_small_denominator`；默认路径：NaN
② 极小分母 ⇒ 巨大**有限**值                                 分母 ``|d| <= eps``（值有限）              同上；可见性：:func:`count_extremes` 的 ``huge_finite``
③ 分子溢出 ⇒ ±inf                                           分子极大、**非**除零                       显式保留尾部：:func:`bound_inf`
===========================================================  =========================================  ======================================

为什么 ③ 必须显式：**单看 inf 无法区分 ① 与 ③**，而二者的正确处理相反 —— ① 要屏蔽、
③ 可保留。所以默认一律按 ① 处理（保守），只在你能确认来源时才调用 :func:`bound_inf`。

⚠️ 因子层不做分母检查（改动论文原式会与 golden/差分/平台算例不可比）。
已知会因 ``rank`` 取到 0 而除零的因子：``alpha42 / alpha57 / alpha72 / alpha93``（另有若干间接路径）。
在意 ② 的读者可以：先用 :func:`count_extremes` 的 ``huge_finite`` 看规模，
再用 :func:`mask_small_denominator` 对自己重建的分母做掩码。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["bound_inf", "count_extremes", "mask_small_denominator"]


def count_extremes(frame: pd.DataFrame, *, huge: float = 1e12) -> dict[str, int]:
    """统计极端值/缺失数量（**诊断用**，不修改数据）。

    返回 ``{"pos_inf", "neg_inf", "nan", "huge_finite", "cells"}``：

    * ``pos_inf`` / ``neg_inf``：原则 ① 或 ③ 的候选（来源需查分母才能定性）；
    * ``huge_finite``：**绝对值超过 ``huge`` 的有限值** —— 原则 ② 的信号
      （极小分母导致的巨大有限值；默认路径不会改动它，所以必须让它**可见**）；
    * ``nan``：缺失。

    ``huge`` 需按因子量纲自定（默认 1e12 只适用于 O(1) 量级的因子）。
    """
    values = frame.to_numpy(dtype=float)
    finite = np.isfinite(values)
    return {
        "pos_inf": int(np.isposinf(values).sum()),
        "neg_inf": int(np.isneginf(values).sum()),
        "nan": int(np.isnan(values).sum()),
        "huge_finite": int((finite & (np.abs(values) > huge)).sum()),
        "cells": int(values.size),
    }


def mask_small_denominator(
    numer: pd.DataFrame, denom: pd.DataFrame, *, eps: float = 1e-12
) -> pd.DataFrame:
    """原则 ① ②：分母绝对值 ``<= eps`` 时结果置 NaN（**计算层**的正确做法）。

    比「事后把 inf 变 NaN」更准：**除零与溢出无法从 inf 本身区分**，但分母是可查的。
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
    """原则 ③：把 ±inf 替换为同一截面最大/最小**有限**值（保留尾部信息）。

    **前提**：你已确认这些 inf 来自**分子溢出**而不是**除零**。无法确认时请保持默认
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
