"""alpha101v.registry — 因子注册表与按形参名自动装配（§7.5）。

★ 关键技巧（设计文档 §7.5）：101 个因子有 71 种形参组合，但**形参名只有 9 种**
（``close`` / ``Open`` / ``high`` / ``low`` / ``volume`` / ``vwap`` / ``returns`` /
``cap`` / ``ind``），因此批量调用不需要 101 条映射表，用 ``inspect.signature``
按名字自动装配即可。

⚠️ 配套前提（§7.5）：调用前对面板做**深拷贝**，防止因子内部原地改写入参污染调用方
面板（原始实现 ``alpha1`` 的真实事故，设计文档 §3.3 缺陷 2）。
:func:`run_factor` 默认 ``copy_inputs=True`` 落实该前提。

**当前注册表内容**：M2 的 4 个试点因子（``alpha101`` / ``alpha4`` / ``alpha41`` / ``alpha56``），
由 ``alpha101v.factors`` 在导入时自动登记，状态一律 ``partial``（``verified`` 需六条门槛，见设计文档 §6.8）。
全量 101 个是 M3 的工作。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "REGISTRY",
    "STATUS_VALUES",
    "FactorMeta",
    "field_names",
    "register",
    "run_factor",
    "status_report",
]

#: 因子可判定状态（设计文档 §6.8）：verified 必须六条门槛全满足。
STATUS_VALUES: tuple[str, ...] = ("verified", "partial", "ambiguous", "pending")


@dataclass(frozen=True)
class FactorMeta:
    """因子元信息：函数、论文出处、可判定状态。"""

    name: str
    func: Callable[..., pd.DataFrame]
    paper_ref: str = ""
    status: str = "pending"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALUES:
            raise ValueError(f"status 必须是 {STATUS_VALUES} 之一，收到 {self.status!r}")
        if not callable(self.func):
            raise TypeError(f"func 必须可调用，收到 {type(self.func).__name__}")

    @property
    def params(self) -> tuple[str, ...]:
        """因子函数按名字声明的面板字段（§7.5 自动装配的依据）。"""
        return field_names(self.func)


#: 因子注册表：``{因子名: FactorMeta}``。M2/M3 填充；本轮保持为空（不得假装有因子）。
REGISTRY: dict[str, FactorMeta] = {}


def field_names(func: Callable[..., pd.DataFrame]) -> tuple[str, ...]:
    """返回函数签名里的形参名（即它需要的面板字段）。"""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError) as exc:  # pragma: no cover - 不可内省的可调用对象
        raise TypeError(f"无法内省 {func!r} 的签名：{exc}") from exc
    names: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            raise TypeError(f"因子 {func!r} 不得使用 *args / **kwargs（无法按名装配面板字段）")
        names.append(parameter.name)
    return tuple(names)


def register(
    name: str,
    func: Callable[..., pd.DataFrame],
    *,
    paper_ref: str = "",
    status: str = "pending",
    notes: str = "",
    overwrite: bool = False,
) -> FactorMeta:
    """注册因子并返回其 :class:`FactorMeta`。"""
    if not name:
        raise ValueError("因子名不能为空")
    if name in REGISTRY and not overwrite:
        raise ValueError(f"因子 {name!r} 已注册（需要覆盖请显式 overwrite=True）")
    meta = FactorMeta(name=name, func=func, paper_ref=paper_ref, status=status, notes=notes)
    meta.params  # 触发签名校验（含 *args/**kwargs 拒绝）
    REGISTRY[name] = meta
    return meta


def run_factor(
    name: str,
    panel: Mapping[str, pd.DataFrame],
    *,
    copy_inputs: bool = True,
) -> pd.DataFrame:
    """按 :data:`REGISTRY` 取因子，并从面板按形参名自动装配后调用（§7.5）。

    ``copy_inputs=True``（默认）对每个入参做深拷贝，确保因子的任何原地写入都
    污染不到调用方面板（设计文档 §6.5「输入不可变性」在因子层的落点）。
    """
    meta = REGISTRY.get(name)
    if meta is None:
        available = ", ".join(sorted(REGISTRY)) or "（空）"
        raise KeyError(f"未注册的因子 {name!r}；当前注册表：{available}")

    kwargs: dict[str, pd.DataFrame] = {}
    for field in meta.params:
        if field not in panel:
            raise KeyError(f"因子 {name!r} 需要面板字段 {field!r}，但面板只有 {sorted(panel)}")
        value = panel[field]
        kwargs[field] = value.copy(deep=True) if copy_inputs and isinstance(value, pd.DataFrame) else value

    return _sanitize(meta.func(**kwargs))


def _sanitize(result: pd.DataFrame) -> pd.DataFrame:
    """输出卫生：±inf 一律降级为 NaN（本库契约：**永不输出 ±inf**）。

    为什么需要它：BRAIN 官方 `rank` 归一化是 `[0,1]` **闭区间** ⇒ 当日排名最低的标的取到 **0.0**，
    于是 `rank(a) / rank(b)` 这类比值型因子（alpha42/57/72/93 等）会**除以 0**。
    BRAIN 自己的 `divide` 文档就写着「dividing by zero raises an error; to avoid it, use
    `divide(x, add(y, 0.0001))`」——即这种除法在平台上同样无定义；本库按契约给 **NaN**
    （「信息不足」），既不输出 inf、也不偷偷加 epsilon 改变数值。
    """
    values = result.to_numpy(dtype=float)
    if np.isfinite(values).all():
        return result
    return pd.DataFrame(
        np.where(np.isfinite(values), values, np.nan), index=result.index, columns=result.columns
    )


def status_report() -> pd.DataFrame:
    """生成 verified/partial/ambiguous/pending 统计表（供 CI 产出 docs/verification.md）。"""
    rows = [
        {
            "factor": meta.name,
            "status": meta.status,
            "fields": ",".join(meta.params),
            "paper_ref": meta.paper_ref,
            "notes": meta.notes,
        }
        for meta in sorted(REGISTRY.values(), key=lambda m: m.name)
    ]
    columns = ["factor", "status", "fields", "paper_ref", "notes"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)
