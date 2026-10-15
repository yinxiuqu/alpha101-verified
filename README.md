# alpha101-verified · 一份「可验证的 Alpha101」

> **本项目卖的不是 101 个公式，而是「凭什么说它们算对了」。**
> 生态里不缺 Alpha101 的实现，缺的是**正确性证据**：算子口径对拍、golden 基准、
> 前视/不变量检验、与论文的偏差清单、以及诚实标注「哪几个我也验不了」。

| 项 | 状态（2026-10-09） |
|---|---|
| 里程碑 | **M0/M1 完成**（20 算子 + §8 + 变异测试）、**M2 完成**（规范入库 + `floor(d)` + `elemwise` + 5 试点 + 算子层差分 + 真实面板端到端）、**M3 完成**（**101/101 因子** + 复权 + 规范对照 101/101 等价） |
| 算子层（L1） | ✅ **20/20 通过**，`rtol = 1e-10`；**697** 个测试全绿（20 个文件）；7/7 变异注入被抓住 |
| 算子层差分（L3 提前） | ✅ 与 **vnpy（MIT）** 24 项对拍：**18 项逐点一致 + 6 项已归因口径差异 + 0 项待查**（`tools/differential.py`） |
| 因子层 | ✅ **101/101 已实现**；状态 **`verified` 82 / `partial` 19 / `ambiguous` 0** —— 19 个缺「门槛 3 独立差分」（vnpy 未实现：18 个含 `IndNeutralize` + `alpha56` 需 `cap`），备注逐条写明 |
| **真实数据端到端** | ✅ 359 交易日 × 120 只 A 股（MongoDB + 申万 as-of 行业）：面板契约通过、`vwap` 自洽 **99.86%**、零 ±inf、`ind_neutralize` 残差和 **3.4e-15**；✅ **M3 已补 PIT 安全复权**（除权日假跳空 35.11% → 7.60%） |
| 因子层（L2–L5） | ✅ **L2 规范对照 101/101 等价**；✅ **L3 因子级差分 82 个可比因子 0 待查**；✅ L4 不变量全量通过；✅ **golden 快照已入库**（5×320 冻结基线 + sha256 + 环境版本，已接 CI）；✅ L6 辅助统计（明文不参与判定） |
| `verified` 因子数 | **82/101**（§6.8 六条门槛全满足；其余 19 个缺「门槛 3 独立差分」⇒ 如实标 `partial`。设计文档曾预估 60~80） |
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

> **第一次用？看 [`docs/usage.md`](docs/usage.md)**（安装 → 五分钟上手 → 字段不够怎么办 → 口径 → 自查 → 性能 → 常见问题），并可直接跑 `python examples/hello_alpha101.py`（合成面板，不需要数据库）。

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
| **L2 规范对照** | 论文附录公式 vs 实现 AST 逐节点比对 → 等价/近似/偏离 | ✅ **101/101 等价、0 偏离**（`tools/conformance_report.py`） |
| **L3 双实现差分** | 本库 vs vnpy（polars DSL），逐点 `allclose(rtol=1e-8)` | ✅ **算子层 + 因子层均已做**：算子层 24 项；因子层 82 个可比因子 **0 待查**（`docs/verification.md` §1.5）；19 个无第三方参照 |
| **L4 不变量与元测试** | 输入不可变性 / 时间截断一致性 / 未来扰动 / 缩放不变性 / **变异测试** | ✅ **算子层 + 因子层均已做**（`tests/test_invariants.py`、`tests/test_factors_all.py` 306 项、8/8 变异注入被抓） |
| **L5 golden 快照** | 固定种子面板上冻结 101 个因子输出，防回归 | ✅ **已入库**（`tests/golden/`：5×320 面板 + 101 因子输出 + sha256 + 环境版本，已接 CI） |
| **L6 统计合理性** | IC 符号/衰减形状/暴露检查 | 🟡 **已跑（辅助，非门槛）**：`tools/l6_statistics.py`（结果见 `reports/l6_summary.md`）。**明文：统计不参与 `verified` 判定**，A 股 ≠ 美股只作弱参考 |

**判据（设计文档 §6.8）**：六条门槛全满足才可标 `verified`；缺任一条标 `partial`/`ambiguous`。

