"""alpha101v.factors — 因子层（M2：4 个试点因子）。

转写纪律（设计文档 §4.5 clean-room）
------------------------------------
* 每个因子的公式**逐字来自论文**（arXiv:1601.00991v3，Appendix A），
  出处记在 docstring 与 `registry` 元信息的 ``paper_ref`` 里；公式原文见
  `docs/paper_formulas.md` §5。
* 本文件**不参考任何 GPL 许可实现的代码**；被分析的那份 GPL 仓库目录从未被打开
  （`tests/test_provenance.py` 用机械扫描守住这条纪律——它刚刚就拦下了本文件草稿里
  顺手写下的仓库名，说明守卫有效）。

契约（与设计文档 §7.5 的自动装配配合）
-------------------------------------
* 因子是**纯函数**：形参名 = 面板字段名（`close` / `Open` / `high` / `low` /
  `volume` / `vwap` / `returns` / `cap` / `ind`），因此 `registry.run_factor`
  可用 `inspect.signature` 按名字装配，无需映射表。
* 入参同 (index, columns) 契约；**绝不原地修改入参**（先校验，再计算）。
* 未定义/数据不足 → `NaN`（不做 `fillna(0)`，见设计文档 §3.3 缺陷 7）。

试点覆盖（设计文档 §7.7 的 5 个）
--------------------------------
``alpha101``（纯算术，可手算）/ ``alpha4``（截面 rank → 时序 ts_rank）/
``alpha5``（**依赖逐元素 `abs`**，是 `elemwise` 层的首个消费者）/
``alpha41``（幂运算 + vwap 单位口径）/
``alpha56``（**vnpy 唯一因缺失 `cap` 未实现的因子**）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from .elemwise import abs_
from .operators import (
    _as_frame,
    _check_numeric,
    _check_unique_axes,
    rank,
    ts_rank,
    ts_sum,
)

__all__ = ["PILOT_FACTORS", "alpha4", "alpha41", "alpha5", "alpha56", "alpha101"]


def _panels(**named: object) -> dict[str, pd.DataFrame]:
    """校验一批面板：数值、轴唯一、且彼此同 (index, columns) 契约。

    因子里的原始算术（`close - Open`）不做对齐检查，若两块面板轴不同，pandas 会
    **静默外连接并产出 NaN**。因此因子层必须显式校验，而不是依赖运算不出错。
    """
    frames: dict[str, pd.DataFrame] = {}
    reference: tuple[str, pd.DataFrame] | None = None
    for name, obj in named.items():
        frame = _as_frame(obj, name)
        _check_numeric(frame, name)
        _check_unique_axes(frame, name)
        if reference is None:
            reference = (name, frame)
        else:
            ref_name, ref = reference
            if not frame.index.equals(ref.index) or not frame.columns.equals(ref.columns):
                raise ValueError(
                    f"因子入参必须共享同一 (index, columns) 契约：{name!r} 与 {ref_name!r} 不一致"
                )
        frames[name] = frame
    return frames


def alpha101(close: pd.DataFrame, Open: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame) -> pd.DataFrame:
    """**Alpha#101**（论文逐字）：``((close - open) / ((high - low) + .001))``。

    出处：arXiv:1601.00991v3, Appendix A「Formulaic Expressions for Alphas」，`Alpha#101`。

    ⚠️ 口径提示：`0.001` 是**加性**常数，其相对大小取决于价格量纲
    （论文面向美股价格水平；A 股人民币价位不同 ⇒ 该项的相对影响不同）。
    因此本因子**不是**尺度不变的——这属于论文规范本身，须在 `docs/deviations.md` 登记。
    当 `high == low` 时结果是有限值（除以 `0.001`），不会产生 ±inf。
    """
    p = _panels(close=close, Open=Open, high=high, low=low)
    return (p["close"] - p["Open"]) / ((p["high"] - p["low"]) + 0.001)


def alpha4(low: pd.DataFrame) -> pd.DataFrame:
    """**Alpha#4**（论文逐字）：``(-1 * Ts_Rank(rank(low), 9))``。

    出处：同上，`Alpha#4`。

    结构：先**每日截面** rank（`rank`，pct 口径 (0,1]），再对每只股票做 **9 日时序** rank
    （`ts_rank`，本库默认 pct 口径 ⇒ 名次/9），最后取负。
    口径影响：`ts_rank` 的 pct 与序号口径在此只差全局常数 1/9，**截面排序与 IC 不变**
    （见 `docs/paper_formulas.md` §6.1）。
    """
    p = _panels(low=low)
    return -1.0 * ts_rank(rank(p["low"]), 9)


def alpha5(close: pd.DataFrame, Open: pd.DataFrame, vwap: pd.DataFrame) -> pd.DataFrame:
    """**Alpha#5**（论文逐字）：``(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))``。

    出处：arXiv:1601.00991v3, Appendix A「Formulaic Expressions for Alphas」，`Alpha#5`。

    结构：10 日均量价（`sum(vwap,10)/10`）离差取**截面 rank** ×
    「收盘对 vwap 离差」的**截面 rank 的绝对值**再取负——典型「量价背离」型因子。
    本因子是 **`elemwise.abs_` 的首个消费者**（论文里 `abs` 属 Functions 而非 Operators）。
    单位提示：两处都只依赖**同量纲价格之差**，因此对价格整体缩放不变（已在测试中断言）。
    """
    p = _panels(close=close, Open=Open, vwap=vwap)
    mean_vwap = ts_sum(p["vwap"], 10) / 10.0
    return rank(p["Open"] - mean_vwap) * (-1.0 * abs_(rank(p["close"] - p["vwap"])))


def alpha41(high: pd.DataFrame, low: pd.DataFrame, vwap: pd.DataFrame) -> pd.DataFrame:
    """**Alpha#41**（论文逐字）：``(((high * low)^0.5) - vwap)``。

    出处：同上，`Alpha#41`。论文写 `^0.5`（非 `SignedPower`），故按字面幂实现。
    单位提示：`vwap` 必须与价格同量纲（本库面板契约：`vwap = amount / (volume * 100)`，元/股）。
    """
    p = _panels(high=high, low=low, vwap=vwap)
    return (p["high"] * p["low"]) ** 0.5 - p["vwap"]


def alpha56(returns: pd.DataFrame, cap: pd.DataFrame) -> pd.DataFrame:
    """**Alpha#56**（论文逐字）：``(0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))``。

    出处：同上，`Alpha#56`。**这是 vnpy（MIT 参照实现）唯一因缺少 `cap` 字段而未实现的因子**
    （设计文档 §4.3.1），因此它只能靠「论文规范对照 + 不变量」验证，**无法在 M4 做差分**。

    结构：嵌套时序求和 `Σ_{10} r / Σ_3(Σ_2 r)` 后取截面 rank，再乘 `rank(returns · cap)`，最后取负。
    单位提示：`rank` 对**正数缩放不变**，因此 `cap` 用万元还是元、用总市值还是流通市值，
    **不改变本因子的截面排序**（这是 `rank` 的性质，已在测试中断言）；但它**会**影响
    与其他因子复合后的量纲，故面板契约仍要求显式声明单位。
    """
    p = _panels(returns=returns, cap=cap)
    short = ts_sum(p["returns"], 2)
    denom = ts_sum(short, 3)
    numer = ts_sum(p["returns"], 10)
    return -1.0 * (rank(numer / denom) * rank(p["returns"] * p["cap"]))


@dataclass(frozen=True)
class FactorSpec:
    """试点因子的注册定义（论文出处 + 可判定状态）。"""

    name: str
    func: Callable[..., pd.DataFrame]
    paper_ref: str
    status: str
    notes: str


#: M2 试点因子清单。`status` 一律为 ``partial``：`verified` 需六条门槛全满足（设计文档 §6.8），
#: 而 L2 自动对照工具（M3）、L3 差分（M4，且 alpha56 无法差分）、L5 golden 快照（M5）均未完成。
PILOT_FACTORS: tuple[FactorSpec, ...] = (
    FactorSpec(
        name="alpha101",
        func=alpha101,
        paper_ref="Appendix A, Alpha#101（逐字：((close - open) / ((high - low) + .001))）",
        status="partial",
        notes="纯算术，可手算核对；含加性常数 0.001 ⇒ 非尺度不变（论文规范本身，见 deviations）",
    ),
    FactorSpec(
        name="alpha4",
        func=alpha4,
        paper_ref="Appendix A, Alpha#4（逐字：(-1 * Ts_Rank(rank(low), 9))）",
        status="partial",
        notes="截面 rank → 9 日 ts_rank；pct/序号口径差异只影响全局常数，不影响截面排序",
    ),
    FactorSpec(
        name="alpha5",
        func=alpha5,
        paper_ref=(
            "Appendix A, Alpha#5（逐字："
            "(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))）"
        ),
        status="partial",
        notes="elemwise.abs_ 的首个消费者；只依赖同量纲价格之差 ⇒ 对价格缩放不变",
    ),
    FactorSpec(
        name="alpha41",
        func=alpha41,
        paper_ref="Appendix A, Alpha#41（逐字：(((high * low)^0.5) - vwap)）",
        status="partial",
        notes="纯截面算术；强依赖 vwap 单位口径（amount/(volume*100)）",
    ),
    FactorSpec(
        name="alpha56",
        func=alpha56,
        paper_ref=(
            "Appendix A, Alpha#56（逐字："
            "(0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))）"
        ),
        status="partial",
        notes="vnpy 因缺 cap 未实现 ⇒ 无第三方可差分，只能靠规范对照 + 不变量（设计文档 §4.3.1）",
    ),
)


def _register_pilots() -> None:
    """把试点因子登记进 `registry`（幂等：重复导入不会报错）。"""
    from . import registry

    for spec in PILOT_FACTORS:
        if spec.name in registry.REGISTRY:
            continue
        registry.register(
            spec.name,
            spec.func,
            paper_ref=spec.paper_ref,
            status=spec.status,
            notes=spec.notes,
        )


_register_pilots()
