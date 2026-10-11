#!/usr/bin/env python
"""生成公众号素材：图 + 写作纲要（全部来自本仓库的可复现产物）。

**素材的口径纪律**：所有数字都标出**来源文件与样本量**，并保留「这不是正确性证据」的措辞——
本项目的卖点是「知道自己哪里不知道」，素材不能反过来把这个卖点丢掉。

产物（默认 `reports/wechat/`）：

* `fig1_ic_horizon.png`   —— 平均 IC 随 horizon（含「与短周期预期相反」的如实标注）
* `fig2_pairwise_corr.png`—— 两两 PnL 相关分布 + 论文 15.9% 参照线（**弱参考**）
* `fig3_exposure.png`     —— 市值暴露与行业解释力分布
* `fig4_evidence_chain.png`—— L1–L5 证据链与 82/19 状态划分（「凭什么信」）
* `outline.md`            —— 标题候选、主线立场、数字表、结构、避坑清单、配图说明

用法::

    python tools/l6_statistics.py --n-codes 60      # 先产出 reports/l6_*.csv
    python tools/make_wechat_material.py            # 再出图与纲要
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT_DIR = REPORTS / "wechat"
PAPER_PAIRWISE = 0.159

# 中文字体（本机已装 Noto CJK；给足回退）
plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK SC", "Noto Serif CJK SC", "WenQuanYi Zen Hei", "Source Han Sans SC", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 160
INK = "#1f2933"
ACCENT = "#2f6f9f"
WARN = "#c05621"


def _save(fig, name: str) -> pathlib.Path:
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  ✅ {path.relative_to(ROOT)}")
    return path


def fig_ic_horizon(table: pd.DataFrame, horizons=(1, 2, 3, 5, 10)) -> pathlib.Path:
    means = [float(table[f"ic{h}_mean"].mean()) for h in horizons]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    bars = ax.bar([str(h) for h in horizons], means, color=ACCENT, width=0.6)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.bar_label(bars, fmt="%+.4f", padding=3, fontsize=8, color=INK)
    ax.set_title(f"101 个因子的横截面 IC（Spearman）随 horizon 变化\n"
                 f"样本：{int(table['ic1_days'].max())} 个交易日 × A 股，hfq 复权", fontsize=10)
    ax.set_xlabel("horizon（交易日）")
    ax.set_ylabel("平均 IC")
    ax.annotate("|IC| 最大处出现在 h=10——与「短周期应更强」的直觉相反。\n"
                "只作观察、不下结论：A 股≠美股，样本量也有限。",
                xy=(0.02, 0.97), xycoords="axes fraction", va="top", fontsize=8, color=WARN)
    return _save(fig, "fig1_ic_horizon.png")


def fig_pairwise_corr(pairwise_path: pathlib.Path) -> pathlib.Path | None:
    if not pairwise_path.exists():
        print("  ⚠️ 缺 reports/l6_pairwise_corr.csv（先跑 tools/l6_statistics.py），跳过 fig2")
        return None
    values = pd.read_csv(pairwise_path)["corr"].to_numpy(dtype=float)
    mean = float(np.mean(values))
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.hist(values, bins=60, color=ACCENT, alpha=0.85)
    ax.axvline(PAPER_PAIRWISE, color=WARN, linestyle="--", linewidth=1.6,
               label=f"论文断言 15.9%＝{PAPER_PAIRWISE:.3f}")
    ax.axvline(mean, color=INK, linewidth=1.6, label=f"本仓库实测均值 {mean:.3f}")
    ax.set_title(f"101 个因子的两两 PnL 相关分布（{values.size} 对）\n"
                 "同量级 ≠ 验证：A 股 vs 美股、60 只样本，只作弱参考", fontsize=10)
    ax.set_xlabel("两两相关（日度 PnL）")
    ax.set_ylabel("因子对数量")
    ax.legend(fontsize=8)
    return _save(fig, "fig2_pairwise_corr.png")


def fig_exposure(table: pd.DataFrame) -> pathlib.Path:
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    axes[0].hist(table["cap_exposure_mean"].to_numpy(dtype=float), bins=25, color=ACCENT, alpha=0.85)
    axes[0].set_title("与 log(市值) 的截面秩相关", fontsize=9)
    axes[0].set_xlabel("暴露（均值）")
    axes[0].set_ylabel("因子数")
    axes[1].hist(table["industry_exposure_mean"].to_numpy(dtype=float), bins=25, color=ACCENT, alpha=0.85)
    axes[1].set_title("行业解释力 sqrt(R²)（申万 L1）", fontsize=9)
    axes[1].set_xlabel("sqrt(R²)")
    fig.suptitle("101 个因子的暴露分布：市值暴露几乎为零；行业解释力偏高（60 只样本下本就如此）", fontsize=10)
    return _save(fig, "fig3_exposure.png")


def fig_evidence_chain() -> pathlib.Path:
    layers = [
        ("L1", "算子层 20/20", "解析期望值 + 权威实现（pandas/scipy/statsmodels）对拍", "通过"),
        ("L2", "规范对照", "论文附录公式 ↔ 实现 AST：算子/字段/字面量三重对照", "101/101 等价"),
        ("L3", "双实现差分", "本库 vs vnpy：算子层 27 项 + 因子层 82 个可比因子", "0 待查"),
        ("L4", "不变量与变异", "入参不可变 / 时间截断一致性 / 8 个注入 bug 必须被抓", "全部通过"),
        ("L5", "golden 快照", "定种子面板冻结 101 个因子输出，防依赖漂移", "已入库"),
        ("L6", "统计合理性", "辅助层：明文不参与判定（统计显著 ≠ 实现正确）", "已跑"),
    ]
    fig, ax = plt.subplots(figsize=(9.2, 4.2))
    ax.axis("off")
    ax.set_title("「凭什么信」：六层证据链 + 状态划分（verified 82 / partial 19）", fontsize=11)
    for i, (tag, title, detail, status) in enumerate(layers):
        y = 0.86 - i * 0.145
        ax.add_patch(plt.Rectangle((0.02, y - 0.10), 0.09, 0.11, color=ACCENT, alpha=0.15))
        ax.text(0.065, y - 0.045, tag, ha="center", va="center", fontsize=11, color=ACCENT, weight="bold")
        ax.text(0.13, y - 0.015, title, fontsize=9.5, color=INK, weight="bold")
        ax.text(0.30, y - 0.015, detail, fontsize=8.5, color=INK)
        ax.text(0.97, y - 0.015, status, fontsize=9, color=INK if status != "0 待查" else WARN, ha="right")
    ax.text(0.02, 0.02, "verified 82/101：六条门槛全满足；partial 19/101：vnpy 未实现该因子 ⇒ "
                        "「独立差分」这一必需门槛原理上不可满足，如实标注、不豁免。",
            fontsize=8.5, color=WARN)
    return _save(fig, "fig4_evidence_chain.png")


OUTLINE = """# 公众号素材：《101 个公式化 Alpha》到底能不能被验证？

