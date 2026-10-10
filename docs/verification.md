# 验证结果矩阵（verification.md）

| 项 | 内容 |
|---|---|
| 文档版本 | v0.1（2026-10-09，M0/M1 交付时生成） |
| 判据来源 | 设计文档 §6（六层协议）、§6.8（`verified` 六条门槛）、§10.4（DoD） |
| 执行环境 | Python 3.11.16 / pandas 2.3.3 / numpy 1.26.4 / scipy 1.17.1 / statsmodels 0.14.6 / pytest 9.1.1 |
| 复现命令 | `/home/yinxiuqu/anaconda3/envs/qa/bin/python -m pytest -q` |

## 0. 一句话状态

**L1 算子层：20/20 通过，证据完备。**
**因子层：0/101 —— 尚未开始，因此 `verified` = 0/101（不是「全部通过」）。**

---

## 1. L1 · 算子层验证（设计文档 §6.2：这一层没有「大概对」）

| 指标 | 结果 |
|---|---|
| 算子数 | **20/20**（16 时序/截面 + 1 构件 + 3 中性化） |
| 测试总数 | **643**（12 个测试文件，含变异测试、差分包装、规范对照与真实数据端到端） |
| 结果 | **643 passed / 0 failed**（约 9 分钟；其中 101 因子契约/不变量约 4.5 分钟、真实数据约 3.5 分钟、变异约 2 分钟） |
| 数值容差 | 与权威实现对拍 `rtol = 1e-10`（statsmodels 残差、pandas rolling、scipy `rankdata`） |
| 失败即停 | 本层未 100% 通过前不得进入因子实现（§10.4 第 6 条） |

各文件规模与职责：

| 文件 | 收集用例数 | 覆盖 |
|---|---|---|
| `tests/test_operators.py` | 57 | §8 全部用例：A 组 28 项、B 组 8 项、中性化组 15 项 + API 面/契约 |
| `tests/test_elemwise.py` | 17 | 论文 4 个一元函数（`abs`/`log`/`sign`/`signedpower`），覆盖 15 个因子 |
| `tests/test_factors.py` | 43 | M2 的 5 个试点因子：封闭解 / 独立第二实现 / L2 算子调用结构 / L4 不变量 |
| `tests/test_factors_all.py` | 306 | **M3 全量 101 因子**：注册完整性、可算不产 ±inf、入参不可变、**时间截断一致性**、L2 对照门禁 |
| `tests/test_adjust.py` | 11 | 复权：参考价口径、hfq 因果 vs qfq 非因果、只缩放价格字段 |
| `tests/test_adapters_real_data.py` | 35 | 真实 A 股端到端：面板契约 / vwap 单位自洽 / 因子零 inf / PIT 中性化正交 / 真实数据截断一致性（无库自动跳过） |
| `tests/test_differential.py` | 4 | vnpy 算子层差分包装（参照缺失时自动跳过）+ 参照文件 SHA256 完整性 |
| `tests/test_invariants.py` | 129 | §6.5：输入不可变性（22 个调用点）、截断一致性（19 算子）、未来扰动（19 算子）、缩放不变性、脏数据 |
| `tests/test_panel.py` | 14 | §7.4 面板契约、单位口径（含设计文档 §10.2 的实测样本） |
| `tests/test_registry.py` | 10 | §7.5 自动装配机制 + 深拷贝防污染 |
| `tests/test_provenance.py` | 5 | §9 R1 零 GPL 血缘 + §7.1 运行时依赖约束（机械守卫） |
| `tests/test_mutation.py` | 8 | §8.4 的 7 条注入 + 1 条勘误钉死 |

**独立权威实现对拍清单**（「算子层可 100% 判定」的落点）：

| 算子 | 对拍对象 | 容差 | 测试 |
|---|---|---|---|
| `stddev` / `covariance` | `pandas.rolling().std()/cov()`、`numpy.std(ddof=0)` | `rtol=1e-10` | `test_a04`、`test_a21`、`test_a22` |
| `correlation` | `pandas.rolling().corr()` | `rtol=1e-10` | `test_a21` |
| `ts_rank` / `rolling_rank` | `scipy.stats.rankdata` | 精确相等 | `test_a10`、`test_a24` |
| `decay_linear` | `numpy.average(weights=1..d)` | `rtol=1e-12` | `test_a18` |
| `rank` | `scipy.stats.rankdata(row,'average')/n` | `rtol=1e-10` | `test_b01`、`test_b02` |
| `scale` | 解析不变量 `Σ\|x\| = k`（逐日） | `rtol=1e-10` | `test_b05`、`test_b06` |
| `ind_neutralize` | `statsmodels.OLS(y, dummies).resid` | `rtol=1e-10` | `test_c02` |
| `neutral` | `statsmodels.OLS(y, X).resid` + 闭式公式 | `rtol=1e-10` | `test_c10`、`test_c13` |
| `ind_neutralize` ↔ `neutral` | 两条独立实现互证 | `rtol=1e-10` | `test_c06`、`test_c11` |
| `neu_industry` | `groupby(...).transform('mean')` | `rtol=1e-12` | `test_c08` |

