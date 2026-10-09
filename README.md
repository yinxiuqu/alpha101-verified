# alpha101-verified · 一份「可验证的 Alpha101」

> **本项目卖的不是 101 个公式，而是「凭什么说它们算对了」。**
> 生态里不缺 Alpha101 的实现，缺的是**正确性证据**：算子口径对拍、golden 基准、
> 前视/不变量检验、与论文的偏差清单、以及诚实标注「哪几个我也验不了」。

| 项 | 状态（2026-10-09） |
|---|---|
| 里程碑 | **M0 完成**（骨架/许可/面板契约/CI）、**M1 完成**（20 个算子 + §8 全部用例 + 变异测试） |
| 算子层（L1） | ✅ **20/20 通过**，`rtol = 1e-10`；219 个测试全绿；7/7 变异注入被抓住 |
| 因子层（L2–L5） | ⛔ **尚未开始（0/101）**——按设计文档 §10.4「M1 未 100% 通过前不得进入 M2」 |
| `verified` 因子数 | **0/101**（诚实计数：没有因子，就没有 verified） |
| 许可 | **MIT**（clean-room，零 GPL 血缘；CI 有机械守卫） |

---

## 为什么做这个

| 现有实现 | 有没有测试 | 真实短板 |
|---|---|---|
| vnpy `alpha_101.py`（MIT） | ⚠️ 约 100 个**冒烟测试**，断言只有 `assert "data" in result.columns` | **没有正确性证据**；只覆盖 **82/101**（缺 alpha56 + 18 个 `IndNeutralize` 因子）；那 18 个在它的测试里被**静默摘掉了中性化** |
| yli188（878 星） | ❌ 无 | **无许可证**（默认保留所有权利，法律上不可复用） |
| `QAFactor_Alpha101`（GPL-3.0） | ❌ 无 | 22 个因子在 pandas ≥ 1.0 下必崩；`scale` 轴向错；`IndNeutralize` 逐日求逆遇奇异行业即崩；**35 个 fork 五年内无一人修改** |

**结论：**「能不能算」已经有人免费给了；「算得对不对」是生态真空白。

本仓库因此从公开论文 clean-room 重写（**不修复、不 fork 那个 GPL 仓库**），
把 vnpy（MIT）当**测试期**差分对拍参照，交付「可验证」三件套：
**① 口径可判定 ② 证据可复现 ③ 验不了的如实标注**。

许可证边界（设计文档 §5.3）：
`QAFactor_Alpha101`（GPL-3.0）**只被允许本地跑数值对比**，其**代码一行都不进本仓库**；
vnpy（MIT）仅作测试期参照并署名；运行时依赖只有 `numpy / pandas / scipy`。

---

## 快速开始

```bash
PY=/home/yinxiuqu/anaconda3/envs/qa/bin/python     # Python 3.11 / pandas 2.3.3

$PY -m pytest -q                                   # 全量（含变异测试，约 2~3 分钟）
$PY -m pytest tests/test_operators.py -q           # M1 闸门：算子层 20/20
$PY -m pytest tests/test_mutation.py -q            # 变异测试：7/7 注入必须被抓住
```

```python
import pandas as pd
from alpha101v import rank, scale, decay_linear, ind_neutralize

# 面板契约：index = 交易日（升序唯一），columns = 股票代码
factor = decay_linear(rank(close), 5)          # 截面 rank 默认 pct=True（(0,1]）
daily  = scale(factor, k=1.0)                  # 每日 Σ|x| = 1（axis=1）
resid  = ind_neutralize(factor, industry)      # 逐日组内去均值 = 行业哑变量 OLS 残差
```

无需安装（`conftest.py` 会把 `src/` 加进 `sys.path`）；如需安装：`pip install -e .[test]`。

---

## 验证套件：六层协议现在走到哪