> 生成方式：`python tools/l6_statistics.py --n-codes 60 && python tools/make_wechat_material.py`
> 所有数字都可在仓库里复跑；图见同目录 `fig1`–`fig4`。

## 一句话定位

别人交付「101 个因子都能跑」；我们交付「**101 个因子各自被验证到什么程度，以及哪些我承认验不了**」。

## 标题候选（择一）

1. 我把 101 个公式化 Alpha 重写了一遍，然后老实标出「19 个我验不了」
2. 101 个因子的可验证性报告：82 个有据可查，19 个只能标 partial
3. 统计上好看 ≠ 实现正确：一次「六层证据链」的工程实验
4. 论文说两两相关 15.9%，我在 A 股上量到 16.4%——但这什么也证明不了

## 主线立场（全文不偏离）

* **统计显著不是正确性证据**（设计文档 §6.7 明文）：IC 好只能说明「在某个市场某个区间像那么回事」；
* **诚实的边界比漂亮的总数值钱**：19 个因子缺「独立实现逐点对拍」这一**必需**门槛 ⇒ 一律标 `partial`，
  备注里逐条写清「缺哪条、为什么」；
* **参照实现也会错**：对拍时发现 vnpy 的 `quesval2` **条件取反**（与它自己的文档相反）——双向对拍的价值就在这；
* **口径必须能被追溯**：`ts_decay_linear` 的方向、`ts_arg_max` 的基准、`rank`/`ts_rank` 的归一化区间，
  全部按 WorldQuant BRAIN 官方文档定案，并留了「结论 ↔ 原文出处」的对照清单。

## 关键数字（全部可复跑，标注样本）