**终态：`verified` 82/101、`partial` 19/101、`ambiguous` 0。** 19 个 `partial` 全部是
「vnpy 未实现 ⇒ 无第三方参照 ⇒ 门槛 3（必需）原理上不可满足」的因子
（18 个含 `IndNeutralize` + `alpha56` 需 `cap`），备注里逐条写明缺哪条、为什么。
设计文档 §6.8 的诚实预期是「`verified` 不可能是 101/101，预估 60~80」，实测 82。

---

## 一页复现（每条声明都能自己跑出来）

```bash
python -m pytest -q                                  # 682 项全绿（约 22 分钟）

python tools/conformance_report.py                   # L2：期望「等价 101（共 101 个因子）」
python tools/conformance_report.py --table           # 101 行偏差清单（docs/deviations.md §4 由此生成）

bash tools/fetch_vnpy_reference.sh                   # L3：抓 vnpy 参照（SHA256 固定，进 gitignored 的 .vnpy-ref/）
python tools/differential.py                         #      算子层 27 项：19 一致 + 8 已归因 + 0 待查
python tools/factor_differential.py                  #      因子层 82 个可比因子：64 一致 + 18 已归因 + 0 待查

python tools/golden_snapshot.py --check              # L5：与冻结基线比对（NaN 模式 + 数值）
python -m pytest tests/test_golden.py -q             #      5 项

python tools/real_panel_smoke.py --n-codes 120       # 真实 A 股端到端（需本地 MongoDB）

python -m pytest tests/test_mutation.py -q           # 8 个已知 bug 注入必须全部被抓住
```

