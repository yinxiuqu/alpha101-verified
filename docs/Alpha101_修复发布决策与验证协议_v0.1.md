# Alpha101 修复发布决策与验证协议 v0.1

> **⚠️ 版本说明**：本文档内容已更新至 **v0.2**（2026-10-09 二次修订，加入 vnpy 实现逐行核查与"vnpy 参照 + 自建验证层"路线）。**文件名保留 `_v0.1` 以避免移交路径失效；一切以内容版本号为准。**

| 项 | 内容 |
|---|---|
| 文档版本 | **v0.2**（文件名仍为 v0.1） |
| 创建日期 | 2026-10-09（v0.1）／2026-10-09 二次修订（v0.2） |
| 状态 | 决策已定稿；验证协议与工程方案待在新工作区执行 |
| 产出会话 | quantming 会话（只读分析，未修改任何被分析的文件） |
| 移交目标 | 独立工作区 + 新会话，用于 Alpha101 开源项目 |
| 分析对象 | `/home/yinxiuqu/qa_ecosystem/QAFactor_Alpha101`（yutiansut/QAFactor_Alpha101）；参照对象 vnpy `alpha_101.py` |
| 一句话结论 | **不修复原仓库、不发布 GPL 衍生版；从公开论文 clean-room 重写，并把 vnpy（MIT）当作差分对拍参照，交付"带验证套件的可验证 Alpha101"。** |

---

## 0. TL;DR（先看这 10 条）

1. **WorldQuant 官方没有任何因子/Alpha101 代码。** 官方 GitHub 组织只有 2 个无关 fork（nixpkgs、gss-token），已核实。
2. **那篇著名的《101 Formulaic Alphas》不是 WorldQuant 的论文**：单作者 Zura Kakushadze，机构 Quantigic Solutions LLC，2016 年发在 Wilmott Magazine。它只是"脱敏后的公开配方"，是事实标准，但不是官方标准。
3. **WorldQuant 唯一的官方"可验证"入口是 BRAIN 平台**（官方仿真器 + 官方表达式语言 + 官方评估指标）。它验证的是**alpha 的表现**，不是**你的实现与原式是否一致**，且只吃它自己的表达式语言，无法直接验证 pandas 代码。
4. **因此：不存在"官方标准答案"可用于验证实现正确性。** 验证只能建立在「论文规范 + 算子权威实现 + 独立双实现差分 + 不变量/前视检验」之上。
5. 本项目上游已死：**51 星 / 35 fork / 0 issue / 最后提交 2021-03-25**。
6. **35 个 fork 的 `pushed_at` 全部等于 2021-03-25** —— 五年内无一人修改过它。
7. 上游许可证是 **GPL-3.0**。修复后发布会被强制继续 GPL-3.0；把代码并入将来要发布的 `quantming` 会**传染**。
8. 生态里最流行的替代实现（878 星）**没有许可证**（默认保留所有权利，法律上不可复用）；**vnpy 提供 MIT 许可的 `alpha_101.py`**，可合法自由使用——**但它实际只覆盖 82/101**：缺 alpha56（无 `cap` 字段）+ 18 个含 `IndNeutralize` 的行业中性因子（该算子整个缺失），且那 18 个因子在测试里被**静默摘掉了中性化**（见 §4.3.1）。
9. **vnpy 有测试，但只是冒烟测试**：约 100 个测试函数的断言**全部只有 `assert "data" in result.columns`**（只验"算得出"，不验"算得对"）。所以要精确表述为——**现有实现普遍缺乏「正确性证据」**，而不是"没有测试"。
10. 推荐方案：**自建轻量库（numpy/pandas，MIT）+ 六层验证协议 + 算子层 20 条测试用例**，并把 **vnpy 当作测试期的差分对拍参照**（省掉自己写第二实现的 1 人日）。工作量估算下调为 **≈3 人日**；先做算子层与 3~5 个因子试点打通，再放量到 101 个。

---

## 1. 问题陈述

原始诉求演进为三个问题，本文档逐一给出可执行结论：

| # | 问题 | 归属章节 |
|---|---|---|
| Q1 | WorldQuant 官方是否有可验证的代码或论文？ | §2 |
| Q2 | 是否值得把这个项目修复并同步到 GitHub？ | §3–§5 |
| Q3 | 如何**确切地验证**一个 Alpha101 实现是否正确？ | §6、§8 |

**范围声明**：本文档只做分析与设计。所有实测数据来自 2026-10-09 的只读检查（GitHub API、本地文件、本地 MongoDB、AST 静态分析），未执行任何因子计算。

---

## 2. WorldQuant 官方可验证性调研

### 2.1 结论表

