"""申万行业 as-of 成员 → **PIT 行业标签面板**（可选适配层）。

数据源（设计文档 §10.2 指定）
----------------------------
``/home/yinxiuqu/quantming/data/sw_industry/members.parquet``（覆盖约 98.4%）::

    index_code  level  src     con_code  in_date     out_date  is_new  iface
    801010.SI   L1     SW2021  000019    2021-12-13  NaT       Y       index_member

``out_date`` 为 ``NaT`` 表示**仍在成分内**。另有 ``classify.parquet`` 提供
``index_code → industry_name``（中文名），本模块可选地用它把标签换成人可读的名称。

**为什么必须是 as-of**：原始 GPL 仓库用的是「固定 2017-01 快照」（设计文档 §3.3 缺陷 5），
那等于把未来信息灌进历史因子。本模块按 ``(交易日, 股票)`` 取 **``in_date <= t`` 且
(``out_date`` 为空或 ``> t``)** 的最近一次成分记录，构造 ``ind`` 面板——这正是
:func:`alpha101v.neutralize.ind_neutralize` 支持的逐日 DataFrame 形态。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

__all__ = ["coverage_of", "load_sw_industry", "load_sw_industry_names"]

DEFAULT_MEMBERS: str | None = None     # 不设默认绝对路径（别人机器上必崩）；用参数或环境变量
DEFAULT_CLASSIFY: str | None = None    # 同上：由调用方显式传入，或设置 ALPHA101V_SW_CLASSIFY


def _require_path(value: str | Path | None, env: str, what: str) -> Path:
    """把「没给路径」变成明确错误，而不是在别人机器上抛出难以理解的 FileNotFoundError。"""
    import os

    resolved = value or os.environ.get(env)
    if not resolved:
        raise FileNotFoundError(
            f"{what} 未指定：请显式传参，或设置环境变量 {env}。"
            "（本库不再内置作者本机路径 —— 那种默认值只在作者机器上「恰好能用」）"
        )
    return Path(resolved)


def load_sw_industry_names(classify_path: str | Path | None = DEFAULT_CLASSIFY) -> dict[str, str]:
    """``index_code → industry_name``（中文名，便于人工核对与文档展示）。"""
    classify = pd.read_parquet(_require_path(classify_path, "ALPHA101V_SW_CLASSIFY", "申万分类文件"))
    required = {"index_code", "industry_name"}
    missing = required - set(classify.columns)
    if missing:
        raise KeyError(f"classify.parquet 缺少列 {sorted(missing)}；实际 {sorted(classify.columns)}")
    return dict(zip(classify["index_code"], classify["industry_name"], strict=False))


def load_sw_industry(
    dates: Iterable[pd.Timestamp],
    codes: Iterable[str],
    *,
    members_path: str | Path = DEFAULT_MEMBERS,
    classify_path: str | Path | None = DEFAULT_CLASSIFY,
    level: str = "L1",
    src: str = "SW2021",
    use_names: bool = True,
) -> pd.DataFrame:
    """构造 PIT 行业标签面板（``index``=交易日, ``columns``=股票代码）。

    规则（显式，全部可测）：

    1. 只取 ``level`` / ``src`` 匹配的成分记录；
    2. 对每个 (交易日, 股票)，取 **``in_date <= 交易日``** 的最近一条（``merge_asof`` backward）；
    3. 若该条的 ``out_date`` 非空且 ``<= 交易日`` ⇒ 已调出，标签置 ``NaN``；
    4. 同一 (交易日, 股票) 命中多条（数据里同一 ``in_date`` 多行业）时，按
       ``index_code`` 升序取第一条 —— **确定性的显式策略**，不随机；
    5. 没有任何成分记录的格子为 ``NaN``（覆盖率缺口，不下沉填充——行业标签无法插值）。
    """
    dates = pd.DatetimeIndex(sorted(pd.DatetimeIndex(dates).unique()))
    codes = [str(code) for code in codes]
    if len(dates) == 0 or not codes:
        raise ValueError("dates 与 codes 都不能为空")

    members = pd.read_parquet(members_path)
    required = {"index_code", "level", "src", "con_code", "in_date", "out_date"}
    missing = required - set(members.columns)
    if missing:
        raise KeyError(f"members.parquet 缺少列 {sorted(missing)}；实际 {sorted(members.columns)}")

    members = members[(members["level"] == level) & (members["src"] == src)].copy()
    members = members[members["con_code"].astype(str).isin(codes)]
    members["con_code"] = members["con_code"].astype(str)
    members["in_date"] = pd.to_datetime(members["in_date"])
    members["out_date"] = pd.to_datetime(members["out_date"])

    label_column = "index_code"
    if use_names and classify_path is not None and Path(classify_path).exists():
        names = load_sw_industry_names(classify_path)
        members["label"] = members["index_code"].map(names).fillna(members["index_code"])
        label_column = "label"
    else:
        members["label"] = members["index_code"]

    # merge_asof 要求**按 on-key 全局有序**（by 分组内自然随之有序）：
    # 左表按 (date, code) 排、右表按 (in_date, con_code) 排。
    members = members.sort_values(["in_date", "con_code", "index_code"], ignore_index=True)

    grid = pd.MultiIndex.from_product([dates, codes], names=["date", "code"]).to_frame(index=False)
    grid = grid.sort_values(["date", "code"], ignore_index=True)

    merged = pd.merge_asof(
        grid,
        members[["con_code", "in_date", "out_date", label_column]].rename(
            columns={"con_code": "code"}
        ),
        left_on="date",
        right_on="in_date",
        by="code",
        direction="backward",
    )

    active = merged["out_date"].isna() | (merged["out_date"] > merged["date"])
    merged = merged[active]
    merged = merged.drop_duplicates(["date", "code"], keep="first")

    labels = merged.pivot(index="date", columns="code", values=label_column)
    labels = labels.reindex(index=dates, columns=codes)
    labels.index.name = None
    labels.columns.name = None
    coverage = float(labels.notna().to_numpy().mean())
    if coverage == 0.0:
        raise ValueError(
            f"行业覆盖率 0：level={level} src={src} 下没有任何 (date, code) 命中；"
            "请检查成分表与股票代码格式（如 000001 vs 000001.SZ）"
        )
    labels.attrs["coverage"] = coverage
    labels.attrs["level"] = level
    labels.attrs["src"] = src
    return labels


def coverage_of(labels: pd.DataFrame) -> float:
    """辅助：行业标签覆盖率（``0~1``）。"""
    values = labels.to_numpy()
    return float(np.mean(~pd.isna(values)))