---

### 1.1 规范入库校验（L2 前置，2026-10-09）

L2（规范对照）的**基准文本**已建立并通过机械校验，见 `docs/paper_formulas.md`：

| 校验项 | 结果 |
|---|---|
| 论文来源 | arXiv:1601.00991 **v3**（PDF SHA256 `1f9c21af…36fce9`，`curl` + `pdftotext -layout` 抽取） |
| 公式条数 | **101/101**（编号 1–101 连续，无缺失） |
| **括号平衡** | **101/101 全部平衡（0 条不平衡）** ← 转写保真主证据 |
| 跨行公式合并 | 69 条（按「续行直到括号平衡」合并） |
| 算子定义 | 论文 §「Functions and Operators」逐字入库（含 `indneutralize` = 组内截面去均值，**L-A 确认本库实现**） |
| 与设计文档 §3.2 依赖表交叉验证 | **5/5 完全一致**（`indneutralize` 18、`decay_linear` 22、`returns` 12、`scale` 6、`cap` 1，连因子编号列表都逐一相同） |

论文级核对同时产出 7 项口径问题（含影响面计数：非整数窗口 40 因子、`adv{d}` 45 因子、
逐元素层 15 因子、`decay_linear` 方向 22 因子、`ts_argmax` 基准 6 因子、`scale` 轴向 6 因子、`signedpower` 2 因子），
已分别写入 `docs/operators.md` §3.7/§3.8/§7、`docs/ambiguities.md` A11–A15 与 `docs/deviations.md` §1.2。

### 1.2 算子层差分对拍（L3 提前做，2026-10-09）

M2/M3 之前先把**算子口径**与第二实现对齐（设计文档 §6.4），避免 101 个因子固化错误口径。

* 参照：vnpy（MIT）``cs_function.py`` / ``ts_function.py``，
  由 ``tools/fetch_vnpy_reference.sh`` 下载到 gitignored 的 ``.vnpy-ref/``（含 SHA256 校验，**不入库**）；
* 工具：``tools/differential.py``（24 项对拍，退出码即证据）；测试包装：``tests/test_differential.py``；
* 环境：本机 ``qa`` 已含 polars 1.44（参照侧依赖；本库运行时仍只有 numpy/pandas/scipy）。

| 指标 | 结果 |
|---|---|
| 对拍项 | **24** |
| 对齐后**逐点一致** | **18 项**（`rtol=1e-8`，NaN 位置亦一致） |
| 已归因口径差异 | **6 项**（D1–D6，全部实测存在，见 `docs/operators.md` §6.2） |
| 「不一致（待查）」 | **0 项** |
| 参照能力缺口 | 3 项（不支持非整数窗口；覆盖 82/101；因子级入口缺 talib/`math_function`） |

关键结论：

* ✅ 本库 **`ts_argmax`/`ts_argmin` 的 1-based 自窗口起点**、**`ts_rank(pct=True)`**、
  **`scale` 的每日截面**、**`correlation`/`covariance`**、**`ts_sum`/`delta`/`delay`/`product`**
  与参照**逐点一致** ⇒ 算子层口径不再是「自说自话」；
* ⚠️ **`decay_linear` 权重方向与参照相反**（影响 **22 个因子**，本项目最高风险口径）：
  本库默认不变，新增 `order="oldest_first"` 与参照逐点对齐；未定案前相关因子不得标 `verified`；
* ⚠️ `stddev` 的 ddof（参照 `ts_std`=0、`cs_std`=1，**自身不一致**）、`rank` 并列策略、
  预热期策略、`scale` 零和行、NaN 洞——共 6 条口径差异，全部已归因并可用显式参数对齐。

### 1.3 真实 A 股数据端到端（2026-10-09）