| 问 | 答 | 证据 |
|---|---|---|
| 官方有开源代码吗？ | ❌ **没有** | [github.com/WorldQuant](https://github.com/WorldQuant) 仅 2 个公开仓库：`nixpkgs`(fork)、`gss-token`(fork)，均与因子无关；组织 `is_verified: false` |
| 《101 Formulaic Alphas》是官方论文吗？ | ❌ **不是** | 单作者 Zura Kakushadze；机构 Quantigic Solutions LLC；Wilmott Magazine 2016(84):72-80 |
| 有官方配方/表达式语言吗？ | ✅ **有，但在平台内** | WorldQuant BRAIN：官方仿真器 + Fast Expression 表达式语言 + 官方算子文档 |
| 能用它验证我的实现吗？ | ⚠️ **间接、有限** | BRAIN 验证 alpha 的**表现**（Sharpe/turnover/fitness），不验证实现一致性；且不接受外部代码 |

### 2.2 论文的准确定位（关键澄清）

社区普遍误称"WorldQuant 的 101 个 alpha"，准确事实：

| 项 | 值 |
|---|---|
| 标题 | *101 Formulaic Alphas* |
| 作者 | **Zura Kakushadze**（单作者） |
| 机构 | Quantigic Solutions LLC（**非 WorldQuant**） |
| 首次提交 | 2016-01-05（arXiv v1），v3 2016-03-18 |
| 发表 | **Wilmott Magazine 2016(84), 72–80** |
| 标识 | [arXiv:1601.00991](https://arxiv.org/abs/1601.00991)、SSRN 2701346、DOI 10.48550/arXiv.1601.00991 |
| 许可 | arXiv non-exclusive distribution license（**非** GPL/CC） |
| 篇幅 | 22 页 |

摘要原文关键句：*"We present explicit formulas - **that are also computer code** - for 101 real-life quantitative trading alphas. Their average holding period approximately ranges 0.6-6.4 days. The average pair-wise correlation of these alphas is low, 15.9%."*

**对本项目最重要的三点推论**：

1. 论文自称公式"也是计算机代码"——意味着论文的公式表**就是**规范的主要载体，这支持把它当作 L2 规范来源。
2. 论文明确给出了 **平均持仓 0.6~6.4 天**、**两两相关 15.9%** 两个可检验的统计断言 → 可当作**宏观一致性检验**（见 §6.7），但这需要 WorldQuant 同源的美股数据，A 股不可直接复现，只能作弱参考。
3. 论文**不是** WorldQuant 官方标准，也不对其实现细节（算子口径）做穷尽定义 → **"正确"只能是"与所选定规范一致"**，这是 §6 全部方法论的前提。

### 2.3 BRAIN 平台：唯一的官方裁判，但有边界

| | 说明 |
|---|---|
| 是什么 | WorldQuant 官方公开的 alpha 研究/仿真平台，用户用官方表达式语言写 alpha，平台用官方引擎给官方指标 |
| 能提供什么 | **官方算子语义**（`rank`/`ts_rank`/`decay_linear`/`ts_arg_max`/`IndNeutralize` 等的官方定义）→ 是 L2 算子口径最有价值的第二规范来源 |
| 能验证什么 | alpha 的**事后表现**与**是否通过平台门槛**，不是"你的 Python 实现是否等价于论文原式" |
| 不能做什么 | 不接受外部代码；算子在平台内不可见实现；需注册；文档登录可见（社区有镜像，如 [alexisdpc/WorldQuant-alpha-trading](https://github.com/alexisdpc/WorldQuant-alpha-trading)） |
| 建议用法 | ① 取官方算子文档校准口径（**待办：本项目尚未获取**）② 对少数因子做"行为对齐"抽样（把实现值 vs 平台值做单调性/相关性比较，而非数值相等） |

### 2.4 对验证协议的含义（规范等级）

```
规范权威度排序：
  L-A 论文 arXiv:1601.00991 公式表        ← 因子结构的唯一权威
  L-B BRAIN 官方算子文档                   ← 算子语义的最强参考（待获取）
  L-C 数学定义 + 独立权威实现               ← 算子层可 100% 判定（scipy/pandas/statsmodels）
  L-D 社区实现（vnpy MIT'ed 等）           ← 差分测试参照，不具权威性
  L-E 中文平台公式（如本项目 README 表）    ← 语义体系不同（hrankscore/barcorr/decayMA），仅供参考经济含义
```

⚠️ **重要提醒**：本项目 README 里那份中文公式表（`hrankscore`/`barcorr`/`barref`/`decayMA`/`N日均成交金额`）**是第三套算子语义**，与论文体系不同。**不要用它做正确性判定**，只用它理解因子的经济含义（趋势/反转/量价背离）。

---

## 3. 资产现状实测（QAFactor_Alpha101）

### 3.1 结构

| 文件 | 规模 | 职责 | 可用性 |
|---|---|---|---|
| `alpha101.py` | 928 行 | **101 个因子（编号 1–101 无缺失）** + 20 个算子 + 3 个中性化函数 | ✅ 核心资产 |
| `func.py` | 118 行 | 另一套 18 个算子 | ❌ **死代码**：引用 `self.rolling_rank`、未导入的 `ta`/`np`；且 `alpha101.py` 从未 import 它 |
| `test_101.py` | 48 行 | 唯一案例（分层回测） | ⚠️ 需大改 |
| `data_export_swl2_month.csv` | 3922 × 68 | 申万二级行业月度分类（GBK，2015-01~2020-08） | ⚠️ 非 PIT |
| `README.md` | 119 行 | 中文因子注释表（价格类/量价类/二分类） | ✅ 理解含义的最佳材料 |
| `LICENSE` | 674 行 | **GPL-3.0** | ⚠️ 见 §4.4 |

依赖极轻：仅 `scipy/numpy/pandas/matplotlib/dateutil`，**不依赖 talib，不依赖 QUANTAXIS**，AST 检查无未定义全局名 → 是个**干净可移植的公式库**。

### 3.2 因子依赖结构（精确影响面）

| 依赖项 | 因子编号 | 数量 |
|---|---|---|
| 行业中性化 `ind` 入参 | 48, 58, 59, 63, 67, 69, 70, 76, 79, 80, 82, 87, 89, 90, 91, 93, 97, 100 | **18** |
| `decay_linear` | 31, 39, 57, 58, 59, 63, 66, 71, 72, 73, 76, 77, 82, 87, 88, 89, 91, 92, 93, 96, 97, 98 | **22** |
| `returns` | 1, 8, 14, 19, 25, 29, 34, 35, 36, 39, 52, 56 | 12 |
| `scale` | 28, 29, 31, 32, 60, 100 | 6 |
| `cap` | **56（唯一）** | 1 |

**输入面板只需 9 个字段**：`close / Open / high / low / volume / vwap / returns / cap / ind`。

**★ 关键工程发现**：101 个因子有 **71 种不同的形参组合**，但**形参"名字"只有上述 9 种**。因此批量调用**不需要** 101 条映射表，可用 `inspect.signature` **按名字自动装配**（见 §7.5）。

### 3.3 缺陷清单（8 类，含行号）

| # | 严重度 | 缺陷 | 位置 | 影响面 |
|---|---|---|---|---|
| 1 | 🔴 | `df.as_matrix()` 已于 pandas 1.0 删除 → `AttributeError` | `alpha101.py:140`（`decay_linear`） | **22 个因子必崩** |
| 2 | 🔴 | `alpha1` 原地改写入参：`x = close; x[returns<0] = ...`（别名非拷贝） | `alpha101.py:154-155` | **批量运行时污染整个 close 面板** |
| 3 | 🟠 | `scale()` 求和轴错：`df.div(np.abs(df).sum())` 按列求和并沿列对齐；论文定义为**每日截面**求和 | `alpha101.py:118` | 6 个因子 |
| 4 | 🟠 | `IndNeutralize` 逐日 Python 循环 + `la.inv` → 慢；行业含 NaN 时矩阵奇异 → `LinAlgError` | `alpha101.py:42` | 18 个因子 |
| 5 | 🟠 | 案例分层函数 `data.selects(list_of_codes, ...)` 与当前 QA 版 `selects(code,start,end)` 不兼容 | `test_101.py:40` | 案例不可运行 |
| 6 | 🟡 | `ts_rank` 返回窗口内末值**序号**（1..n），而 `rank()` 返回**截面 pct**，量纲混用 | `alpha101.py:75,113` | 多处表达式 |
| 7 | 🟡 | 101 个因子几乎全部以 `.fillna(0)` 收尾 → "数据不足"与"真值 0"不可区分，制造虚假单调性 | 全文 | 全体 |
| 8 | 🟡 | 零测试、零基准值 → 除 `alpha101` 这类一眼可验者外，无法确认是否复现原式 | — | 全体 |

**附加环境冲突**：本地 `qa` 环境是 **pandas 2.3.3**（QUANTAXIS 2.1.0a2 editable 安装指向 `/home/yinxiuqu/quantaxis`），与 2021 年写法正面冲突；`fillna(method=)` 在 pandas 2.x 已废弃。

### 3.4 官方案例 `test_101.py` 的真实行为（重要澄清）

```python
x = alpha101(close, Open, high, low)     # ← 这是第 101 号因子本身！
pxx = test_factor(x, 10, 60)             # 10 层、60 天
pxx.plot(figsize=(20,8))
```

- `alpha101(...)` 是**因子 #101**（`(close-Open)/(high-low+0.001)`，日内反转），**不是**批量入口。
- 模块名 `alpha101`、文件名 `test_101`、函数名 `alpha101` 三重同名，造成极强误导。
- **项目内不存在任何批量运行 101 个因子的代码。**
- 案例另有 5 处硬伤：硬编码内网 IP `192.168.114.21`（实测不可达）、`selects` 传 list、行业用固定 2017-01 快照（非 PIT）、样本仅上证 50、无 IC/t 值/成本/换手。

---

## 4. 生态与许可证调研

### 4.1 上游元数据（2026-10-09 实测）

| 指标 | 值 |
|---|---|
| 仓库 | [yutiansut/QAFactor_Alpha101](https://github.com/yutiansut/QAFactor_Alpha101) |
| 星标 / fork / watchers / 订阅 | 51 / **35** / 51 / 4 |
| open issues | **0** |
| 最后推送 | **2021-03-25** |
| 创建 | 2020-08-05 |
| 提交数 | **1**（本地为浅克隆，亦为 1） |
| 许可证 | **GPL-3.0** |
| 体积 | 93 KB |
| 归档 | 否（但实质停摆 5 年） |

### 4.2 ★ 35 个 fork 全部是僵尸

逐个检查 fork 列表：**每一个 fork 的 `pushed_at` 都等于 `2021-03-25`**，即全部是"拷走未改"的副本，五年内**无一人修复过它**。

双重解读：
- **需求端弱**：真需要的人要么自己重写了，要么用了别的库。
- **供给端成本高**：想改的人评估后放弃（pandas 兼容 + GPL 是主因）。
- 唯一利好：**若你做到"带验证套件"，你确实是头一个**。但"头一个修好一份没人用的代码"≠ 有价值。

### 4.3 替代实现对比

| 实现 | 星标 | 许可证 | 活跃度 | 覆盖度 | 正确性证据 | 可否合法复用 |
|---|---|---|---|---|---|---|
| QAFactor_Alpha101 | 51 | **GPL-3.0** | ☠️ 2021 停更 | **101/101** | ❌ 无（22 个因子在 pandas≥1.0 下必崩） | 可以，但衍生作品必须继续 GPL |
| [yli188/WorldQuant_alpha101_code](https://github.com/yli188/WorldQuant_alpha101_code) | **878** | **⚠️ 无许可证** | ☠️ 2019 停更（4 open issues） | 未核 | 未核 | ❌ **默认保留所有权利，法律上不可用** |
| [vnpy `alpha_101.py`](https://github.com/vnpy/vnpy/blob/master/vnpy/alpha/dataset/datasets/alpha_101.py) | vnpy 数万星 | **MIT** | ✅ 活跃维护 | **仅 82/101** | ⚠️ **仅冒烟测试** | ✅ **可自由使用/修改/商用** |
| [YutaoWang03/Quant-Alpha101](https://github.com/YutaoWang03/Quant-Alpha101) | — | 待核 | — | 待核 | 待核 | 中文文档版 |
| [laozdao A101 分析](https://github.com/laozdao/dao-quant-research/blob/main/articles/M06-factor-validation/M06-07-worldquant-alpha101-analysis.md) | — | — | — | 研究文章 | — | 参考 |

**三个决定性发现**：
1. 最流行的实现（878 星）**无许可证** —— 比 GPL 更糟，连复制都不允许。说明这个领域"能用"的实现极其稀缺。
2. **vnpy 已在 MIT 下提供 `alpha_101.py` 且活跃维护**（本机 vnpy 3.3.0 尚无 `vnpy.alpha`，该模块为 4.x 新增，升级即得）。这**抹掉了"修复 QAFactor 以填补低端空白"的正当性**——低端已被更好的许可证占了。
3. **但 vnpy 没填的是「正确性证据」这个高端空白**：它只证明"算得出"，不证明"算得对"，且缺 19 个因子。**这正是本项目要占的位置。**

### 4.3.1 vnpy 实现逐行核查（2026-10-09 新增）

**① 覆盖度：只有 82/101**

| 缺口 | 因子 | 数量 | 源码原话 |
|---|---|---|---|
| 缺 `cap` 字段未实现 | alpha56 | 1 | `# Alpha56 (missing cap field, cannot be implemented)` |
| `IndNeutralize` 未实现而注释掉 | 48, 58, 59, 63, 67, 69, 70, 76, 79, 80, 82, 87, 89, 90, 91, 93, 97, 100 | **18** | `# Alpha58 (contains IndNeutralize, currently not implemented)` |

📌 **巧合也是铁证**：缺的正是 `QAFactor_Alpha101` 需要 `ind` 入参的**同一批 18 个因子**。两个独立实现撞上同一堵墙 → `IndNeutralize` 是这条路线的真正分水岭，**也是本项目最硬的差异化点**。

**② 测试性质：冒烟测试（smoke test），非正确性验证**

`tests/test_alpha101.py`（35 KB，约 100 个测试函数，除 56 外每因子一个），**每个测试体的断言只有一句**：

```python
def test_alpha58(self, test_df):
    expr = "(-1) * ts_rank(ts_decay_linear(ts_corr(vwap, volume, 4), 8), 6)"
    result = calculate_by_expression(test_df, expr)
    assert "data" in result.columns          # ← 全部断言仅此一句
```

| 测了 | 没测 |
|---|---|
| ✅ 表达式可解析、可执行、不抛异常 | ❌ 任何数值正确性（无期望值、无基准对拍） |
| ✅ 脏数据不崩：50 只 × 300 天，**注入 NaN close、volume=0、close=1e-10** | ❌ 算子口径正确性、与前视检验 |
| — | ❌ 与论文公式的一致性 |

配套另有 3 个小算子测试（`tests/alpha/test_cs_function.py` 1.7 KB、`test_ta_function.py` 2.6 KB、`test_expression.py` 1.8 KB），规模很小，**未逐行核对**。

**③ 最关键发现：18 个因子在测试中被静默摘掉了中性化**

| 因子 | 论文原式（含中性化） | vnpy 测试里的表达式 |
|---|---|---|
| Alpha58 | `-1 * ts_rank(decay_linear(correlation(**IndNeutralize(vwap, sector)**, volume, 4), 8), 6)` | `(-1) * ts_rank(ts_decay_linear(ts_corr(vwap, volume, 4), 8), 6)` |
| Alpha48 | `**indneutralize**(..., subindustry) / sum(...)` | `(ts_corr(...) * ts_delta(close,1)) / close / ts_sum(...)` |

**`IndNeutralize` 被移除，测试照样通过**——因为断言只检查"有没有算出列"。这是「有测试 ≠ 有验证」的教科书案例，也直接支撑 §6 的验证协议设计。

**④ 值得肯定的部分（比预期强）**

- ✅ **MIT 许可**，法律上完全干净
- ✅ **作者主动标注了 2 处偏差**（专业做法）：
  ```python
  # Alpha21 (the innermost original was >=1, implemented as >1)
  # Alpha24 (the original condition was <=0.05, implemented as <0.05)
  ```
- ✅ 算子分三类（`cs_function` 截面 / `ts_function` 时序 / `ta_function`），用 **polars** 做表达式引擎，性能好
- ✅ 配了完整全栈：`factor_performance.py`（39 KB）、`lab.py`（16 KB）、`model/`、`strategy/`，可直接接机器学习
- ✅ 脏数据用例设计不错（NaN / 零成交量 / 极小价格全覆盖）

**⑤ 代价与依赖**

- 依赖 **polars + vnpy 4.x 全栈**（本机 vnpy 3.3.0 无 `vnpy.alpha`，需升级整个交易框架）
- 因子是**表达式字符串**（自有 DSL：`cs_rank`/`quesval2`/`ts_decay_linear`…），不是 Python 函数；脱离 vnpy 使用等于连引擎一起搬

**⑥ 结论：vnpy 的定位是「基线 + 差分参照」，不是「替代品」**

| | vnpy 解决了 | vnpy 没解决（= 本项目要做的） |
|---|---|---|
| 能不能算 | ✅ 82 个因子开箱即用 | — |
| 算得对不对 | ❌ | ✅ golden 快照 + 算子 1e-10 对拍 + 变异测试 |
| 覆盖度 | ❌ 82/101 | ✅ 补齐 19 个（含 18 个中性化 + alpha56） |
| 可判定状态 | ❌ 仅 2 条行内注释 | ✅ `verified`/`partial`/`ambiguous` + 偏差清单 + 歧义清单 |

> **一句话：vnpy 解决"能不能算"，本项目解决"算得对不对"。前者人家免费给了，后者是生态真空白。**

### 4.4 GPL-3.0 义务分析（一票否决项）

| 你想做的事 | GPL-3.0 允许吗 |
|---|---|
| fork、修改、自己用（不分发） | ✅ 允许，无义务 |
| fork 后发布修改版 | ✅ 允许，但**整个衍生作品必须继续 GPL-3.0**，保留版权声明、提供完整源码 |
| **把代码改成 MIT/Apache 发布** | ❌ **违约** |
| 把代码拷入 `quantming` 内部使用 | ✅ 只要不分发即无义务 |
| **`quantming` 对外发布**（公众号贴代码、开源策略框架、交付客户） | ❌ **触发 GPL 传染，衍生部分需开源** |

对量化项目，最后一行是实打实的商业风险。

### 4.5 clean-room 重写的法律逻辑

> **数学公式与算法思想不受版权保护，受保护的是"表达"（具体代码文本）。**
> 只依据公开论文（arXiv:1601.00991）独立实现 → **不产生 GPL 衍生关系** → 可自选 MIT/Apache-2.0/私有许可。

**clean-room 纪律**（自证清白的依据，必须留痕）：
1. 实现时只打开论文，**不打开** `alpha101.py`。
2. 保留实现日志：每个因子记录"来源 = 论文第 X 节公式 Y"。
3. 若确需参考原实现对齐某算子口径 → **同时承认 GPL 约束**，不能两头占。
4. **反直觉推论**：一旦决定 clean-room 重写，`QAFactor_Alpha101` 的剩余价值退化为「**README 的中文因子注释表**」（注释与分类，非代码表达，可合法参考）。**你真正想要的那部分，本来就不需要动它的代码。**

---

## 5. 决策

### 5.1 四个方案对比

| | A 不动 | B clean-room 重写（推荐） | C 低成本善意 | D 修复原仓库并发布 |
|---|---|---|---|---|
| 动作 | 只当公式字典/注释表用 | 从论文独立实现 + 六层验证套件，自选宽松许可 | 给上游开 issue 列 8 类缺陷 + 复现步骤 | fork GPL 代码，修 8 类 bug，公开发布 |
| 工作量 | 0 | **≈3 人日**（vnpy 作参照后，见 §5.3） | **1 小时** | 1~2 人日修复 + 1 人日打包发布 |
| 许可 | 无影响 | 自选（建议 MIT/Apache-2.0） | 无 | 被迫 GPL-3.0 |
| 差异化 | — | ✅ **"可验证"是生态真空白** | — | ❌ 追平 vnpy 已有能力（且仍缺 19 个） |
| 风险 | 无 | 低 | 无 | 中（GPL 传染、维护负担、零收益） |
| 结论 | 可作降级方案 | ✅ **推荐** | ✅ 建议附带做 | ❌ **不做** |

**明确禁止**：
- ❌ 直接 fork GPL 代码改成 MIT 发布（违约）
- ❌ 把 GPL 代码并入将来要发布的 `quantming`（传染）
- ❌ 为了"修一个五年无人问津的仓库"投入 3 天

### 5.2 唯一有价值的发布定位

发布卖点**绝不能是"修好的 Alpha101"**（红海，且追不上 vnpy 的许可优势与 yli188 的星标优势）。现有实现的真实短板要精确表述：

| 实现 | 有无测试 | 短板 |
|---|---|---|
| vnpy | ⚠️ **有冒烟测试**（约 100 个，断言仅 `"data" in result.columns`） | **没有正确性证据**；缺 19 个因子；18 个因子被摘掉中性化 |
| yli188（878 星） | ❌ 无 | 无许可证，法律上不可用 |
| QAFactor_Alpha101 | ❌ 无 | 22 个因子在 pandas≥1.0 必崩；GPL |

> **因此差异化不是"我有测试"，而是"我能证明算得对"**：无算子对拍、无 golden 基准、无前视/不变量检验、无偏差清单、不说明"哪几个因子论文本身就没写清"。

> **值得发布的唯一形态：一份「可验证的 Alpha101」**
> = clean-room 实现（许可自由）
> + 一套能证明它对不对的测试套件（§6/§8）
> + 《与论文的偏差清单 + 规范歧义清单》（诚实标注哪些无法判定）
> + A 股落地口径适配（复权/单位/PIT 行业/真换手率）

**副作用利好**：这天然是公众号文章的好选题——"我怎么证明 101 个因子算对了"远比"101 个因子清单"有价值。

### 5.3 推荐路线：「vnpy 参照 + 自建验证层」（v0.2 新增）

**不是二选一。** 分工如下：

```
┌─ 库本体（发布物）   numpy / pandas，MIT，clean-room 从论文自写因子层 + 补齐 19 个缺口
├─ 测试期依赖        vnpy 4.x（MIT）→ 差分对拍参照 + 算子口径第二意见（仅出现在 tests/）
├─ 本地一次性对比    QAFactor_Alpha101（GPL）→ 只跑数值不搬代码（可选；使用软件不受限）
└─ 交付差异化        101/101 + 正确性证据 + verified/partial/ambiguous 清单
```

**为什么这样最优**：

| 收益 | 说明 |
|---|---|
| **省掉 1 人日** | 文档 §6.4 原本要求"自己再写第二实现"做差分测试——**vnpy 就是现成的第二实现**：不同作者、不同语言（polars DSL vs pandas）、不同引擎，独立性比自写还好 |
| **算子层有参照** | `vnpy/alpha/dataset/{cs,ts,ta}_function.py` 是 20 个算子口径的现成第二意见（MIT，参考需署名），M1 减半 |
| **公式转写有参照** | 82 个已实现的表达式可用来交叉验证转写，M3 减 1/3 |
| **差异化依然完整** | vnpy 的三大空白（正确性证据 / 19 个缺口 / 可判定状态）**一件都没做** |

**法律边界（务必遵守）**：

| 来源 | 许可 | 允许 | 禁止 |
|---|---|---|---|
| vnpy | MIT | 参考算子口径；用于差分对拍；**署名后复用代码** | （无重大限制，注意署名与保留许可声明） |
| QAFactor_Alpha101 | GPL-3.0 | **本地跑它做数值对比**（使用软件不受限） | **把它的代码搬进要发布的库**（传染） |
| 论文 arXiv:1601.00991 | arXiv 非独占许可 | 依据公式独立实现 | 直接拷贝论文表达（不大可能触及，公式本身不受版权保护） |

**如果只想"马上用起来"**：装 vnpy 4.x，`from vnpy.alpha.dataset.datasets.alpha_101 import Alpha101`，接受 82 个因子 + "算得出但不保证对"，**别做开源项目**。但只要你想发布/想要"可验证"这个卖点，就必须走本路线。

---

## 6. 验证协议（六层）

### 6.1 前提：规范等级与"可判定性"

> **"正确"必须相对于一个选定的规范来定义。** 论文有歧义 → 不存在绝对正确的"标准答案"。

因此把验证拆成三层可判定性：

| 层 | 可判定性 | 依据 |
|---|---|---|
| **算子层（L1）** | ✅ **可 100% 判定** | 算子有唯一数学定义，且有独立权威实现可对拍（scipy/pandas/statsmodels） |
| **因子层（L2-L3）** | ⚠️ **可判定"与所选规范一致 + 与独立实现一致"** | 论文公式表（规范）+ 独立双实现（差分） |
| **语义层（L6）** | ❌ **无法判定，只能记录** | 论文自身歧义、数据源差异 |

**执行顺序固定**：L1 → L2/L3 → L4 → L5 → L6。**L1 不过，后面全部无意义。**

### 6.2 L1 · 算子层验证（先做这个）

因子的错误 90% 出现在算子层。**20 个算子的具体测试用例见 §8**，此处只定判据：

- 数值对拍容差：`rtol = 1e-10`
- **判据：20/20 全通过。这一层没有"大概对"，只有对/错。**
- 必须**钉死并写入文档**的口径分歧点：`stddev` 的 ddof、`rank` 是否 pct、`ts_rank` 是否归一化、`ts_argmax` 的基准与方向、`correlation` 遇常数序列的行为。

### 6.3 L2 · 规范对照（结构一致性）

把**论文附录每个 alpha 的公式**解析成算子树，与实现的 AST 算子树**逐节点比对**，输出三分类：

| 分类 | 含义 | 处置 |
|---|---|---|
| **等价** | 算子树同构（含交换律/结合律的等价变形） | 可进 verified 流程 |
| **近似** | 结构相同但有明确差异（少一个 `rank`、`adv20` 用 volume 替代、常量不同） | 列出差异 + 影响评估 |
| **偏离** | 结构不同 / 有笔误嫌疑 | **剔除，不进统计** |

**产出物：《与论文的偏差清单》**（101 行，每个因子一行）。在"论文为规范"的前提下，这是**可判定**的结论。

### 6.4 L3 · 独立双实现差分测试（最强的正确性证据）

工业界证明"实现没写错"的标准做法。**v0.2 起：第二实现不再需要自写，直接用 vnpy。**

**实现 A（自有）**：from 论文、pandas/numpy、clean-room 自写。
**实现 B（参照）**：**vnpy 的 polars DSL 实现**（MIT，不同作者/不同语言/不同引擎 → 独立性比自写还好）。⚠️ 只覆盖 82 个，且 18 个因子被摘掉中性化，因此**对拍范围仅限这 82 个**。

对拍流程：
1. 把同一份面板分别喂给 A 和 B（vnpy 走 `calculate_by_expression`）。
2. **先做语义归一化**（这是对拍成败的关键）：
   - `cs_rank` → A 的 `rank`（pct 口径是否一致）
   - `ts_rank` → 序号 vs pct 口径
   - `quesval/quesval2` → 条件分支的边界（**vnpy 自己标注了 alpha21 的 `>=1` 改 `>1`、alpha24 的 `<=0.05` 改 `<0.05`**，这类边界差异必须单独列为"已知差异"而非判错）
   - NaN 填充策略、`ts_decay_linear` 的权重方向、`ts_argmax` 基准
3. **逐点对拍** `np.allclose(rtol=1e-8)`，不一致 → 二分定位到具体算子（L1 已保证算子正确，差异必然在公式转写或上述语义）。
4. 差异**归因分类**：`口径差异（可接受，记录）` / `实现 bug（必须修）` / `论文歧义（列入 ambiguities）`。**严禁简单判错。**

**可选第三意见**：本地跑 `QAFactor_Alpha101` 做数值对比（**使用软件不受 GPL 分发限制，但绝不把其代码搬进仓库**）。

**判据**：82 个可比因子全部 `allclose` 或差异已归因；剩余 19 个（vnpy 未实现）只能靠"论文规范对照 + 不变量"验证，**无法做差分**——这一点必须在 `docs/verification.md` 里如实标注。

### 6.5 L4 · 不变量与元测试

> ⚠️ **逻辑定位**：以下是**必要条件，不是充分条件**——**通不过一定错，通过了不代表对**。

| 测试 | 方法 | 判据 |
|---|---|---|
| **缩放不变性** | `close/high/low/open × k`（k>0）后重算 | 排序型因子的**排序结果必须完全不变**；若变了 → 误用绝对价格 |
| **平移不变性** | 价格整体 `+c` | 多数 A101 因子排序应不变 |
| **★ 时间截断一致性（PIT 金标准）** | 用 `[0,T]` 全量算 vs 用 `[0,t]` 截断算，比较 t 时刻 | **必须逐点完全相等**（这是最通用、最强的前视检测，一条顶十条） |
| **未来扰动** | 随机篡改 t 之后的数据 | t 及之前的值必须不变 |
| **变异测试（测试的测试）** | 故意注入已知 bug（如 `scale` 的 axis 反转、`rank` 改 `pct=False`、`decay_linear` 权重反序） | **测试必须失败**——否则证明测试套件是摆设 |
| **边界/脏数据** | NaN、±inf、`volume=0`（vwap→inf）、长期停牌、新股、涨跌停、单成分股行业 | 不崩、不产生 inf、行为有明确定义 |
| **输入不可变性** | 调用前后对入参面板做 `assert_frame_equal` | **入参必须一字未变**（专治 §3.3 缺陷 2） |

### 6.6 L5 · golden 快照（防回归）

构造**小规模确定性数据集**（固定随机种子，如 5 只股票 × 250 天），把 101 个因子的输出**冻结为数值基线/哈希**，接入 CI。任何改动（含无意的 pandas/numpy 升级）立即暴露。**这是唯一能防止"半年后悄悄算错"的机制。**

### 6.7 L6 · 统计合理性（最弱，仅作辅助）

| 检验 | 说明 |
|---|---|
| IC 符号一致性 | 与因子经济分类（趋势/反转/量价背离）方向是否一致 |
| IC 随 horizon 衰减形状 | A101 平均持仓 0.6~6.4 天 → 日频/短周期应最强 |
| 暴露检查 | 行业/市值暴露是否符合预期 |

⚠️ **必须警惕**：**统计显著 ≠ 实现正确，统计不显著 ≠ 实现错误。** A 股上 A101 大面积失效完全正常（论文基于美股）。**永远不要用 IC 好看来"证明"代码对。**

📌 论文给出的两个统计断言（平均持仓 0.6~6.4 天、两两相关 15.9%）**可用于宏观一致性参考，但需同源美股数据**，A 股不可直接复现，只能作弱参考。

### 6.8 `verified` 判据表

| # | 门槛 | 权重 |
|---|---|---|
| 1 | 算子层 20/20 通过（§8） | 必需 |
| 2 | 规范对照为「等价」（或差异已明确记录且不影响） | 必需 |
| 3 | 独立实现逐点 `allclose(rtol=1e-8)` | 必需 |
| 4 | 时间截断一致性 + 缩放不变性 + 入参不可变性 通过 | 必需 |
| 5 | golden 快照已入库 | 必需 |
| 6 | 第三方（vnpy）对拍一致，或差异已归因 | 加分 |

**六条全满足 → `verified`；缺任一条 → `partial` 或 `ambiguous`（必须写明缺哪条、为什么）。**

**诚实的预期管理**：受论文歧义所限，**`verified` 不可能是 101/101**，预估 **60~80 个**，其余应老实标 `ambiguous` 并列出歧义点。**敢于标注"这 20 个我无法验证"比假装全都对更有价值**——这正是现有那 878 星实现没做的事，也是本项目的差异化核心。

---

## 7. clean-room 重写工程方案（方案 B）

### 7.1 目标与非目标

| | 内容 |
|---|---|
| **目标** | ① 从论文独立实现 101 个因子 ② 20 个算子 100% 可判定 ③ 六层验证套件 ④ 偏差/歧义清单 ⑤ A 股口径适配层 ⑥ CI 可复现 |
| **非目标** | ❌ 不做回测框架 ❌ 不做因子挖掘/合成 ❌ 不做数据采集 ❌ 不追求"跑赢市场" ❌ 不依赖 QUANTAXIS/ClickHouse |
| **许可** | MIT 或 Apache-2.0（**不得**引入 GPL 代码） |
| **依赖约束** | 仅 `numpy / pandas / scipy`；测试用 `pytest`；`statsmodels` 仅测试期用于对拍 |

### 7.2 仓库结构（建议）

```
alpha101-verified/
├── LICENSE                     # MIT / Apache-2.0
├── README.md                   # 含"可验证"定位、verified/ambiguous 统计
├── docs/
│   ├── operators.md            # 20 算子口径定义（含所有歧义点决策记录）
│   ├── deviations.md           # 与论文的偏差清单（101 行）
│   ├── ambiguities.md          # 规范歧义清单 + 无法判定的因子
│   └── verification.md         # 六层协议与验证结果矩阵
├── src/alpha101v/
│   ├── operators.py            # 20 个算子（纯函数，输入 DataFrame，返回 DataFrame）
│   ├── neutralize.py           # IndNeutralize（向量化）
│   ├── factors.py              # 101 个因子，统一签名 fn(p: Panel) -> DataFrame
│   ├── registry.py             # 因子注册表 + 元信息（verified/ambiguous、论文出处）
│   ├── panel.py                # 面板契约与校验（PIT、单位、最小字段）
│   └── adapters/               # 数据适配（可选）：mongo / parquet / 通用 DataFrame
├── tests/
│   ├── test_operators.py       # §8 的 20 条用例
│   ├── test_invariants.py      # 缩放/平移/截断/未来扰动/入参不可变
│   ├── test_edge_cases.py      # NaN/inf/停牌/新股
│   ├── test_mutation.py        # 变异测试（故意注入 bug，断言测试会失败）
│   ├── test_conformance.py     # 规范对照：101 个因子的结构断言
│   └── golden/                 # golden 快照基线
├── tools/
│   ├── conformance_report.py   # 生成偏差清单
│   └── differential.py         # 双实现/第三方差分对拍
└── .github/workflows/ci.yml
```

### 7.3 算子层 API 设计

**统一约定（写进 `docs/operators.md`，这是验证的地基）**：

```python
# 约定：所有算子输入/输出均为 DataFrame（index=交易日, columns=股票代码）
# 时间序列算子沿 axis=0（时间）滚动；截面算子沿 axis=1（截面）计算
def ts_sum(df, window: int) -> pd.DataFrame: ...
def sma(df, window: int) -> pd.DataFrame: ...
def stddev(df, window: int, ddof: int = 1) -> pd.DataFrame: ...   # ★ ddof 显式化
def correlation(x, y, window: int) -> pd.DataFrame: ...
def covariance(x, y, window: int) -> pd.DataFrame: ...
def ts_rank(df, window: int, pct: bool = True) -> pd.DataFrame: ...  # ★ pct 显式化
def product(df, window: int) -> pd.DataFrame: ...
def ts_min(df, window: int) -> pd.DataFrame: ...
def ts_max(df, window: int) -> pd.DataFrame: ...
def delta(df, period: int = 1) -> pd.DataFrame: ...
def delay(df, period: int = 1) -> pd.DataFrame: ...
def rank(df) -> pd.DataFrame: ...          # 截面 pct rank, axis=1
def scale(df, k: float = 1) -> pd.DataFrame: ...   # 每日 Σ|x| = k （axis=1！）
def ts_argmax(df, window: int) -> pd.DataFrame: ...  # ★ 基准/方向显式化
def ts_argmin(df, window: int) -> pd.DataFrame: ...
def decay_linear(df, period: int) -> pd.DataFrame: ...  # 权重 1..d/(d(d+1)/2)
def ind_neutralize(df, industry: pd.Series) -> pd.DataFrame: ...  # 向量化，残差与哑变量正交
```

**设计原则**：把所有已知歧义点（ddof / pct / argmax 基准 / scale 轴向）**做成显式参数或显式文档决策**，而不是隐式行为。这样"口径"本身可被测试。

### 7.4 面板契约（`panel.py`）

| 字段 | 要求 |
|---|---|
| `close/Open/high/low` | 前复权价；与收益口径配对（复权一致性断言） |
| `volume` | 单位：**手**（或统一为股，但必须显式声明） |
| `amount` | 单位：**元** |
| `vwap` | **`amount / (volume * 100)`**（在"手+元"约定下）——已在真实数据上实测确认 |
| `returns` | 由前复权 close 计算 |
| `cap` | 市值（建议 `total_mv`，单位万元，需显式声明） |
| `ind` | 行业分类，**必须 PIT/as-of**，覆盖不足时明确降级策略 |

**必须实现的校验**：① 索引单调递增 ② 单位一致性 ③ **PIT 校验（任意字段不得含未来信息）** ④ 最小历史长度（满足最大窗口 250 日）⑤ 列集合一致性。

### 7.5 因子注册与自动分发（`registry.py`）

**★ 关键技巧**：101 个因子的形参组合有 71 种，但**形参名字只有 9 种** → 可用 `inspect.signature` 按名字自动装配，**无需 101 条映射表**：

```python
def run_factor(name: str, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    fn = REGISTRY[name].func
    kwargs = {p: panel[p] for p in inspect.signature(fn).parameters}
    return fn(**kwargs)
```

⚠️ **前提**：① 每个因子调用前对面板做**深拷贝或写保护**（防入参污染，见 §6.5"输入不可变性"）② 注册表同时记录 `verified`/`ambiguous` 状态与论文出处。

### 7.6 测试与 CI

| 层 | 内容 |
|---|---|
| CI 触发 | push / PR；固定 `numpy/pandas` 版本矩阵（如 pandas 2.2 / 2.3） |
| 单元 | `pytest tests/test_operators.py -v` → 20/20 必须通过 |
| 不变量 | `pytest tests/test_invariants.py` → 含时间截断一致性（耗时可观，可用小面板） |
| 变异 | `pytest tests/test_mutation.py` → **断言"注入 bug 后测试失败"**，防止套件退化 |
| golden | 快照比对，失败即阻断 |
| 报告 | CI 产出 `docs/verification.md` 的 verified/ambiguous 统计表 |

### 7.7 里程碑与工作量

| 里程碑 | 内容 | 估算（v0.1） | 估算（v0.2，vnpy 参照后） | 变化原因 |
|---|---|---|---|---|
| **M0** | 仓库骨架 + LICENSE + 面板契约 + CI 空跑 | 0.5 | 0.5 | — |
| **M1** | 20 个算子 + §8 全部用例通过（**最关键**） | 1 | **0.5** | vnpy `{cs,ts,ta}_function.py` 提供算子口径参照 + 对拍 |
| **M2** | 3~5 个因子端到端试点（建议 `alpha101`(可手算)、`alpha4`、`alpha5`、`alpha41`、`alpha56`(唯一用 cap，vnpy 缺)）+ L2/L3/L4 全跑 | 1 | 1 | 不变（要真做对） |
| **M3** | 101 个因子全量实现 + 规范对照 + 偏差清单 | 1.5 | **1** | 82 个有 vnpy 表达式可交叉验证；**19 个缺口仍须自己补** |
| **M4** | 差分对拍（vnpy B 实现）+ 差异归因 | 1 | **0.2** | **第二实现直接用 vnpy，不必自写** |
| **M5** | golden 快照 + 文档（deviations/ambiguities/verification）+ 发布 | 1 | 1 | — |
| **合计** | | **5~6 人日** | **≈3 人日** | 省 2~3 人日（不含数据适配） |

⚠️ **19 个缺口无法借力 vnpy**（18 个中性化因子 + alpha56），**必须自研**：其中 `IndNeutralize` 的向量化实现是本项目最硬的技术活，也是最核心的差异化——两个主流实现（vnpy、QAFactor）都栽在这里。

**⚠️ 不要一上来做 M3。** 一旦口径有问题（复权/单位/PIT/算子），你会拿 101 个因子做一次大规模错误实验并全部返工。**M2 的 3~5 个因子试点能在半天内把口径钉死。**

---

## 8. 算子层测试用例表（可直接照着写测试）

**约定**：下列用例中，`df` 为 `DataFrame`；A 组为单列时间序列样例，B 组为多列截面样例。所有期望值均在"标准口径"下给出。

### 8.1 时间序列算子（A 组）

设 `x` 为单列序列 `[1, 2, 3, 4, 5]`（index = 5 个连续交易日）。

| 算子 | 调用 | 期望输出 | 断言要点 | 歧义点/备注 |
|---|---|---|---|---|
| `ts_sum` | `ts_sum(x, 3)` | `[NaN, NaN, 6, 9, 12]` | 前 `window-1` 为 NaN | min_periods 策略须显式 |
| `sma` | `sma(x, 3)` | `[NaN, NaN, 2, 3, 4]` | 等权 | — |
| `stddev` | `stddev(x, 3)` | ddof=1 → `[NaN,NaN,1,1,1]`；ddof=0 → `[NaN,NaN,0.8165,0.8165,0.8165]` | **必须选定 ddof 并断言** | ★ pandas 默认 ddof=1、numpy 默认 0，社区分歧点 |
| `delta` | `delta(x, 1)` | `[NaN, 1, 1, 1, 1]` | — | — |
| `delta` | `delta(x, 2)` | `[NaN, NaN, 2, 2, 2]` | — | — |
| `delay` | `delay(x, 2)` | `[NaN, NaN, 1, 2, 3]` | — | — |
| `ts_min` | `ts_min(x, 3)` | `[NaN, NaN, 1, 2, 3]` | — | — |
| `ts_max` | `ts_max(x, 3)` | `[NaN, NaN, 3, 4, 5]` | — | — |
| `product` | `product(x, 2)` | `[NaN, 2, 6, 12, 20]` | — | — |
| `ts_rank` | `ts_rank([1,2,3], 3)` 末值 | 序号口径 → `3`；pct 口径 → `1.0` | **必须选定口径并断言** | ★ 原实现返回**序号**（`rankdata(...)[-1]`） |
| `ts_argmax` | `ts_argmax([1,3,2], 3)` | 1-based 自窗口起点 → `2`；"距今几天"→ `1` | **必须选定基准并断言** | ★ 原实现 `np.argmax(...)+1` = 自窗口起点 1-based |
| `ts_argmin` | `ts_argmin([3,1,2], 3)` | 同上口径 → `2` / `1` | 同上 | ★ 同上 |
| `decay_linear` | `decay_linear([1,2,3], 3)` | `(1·1+2·2+3·3)/6 = 14/6 ≈ 2.3333` | 权重恰为 `1..d / (d(d+1)/2)`，末值权重最大；与 `np.average(w=...)` 对拍 | ★ 原实现用已删除的 `as_matrix()` |
| `correlation` | `correlation([1,2,3,4,5],[2,4,6,8,10], 3)` | `[NaN,NaN,1,1,1]` | 完全线性 → 1.0 | — |
| `correlation` | 常数序列 `[1,1,1]` 对 `[1,2,3]` | `NaN`（**不是 inf/0**） | 分母为 0 的行为必须显式 | ★ 须断言 |
| `covariance` | `covariance([1,2,3,4,5],[2,4,6,8,10], 3)` | ddof 一致时 `[NaN,NaN,1,1,1]`（ddof=1）→ 与 pandas `rolling().cov()` 对拍 | 逐点 `allclose` | ddof 同 `stddev` |
| `rolling_rank` | 辅助函数 | 与 `scipy.stats.rankdata(w)[-1]` 一致 | 逐窗口验证 | 被 `ts_rank` 使用 |

### 8.2 截面算子（B 组）

设单日截面 `row = [10, 20, 30, 40]`（4 只股票）。

| 算子 | 调用 | 期望输出 | 断言要点 | 歧义点/备注 |
|---|---|---|---|---|
| `rank` | `rank(row)` | pct → `[0.25, 0.5, 0.75, 1.0]` | 与 `scipy.stats.rankdata(row,'average')/n` 逐点相等；值域 ⊆ (0,1] | ★ 原实现 `pct=True, axis=1` → 正确 |
| `rank` | 含并列 `[10, 10, 30]` | `[0.3333, 0.3333, 1.0]`（average 法） | 并列处理必须显式 | 并列策略（average/min/max）是隐藏分歧点 |
| `scale` | `scale(row, k=1)` | `[10,20,30,40]/100 = [0.1,0.2,0.3,0.4]` | **★ 断言 `row.abs().sum() == k`（逐日）** | ★ 原实现按列求和 → 断言必失败，专抓 §3.3 缺陷 3 |
| `scale` | `scale(row, k=3)` | 各行 `Σ|x| == 3` | 同上 | — |

### 8.3 中性化算子

| 算子 | 输入 | 期望 | 断言要点 | 备注 |
|---|---|---|---|---|
| `ind_neutralize` | 3 个行业（各 ≥2 只股票）的因子值 | 每个行业的**残差均值为 0**；残差与行业哑变量**内积 ≈ 0** | ① 正交性断言 ② 与 `statsmodels.OLS(y, dummies).resid` 对拍 `rtol=1e-10` | ★ 原实现逐日 `la.inv`，慢且遇空行业奇异 |
| `ind_neutralize` | 某行业全部为 NaN | **不崩**；该行残差为 NaN 或按显式策略处理 | 不得抛 `LinAlgError` | ★ 专抓 §3.3 缺陷 4 |
| `ind_neutralize` | 某行业只有 1 只股票 | 残差恒为 0（或显式策略） | 行为须文档化 | 共线性边界 |
| `neu_industry` | 因子值 + 行业序列 | `a / sector_mean(a)`（逐日按行业分组均值） | 与 `groupby(level=...).transform('mean')` 对拍 | 原实现用矩阵乘法拼装，可简化 |
| `neutral` | 因子值 + 行业哑变量 | OLS 残差 | 同 `ind_neutralize` | 原实现 `y - X·(XᵀX)⁻¹Xᵀy` |

### 8.4 元测试（变异测试，§6.5）

| 注入的 bug | 必须失败的测试 |
|---|---|
| `scale` 的 `sum(axis=1)` 改为 `sum()`（默认 axis=0） | §8.2 的 `scale` 断言 |
| `rank` 的 `pct=True` 改为 `False` | §8.2 的 `rank` 断言 |
| `decay_linear` 权重反序 | §8.1 的 `decay_linear` |
| `ts_argmax` 去掉 `+1` | §8.1 的 `ts_argmax` |
| `stddev` 的 ddof 从 1 改 0 | §8.1 的 `stddev` |
| 因子内部对入参做原地赋值（复刻 §3.3 缺陷 2） | §6.5「输入不可变性」 |
| `ts_sum` 的 `min_periods` 放宽（预热期填值） | §6.5「时间截断一致性」 |

**判据：每一个注入都必须让至少一个测试失败。** 这是证明"测试套件真的有效"的唯一方式。

---

## 9. 风险登记册

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| R1 | **GPL-3.0 传染**：误引原仓库代码进新库 | 🔴 高 | clean-room 纪律留痕；CI 加代码血缘检查；新库不出现原仓库路径 |
| R2 | **论文歧义**导致"验证通过"实为假象 | 🔴 高 | 强制产出《歧义清单》；歧义因子一律标 `ambiguous` 不得标 `verified` |
| R3 | **前视污染**（行业非 PIT、ffill 越界、全样本拟合） | 🔴 高 | 时间截断一致性 + 未来扰动测试作为准入门槛（§6.5） |
| R4 | **单位错配**（手/股、元/千元、万元） | 🟠 中 | §7.4 面板契约显式声明 + 单位断言测试 |
| R5 | **口径漂移**（ddof、pct、argmax 基准选择后未文档化） | 🟠 中 | 全部歧义点做成显式参数 + 写入 `docs/operators.md` |
| R6 | **统计幻觉**：用 IC 好看"证明"实现正确 | 🟠 中 | §6.7 明文禁止；统计只作辅助证据 |
| R7 | **测试套件退化**（写了个永远通过的测试） | 🟠 中 | 变异测试（§8.4）必须让注入的 bug 被抓住 |
| R8 | **依赖漂移**：pandas 升级导致行为变化 | 🟡 低 | golden 快照 + CI 版本矩阵 |
| R9 | **无差异化**：做出来等于 vnpy 已有的东西 | 🟡 低 | 定位锁定"可验证"（§5.2），核心交付是测试与清单而非公式 |
| R10 | **重复劳动**：与 quantming 已有因子池重复 | 🟡 低 | 后续若回流 quantming，先做正交化增量测试 |

---

## 10. 移交说明（Handover）

### 10.1 移交物清单

| # | 移交物 | 位置/状态 |
|---|---|---|
| 1 | **本文档** | `quantming/docs/Alpha101_修复发布决策与验证协议_v0.1.md`（自包含，新会话可独立使用） |
| 2 | 被分析源码（**只读参考，禁止拷贝代码**） | `/home/yinxiuqu/qa_ecosystem/QAFactor_Alpha101/` |
| 3 | 环境事实 | 见 §10.2 |
| 4 | 新会话启动提示词 | 见 §10.3（可直接粘贴） |
| 5 | 第一批动作与验收标准（DoD） | 见 §10.4 |

**建议的新工作区**：`/home/yinxiuqu/alpha101-verified`（可改）。

```bash
# 移交操作（在普通终端执行，非沙箱内）
mkdir -p /home/yinxiuqu/alpha101-verified/docs
cp /home/yinxiuqu/quantming/docs/Alpha101_修复发布决策与验证协议_v0.1.md \
   /home/yinxiuqu/alpha101-verified/docs/
cd /home/yinxiuqu/alpha101-verified && git init
```

> ⚠️ **为什么不直接在原仓库目录上工作**：原仓库是 **shallow clone（仅 1 个 commit）**，且为 GPL-3.0。新项目应**全新初始化**，与原仓库零代码血缘，避免 R1 与许可混淆。

### 10.2 必须复制的环境事实（新会话无此上下文）

**Python 环境**

| 项 | 值 |
|---|---|
| 推荐解释器 | `/home/yinxiuqu/anaconda3/envs/qa/bin/python`（**Python 3.11.16**） |
| 该环境关键版本 | **pandas 2.3.3** / numpy 1.26.4 / scipy 1.17.1 / statsmodels 0.14.6 / numba 0.67.0 / matplotlib 3.11.1 / scikit-learn 1.9.0 / pyarrow 17.0.0 / pymongo 4.17.0 |
| base conda | Python 3.8.8，**无** QUANTAXIS，**无** pymongo |
| QUANTAXIS（**新库不应依赖**） | 2.1.0a2，editable 安装指向 `/home/yinxiuqu/quantaxis`，仅在 `qa` 环境 |
| **vnpy（差分参照用途）** | 本机 `vnpy3` 环境是 **vnpy 3.3.0 / Python 3.10.4，无 `vnpy.alpha`**。`vnpy.alpha` 为 **4.x 新增**，用差分对拍需另装 4.x + **polars**；**不要**把 vnpy 放进库的运行时依赖 |

**vnpy 参照实现的位置（差分对拍用，MIT）**

| 内容 | 路径 |
|---|---|
| 因子表达式定义 | `vnpy/alpha/dataset/datasets/alpha_101.py`（**仅 82/101**） |
| 冒烟测试（含 18 个"摘掉中性化"的表达式） | `tests/test_alpha101.py` |
| 算子实现 | `vnpy/alpha/dataset/cs_function.py` / `ts_function.py` / `ta_function.py` |
| 表达式求值入口 | `from vnpy.alpha.dataset.utility import calculate_by_expression` |

**⚠️ 沙箱陷阱**：在 DSH 沙箱内运行任何触及 QUANTAXIS 的脚本，必须前缀 `HOME=/tmp`，否则因无法写 `~/.quantaxis/log/` 而 `OSError: Read-only file system`。新库应**完全避免**依赖 QUANTAXIS。

**本地 MongoDB（可用于 A 股口径适配与端到端验证）**

| 项 | 值 |
|---|---|
| 连接 | `127.0.0.1:27017`，库名 `quantaxis`（约 9.07 GB） |
| `stock_day` | **18,185,215** 条；`000001` 覆盖 **1991-04-03 ~ 2026-09-24**；原始字段名是 **`vol`**（QA 读取时才改名为 `volume`） |
| `stock_daily_basic` | **18,183,019** 条；1990-12-19 ~ 2026-09-24；含 **`turnover_rate` / `turnover_rate_f` / `total_mv` / `circ_mv` / `free_share` / `limit_status`** ← 真换手率、真市值的现成来源 |
| `stock_block` | 115,470 条 / **1172 个板块**；`上证50` 存在但有 **100 条**（tdx + baostock 双源重复，用前须去重） |
| `stock_xdxr` | 184,681 条（复权/股本） |
| `stock_list` | 5,574 条 |

**单位口径（已在真实数据上实测确认，务必沿用）**

```
volume          单位 = 手
amount          单位 = 元
vwap            = amount / (volume * 100)      # 实测 11.9104 ∈ [low,high] ✓
turnover_rate   单位 = %
total_mv/circ_mv 单位 = 万元
验证样本: 000001 @2026-09-04  vol=814372 amount=969948416 close=11.89
          turnover_rate(总股本)=0.4197  turnover_rate_f(自由流通)=0.9979  ✓ 自洽
```

**行业分类建议**：`/home/yinxiuqu/quantming/data/sw_industry/members.parquet`（申万 as-of 成员，覆盖 98.4%）。**不要**使用原仓库的 `data_export_swl2_month.csv`（固定 2017-01 快照，非 PIT）。

**被分析源码的关键事实（供写 issue / 偏差清单引用）**

- `alpha101.py`：928 行；**101 个因子（编号 1–101 无缺失）**；71 种形参组合、9 种形参名。
- 依赖影响面：`ind` 18 个 / `decay_linear` 22 个 / `returns` 12 个 / `scale` 6 个 / `cap` 1 个（详见 §3.2）。
- `func.py` 是死代码（未被 import，且引用未导入的 `ta`/`np`）。
- `test_101.py` 的 `alpha101(...)` 只是**因子 #101**，不是批量入口。

### 10.3 新会话启动提示词（可直接粘贴）

```
我在 /home/yinxiuqu/alpha101-verified 下开一个开源项目：一份「可验证的 Alpha101」实现。
请先完整阅读 docs/Alpha101_修复发布决策与验证协议_v0.1.md（内容版本 v0.2），它是唯一的设计依据。

背景要点（不要重新调研，已被验证过）：
- WorldQuant 官方无开源代码；《101 Formulaic Alphas》是 Kakushadze/Quantigic 的论文
  (arXiv:1601.00991, Wilmott 2016)，是事实规范但不是官方标准。
- 参考实现 A：/home/yinxiuqu/qa_ecosystem/QAFactor_Alpha101 是 GPL-3.0。
  ★ 严禁打开或拷贝该目录下的任何代码文件；只允许参考其 README 的中文因子注释表理解经济含义。
  （本地跑它做数值对比是允许的，但代码不得进仓库。）
- 参考实现 B：vnpy 的 alpha_101.py 是 MIT，可自由参照/署名复用，我们用它做差分对拍。
  ★ 但它只有 82/101：缺 alpha56（无 cap）+ 18 个含 IndNeutralize 的行业中性因子，
    且那 18 个因子在它的测试里被静默摘掉了中性化。所以对拍范围仅限这 82 个。
- 新库自选 MIT 许可，运行时只依赖 numpy/pandas/scipy（statsmodels/vnpy 仅测试期对拍用）。

本轮任务（对应文档 M0 + M1）：
1. 建仓库骨架（按 §7.2 结构）+ MIT LICENSE + README（含"可验证"定位）
2. 实现 docs/operators.md 的约定与 §7.3 的 20 个算子 API
3. 实现 tests/test_operators.py，覆盖 §8 的全部用例（A 组/B 组/中性化组）
4. 实现 tests/test_mutation.py，覆盖 §8.4 的 6 个注入，断言每个注入都会让测试失败
5. 跑通：pytest 全绿 + 变异测试全部按预期失败
6. 产出 docs/operators.md（含所有歧义点 ddof/pct/argmax基准/scale轴向 的显式决策）

解释器用 /home/yinxiuqu/anaconda3/envs/qa/bin/python（Python 3.11, pandas 2.3.3）。
本轮不要实现任何因子（因子是 M2/M3），先把算子层的地基打对。
完成后汇报：测试数量、通过情况、变异测试结果、以及你对歧义点的每一处决策及理由。
```

**下一轮重点预告（M2 起最容易翻车、也最值钱的一步）**：`IndNeutralize` 的向量化实现。vnpy 与 QAFactor 两个主流实现**都栽在这一个算子上**（一个整个算子缺失，一个逐日 `la.inv` 遇奇异行业就崩）。把它做对（正交性断言 + 对拍 `statsmodels.OLS` 残差），本项目就拿到了最硬的差异化。

### 10.4 第一批动作与验收标准（DoD）

| # | 动作 | 验收标准 |
|---|---|---|
| 1 | 仓库骨架 + MIT LICENSE | 目录结构与 §7.2 一致 |
| 2 | `docs/operators.md` 口径定义 | 6 个歧义点（ddof/pct/ts_rank口径/argmax基准/scale轴向/相关系数遇常数）**全部显式决策并写明理由** |
| 3 | 20 个算子实现 | 纯函数，输入输出均为 DataFrame，无副作用 |
| 4 | `tests/test_operators.py` | **20/20 通过**，覆盖 §8 全部用例 |
| 5 | `tests/test_mutation.py` | **6/6 注入均被测试抓住**（这是套件有效性的证明） |
| 6 | 失败即停 | **M1 未 100% 通过前，不得进入因子实现（M2）** |

**下一轮（M2）预告**：实现 3~5 个试点因子（建议 `alpha101` 可手算、`alpha4`、`alpha5`、`alpha41`、`alpha56`），并首次跑 L2 规范对照 / L3 差分 / L4 不变量。

---

## 附录 A · 关键路径与行号索引

**被分析源码（只读参考，禁止拷贝）**

| 内容 | 路径:行 |
|---|---|
| 因子库主文件 | `/home/yinxiuqu/qa_ecosystem/QAFactor_Alpha101/alpha101.py` |
| 缺陷 1：`as_matrix()` | `alpha101.py:140` |
| 缺陷 2：`alpha1` 原地改写入参 | `alpha101.py:154-155` |
| 缺陷 3：`scale` 轴向错误 | `alpha101.py:118` |
| 缺陷 4：`IndNeutralize` 逐日求逆 | `alpha101.py:42` |
| 缺陷 5：案例分层不兼容 | `test_101.py:40` |
| 缺陷 6：`ts_rank` 序号口径 | `alpha101.py:75`、`alpha101.py:113` |
| 因子 #101（案例中的"批量入口"） | `alpha101.py:769` |
| 死代码 | `func.py`（全文） |
| 中文因子注释表 | `README.md:12-119` |
| GPL-3.0 | `LICENSE` |

**上游与生态**

| 内容 | URL |
|---|---|
| 上游仓库 | https://github.com/yutiansut/QAFactor_Alpha101 |
| 878 星（无许可证）实现 | https://github.com/yli188/WorldQuant_alpha101_code |
| vnpy MIT 实现 | https://github.com/vnpy/vnpy/blob/master/vnpy/alpha/dataset/datasets/alpha_101.py |
| 论文 | https://arxiv.org/abs/1601.00991 |
| WorldQuant 官方 GitHub（仅 2 个无关 fork） | https://github.com/WorldQuant |
| WorldQuant BRAIN 平台 | https://platform.worldquantbrain.com |
| BRAIN 文档社区镜像 | https://github.com/alexisdpc/WorldQuant-alpha-trading |

---

## 附录 B · 术语表

| 术语 | 含义 |
|---|---|
| Alpha101 | 本项目中特指《101 Formulaic Alphas》论文的 101 个价量因子公式 |
| 面板 / Panel | `DataFrame`，index=交易日、columns=股票代码 |
| 截面算子（axis=1） | 沿股票维度计算（`rank`/`scale`），每日一次 |
| 时序算子（axis=0） | 沿时间维度滚动（`ts_sum`/`decay_linear`），逐股票一条序列 |
| PIT | Point-In-Time，只使用该时点及之前可知的信息 |
| 时间截断一致性 | 用 `[0,T]` 与 `[0,t]` 分别计算，在 t 处结果必须相同——最通用的前视检测 |
| clean-room | 只依据公开规范独立实现，不接触原实现代码，以规避许可传染 |
| 变异测试 | 故意注入 bug，断言测试套件会失败——证明测试有效 |
| golden 快照 | 冻结的期望输出基线，用于防回归 |
| verified / partial / ambiguous | 因子的三种验证状态，见 §6.8 |

---

## 附录 C · 文档变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-09 | 首版：WorldQuant 官方性调研、资产实测、许可证分析、决策、六层验证协议、clean-room 工程方案、算子测试用例表、移交包 |
| **v0.2** | 2026-10-09 | **（文件名仍为 v0.1）**① 新增 §4.3.1「vnpy 实现逐行核查」：**实际仅 82/101**（缺 alpha56 + 18 个 `IndNeutralize` 因子）、测试为**冒烟测试**（断言仅 `assert "data" in result.columns`）、18 个因子在测试中被**静默摘掉中性化**、2 处主动标注的边界偏差（alpha21/alpha24）。② 修正 §5.2 表述：从"没有测试"精确为"**缺乏正确性证据**"。③ 新增 §5.3「vnpy 参照 + 自建验证层」推荐路线与法律边界表。④ §6.4 差分测试改为**直接用 vnpy 作第二实现**（对拍范围 82 个）。⑤ §7.7 工作量由 5~6 人日**下调至 ≈3 人日**（M1 减半、M3 减 1/3、M4 降至 0.2）。⑥ §10.2/§10.3 移交包同步更新（vnpy 环境与参照路径、启动提示词、`IndNeutralize` 重点预告）。 |

**待办（移交后由新会话补齐）**

- [ ] 取 WorldQuant BRAIN 官方算子文档，作为 L2 算子口径的第二规范来源（§2.3）
- [x] ~~补充 vnpy `alpha_101.py` 的许可证与算子口径核对~~ → **v0.2 已完成**（MIT；覆盖 82/101；冒烟测试；见 §4.3.1）。**待补**：逐行核对 `tests/alpha/test_{cs,ts,ta}_function.py` 三个算子测试文件的内容
- [ ] 补充 `YutaoWang03/Quant-Alpha101` 的许可证核查（§4.3 标记为"待核"）
- [ ] 论文 PDF 逐条文字核对（本次未能抓取 PDF 正文，公式表以论文题目/摘要与社区转述为准 → **M3 前必须用论文原文逐条核对**）
- [ ] 安装 vnpy 4.x + polars 到独立环境（**不要污染 `qa` 环境**），验证 `calculate_by_expression` 可用，作为 M4 差分对拍的前置条件