| 层 | 内容 | 本仓库状态 |
|---|---|---|
| **L1 算子层** | 20 个算子的数学定义与权威实现对拍（pandas/scipy/statsmodels） | ✅ **已做**，20/20；见 `docs/operators.md` |
| **L2 规范对照** | 论文附录公式 vs 实现 AST 逐节点比对 → 等价/近似/偏离 | ⛔ M3 |
| **L3 双实现差分** | 本库 vs vnpy（polars DSL），逐点 `allclose(rtol=1e-8)` | ⛔ M4（对拍范围仅 82/101） |
| **L4 不变量与元测试** | 输入不可变性 / 时间截断一致性 / 未来扰动 / 缩放不变性 / **变异测试** | 🟡 **算子层已做**（`tests/test_invariants.py`、`tests/test_mutation.py`），因子层待 M2 |
| **L5 golden 快照** | 固定种子面板上冻结 101 个因子输出，防回归 | ⛔ M5 |
| **L6 统计合理性** | IC 符号/衰减形状/暴露检查 | ⛔ 需因子与 A 股数据；**明文禁止用「IC 好看」证明代码正确** |

**判据（设计文档 §6.8）**：六条门槛全满足才可标 `verified`；缺任一条标 `partial`/`ambiguous`。
因为 L2/L3/L5 未做、因子未写，**当前 `verified` = 0/101**。这不是保守，而是本项目的立身之本。

---

## 证据索引（每个声明都指向一个可复现的命令）

| 声明 | 证据 |
|---|---|
| 20 个算子 API 恰好这些、无多无少 | `tests/test_operators.py::test_api_surface_is_exactly_twenty` |
| 「ddof 默认 1」「预热期必须 NaN」「scale 是 axis=1」等口径 | `docs/operators.md` §3 + 对应 `test_a*` / `test_b*` |
| 论文规范文本已完整入库（L2 基准） | `docs/paper_formulas.md` §2：101/101 条公式、**0 条括号不平衡**、可复现的 `curl`+`pdftotext` 命令与 PDF SHA256 |
| 设计文档 §3.2 依赖表经论文原文独立证实 | `docs/paper_formulas.md` §8：5/5 一致（连因子编号列表都逐一相同） |
| 与 `statsmodels.OLS` 残差逐点一致（`rtol=1e-10`） | `test_c02`（`ind_neutralize`）、`test_c10`（`neutral`） |
| 残差与行业哑变量正交、行业内残差均值为 0 | `test_c01` |
| 共线/空行业不抛 `LinAlgError` | `test_c03`、`test_c12` |
| 入参一字未改（专治 §3.3 缺陷 2） | `tests/test_invariants.py::test_inputs_are_not_modified`（22 个调用点） |
| 无前视（PIT 金标准） | `test_time_truncation_consistency`（19 个算子）+ `test_future_perturbation_does_not_change_past` |
| 未用将被删除的 pandas API（原实现死于 `as_matrix`） | `test_no_deprecated_pandas_api_warnings`（22 个调用点在 `FutureWarning`/`DeprecationWarning` 转异常下运行，0 警告） |
| 测试套件不是摆设 | `tests/test_mutation.py`（7/7 注入被抓住）+ 前视对照实验 `test_truncation_consistency_has_teeth_...` |
| 零 GPL 血缘、运行时依赖只有 numpy/pandas/scipy | `tests/test_provenance.py`（源码 token 扫描 + 子进程 import 检查 + pyproject 解析） |
| 面板契约（单位/前复权/pit 前提） | `tests/test_panel.py` + `src/alpha101v/panel.py` |

---

## 仓库结构

