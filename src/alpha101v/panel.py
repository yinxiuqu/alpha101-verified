"""alpha101v.panel — 面板契约与校验（M0）。

设计依据：设计文档 §7.4「面板契约」。本模块只做**声明与校验**，不做数据采集，
也不做缺失值填充（缺数据应当由调用方在入库前解决，而不是让因子猜测）。

约定（全部显式，禁止隐式单位）
------------------------------
============ ==========================================================
字段          单位 / 口径
============ ==========================================================
close/Open   元，**前复权**（与 returns 口径配对）
high/low     元，前复权
volume       **手**
amount       **元**
vwap         元/股 = ``amount / (volume * 100)``（手+元口径下实测确认）
returns      小数（**不是百分数**），由前复权 close 计算
cap          市值，**万元**（建议 total_mv）
ind          行业分类，**必须 PIT/as-of**，非数值
============ ==========================================================

必查项：① index 单调递增且唯一 ② 各字段共享同一 (index, columns) 契约
③ 数值字段为数值 dtype（``ind`` 除外）④ 不含 ±inf ⑤ 最小历史长度（默认 250 日，
覆盖论文最长窗口）⑥ 字段名在白名单内。

⚠️ **PIT 无法从数据本身判定**：本模块只能检查「形状与单位自洽」，
真正的时点合规要靠设计文档 §6.5 的**时间截断一致性**与**未来扰动**测试。
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

__all__ = [
    "ALL_FIELDS",
    "MIN_HISTORY_DAYS",
    "OPTIONAL_FIELDS",
    "PRICE_FIELDS",
    "REQUIRED_FIELDS",
    "UNITS",
    "PanelContractError",
    "assert_valid_panel",
    "is_non_numeric_field",
    "returns_from_close",
    "validate_panel",
    "vwap_from_amount",
]

#: 9 个字段即 Alpha101 全部所需输入（设计文档 §3.2）。
REQUIRED_FIELDS: tuple[str, ...] = ("close", "Open", "high", "low", "volume", "vwap", "returns")
OPTIONAL_FIELDS: tuple[str, ...] = (
    "amount",
    "cap",
    "ind",
    # 论文 `IndClass.sector/industry/subindustry` 的落地（因子层形参名即这三个键）；
    # A 股映射为申万 L1/L2/L3，见 docs/ambiguities.md A24。
    "ind_sector",
    "ind_industry",
    "ind_subindustry",
)
ALL_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS

#: 价格类字段（缩放/平移不变量测试的对象）。
PRICE_FIELDS: tuple[str, ...] = ("close", "Open", "high", "low", "vwap")

#: 论文最长滚动窗口为 250 日（§7.4 最小历史长度要求）。
MIN_HISTORY_DAYS: int = 250

#: 行业标签字段不是数值，校验时豁免 dtype 检查（含 `ind_sector/ind_industry/ind_subindustry`）。
def is_non_numeric_field(name: str) -> bool:
    """行业标签类字段（`ind` 及各 `ind_<level>`）不是数值，豁免 dtype/inf 检查。"""
    return name == "ind" or name.startswith("ind_")

UNITS: dict[str, str] = {
    "close": "元（前复权）",
    "Open": "元（前复权）",
    "high": "元（前复权）",
    "low": "元（前复权）",
    "volume": "手",
    "amount": "元",
    "vwap": "元/股 = amount / (volume * 100)",
    "returns": "小数（非百分数），由前复权 close 计算",
    "cap": "万元（建议 total_mv）",
    "ind": "行业分类标签（必须 PIT/as-of；非数值）",
    "ind_sector": "行业标签·论文 IndClass.sector（A 股映射申万 L1；非数值，PIT）",
    "ind_industry": "行业标签·论文 IndClass.industry（A 股映射申万 L2；非数值，PIT）",
    "ind_subindustry": "行业标签·论文 IndClass.subindustry（A 股映射申万 L3；非数值，PIT）",
}


class PanelContractError(ValueError):
    """面板违反契约时抛出；``args[0]`` 是全部问题的多行清单。"""


def _check_frame(name: str, frame: object, min_history: int | None) -> list[str]:
    problems: list[str] = []
    if not isinstance(frame, pd.DataFrame):
        return [f"字段 {name!r} 不是 DataFrame（收到 {type(frame).__name__}）"]

    index = frame.index
    if not index.is_monotonic_increasing:
        problems.append(f"字段 {name!r} 的 index 未单调递增（PIT 前提）")
    if not index.is_unique:
        problems.append(f"字段 {name!r} 的 index 有重复值")
    if not isinstance(index, pd.DatetimeIndex):
        problems.append(f"字段 {name!r} 的 index 不是 DatetimeIndex（交易日索引，PIT 校验需要）")
    if not frame.columns.is_unique:
        problems.append(f"字段 {name!r} 的 columns 有重复股票代码")

    if not is_non_numeric_field(name):
        bad = [c for c in frame.columns if not pd.api.types.is_numeric_dtype(frame[c])]
        if bad:
            problems.append(f"字段 {name!r} 含非数值列：{bad[:5]}")

        values = frame.to_numpy(dtype=float) if frame.shape[1] else np.empty((0, 0))
        if np.isinf(values).any():
            n_inf = int(np.isinf(values).sum())
            problems.append(f"字段 {name!r} 含 {n_inf} 个 ±inf（脏数据，须先处理）")

    if min_history is not None and len(frame) < min_history:
        problems.append(
            f"字段 {name!r} 只有 {len(frame)} 行，少于最小历史长度 {min_history} 行"
            "（论文最长窗口 250 日）"
        )
    return problems


def validate_panel(
    fields: Mapping[str, pd.DataFrame],
    *,
    required: tuple[str, ...] = REQUIRED_FIELDS,
    min_history: int | None = MIN_HISTORY_DAYS,
    allow_extra: bool = False,
) -> list[str]:
    """校验面板契约，返回问题清单（**空列表 = 通过**）。

    参数
    ----
    fields : ``{字段名: DataFrame}``，index=交易日、columns=股票代码。
    required : 必须存在的字段，默认 :data:`REQUIRED_FIELDS`。
    min_history : 最小行数；``None`` 表示跳过（小面板测试用）。
    allow_extra : 是否允许白名单（:data:`ALL_FIELDS`）之外的字段名。
    """
    if not isinstance(fields, Mapping):
        return [f"面板必须是 {{字段名: DataFrame}} 映射，收到 {type(fields).__name__}"]

    problems: list[str] = []

    missing = [f for f in required if f not in fields]
    if missing:
        problems.append(f"缺少必需字段：{missing}")
    if not allow_extra:
        unknown = [f for f in fields if f not in ALL_FIELDS]
        if unknown:
            problems.append(f"出现白名单之外、单位未声明的字段：{unknown}（建议 allow_extra=True）")

    reference: tuple[pd.DataFrame, str] | None = None
    for name, frame in fields.items():
        problems.extend(_check_frame(name, frame, min_history))
        if reference is None and isinstance(frame, pd.DataFrame):
            reference = (frame, name)

    if reference is not None:
        ref, ref_name = reference
        for name, frame in fields.items():
            if not isinstance(frame, pd.DataFrame) or name == ref_name:
                continue
            if not frame.index.equals(ref.index):
                problems.append(f"字段 {name!r} 的 index 与 {ref_name!r} 不一致（无法逐元素配对）")
            elif not frame.columns.equals(ref.columns):
                problems.append(f"字段 {name!r} 的 columns 与 {ref_name!r} 不一致（股票集合必须一致）")

    return problems


def assert_valid_panel(
    fields: Mapping[str, pd.DataFrame],
    *,
    required: tuple[str, ...] = REQUIRED_FIELDS,
    min_history: int | None = MIN_HISTORY_DAYS,
    allow_extra: bool = False,
) -> None:
    """同 :func:`validate_panel`，但有错即抛 :class:`PanelContractError`。"""
    problems = validate_panel(
        fields, required=required, min_history=min_history, allow_extra=allow_extra
    )
    if problems:
        raise PanelContractError("面板违反契约：\n- " + "\n- ".join(problems))


def vwap_from_amount(amount: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """``vwap = amount / (volume * 100)``（amount 元、volume 手 ⇒ 乘以 100 换股）。

    volume 为 0 时结果为 NaN（不是 inf）：停牌/零成交的 vwap 无定义。
    """
    if amount.shape != volume.shape or not amount.index.equals(volume.index):
        raise ValueError("amount 与 volume 必须同形同索引")
    shares = volume.where(volume != 0) * 100.0
    return amount / shares


def returns_from_close(close: pd.DataFrame, *, fill_first: bool = False) -> pd.DataFrame:
    """由（前复权）close 计算简单收益率：``close_t / close_{t-1} - 1``。

    显式策略
    --------
    * ``fill_first=False``（默认）时首日为 NaN —— 不填充，避免把「未知」伪装成 0
      （对齐设计文档 §3.3 缺陷 7 的批评：``fillna(0)`` 让缺失与真值不可区分）。
    * **非正价格（<= 0）视为脏数据 → 该格为 NaN**，绝不产生 ±inf；
      停牌（价格不变）自然是 0 收益。
    * ``fill_method=None``：不做前向填充 —— 用 ffill 补价格再算收益会**伪造**信息。
    """
    valid = close.where(close > 0)
    rets = valid.pct_change(fill_method=None)
    if fill_first:
        rets = rets.fillna(0.0)
    return rets
