#!/usr/bin/env python
"""L6 辅助统计（设计文档 §6.7）—— **不是门槛，永远不能用来证明实现正确**。

⚠️ 三条必须写在最前面的纪律（§6.7 原文精神）：

1. **统计显著 ≠ 实现正确，统计不显著 ≠ 实现错误**。本工具的输出**不参与**
   `verified/partial` 判定，也不得用来调整任何因子的状态；
2. 论文的两个统计断言（**平均持仓 0.6~6.4 天**、**两两相关 15.9%**）基于**美股**，
   本项目跑的是 **A 股**（本地 MongoDB）⇒ 数字不可直接对照，**只能作弱参考**；
3. 样本量（股票数 × 交易日数）决定了统计功效，报告里必须显式声明，不许当成结论。

它算四件事：

* **横截面 IC**（Spearman）：horizon = 1/2/3/5/10 日，逐日截面相关 → 均值/标准差/IR/t 值/正比例；
* **IC 衰减形状**：若「平均持仓 0.6~6.4 天」成立，IC 应在 1~5 日区间最强；
* **暴露检查**：与 `log(市值)` 的截面秩相关、按申万 L1 的行业解释力（ANOVA 的 R² 开方）；
* **两两相关**：101 个因子的日度 PnL 序列两两相关的均值（对照论文 15.9% 的「弱参考」用法）。

用法::

    python tools/l6_statistics.py --n-codes 120 --start 2023-01-03 --end 2024-06-28
    python tools/l6_statistics.py --factors alpha4,alpha5,alpha101        # 只跑少数因子（快速核查）
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

import numpy as np
import pandas as pd
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

HORIZONS = (1, 2, 3, 5, 10)
OUT_DIR = ROOT / "reports"


# ---------------------------------------------------------------------------
# 统计原语（被 tests/test_l6_statistics.py 用合成面板做正确性验证）
# ---------------------------------------------------------------------------


MIN_STOCKS = 5


def spearman_ic(factor: pd.DataFrame, forward_return: pd.DataFrame) -> pd.Series:
    """逐日截面 Spearman IC（当日因子值 vs 未来 h 日收益）——**全向量化**。

    实现：Spearman = 秩上的 Pearson，故先逐日取秩（`rank(axis=1)`，NaN 保持 NaN），
    再用 Pearson 的闭式一次算完所有交易日：

    ``rho_t = (n·Σxy − Σx·Σy) / sqrt((n·Σx² − (Σx)²)(n·Σy² − (Σy)²))``

    为什么不用 `scipy.stats.spearmanr` 逐日循环：101 个因子 × 5 个 horizon × 数百交易日
    ⇒ 十几万次调用，实测把整个工具拖到 25 s/因子（整轮几十分钟）。
    少于 `MIN_STOCKS` 只有效股票的交易日不给 IC（不制造假信号）。
    """
    common = factor.notna() & forward_return.notna()
    x = factor.where(common).rank(axis=1, method="average")
    y = forward_return.where(common).rank(axis=1, method="average")
    n = common.sum(axis=1).astype(float)
    sx, sy = x.sum(axis=1), y.sum(axis=1)
    sxy, sxx, syy = (x * y).sum(axis=1), (x * x).sum(axis=1), (y * y).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        numerator = n * sxy - sx * sy
        denominator = np.sqrt((n * sxx - sx ** 2) * (n * syy - sy ** 2))
        rho = numerator / denominator
    rho = rho.where(n >= MIN_STOCKS)
    return rho


def ic_summary(ic: pd.Series) -> dict[str, float]:
    """IC 的均值/标准差/IR/t 值/正比例/有效天数。"""
    values = ic.dropna().to_numpy(dtype=float)
    if values.size < 2:
        return {"days": float(values.size), "mean": np.nan, "std": np.nan, "ir": np.nan,
                "t": np.nan, "positive": np.nan}
    mean, std = float(values.mean()), float(values.std(ddof=1))
    return {
        "days": float(values.size),
        "mean": mean,
        "std": std,
        "ir": mean / std if std else np.nan,
        "t": mean / std * np.sqrt(values.size) if std else np.nan,
        "positive": float((values > 0).mean()),
    }


def forward_returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """未来 h 日收益（用 hfq 价格；最后一 h 行为 NaN，天然不含前视）。"""
    return close.shift(-horizon) / close - 1.0


def cross_sectional_rank_corr(factor: pd.DataFrame, other: pd.DataFrame) -> pd.Series:
    """逐日截面 Spearman 相关（用于暴露检查，例如与 log 市值）。"""
    return spearman_ic(factor, other)


def industry_exposure(factor: pd.DataFrame, industry: pd.DataFrame) -> pd.Series:
    """行业暴露：逐日对因子做一元方差分析，返回 ``sqrt(R²) ∈ [0,1]``（**向量化**）。

    行业标签可以是 `DataFrame`（PIT）或 `Series`（静态快照，按股票名广播）。
    """
    labels = industry
    if isinstance(labels, pd.Series):
        labels = pd.DataFrame(
            np.tile(labels.to_numpy(dtype=object), (len(factor.index), 1)),
            index=factor.index, columns=factor.columns,
        )
    elif not labels.index.equals(factor.index):
        labels = labels.reindex(index=factor.index, columns=factor.columns)

    long = pd.DataFrame({
        "value": factor.stack(future_stack=True),
        "group": labels.stack(future_stack=True),
    }).dropna()
    if long.empty:
        return pd.Series(np.nan, index=factor.index)
    long.index = long.index.set_names(["day", "stock"])
    valid_days = long.groupby(level="day")["group"].nunique()
    enough = long.groupby(level="day")["value"].size() >= 10
    keep_days = valid_days[(valid_days >= 2)].index.intersection(enough[enough].index)
    long = long[long.index.get_level_values("day").isin(keep_days)]

    grand = long.groupby(level="day")["value"].transform("mean")
    ss_total = long.assign(diff=long["value"] - grand).groupby(level="day")["diff"].apply(
        lambda s: float((s ** 2).sum())
    )
    grouped = long.groupby([long.index.get_level_values("day"), "group"])["value"]
    sizes, means = grouped.size(), grouped.mean()
    day_index = means.index.get_level_values(0)
    grand_mean = long.groupby(level="day")["value"].mean()
    ss_between = (
        (sizes * (means - grand_mean.reindex(day_index).to_numpy()) ** 2)
        .groupby(level=0)
        .sum()
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = (ss_between / ss_total).reindex(factor.index)
    return np.sqrt(r2.where(r2 >= 0))


def factor_pnl(factor: pd.DataFrame, forward_return: pd.DataFrame) -> pd.Series:
    """因子的日度 PnL 代理：当日因子**截面标准化**后与次日收益的内积/只数（BRAIN 常见口径，向量化）。"""
    mean = factor.mean(axis=1)
    std = factor.std(axis=1, ddof=0)
    factor_z = factor.sub(mean, axis=0).div(std.replace(0.0, np.nan), axis=0)
    product = factor_z * forward_return
    return product.sum(axis=1, min_count=1) / factor_z.notna().sum(axis=1).replace(0, np.nan)


def pairwise_pnl_correlations(pnls: dict[str, pd.Series]) -> pd.DataFrame:
    """所有因子对之间的 PnL 相关（长表：factor_a / factor_b / corr），供复核与画图。"""
    names = sorted(pnls)
    frame = pd.DataFrame({name: pnls[name] for name in names}).dropna(how="all")
    rows: list[dict[str, object]] = []
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            pair = frame[[left, right]].dropna()
            if pair.shape[0] < 30:
                continue
            value = pair[left].corr(pair[right])
            if np.isfinite(value):
                rows.append({"factor_a": left, "factor_b": right, "corr": float(value), "days": int(pair.shape[0])})
    return pd.DataFrame(rows)


def average_pairwise_pnl_correlation(pnls: dict[str, pd.Series]) -> tuple[float, int]:
    """所有因子对之间的 PnL 相关均值（对照论文 15.9% 的弱参考）。"""
    table = pairwise_pnl_correlations(pnls)
    return (float(table["corr"].mean()) if not table.empty else np.nan), int(table.shape[0])


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def load_inputs(n_codes: int, start: str, end: str) -> tuple[dict, list[str]]:
    """真实 A 股面板 + 申万 L1 行业（PIT）。"""
    import pymongo  # noqa: PLC0415

    from alpha101v.adapters.industry import load_sw_industry  # noqa: PLC0415
    from alpha101v.adapters.mongo import load_panel  # noqa: PLC0415

    client = pymongo.MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    try:
        pool = sorted({
            str(doc["code"]) for doc in client["quantaxis"]["stock_daily_basic"].find({"date": end}, {"code": 1})
        })
    finally:
        client.close()
    if not pool:
        raise SystemExit(f"{end} 在 stock_daily_basic 里没有数据")
    rng = np.random.default_rng(20261011)
    codes = sorted(rng.choice(pool, size=min(n_codes, len(pool)), replace=False).tolist())
    panel = load_panel(codes, start, end, adjust="hfq")
    index, columns = panel["close"].index, panel["close"].columns
    panel["ind_sector"] = load_sw_industry(index, columns, level="L1")
    panel["ind_industry"] = load_sw_industry(index, columns, level="L2")
    panel["ind_subindustry"] = load_sw_industry(index, columns, level="L3")
    return panel, codes


def main() -> int:
    parser = argparse.ArgumentParser(description="L6 辅助统计（不是门槛）")
    parser.add_argument("--n-codes", type=int, default=120)
    parser.add_argument("--start", default="2023-01-03")
    parser.add_argument("--end", default="2024-06-28")
    parser.add_argument("--factors", help="只跑这些因子（逗号分隔）；默认全部 101 个")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    from alpha101v import registry  # noqa: PLC0415

    panel, codes = load_inputs(args.n_codes, args.start, args.end)
    index, columns = panel["close"].index, panel["close"].columns
    names = (
        [f"alpha{n}" for n in (int(x) for x in args.factors.split(","))]
        if args.factors
        else sorted(registry.REGISTRY, key=lambda s: int(s[5:]))
    )
    print(f"面板 {panel['close'].shape}（{len(codes)} 只 × {len(index)} 交易日）；因子 {len(names)} 个")
    print("⚠️ L6 不是门槛：统计显著 ≠ 实现正确；A 股 ≠ 美股，论文数字只作弱参考")

    close = panel["close"]
    forward = {h: forward_returns(close, h) for h in HORIZONS}
    log_cap = np.log(panel["cap"].where(panel["cap"] > 0))
    industry = panel["ind_sector"]

    rows: list[dict] = []
    pnls: dict[str, pd.Series] = {}
    for position, name in enumerate(names, start=1):
        if position % 10 == 1 or position == len(names):
            print(f"  [{position}/{len(names)}] {name} ...", flush=True)
        factor = registry.run_factor(name, panel)
        record: dict[str, object] = {"factor": name}
        for horizon in HORIZONS:
            summary = ic_summary(spearman_ic(factor, forward[horizon]))
            for key, value in summary.items():
                record[f"ic{horizon}_{key}"] = value
        cap_exposure = cross_sectional_rank_corr(factor, log_cap).dropna()
        industry_exp = industry_exposure(factor, industry).dropna()
        record["cap_exposure_mean"] = float(cap_exposure.mean()) if cap_exposure.size else np.nan
        record["industry_exposure_mean"] = float(industry_exp.mean()) if industry_exp.size else np.nan
        pnl = factor_pnl(factor, forward[1])
        pnls[name] = pnl
        record["pnl_sharpe"] = (
            float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(252)) if pnl.std(ddof=1) else np.nan
        )
        rows.append(record)

    table = pd.DataFrame(rows)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    # 文件名保持稳定（便于在文档里引用），日期写进报告正文
    csv_path = out_dir / "l6_ic.csv"
    table.to_csv(csv_path, index=False)

    pairwise = pairwise_pnl_correlations(pnls)
    pairwise_path = out_dir / "l6_pairwise_corr.csv"
    pairwise.to_csv(pairwise_path, index=False)
    mean_pairwise = float(pairwise["corr"].mean()) if not pairwise.empty else np.nan
    pairs = int(pairwise.shape[0])
    mean_ic_by_horizon = {h: float(table[f"ic{h}_mean"].mean()) for h in HORIZONS}
    best_horizon = max(mean_ic_by_horizon, key=lambda h: abs(mean_ic_by_horizon[h]))
    report_path = out_dir / "l6_summary.md"
    lines = [
        f"# L6 辅助统计报告（{stamp}）",
        "",
        f"* 面板：**{len(codes)} 只 A 股 × {len(index)} 交易日**（本地 MongoDB，hfq 复权，申万 L1 行业 PIT）",
        f"* 因子：{len(names)} 个；IC 口径：逐日横截面 Spearman（至少 5 只股票才算）",
        "",
        "> ⚠️ **L6 不是门槛**：统计显著 ≠ 实现正确，统计不显著 ≠ 实现错误（设计文档 §6.7）。",
        "> 论文的两个断言（平均持仓 0.6~6.4 天、两两相关 15.9%）基于**美股**，本报告是 **A 股** ⇒ 只作弱参考。",
        "",
        "## IC 均值随 horizon 的衰减形状",
        "",
        "| horizon（交易日） | " + " | ".join(str(h) for h in HORIZONS) + " |",
        "|---|" + "---|" * len(HORIZONS),
        "| 平均 IC | " + " | ".join(f"{mean_ic_by_horizon[h]:+.4f}" for h in HORIZONS) + " |",
        "",
        f"绝对值的最大处出现在 **h = {best_horizon}**（|IC| = {abs(mean_ic_by_horizon[best_horizon]):.4f}）"
        "——论文称平均持仓 0.6~6.4 天，若成立则短周期应更强；此处只是**观察**，不作结论。",
        "",
        "## 两两相关（对照论文 15.9%，弱参考）",
        "",
        f"* 101 个因子的日度 PnL 两两相关均值：**{mean_pairwise:.3f}**（{pairs} 对，"
        f"论文 0.159；A 股样本 {len(codes)} 只 × {len(index)} 日，**不可直接对照**）",
        "",
        "## 暴露检查（截面秩相关 / 行业解释力）",
        "",
        f"* 与 `log(市值)` 的平均暴露：均值 {table['cap_exposure_mean'].mean():+.3f}，"
        f"绝对值最大 {table['cap_exposure_mean'].abs().max():.3f}（{table.loc[table['cap_exposure_mean'].abs().idxmax(), 'factor']}）",
        f"* 行业（申万 L1）解释力 `sqrt(R²)` 的平均值：{table['industry_exposure_mean'].mean():.3f}，"
        f"最大 {table['industry_exposure_mean'].max():.3f}",
        "",
        "## IC 最强的 10 个因子（按 |IC1| 排序）",
        "",
        "| 因子 | IC1 均值 | IC1 IR | IC1 t | IC5 均值 | PnL Sharpe |",
        "|---|---|---|---|---|---|",
    ]
    top = table.reindex(table["ic1_mean"].abs().sort_values(ascending=False).index).head(10)
    for _, row in top.iterrows():
        lines.append(
            f"| `{row['factor']}` | {row['ic1_mean']:+.4f} | {row['ic1_ir']:+.3f} | {row['ic1_t']:+.2f} | "
            f"{row['ic5_mean']:+.4f} | {row['pnl_sharpe']:+.2f} |"
        )
    lines += [
        "",
        "## 纪律声明",
        "",
        "1. 本报告**不参与** `verified/partial` 判定，也不得据此调整任何因子状态；",
        "2. A 股与美股的数据分布、参与者结构、涨跌停与 T+1 制度都不同 ⇒ 论文数字不可复现属正常；",
        "3. 样本量有限（见首行面板尺寸），IC 的 t 值受截面相关与横截面聚集影响，**不是**独立样本意义下的 t 检验；",
        "4. 正确性证据在 L1–L5（`docs/verification.md` §2），不在这里。",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"逐年表已写入 {csv_path}；两两相关分布已写入 {pairwise_path}")
    print(f"报告已写入 {report_path}")
    print(f"平均 IC（h=1/2/3/5/10）：" + " / ".join(f"{mean_ic_by_horizon[h]:+.4f}" for h in HORIZONS))
    print(f"两两相关均值（弱参考，论文 15.9%）：{mean_pairwise:.3f}（{pairs} 对）")
    print("⚠️ 纪律：L6 不参与 verified/partial 判定")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