```
alpha101-verified/
├── LICENSE                     # MIT
├── README.md
├── pyproject.toml              # 运行时依赖仅 numpy/pandas/scipy
├── conftest.py                 # 让 src 布局免安装可导入
├── docs/
│   ├── Alpha101_修复发布决策与验证协议_v0.1.md   # 设计依据（内容版本 v0.2）
│   ├── operators.md            # ★ 算子口径唯一权威（含歧义点决策 + 4 条文档勘误 + 论文核对回写）
│   ├── paper_formulas.md       # ★ 论文规范入库：101/101 条公式逐字（括号平衡校验 0 不平衡）
│   ├── verification.md         # 六层协议与验证结果矩阵
│   ├── ambiguities.md          # 规范歧义清单（已决策 / 待决 / 无法判定）
│   └── deviations.md           # 与论文/GPL 原实现的偏差清单（101 行清单 M3 生成）
├── src/alpha101v/
│   ├── operators.py            # 17 个算子（纯函数，DataFrame→DataFrame）
│   ├── neutralize.py           # 3 个中性化算子（向量化，无矩阵求逆）
│   ├── panel.py                # 面板契约与校验（M0）
│   ├── registry.py             # 因子注册与按形参名自动装配（§7.5；表为空 = 尚无因子）
│   └── adapters/               # 数据适配（M2 起；运行时不得引入 pymongo/QUANTAXIS）
├── tests/
│   ├── test_operators.py       # §8 全部用例：A 组 / B 组 / 中性化组（54 个）
│   ├── test_invariants.py      # §6.5 不变量（129 个）
│   ├── test_panel.py           # 面板契约（13 个）
│   ├── test_registry.py        # 自动装配机制（10 个）
│   ├── test_provenance.py      # 许可/依赖机械守卫（5 个）
│   ├── test_mutation.py        # 变异测试（8 个：7 注入 + 1 勘误钉死）
│   └── golden/                 # golden 快照（M5 建；现为空并有说明）
├── tools/                      # conformance_report.py / differential.py（M3/M4 建）
└── .github/workflows/ci.yml    # pandas 2.1/2.2/2.3 矩阵 + 算子闸门 + 变异步骤
```

**与设计文档 §7.2 的结构差异（全部是里程碑顺序，不是遗漏）**：
`src/alpha101v/factors.py`、`tests/test_edge_cases.py`、`tests/test_conformance.py`、
`tests/golden/` 的内容、`tools/*.py` 属 **M2–M5**。本轮宁可留空并在文件里写明原因，
也不放「看起来跑得通」的假实现——那正是本项目要反对的东西。
§7.2 中的 `test_edge_cases.py`（NaN/inf/停牌/新股）目前在 `test_operators.py:test_a26`、
`test_invariants.py`（脏数据三连）与 `test_panel.py` 里已覆盖算子层部分。

---

## 路线图

| 里程碑 | 内容 | 状态 |
|---|---|---|
| **M0** | 骨架 + MIT + 面板契约 + CI | ✅ |
| **M1** | 20 个算子 + §8 全部用例 + 变异测试 | ✅ |
| M2 | 3~5 个试点因子（`alpha101` 可手算、`alpha4`、`alpha5`、`alpha41`、`alpha56`）+ L2/L3/L4 首跑 | ⛔ **前置：①非整数窗口 `floor(d)` 改码（40 因子吃紧）②`elemwise` 层（15 因子需要）——见 `docs/deviations.md` §1.2** |
| M3 | 101 个因子 + 规范对照 + 偏差清单 | ⛔ |
| M4 | vnpy 差分对拍（82 个）+ 差异归因 | ⛔ |
| M5 | golden 快照 + 文档 + 发布 | ⛔ |

⚠️ 设计文档 §7.7 的提醒照抄在此：**不要一上来做 M3**。口径（复权/单位/PIT/算子）
一旦有问题，拿 101 个因子做一次大规模错误实验会全部返工。

---

## 归属与许可

* 本仓库代码：**MIT**（见 `LICENSE`）。
* 规范来源：Zura Kakushadze, *101 Formulaic Alphas*, Wilmott Magazine 2016(84):72–80，
  [arXiv:1601.00991](https://arxiv.org/abs/1601.00991)。**该论文不是 WorldQuant 官方标准**，
  且 WorldQuant 未开源任何因子代码——「正确」只能定义为「与所选规范一致」。
* 差分对拍参照：[vnpy](https://github.com/vnpy/vnpy)（MIT）的 `alpha_101.py` 与
  `{cs,ts,ta}_function.py`。**仅用于测试期对拍**，M4 启用时将在本文件与 `docs/verification.md`
  补上明确的署名与许可声明。
* **clean-room 声明**：本仓库从公开论文与数学定义独立实现。被分析的 GPL-3.0 仓库
  （`QAFactor_Alpha101`）**代码从未被打开或拷贝**；其 README 的中文注释表仅用于理解经济含义
  （注释与分类不构成代码表达）。`tests/test_provenance.py` 用机械扫描守住这条纪律。