数据源：本地 MongoDB ``quantaxis``（``stock_day`` + ``stock_daily_basic``）与申万 as-of 成员 parquet
（设计文档 §10.2）；适配层 ``src/alpha101v/adapters/``（**延迟导入** pymongo，运行时依赖不变）。
可复跑：``python tools/real_panel_smoke.py``；测试：``tests/test_adapters_real_data.py``（11 项）。

两次冒烟（60 只 × 58 日；**120 只 × 359 交易日**）：

| 校验项 | 结果 |
|---|---|
| 面板契约（含最小历史 250 日） | ✅ 通过（359 交易日的窗口才满足 250 日门槛，58 日窗口按预期被判不足） |
| **单位口径**：`vwap ∈ [low, high]` 自洽率 | **99.86%**（120 只）/ 99.80%（60 只）——把「手」当「股」会立刻失败 |
| 申万 L1 as-of 行业覆盖率 | **98.0%**（与设计文档 §10.2 的「约 98.4%」独立吻合） |
| 5 个试点因子 | 全部算得出，覆盖面 95%~98%，**零 ±inf** |
| **PIT 行业中性化**：逐日行业内残差和 | 最大绝对值 **3.4e-15**（≈ 0）——最硬的算子在真实 PIT 面板上成立 |
| 因子入参 | 只读；不修改任何集合 |

⚠️ **已知数据口径限制（如实标注，尚未修）**：

1. **价格未复权**：``stock_day`` 是原始价（复权信息在 ``stock_xdxr``）。面板契约要求**前复权价**，
   因此 `returns` 在除权除息日会出现**假跳空**，直接影响使用 `returns` 的因子（试点里的 ``alpha56``）。
   本轮的因子多为排序型，结论不受影响；但 M3 必须补复权（或改用已复权数据源）。
2. **`vwap` 有 0.14% 的格子落在 `[low, high]` 之外**：真实数据自身的瑕疵（疑似零成交/异常量额），
   本库不静默修正——保持原值并在契约里允许，需要清洗由调用方决定。
3. **市值口径未定**：冒烟用 ``total_mv``（万元）；``circ_mv``（流通市值）未被采纳，
   两者对 ``rank`` 型因子等价（已测），但对量纲敏感的组合会有差异（记入 `docs/ambiguities.md`）。

### 1.4 M3：全量 101 因子 + 规范对照（2026-10-09）

| 项 | 结果 |
|---|---|
| 因子实现 | **101/101**（`src/alpha101v/factors.py`，论文逐字转写，每个函数 docstring 保留原文一行） |
| 状态分布 | `partial` **74** / `ambiguous` **27** / `verified` **0**（`verified` 需六条门槛，M4/M5 未完成） |
| **L2 规范对照** | ✅ **101/101 等价**（`tools/conformance_report.py`：算子／字段／字面量三重对照，0 偏离） |
| L4 不变量（全量） | ✅ 101 个因子全部通过：可算不产 ±inf、入参不可变、**时间截断一致性** |
| 复权（数据前置） | ✅ 见 §1.3 与 `docs/deviations.md` §1.2 P1；除权日假跳空消除（35.11% → 7.60%） |

**M3 期间由「全量因子跑」暴露并修掉的一个真 bug**：`correlation` 在**近乎零方差**的窗口里
pandas 会返回 ±inf（违反本库「分母为 0 ⇒ NaN」的承诺），已掩为 NaN 并补回归用例
（`tests/test_operators.py::test_a20b_...`）；vnpy 的 `ts_corr` 也显式把 infinite 置 null，两边一致。

**ambiguous 的 27 个因子**（规范本身未定且改变数值，设计文档 §9 R2 要求不得标 `verified`）：

* `decay_linear` 权重方向未定案 → **22 个因子**（与 vnpy 相反，BRAIN 文案未取得）；
* `ts_argmax`/`ts_argmin` 基准未定案 → 6 个（论文只写 "which day"）；
* `^` 语义（论文字面 `x^a` vs 保号幂）产生实质差异 → 2 个（alpha48、alpha90）。

## 2. 六层协议状态