| 项 | 数字 | 来源 |
|---|---|---|
| 因子实现 | 101/101（论文逐字转写） | `tools/conformance_report.py` → 「等价 101」 |
| 状态划分 | `verified` **82** / `partial` **19** / `ambiguous` **0** | `docs/verification.md` §1.7 |
| 规范对照 | 101/101 等价、0 偏离 | `tools/conformance_report.py --table` |
| 与第三方逐点差分 | 因子层 82 个可比因子 **0 待查** | `tools/factor_differential.py` |
| 平均 IC（h=1/2/3/5/10） | **+0.0131 / +0.0110 / +0.0126 / +0.0131 / +0.0149** | `reports/l6_ic.csv`（60 只 × 359 日 A 股） |
| 两两 PnL 相关均值 | **0.164**（4950 对）；论文断言 15.9% | `reports/l6_pairwise_corr.csv` |
| 市值暴露 | 均值 +0.000，\\|最大\\| 0.160 | `reports/l6_ic.csv` |
| golden 快照 | 101 个因子输出冻结 + sha256 + 环境版本 | `tests/golden/` |

## 建议结构

1. **钩子**：把「101/101 完成」和「82/101 verified」并排放出来——为什么不是 101？这 19 个差在哪？
2. **规范从哪来**：论文是「公式即代码」但我能拿到的一手规范只有论文 + 平台文档；
   而平台文档**登录可见且不返回因子矩阵** ⇒ 「正确」只能是「与所选规范一致」（附依据清单）。
3. **六层证据链**（配 `fig4`）：L1 算子对拍 → L2 规范对照 → L3 双实现差分 → L4 不变量与变异 →
   L5 golden 防回归 → L6 统计只作辅助。**每层都给出失败案例**（引用过被删 API、原地污染入参、
   零方差相关系数给 inf、`rank` 归一化区间曾与官方不同）。
4. **翻车与修正**（正文最有料的一段）：`^` 的语义、`rank` 归一化 `[0,1]`、`ddof=0`、稀疏 decay ——
   四处都是「按官方文档改掉自己原本的默认值」，并说明为什么要改（否则 alpha48 的分母会翻号）。
5. **承认验不了的**（配 `fig1`/`fig2`）：19 个因子无第三方参照 ⇒ `partial`；行为对齐（平台侧）
   因账号无中国区数据权限而**卡住**——把「为什么卡住」也当成结论交付。
6. **收尾立场**：可验证性是一份**清单**而不是一句口号；
   「敢于标注『这 19 个我无法验证』比假装全都对更有价值」。

## 避坑清单（写作时别踩）

* ❌ 不要把 IC 好说成「因子有效」或「实现正确」——本期统计**不参与**任何状态判定；
* ❌ 不要把 16.4% 与 15.9% 说成「验证了论文」——不同市场、不同样本，只能说「同量级」；
* ❌ 不要用「跑通了 101 个」当卖点——卖点是**每一层的判据与失败案例**；
* ✅ 每个数字都带来源文件与样本量；✅ 引用官方文档只用必要短句并注明来源 WorldQuant BRAIN。

## 配图说明

* `fig1_ic_horizon.png`：IC 随 horizon 的柱状图，角标注明「最大处 h=10，与短周期预期相反，只作观察」；
* `fig2_pairwise_corr.png`：两两相关分布 + 15.9% 与 0.164 两条参考线，标题直接写「同量级 ≠ 验证」；
* `fig3_exposure.png`：市值暴露与行业解释力分布；
* `fig4_evidence_chain.png`：六层证据链与 82/19 划分（替代常见的「Sharpe 截图」）。
"""


def main() -> int:
    global OUT_DIR

    parser = argparse.ArgumentParser(description="生成公众号素材（图 + 写作纲要）")
    parser.add_argument("--ic", default=str(REPORTS / "l6_ic.csv"))
    parser.add_argument("--pairwise", default=str(REPORTS / "l6_pairwise_corr.csv"))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    OUT_DIR = pathlib.Path(args.out_dir)
    ic_path = pathlib.Path(args.ic)
    if not ic_path.exists():
        print(f"❌ 缺 {ic_path}：先跑 python tools/l6_statistics.py --n-codes 60")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table = pd.read_csv(ic_path)
    print(f"读入 {ic_path}（{table.shape[0]} 个因子）")

    fig_ic_horizon(table)
    fig_pairwise_corr(pathlib.Path(args.pairwise))
    fig_exposure(table)
    fig_evidence_chain()
    (OUT_DIR / "outline.md").write_text(OUTLINE, encoding="utf-8")
    print(f"  ✅ {(OUT_DIR / 'outline.md').relative_to(ROOT)}")
    print("⚠️ 素材口径：全部数字标注来源与样本量；统计不参与 verified 判定")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