⚠️ **BRAIN 官方算子文档不在仓库里**（登录墙内的专有文档，`refs/` 已 gitignore）。
要复核 L-B 结论（`ts_decay_linear` 方向、`ts_arg_max` 基准、`^` 的 `power`/`signed_power`、
`rank`/`ts_rank` 归一化、`ts_std_dev` 的 ddof），需要你自己的会话：登录后
`GET https://api.worldquantbrain.com/operators`（列表）与 `GET /operators/{name}`（完整正文，
即页面 `Show more` 的内容）。所有引文与结论都写在 `docs/operators.md` §3.13 —— 
即使拿不到文档，也能看到「依据什么、选择了什么、漏在哪」。

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
| 算子层与第二实现（vnpy，MIT）逐点一致 | `tools/differential.py`：27 项中 **19 项对齐后逐点一致**，8 项为已归因口径差异（D1/D3–D8；原 D2「ddof」已因官方口径落地而消失） |
| **101 个因子与论文公式结构一致** | `tools/conformance_report.py`：算子／字段／字面量三重对照 ⇒ **101/101 等价、0 偏离** |
| **官方口径落地（L-B 算例）** | `rank`/`ts_rank` 归一化 `(名次−1)/(n−1) ∈ [0,1]`、`ts_std_dev` ddof=0、`ts_decay_linear` 稀疏 NaN→0 —— 四个官方算例已逐字进测试（`docs/operators.md` §3.1/§3.2/§3.12/§3.13.3） |
| **BRAIN 完整算子文档（L-B，API 级）** | 66 个算子的**完整正文 + 官方算例**（本地语料 `refs/brain_operator_docs.md`，gitignored）：三处默认口径**已落地**（归一化 `[0,1]`、`ts_std_dev` ddof=0、decay 稀疏 NaN→0），四个官方算例逐字进测试（`docs/operators.md` §3.13.3） |
| **BRAIN 官方算子文档（L-B）定案** | `refs/WorldQuant_BRAIN.pdf`（登录墙内文档，gitignored）：`ts_decay_linear` 方向、`ts_arg_max/min` 基准（今天=0）、`^` 的 `power`/`signed_power` 之分 —— 原文引文见 `docs/operators.md` §3.13 |
| **因子级与 vnpy 逐点一致** | `tools/factor_differential.py`：82 个可比因子 0 个「待查」（64 逐点一致 + 18 已归因：2 参照 bug、14 离散平局/数值病态、2 覆盖差异）；19 个因子无第三方参照 |
| 全量因子的 PIT 与契约 | `tests/test_factors_all.py`：101 个因子逐一验证「可算不产 ±inf／入参不可变／时间截断一致性」 |
| 复权修正除权日假跳空 | `tests/test_adjust.py`（11 项）+ `tests/test_adapters_real_data.py`（真实数据 35.11% → 7.60%） |
| 试点因子算得对（封闭解 + 独立第二实现） | `tests/test_factors.py`：alpha4/alpha5/alpha56 用 `scipy.rankdata` + 显式循环另写一份对拍；alpha101/alpha41 用论文公式裸 numpy 直算 |
| 真实数据上契约与不变量成立 | `tests/test_adapters_real_data.py`（11 项）：面板契约、`vwap` 单位自洽、因子零 ±inf、PIT 行业中性化正交、真实数据时间截断一致性 |
| **L6 辅助统计（不是门槛）** | `tools/l6_statistics.py` + `reports/l6_summary.md`：60 只 × 359 日 A 股上跑完 101 个因子——平均 IC（h=1/2/3/5/10）**+0.0131/+0.0110/+0.0126/+0.0131/+0.0149**，两两 PnL 相关 **0.164**（4950 对，论文断言 15.9% 属**同量级弱参考**）。⚠️ 明文：不参与 `verified/partial` 判定，一个状态都没动 |
| **美股真实数据验证（已完成）** | 新浪源 80 只 × 753 日：面板契约 ✅、`vwap∈[low,high]` 99.49%、**±inf 0 个**、覆盖率 89.5%、时间截断一致性 ✅，**82 个因子对拍 vnpy：64 一致 + 18 已归因 + 0 待查**（与合成面板/A 股结论一致）⇒ `reports/us_verification_report.md`；数据已按用户要求删除并留审计。另：`tools/us_data_verification.py` |
| ~~美股验证的原始阻塞（历史记录）~~ | `tools/us_data_verification.py`（取数→验证→**删除+审计**）+ `tools/factor_differential.py --panel-file`。实测该 tushare 账号 `us_daily` 限 **1 次/小时**、复权接口**无权限**、且无行业字段 ⇒ 本轮如实记「未完成」；删除审计见 `reports/us_data_audit.md`（`docs/verification.md` §1.11） |
| **101 个因子在说什么** | `docs/factor_meaning.md`：机械事实表（字段/算子/窗口/结构形态，由 `tools/factor_meaning.py` 从公式逐条提取、可 `--check` 防漂移）+ 逐条经济解读（**标注为推断**，不影响任何因子状态）。**alpha1–alpha101 全部完成（五批）** |
| **A 股 T+1 审计** | `docs/t1_audit.md`：逐项核对「因子层是否含美股 T+0 假设」——结论是**不含**（无执行层、无前视、评估只用 h≥1 前瞻收益），并列出使用者必须自行处理的三件事（信号后移一天、涨跌停/停牌、T+1 持仓约束） |
| **给使用者的实践指南** | `docs/usage.md`（安装 → 五分钟上手 → 接自己的数据 → 字段不够怎么办 → 口径 → 自查 → 性能 → 常见问题）+ `examples/hello_alpha101.py`、`examples/from_my_csv.py`（都可直接跑） |
| **L-B 文档语料（本地，gitignored）** | `tools/fetch_brain_docs.py` → `refs/brain_docs/`：算子完整正文 66（53 有详情页）、Learn 教程 17 页、数据集 150 个、数据字段 **4367** 个（含描述与数据集）+ 字段名总表 4545，均含 MD 与 PDF。**登录墙内的专有文档：只作本地依据，不提交、不分发** |
| **第二独立参照差分（MIT）** | `tools/second_reference_differential.py`：对拍 19 个 `partial` 因子（第一参照 vnpy 未实现它们）。已证明两处参照侧口径偏离（并列取号、窗口不足 0-vs-NaN），一条归因被**证伪**（小数窗口）⇒ **19 个状态不升级**。结果表 `reports/second_reference_diff.csv`（`verification.md` §1.12） |
| **BRAIN 行为对齐工具（补充证据）** | `tools/brain_alignment.py`：同表达式两边的日度 PnL 做**单调性**比较（Spearman），两条取数路径都**零配额**、且不接受命令行凭据；`--submit` 拒绝执行（不代耗配额）。⛔ **未完成且非工具问题**：该账号只有 **USA** 数据（`/data-sets?region=USA`=150；`CHINA`/`CHN`/`GLB`/`EUR`/`ASI` 全 0，两种拼写都试过）⇒ 拿不到 A 股平台结果、不同市场无法对齐。可用 `--check-region` 只读复验（退出码 3 = 无中国区数据；`docs/verification.md` §1.9） |
| 真实面板冒烟可复跑 | `tools/real_panel_smoke.py`（359 交易日 × 120 只，退出码即证据） |
| 测试套件不是摆设 | `tests/test_mutation.py`（**8/8** 注入被抓住）+ 前视对照实验 `test_truncation_consistency_has_teeth_...` |
| **golden 防回归（L5）** | `tests/test_golden.py` + `tools/golden_snapshot.py --check`：冻结 101 个因子输出，NaN 模式必须一致、数值 `allclose`；长窗口因子在基线上有值（选 5×320 而非 5×250 的理由可验证） |
| 干净室纪律（比 GPL 更严的一例） | `YutaoWang03/Quant-Alpha101` 经只读 API 查证**未声明许可证**（`spdx_id: null`）⇒ 本项目对它既不参照也不对比（`docs/deviations.md` §1.1 第 8 行） |
| 状态划分不是拍脑袋 | `tests/test_factors_all.py::test_verified_and_partial_split_follows_the_six_gates`：82/19 的划分与「无参照集合」逐一对齐，并与 `tools/factor_differential.py` 的 `NOT_COMPARABLE` 交叉断言 |
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
│   ├── usage.md              # ★ 使用指南（给第一次用的人）
│   ├── verification.md         # 六层协议与验证结果矩阵
│   ├── ambiguities.md          # 规范歧义清单（已决策 / 待决 / 无法判定）
│   └── deviations.md           # 与论文/GPL 原实现的偏差清单（101 行清单 M3 生成）
├── src/alpha101v/
│   ├── operators.py            # 17 个算子（纯函数，DataFrame→DataFrame）
│   ├── neutralize.py           # 3 个中性化算子（向量化，无矩阵求逆）
│   ├── panel.py                # 面板契约与校验（M0）
│   ├── registry.py             # 因子注册与按形参名自动装配（§7.5；表为空 = 尚无因子）
│   └── adapters/               # 数据适配（可选层，**延迟导入**驱动；不污染运行时依赖）
│       ├── mongo.py            # MongoDB(quantaxis) → §7.4 面板（vol→volume、vwap=amount/(vol*100)）
│       └── industry.py         # 申万 as-of 成员 → **PIT 行业标签面板**（逐日，非固定快照）
├── tests/
│   ├── test_operators.py       # §8 全部用例：A 组 / B 组 / 中性化组（54 个）
│   ├── test_invariants.py      # §6.5 不变量（129 个）
│   ├── test_panel.py           # 面板契约（13 个）
│   ├── test_registry.py        # 自动装配机制（10 个）
│   ├── test_provenance.py      # 许可/依赖机械守卫（5 个）
│   ├── test_mutation.py        # 变异测试（8 个：7 注入 + 1 勘误钉死）
│   ├── test_elemwise.py        # 逐元素层（abs/log/sign/signedpower）
│   ├── test_factors.py         # 5 个试点因子：封闭解 / 独立第二实现 / L2 结构 / L4 不变量
│   ├── test_differential.py    # vnpy 算子层差分包装（参照缺失自动跳过）
│   ├── test_adapters_real_data.py  # 真实 A 股数据端到端（无数据库时跳过）
│   └── golden/                 # golden 快照（5×320 冻结基线 + sha256 + 环境版本，已接 CI）
├── tools/
│   ├── conformance_report.py   # ★ 规范对照：论文公式 ↔ 实现 AST（算子/字段/字面量），生成偏差清单
│   ├── differential.py         # ★ 算子层差分对拍（本库 vs vnpy MIT），退出码即证据
│   ├── fetch_vnpy_reference.sh # 下载参照源码到 gitignored 的 .vnpy-ref/（含 SHA256 校验）
│   └── README.md               # conformance_report.py 待 M3
└── .github/workflows/ci.yml    # pandas 2.1/2.2/2.3 矩阵 + 算子闸门 + 变异步骤
```

**与设计文档 §7.2 的结构对照（截至 v0.1.1，已全部补齐）**：
`src/alpha101v/factors.py`（101 个因子）、`tests/golden/`（冻结基线）、`tools/*.py`（规范对照、
算子层与因子层差分、golden 快照、第二参照差分、发布前安全确认等）均已就位。
§7.2 里的 `test_edge_cases.py` / `test_conformance.py` 未单独立文件，而是**并入**
`test_operators.py`（NaN/inf/停牌/新股的边界用例）、`test_invariants.py`（脏数据三连）
与 `test_panel.py`（面板契约）——覆盖等价，只是不按文件名一一对应。
§7.2 中的 `test_edge_cases.py`（NaN/inf/停牌/新股）目前在 `test_operators.py:test_a26`、
`test_invariants.py`（脏数据三连）与 `test_panel.py` 里已覆盖算子层部分。

---

## 路线图

| 里程碑 | 内容 | 状态 |
|---|---|---|
| **M0** | 骨架 + MIT + 面板契约 + CI | ✅ |
| **M1** | 20 个算子 + §8 全部用例 + 变异测试 | ✅ |
| **M2** | 5 个试点因子 + L2/L3/L4 首跑 | ✅ **完成**：`floor(d)`、`elemwise` 层、5 个试点因子（`alpha101`/`alpha4`/`alpha5`/`alpha41`/`alpha56`）、算子层 L3 差分、真实 A 股端到端。当时的余项（L2 全量 AST 对照、因子级差分）后续已由 M3 / M4+L-B 补齐 ✓ |
| M3 | 101 个因子 + 规范对照 + 偏差清单 | ✅ 完成：101/101 因子、L2 对照 101/101 等价、PIT 安全复权、偏差清单由工具生成（`docs/deviations.md` §4） |
| **M4+L-B** | 因子级差分对拍 + BRAIN 官方文档定案 | ✅ **完成**：64 一致 + 18 已归因、**0 待查**；顺带实测出参照侧 `quesval2` 取反的 bug（`docs/verification.md` §1.5） |
| **M5** | golden 快照 + 状态终态 + 发布收尾 | ✅ **完成**：`tests/golden/`（5×320 冻结基线 + sha256 + 环境版本，已接 CI）、`verified` 82/101 |
| **v0.1.1** | 第二独立参照差分（MIT 的 `alpha101-pipeline`）+ 使用指南 + 美股真实数据验证 + 发布（GitHub） | ✅ **完成**：19 个 `partial` 全部实测、无一条逐点一致 ⇒ 状态如实保持；另交付 `docs/usage.md` 与两个可跑示例 |

⚠️ 设计文档 §7.7 的提醒照抄在此：**不要一上来做 M3**。口径（复权/单位/PIT/算子）
一旦有问题，拿 101 个因子做一次大规模错误实验会全部返工。

---

## 归属与许可

* 本仓库代码：**MIT**（见 `LICENSE`）。
* 规范来源：Zura Kakushadze, *101 Formulaic Alphas*, Wilmott Magazine 2016(84):72–80，
  [arXiv:1601.00991](https://arxiv.org/abs/1601.00991)。**该论文不是 WorldQuant 官方标准**，
  且 WorldQuant 未开源任何因子代码——「正确」只能定义为「与所选规范一致」。
* 差分对拍参照：[vnpy](https://github.com/vnpy/vnpy)（MIT）的 `alpha_101.py` 与
  `{cs,ts,ta}_function.py`。**仅用于测试期对拍**（下载到 gitignored 的 `.vnpy-ref/`，不进仓库）。署名与许可声明见
  `docs/verification.md` §1.2/§1.5 与 `tools/README.md`；另有第二参照 `alpha101-pipeline`（MIT，
  独立 venv）用于 19 个 `partial` 因子的对拍，见 `docs/verification.md` §1.12。
* **clean-room 声明**：本仓库从公开论文与数学定义独立实现。被分析的 GPL-3.0 仓库
  （`QAFactor_Alpha101`）**代码从未被打开或拷贝**；其 README 的中文注释表仅用于理解经济含义
  （注释与分类不构成代码表达）。`tests/test_provenance.py` 用机械扫描守住这条纪律。