| 层 | 判据 | 状态 | 说明 |
|---|---|---|---|
| **L1 算子层** | 20/20 | ✅ **通过** | 见 §1 |
| **L2 规范对照** | 101 行偏差清单 | ✅ **101/101 等价** | `tools/conformance_report.py` 已交付；对照粒度为算子级（见 §1.4 与工具文档的能力边界） |
| **L3 双实现差分** | 82 个可比因子 `allclose(rtol=1e-8)` | 🟡 **算子层已做**（§1.2：24 项对拍，18 一致 + 6 归因 + 0 待查）；**因子层待 M4** | 因子级差分需 `math_function` + 处理 talib 依赖；19 个缺口无法差分 |
| **L4 不变量与元测试** | 截断/缩放/未来扰动/入参不可变/变异 | 🟡 **算子层已做**（见 §3） | 因子层待 M2；golden 未建 |
| **L5 golden 快照** | 快照入库 | ⛔ **未建** | 无因子可冻结；算子层不需要（有解析期望值 + 权威对拍，比冻结快照更强） |
| **L6 统计合理性** | IC 符号/衰减/暴露 | ⛔ **不适用** | 无因子；且明文禁止用「IC 好看」证明代码正确（§6.7） |

---

## 3. L4 结果：不变量与变异测试

### 3.1 不变量（算子层）

| 不变量 | 覆盖 | 结果 |
|---|---|---|
| 输入不可变性 | 22 个调用点（20 算子 + 2 个面板工具） | ✅ 全部一字未改 |
| 时间截断一致性（PIT 金标准） | 19 个 PIT 算子，`[0,40]` vs `[0,25]` | ✅ 逐点**完全相等** |
| 未来扰动 | 同上，篡改 t≥25 的数据 | ✅ t<25 逐点不变 |
| 截断判据的有效性（控制实验） | 故意前视的居中滚动算子 | ✅ 判据**判失败**（证明判据有牙齿） |
| 缩放不变性 | `rank` / `ts_rank` / `scale`，整体 ×3.5 | ✅ 不变（`rtol=1e-12`） |
| 平移不变性（限定范围） | `rank` 在 +1000 下不变 | ✅（其余算子不承诺，见 operators.md §3.6） |
| 有限输入不产生 ±inf | 22 个调用点 | ✅ |
| 脏数据不崩（NaN / 0 混入） | 22 个调用点 | ✅ |
| 不触发 pandas 弃用警告（`FutureWarning`/`DeprecationWarning` 转异常） | 22 个调用点 | ✅（0 警告） |

### 3.2 变异测试（§8.4：每个注入都必须被抓住）

运行方式：把仓库副本复制到临时目录 → 对 `src/alpha101v/operators.py` 做**字面替换**注入 bug →
在副本里跑**真实 pytest 子进程** → 断言退出码非 0 **且**预期抓取者出现在失败清单里。
另有前置断言：**干净副本必须先全绿**，否则「注入后失败」不可信（防假阳性）。

| # | 注入的 bug（§8.4 表） | 断言抓取者 | 实测同时抓住的测试 | 结果 |
|---|---|---|---|---|
| m1 | `scale` 的 `sum(axis=1)` → `sum(axis=0)` | `test_b05_scale_sum_abs_equals_k_per_row` | **4 个**：轴契约、`b05`、`b06`、`b07` | ✅ 被抓住 |
| m2 | `rank` 的 `pct=pct` → `pct=False` | `test_b01_rank_pct_matches_rankdata_over_n` | **3 个**：`b01`、`b02`、`b04` | ✅ 被抓住 |
| m3 | `decay_linear` 权重反序 | `test_a17_decay_linear_weights` | **2 个**：`a17`（解析值）、`a18`（逐窗口 vs `np.average`） | ✅ 被抓住 |
| m4 | `ts_argmax` 去掉 `+1` | `test_a12_ts_argmax_default_basis_is_window_start` | **3 个**：`a12`、`a13`（两种基准）、`a14`（方向与并列） | ✅ 被抓住 |
| m5 | `stddev` 默认 `ddof` 1 → 0 | `test_a03_stddev_default_is_ddof1` | **1 个**：`a03` | ✅ 被抓住 |
| m6 | `delta` 原地改写入参（复刻 §3.3 缺陷 2） | `test_inputs_are_not_modified[delta]` | **1 个**：入参不可变性 `[delta]` 参数化点 | ✅ 被抓住 |
| m7 | `ts_sum` 的 `min_periods` 放宽为 1 | `test_a01_ts_sum` | **4 个**：`Series` 语法糖、`a01`、`a25`（预热期）、`a26`（窗口内 NaN 传播） | ✅ 被抓住 |

（实测清单来自一次性盘点脚本：对每个变异跑完整的 `tests/test_operators.py` / `tests/test_invariants.py`
并收集全部 FAILED 节点；本文件只记录结论，脚本不入库。）

**7/7 全部被抓住。** 另有一条专门的勘误测试
（`test_errata_min_periods_is_caught_by_warmup_assertion_not_truncation`）同时证明：
m7 由「预热期必须 NaN」断言抓住，而设计文档 §8.4 归因的「时间截断一致性」**抓不住**它——
后者对「放宽 min_periods」天然无感（不引入前视）。详见 `docs/deviations.md` §2 勘误 3。

### 3.3 结论

从这两个维度可以给出**有限但确凿**的结论：

* 测试套件**不是摆设**：7 个已知 bug 全部被现有测试抓住；
* 算子层的口径**是可判定的**：每一处歧义点决策都有独立权威实现对拍，不是自说自话。

⚠️ 仍然只是**必要条件**，不是充分条件：通过了不代表对（§6.5 原文）。

---

## 4. 尚未验证的部分（如实标注）

| # | 未验证项 | 为什么 | 计划 |
|---|---|---|---|
| 1 | 因子的正确性（`verified` 仍为 0/101） | **L2 结构对照 ✅**、L4 不变量 ✅ 已完成；缺 L3 因子级差分（M4）与 L5 golden 快照（M5） | M4 / M5 |
| 2 | 与论文公式的结构一致性（L2） | **基准文本已入库并通过 101/101 括号平衡校验**（§1.1）；缺的是「实现 AST ↔ 论文算子树」的逐节点比对工具（`tools/conformance_report.py`）与因子本身 | M3 |
| 3 | 与 vnpy 的**因子级**差分一致性（L3） | 算子层已完成（§1.2）；因子级需 `calculate_by_expression` + `math_function` + talib 处理，且参照只覆盖 82/101 | M4 |
| 4 | 19 个缺口因子（18 个 `IndNeutralize` + `alpha56`） | **无法差分**，只能靠 L2 规范对照 + L4 不变量 | M3/M4，结论须标注「无第三方对拍」 |
| 5 | golden 快照防回归（L5） | 无因子可冻结 | M5 |
| 6 | BRAIN 官方算子文档（L-B 级规范） | 未获取（设计文档 §2.3 待办） | 取到后复核 `days_ago` 等口径 |
| 7 | A 股落地口径（复权/PIT 行业/真换手率/单位） | 🟡 **部分完成**（§1.3）：PIT 行业、单位口径、市值已接上并验证；**复权未做** ⇒ `returns` 在除权日有假跳空 | M3 补复权（`stock_xdxr`）或改用已复权源 |
| 8 | 中性化算子在大面板上的性能 | M1 只承诺正确性 | M2 起基准测试 |

---

## 5. 复现与 CI

```bash
PY=/home/yinxiuqu/anaconda3/envs/qa/bin/python

$PY -m pytest -q                                   # 全量 643 项（真实数据 35 项在无库时自动跳过）
$PY -m pytest tests/test_operators.py -q           # M1 闸门（54 项，约 8 秒）
$PY -m pytest tests/test_mutation.py -q            # 变异测试（8 项，约 2 分钟）
$PY -m pytest tests/test_provenance.py -q          # 许可/依赖机械守卫
```

CI（`.github/workflows/ci.yml`）把上述四项拆成独立步骤，并在 **pandas 2.1 / 2.2 / 2.3** 矩阵上跑，
防止依赖漂移（§9 R8）。

## 6. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-09 | 首版：L1 20/20 与 219 项测试结果、六层状态、L4 不变量与 7/7 变异结果、8 项未验证事项 |
| **v0.3** | 2026-10-09 | 新增 §1.2 **算子层差分对拍**（24 项：18 一致 + 6 归因 + 0 待查）；更新 §2 的 L3 行为「算子层已做」、§4 第 3 项、测试总数 219→277（新增 `test_elemwise`/`test_factors`/`test_differential`） |
| **v0.4** | 2026-10-09 | 新增 §1.3 **真实 A 股端到端**（359 交易日 × 120 只：契约通过、vwap 自洽 99.86%、行业覆盖 98.0%、5 因子零 inf、PIT 中性化残差和 3.4e-15）与 3 条数据口径限制（**未复权**、0.14% vwap 越界、市值口径待定）；测试总数 277→297；§4 第 7 项改为「部分完成」 |
| v0.2 | 2026-10-09 | 新增 §1.1 规范入库校验（论文 101/101 公式、0 条括号不平衡、与设计文档 §3.2 依赖表 5/5 一致）；更新 §4 第 2 项（L2 基准文本已就位） |
