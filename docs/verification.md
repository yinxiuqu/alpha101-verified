# 验证结果矩阵（verification.md）

| 项 | 内容 |
|---|---|
| 文档版本 | v0.1（2026-10-09，M0/M1 交付时生成） |
| 判据来源 | 设计文档 §6（六层协议）、§6.8（`verified` 六条门槛）、§10.4（DoD） |
| 执行环境 | Python 3.11.16 / pandas 2.3.3 / numpy 1.26.4 / scipy 1.17.1 / statsmodels 0.14.6 / pytest 9.1.1 |
| 复现命令 | `/home/yinxiuqu/anaconda3/envs/qa/bin/python -m pytest -q` |

## 0. 一句话状态

**L1 算子层：20/20 通过，证据完备。**
**因子层：101/101 已实现；终态 `verified` 82/101、`partial` 19/101、`ambiguous` 0。**
19 个 `partial` 全部是「vnpy 未实现 ⇒ 无第三方参照 ⇒ 门槛 3（必需）原理上不可满足」的因子
（18 个含 `IndNeutralize` + `alpha56` 需 `cap`），逐条备注写明缺哪条、为什么——**不是「全部通过」**。
六条门槛的状态见 §2，M5 的 golden 快照与状态划分见 §1.7。

---

## 1. L1 · 算子层验证（设计文档 §6.2：这一层没有「大概对」）

| 指标 | 结果 |
|---|---|
| 算子数 | **20/20**（16 时序/截面 + 1 构件 + 3 中性化） |
| 测试总数 | **682**（18 个测试文件，含变异测试、差分包装、规范对照、因子级差分与真实数据端到端） |
| 结果 | **682 passed / 0 failed**（约 22 分钟；其中因子级差分门禁约 11 分钟、101 因子契约/不变量约 4.5 分钟、真实数据约 3.5 分钟） |
| 数值容差 | 与权威实现对拍 `rtol = 1e-10`（statsmodels 残差、pandas rolling、scipy `rankdata`） |
| 失败即停 | 本层未 100% 通过前不得进入因子实现（§10.4 第 6 条） |

各文件规模与职责：

| 文件 | 收集用例数 | 覆盖 |
|---|---|---|
| `tests/test_operators.py` | 57 | §8 全部用例：A 组 28 项、B 组 8 项、中性化组 15 项 + API 面/契约 |
| `tests/test_elemwise.py` | 21 | 逐元素层 7 个函数（`abs`/`log`/`sign`/**`power`**/`signedpower`/`min`/`max`），含 BRAIN `power` 与 `signed_power` 的语义分野 |
| `tests/test_factors.py` | 43 | M2 的 5 个试点因子：封闭解 / 独立第二实现 / L2 算子调用结构 / L4 不变量 |
| `tests/test_factors_all.py` | 306 | **M3 全量 101 因子**：注册完整性、可算不产 ±inf、入参不可变、**时间截断一致性**、L2 对照门禁 |
| `tests/test_adjust.py` | 11 | 复权：参考价口径、hfq 因果 vs qfq 非因果、只缩放价格字段 |
| `tests/test_adapters_real_data.py` | 35 | 真实 A 股端到端：面板契约 / vwap 单位自洽 / 因子零 inf / PIT 中性化正交 / 真实数据截断一致性（无库自动跳过） |
| `tests/test_differential.py` | 4 | vnpy 算子层差分包装（参照缺失时自动跳过）+ 参照文件 SHA256 完整性 |
| `tests/test_invariants.py` | 129 | §6.5：输入不可变性（22 个调用点）、截断一致性（19 算子）、未来扰动（19 算子）、缩放不变性、脏数据 |
| `tests/test_panel.py` | 14 | §7.4 面板契约、单位口径（含设计文档 §10.2 的实测样本） |
| `tests/test_l6_statistics.py` | 10 | **L6 统计代码正确性**：IC=±1 的合成情形、秩不变性、手算对照、行业 ANOVA、向量化与 `scipy` 逐日等价 |
| `tests/test_brain_alignment.py` | 6 | **行为对齐工具正确性**：单调关系检测、按日期对齐、PnL 文件解析、**配额纪律**（无确认不提交）、**凭据纪律**（不接受命令行 cookie） |
| `tests/test_usage_guide.py` | 6 | **使用指南防漂移**：字段表与注册表一致、文档本地链接有效、关键小节不丢、两个示例必须真能跑 |
| `tests/test_us_verification.py` | 5 | **美股工具**：删除审计如实、拆股后复权方向（含「方向写反」的回归测试）、分红不修的声明 |
| `tests/test_golden.py` | 5 | **M5 L5 门禁**：与冻结基线一致（NaN 模式 + 数值）、覆盖 101 个因子、长窗口因子有值、清单可复现、面板确定性 |
| `tests/test_factor_differential.py` | 3 | **M4 因子级差分门禁**：合成面板 0 待查、19 个缺口集合必须与参照实现一致、真实行情定点核查 |
| `tests/test_registry.py` | 10 | §7.5 自动装配机制 + 深拷贝防污染 |
| `tests/test_provenance.py` | 6 | §9 R1 零 GPL 血缘 + §7.1 运行时依赖约束（机械守卫） |
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
| 状态分布（M3 快照） | `partial` 74 / `ambiguous` 27 / `verified` 0 —— ⚠️ **该快照已被 §1.6 更新**：2026-10-10 的 L-B 定案把 27 个 `ambiguous` 清零，现为 **`partial` 101 / `ambiguous` 0 / `verified` 0** |
| **L2 规范对照** | ✅ **101/101 等价**（`tools/conformance_report.py`：算子／字段／字面量三重对照，0 偏离） |
| L4 不变量（全量） | ✅ 101 个因子全部通过：可算不产 ±inf、入参不可变、**时间截断一致性** |
| 复权（数据前置） | ✅ 见 §1.3 与 `docs/deviations.md` §1.2 P1；除权日假跳空消除（35.11% → 7.60%） |

**M3 期间由「全量因子跑」暴露并修掉的一个真 bug**：`correlation` 在**近乎零方差**的窗口里
pandas 会返回 ±inf（违反本库「分母为 0 ⇒ NaN」的承诺），已掩为 NaN 并补回归用例
（`tests/test_operators.py::test_a20b_...`）；vnpy 的 `ts_corr` 也显式把 infinite 置 null，两边一致。

**ambiguous 的 27 个因子 → 已于 2026-10-10 全部定案（L-B 官方文档，见 §1.6）**：
`decay_linear` 方向 22 个、`ts_argmax`/`ts_argmin` 基准 6 个、中缀 `^` 语义 2 个（去重 27）。
定案后 `ambiguous` 清零，101 个因子一律 `partial`。

### 1.5 M4：因子级差分对拍（2026-10-10）

**范围 82/101**：vnpy 未实现的 **19 个**结构上无法差分（18 个含 `IndNeutralize` + `alpha56` 无 `cap`），
只能靠 L2 规范对照 + L4 不变量。

语义归一化（§6.4 第一步，默认全开、每项都有实测依据）：rank 并列→`min`、decay 方向→`oldest_first`、
`stddev`→`ddof=0`、`adv{d}` 口径（面板 `amount` 喂成 `volume`）、非整数窗口 floor→round、
只比较「两侧都有限」的格子（预热期策略不同：本库严格 NaN，vnpy 多处 `min_samples=1`）。

结果（确定性合成面板 320 交易日 × 15 只）：

| 判定 | 个数 |
|---|---|
| **一致**（逐点 `allclose`，rtol 1e-8） | **64** |
| 已归因：参照 `quesval2` 条件取反（§1.5.1） | 2 |
| 已归因：离散平局/数值病态经 rank 放大（§1.5.3） | 14 |
| 已归因：覆盖差异经截面算子传播（§1.5.2） | 2 |
| **实偏差（待查）** | **0** |

#### 1.5.1 参照侧 bug：vnpy 的 `quesval2` 与它自己的文档语义相反

实测（`tools/factor_differential.py --no-fix-reference` 可复现）::

    quesval2(threshold=[1,5,9], feature1=[3,5,7], 100, -100) -> [-100, -100, 100]
    其 docstring「threshold < feature1 取 feature2」应为            [ 100,  100, -100]

成因：join 时 `suffix="_cond"` 只加在**右侧**帧上，于是比较双方被调换。影响面：所有用它表达
条件分支的因子（布尔型因子整片取反）。处置：对拍时以「交换前两个参数再调原实现」修正参照
（工具内 `fix_reference_quesval2`），**不改本库逻辑**（本库按论文语义实现）。修正前一致 55 个 → 修正后 64 个。

#### 1.5.2 覆盖差异经截面算子传播

`rank`/`scale` 的分母是**当日有效格子数**；两侧预热期/缺失策略不同 ⇒ 当天有效数不同 ⇒ 整天的
rank 值整体平移。判定规则：所有不一致格子都落在「当日有效数不同」的交易日（alpha78/85/94 等）。

#### 1.5.3 离散平局/数值病态（14 个：机制已复算定位，未逐因子复算）

代表例 `alpha45` 的逐算子复算：

* `corr(close, volume, 2)` 在数学上恒为 ±1，但本库唯一值 **34237** 个、vnpy **26051** 个
  （且 vnpy 会落到精确 `-1.0`）⇒ **数学精确并列被两侧不同的浮点噪声打破**；
* 对齐后 `rank` 用 `method="min"`，并列一旦被打断，名次整体位移 ⇒ **rank 结果差 95%**；
* `corr(sum(close,5), sum(close,20), 2)` 更出现 **6.03e+03**（\|corr\|>1）的数值病态值。

这一类**不是转写错误**：L2 对照 101/101 等价；算子层与 vnpy 对拍 18/18 项逐点一致（含 `correlation`）。
**诚实的边界**：只有 alpha45 逐算子复算过，其余 13 个属于「同机制 + 量级签名（不一致格数 0.04%~74%、
\|Δ\| 为 1/n 量级）」的推断。彻底闭环需要的不是继续对齐口径，而是**平局可判定**的比较方式
（例如两侧都把中间量量化到同一网格后再排名）——列为后续工作。

### 1.6 L-B：WorldQuant BRAIN 官方算子文档入库（2026-10-10，M4 后续）

**来源**：BRAIN 平台 `learn/operators` 页面打印件 11 页（sha256 `8a20029d93d9ecd8…`，
打印于 2026-10-10 21:07），本地存于 gitignored 的 `refs/`，**不入库**（登录墙内的专有文档）。

**它定案了什么**（原先 27 个 `ambiguous` 因子的三条歧义，原文引文见 `docs/operators.md` §3.13）：

| 议题 | BRAIN 原文要点 | 处置 |
|---|---|---|
| `ts_arg_max`/`ts_arg_min` 基准 | "If **today's value is the maximum, returns 0**" ⇒ `days_ago` | **默认翻转**为 `days_ago`（原默认 1-based 自窗口起点与官方相反）；6 个因子（1/57/60/96/98/100）取值随之改变 |
| `ts_decay_linear` 方向 | "averaging **recent** values and reducing the impact of **older** data" | 本库默认 `recent_first` **正确**；22 个因子定案 |
| 中缀 `^` | `power`（负底数 + 非整数指数**丢符号**）与 `signed_power`（保号）是两个算子 | 论文 `^` → 新增的 `elemwise.power`；**alpha48 修复**（负收益平方得正）；alpha90 两读法同值 |

**它同时印证了本库既有决策**（无需改码）：`scale` 逐日截面 `Σ|x|=k`（且确认 BRAIN 另有 `ts_scale`）、
`group_neutralize` = 组内减去组均值、`sign` 遇 NaN 返回 NaN、`log` 面向正值、
`add/multiply/subtract` 默认 `filter=false` ⇒ 算术不吞 NaN、`min/max` 至少两个输入（逐元素）。

**状态影响**：`ambiguous` **27 → 0**（当时 101 个因子一律 `partial`；L5 golden 快照在 M5 补齐后
终态为 `verified` 82 / `partial` 19，见 §1.7）。因子级差分的语义归一化新增两条对齐开关
（argmax 基准、`pow` 口径），对拍结果不变（64 一致 + 18 已归因 + 0 待查）⇒ 说明差异**只在口径选择**，
不在数值实现。

**API 级完整文档（2026-10-10 补充）**：打印件只有首行描述，随后用会话凭据抓取了完整文档
（`GET /operators/{name}`，65/66 个算子有正文，本地语料 `refs/brain_operator_docs.md`）。
完整正文里的**官方算例**又定案了三处默认口径差异（`docs/operators.md` §3.13.3）：

1. `rank`/`ts_rank` 归一化是 **[0,1] 闭区间 `(名次−1)/(n−1)`**（本库与 vnpy 都取 `(0,1]` 的 `名次/n`）⇒ 影响**全部 101 个因子**；
2. `ts_std_dev` 算例除以 n ⇒ **ddof=0**（本库默认 1）⇒ 8 个因子；
3. `ts_decay_linear` 默认**稀疏模式（NaN 当 0）**（本库严格整窗）⇒ 22 个因子。

这三处**已于同日落地**（`docs/operators.md` §3.1/§3.2/§3.12/§3.13.3）：

* 归一化默认改为 `zero_to_one`（`(名次−1)/(n−1) ∈ [0,1]`），`one_over_n`/`ordinal` 保留 ⇒ 影响全部 101 个因子；
* `stddev`/`covariance` 默认 `ddof=0`；`decay_linear` 默认稀疏（`dense=False`，NaN 计 0）；
* 四个官方算例逐一复核：`rank((4,3,6,10,2)) = (0.5,0.25,0.75,1,0)`、`ts_rank` 的 `3/(5−1)=0.75`、
  `ts_std_dev` 算例 `sqrt(0.0002) ≈ 0.0141`、`ts_decay_linear` 算例 `(6·1+8·2+10·3)/6 ≈ 8.67`（均已进测试）。

⚠️ **顺带发现的后果（已处理并记录）**：官方 `rank` 是 **[0,1] 闭区间**，当日排名最低的标的取到 **0.0**，
于是 `rank(a)/rank(b)` 型因子（alpha42/57/72/93 等）会**除以 0**。BRAIN 自己的 `divide` 文档即写明
「dividing by zero raises an error; to avoid it, use `divide(x, add(y, 0.0001))`」⇒ 平台同样无定义。
本库在**因子输出边界**把 ±inf 统一降级为 **NaN**（`registry.run_factor` 的 `_sanitize`），
既不输出 inf、也不偷偷加 epsilon 改数值。

**文档也没给出的**：`dense=true` 分支、`min/max` 的 NaN 口径、滚动算子 `min_periods`、
`if_else` 条件为 NULL 的分支 —— 均为库级约定，本库显式决策并测试（§3.12）。

### 1.7 M5：golden 快照与状态终态（2026-10-11）

**L5 golden 快照**（设计文档 §6.6）：`tests/golden/` 下冻结了确定性面板（**5 只 × 320 交易日**，
种子 `20261010`）上 101 个因子的输出。

| 文件 | 内容 |
|---|---|
| `panel.npz` | 面板（9 个数值字段 + 3 个行业层级），供第三方独立复算 |
| `factor_values.npz` | 101 个因子输出矩阵（float64，NaN 原样） |
| `manifest.json` | 面板与逐因子 sha256、种子/规模、**环境版本**、生成命令、判据说明 |

**判据**：**NaN 模式必须完全一致** + `allclose(rtol=1e-9, atol=1e-12)`；哈希不一致但数值一致只报
「漂移提示」（CI 还跑 pandas 2.1/2.2/2.3 依赖矩阵，末位差属正常）。
⚠️ **golden 只防回归、不证明正确性**——它回答「今天和昨天一样吗」，正确性由 L1–L4 负责。

📌 **对 §6.6 示例的有意偏离**：§6.6 举例「如 5×250」，但 **250 日正是 A101 最长窗口**
（`alpha19/39` 的 `Σ250`、`alpha48` 的 250 日相关），5×250 会让这些因子整片 NaN ⇒ 改用 **5×320**，
并把它写进 `manifest.json` 的 `deviation_from_design_doc` 字段与 `tests/golden/README.md`；
`test_golden_panel_exercises_the_longest_windows` 守着这条理由。

**状态终态**（§6.8 六条门槛）：**`verified` 82/101**、`partial` **19/101**、`ambiguous` **0**。
19 个 `partial` 全部是「vnpy 未实现、无第三方参照」的因子（18 个含 `IndNeutralize` + `alpha56` 需 `cap`），
按门槛 3（**必需**）在原理上无法满足，备注里逐条写明「缺哪条、为什么」。
设计文档 §6.8 的诚实预期是「`verified` 不可能是 101/101，预估 60~80」，实测 82 —— 未超预期夸大。

### 1.8 L6 辅助统计（2026-10-11，**不是门槛**）

`tools/l6_statistics.py` 在本地真实 A 股面板（**60 只 × 359 交易日**，hfq + 申万 PIT 行业）上跑完 101 个因子：

| 项 | 结果 |
|---|---|
| 平均 IC（h=1/2/3/5/10，截面 Spearman） | **+0.0131 / +0.0110 / +0.0126 / +0.0131 / +0.0149** |
| IC 最强（按 \|IC1\|） | alpha15 +0.054、alpha83 +0.045、alpha57 +0.041…（完整表 `reports/l6_ic.csv`） |
| **两两 PnL 相关均值** | **0.164**（4950 对）—— 论文断言 **15.9%**（**同量级，但不构成验证**：A 股 vs 美股、样本 60 只） |
| 市值暴露（截面秩相关） | 均值 +0.000，绝对值最大 0.160（alpha37） |
| 行业暴露（申万 L1，sqrt(R²)） | 均值 0.611，最大 0.807（60 只股票的小样本下行业解释力本就偏高） |

**三条必须与结果一起读的纪律**（设计文档 §6.7）：

1. **统计显著 ≠ 实现正确**：本表**不参与** `verified/partial` 判定，一个因子状态都没动；
2. **A 股 ≠ 美股**：论文的 0.6~6.4 天持仓与 15.9% 相关都基于美股，此处只作弱参考。
   本次 IC 绝对值最大处落在 **h=10**（与「短周期应更强」的直觉相反）——**只作观察、不下结论**，
   样本量（60 只 × 359 日）与 A 股制度差异都足以解释；
3. 向量化实现已与「逐日 `scipy.stats.spearmanr`」做过逐点等价性验证（`tests/test_l6_statistics.py`，
   最大差 5.6e-17）——**提速不等于换口径**。

### 1.9 BRAIN 行为对齐抽样（补充证据层：工具已交付，平台侧待会话）

平台**只返回 alpha 的表现**（PnL/Sharpe/turnover），**不返回因子矩阵** ⇒ 「行为对齐」只能是
同一表达式两侧各出一条日度 PnL，比较**单调性**（Spearman）而非数值相等；且两侧必须**同一市场**
（本库是 A 股 ⇒ 平台侧须选 **CHN**）。

`tools/brain_alignment.py` 已交付并本地跑通（alpha5 本地 PnL 年化 Sharpe ≈ +1.50，60 只 × 359 日），
两条取数路径都是**零配额**：`--alpha-id`（读已有仿真）/ `--platform-pnl`（读导出的 PnL 文件）；
`--submit` 会被拒绝执行（不代用户消耗配额）；凭据只从 `BRAIN_COOKIE` 或文件读。

**状态：⛔ 被「数据权限」卡住（比会话过期更根本）**。2026-10-11 实测（三条独立证据）：

1. 会话层面：上一轮 JWT 于 00:50 过期 ⇒ `/users/self` 返回 401（用户随后提供了新会话，已恢复）；
2. **权限层面（决定性）**：该账号**只有 USA 数据**。2026-10-11 用**新会话**复测（排除会话因素）：
   * `/data-sets?region=USA` = **150**（对照组，证明区域过滤本身有效）；
   * `/data-sets?region=CHINA` = **0**、`region=CHN` = **0**（**两种拼写都试过**——平台 UI 用 `CHN`，
     而 WQB 等第三方库用 `CHINA`，因此不能只试一种）；
   * `/data-fields?region=CHN&universe=…` 在 `TOP2000U/TOP1000U/TOP3000U/TOP2000A` 下**全是 count=0**，
     不带 universe 则报 `Invalid query`（该接口强制要求完整上下文）；
   * `region=GLB/EUR/ASI` 也都是 0。
   这与平台规则一致：**欧洲与亚洲市场仅对部分研究顾问开放**，普通账户拿不到中国区数据。

⇒ 平台侧**只能产出美股 PnL**，而本库的数据是 A 股 ⇒ **「同一市场」这个前提不成立**，
按设计文档 §2.3 的原意（同表达式、同市场、比单调性）**无法完成**，不是差一步、而是缺一项权限。
`/simulations` 也确认只接受 POST（即任何平台侧仿真都要消耗配额）。

**可复验（只读、不消耗配额）**：`python tools/brain_alignment.py --check-region` 会打印
``USA / CHINA / CHN`` 三个区域的数据集数并给出退出码（**0 = 有中国市场；3 = 没有**）。
用户侧还可以按平台自己的三处核对：Settings 的 Region 下拉是否有 China、账户是否为
Research Consultant / 特定竞赛参与者、以及在 WQB 里用 `region='CHINA'` 搜数据集。

**要真正收口只有两条路**：① 给账号开通中国区数据（成为研究顾问或参加相应竞赛），或
② 提供同源美股数据，让本库侧复现美股 PnL，然后任选 `--alpha-id` / `--platform-pnl` 收口。
在拿到其中任一之前，本项**保持未完成**，不写成「已验证」——这是设计文档 §6.4「严禁简单判错」的同一条纪律。

📌 **顺带记录的平台工程细节**：连抓 400+ 请求会触发 ``{"message":"API rate limit exceeded"}``
（实测），`tools/fetch_brain_docs.py` 因此内置 0.35 s 间隔 + 遇 429 按 5/15/45/90 s 退避重试。

### 1.10 L-B 文档语料（本地，gitignored）

`refs/brain_docs/`（由 `tools/fetch_brain_docs.py` 抓取，**不入库**：登录墙内的专有文档）：

| 文件 | 内容 |
|---|---|
| `operators.md/pdf`（35 页） | **66 个算子**的完整正文（53 个有详情页）+ 官方算例 |
| `tutorials.md/pdf`（54 页） | Learn 教程正文：5 个 pack / 17 页 |
| `data_sets.md/pdf`（49 页） | 数据集目录 150 个（类别/覆盖区域/延迟/描述） |
| `data_fields.md` + `data_fields_summary.md` | 数据字段目录 **4367 个**（含描述与所属数据集，上下文 EQUITY/USA/TOP3000/delay=1）+ 字段名总表 4545 个 |
| `raw/*.json`（73+） | 原始 API 响应，可复核、可再加工 |

### 1.11 美股真实数据验证（tushare 受阻 → 改用新浪，**已完成**，2026-10-12）

**目标**：用真实**美股**行情再跑一遍算子/因子验证（A 股已做过），以回答「算子和因子在另一个市场上是否依然成立」。
完整报告见 [`reports/us_verification_report.md`](../reports/us_verification_report.md)。

**第一步：tushare（用户最初指定）不可行 —— 三条硬约束（都有原始报错）**

| 探测 | 结果 |
|---|---|
| `us_basic` | ✅ 6000 只；但 `classify` 只有 `EQ/ADR/PF/GDR`（**证券类型，不是行业**） |
| `us_daily` | ⚠️ 先 `频率超限(1次/分钟)`，连续试探后升级为 **`频率超限(1次/小时)`** |
| `us_daily_adj` / `us_adjfactor` | ❌ `抱歉，您没有接口(...)访问权限` ⇒ 只有未复权价 |

**第二步：经用户同意改用免费源 —— 实测对比后选新浪**

| 源 | 实测 |
|---|---|
| Yahoo chart API | ❌ HTTP 403（被挡） |
| Stooq CSV | ❌ 返回 JS 验证挑战页 |
| 腾讯 fqkline | ✅ 可用，但 **`qfq`/`hfq` 对美股无效**（三种口径返回同一份未复权价） |
| **新浪 US_MinKService** | ✅ **首选**：一次请求拿**全历史**（AAPL 10050 行，1984 至今），字段含**成交额** ⇒ `vwap = 成交额/成交量` 是**真 VWAP** |

**第三步：真实结果（80 只 × 753 个交易日，2022-01-03 ~ 2024-12-31）**

| 检查 | 结果 |
|---|---|
| 面板契约 | ✅ 通过 |
| `vwap ∈ [low, high]` | **99.49%** |
| 因子可跑数 | **82/101**（缺 `cap`/`ind_*` 的 19 个自动跳过） |
| ±inf | **0 个** |
| 平均覆盖率 | **89.5%** |
| 时间截断一致性（抽样 12 个因子） | ✅ **全部通过** |
| **因子级差分 vs vnpy（82 个可比因子）** | ✅ **64 逐点一致 + 18 已归因 + 0 待查**（归因构成与合成面板/A 股**完全一致**） |

**两个被真实数据抓出来的 bug（都已修 + 留回归测试）**

1. **拆股漏检**：比例表只列到 10:1 ⇒ 漏掉 **20:1**（GOOGL 2022-07-18、AMZN 2022-06-06）；
   成交量判据要求「精确 1/r 倍」⇒ 漏掉 **LRCX 10:1**（当日成交量只增 4.7 倍）。
   修法：比例表补到 20:1；成交量改为**物理判据**（正拆要求成交量 ≥2 倍，反拆 ≤0.5 倍）。
   修正后 `|单日收益| > 35%` 的格子从 **3 → 0**（那 3 个全是漏检的拆股假暴跌）。
2. **列名兼容**：`build_panel` 原先按 tushare 列名写死（`trade_date`/`ts_code`/`vol`）⇒ 新浪路径（`date`/文件名/`volume`）全线报错。
   已做成兼容两套列名，并有测试守着。

**未覆盖项（不假装完成）**：18 个 `IndNeutralize` 因子（免费源无行业字段，留待 A 股数据覆盖）、
`alpha56`（需 `cap`）、**分红未复权**（拆股已修；对因子级差分无影响，因为两侧吃同一份面板）、
样本 80 只而非计划的 162 只（**限流**所致：0.3 s 间隔会被新浪挡掉一半，已改为 1.2 s + 重试 + 断点续取）。

**数据处置**：用户不持有美股数据 ⇒ 验证后已执行 `python tools/us_data_verification.py --delete --audit`，
审计见 [`reports/us_data_audit.md`](../reports/us_data_audit.md)。数据全程只在 gitignored 的 `refs/` 下，**从未进入 git**。

### 1.12 第二独立参照差分（MIT 许可）：接入完成，**19 个 partial 暂不升级**（2026-10-12）

**动机**：19 个 `partial` 因子（18 个含 `IndNeutralize` + `alpha56` 需 `cap`）卡在**门槛 3「独立逐点对拍」**上——
第一参照（vnpy）没有实现它们，所以这条门槛原理上无法满足。用户选择「补第二个独立参照」来攻这个缺口。

**参照选型（先过许可这关）**：社区主流实现要么 `license=None`、要么 `NOASSERTION`（**不具备可用许可**），
最终选定 **[alpha101-pipeline](https://pypi.org/project/alpha101-pipeline/) 0.6.2**：
PyPI 分类器明写 **MIT** ⓐ、独立作者、DuckDB/SQL 实现、**覆盖全部 101 个公式（含全部 19 个）**、支持 `IndNeutralize` 与 `cap`。
它装进仓库内**独立 venv**（`.refs/venv-ref`，gitignored），**不进运行时依赖**（`pyproject` 不动，
`tests/test_provenance.py` 继续守 numpy/pandas/scipy）；**GPL 实现一律不用**（设计文档 §1.1 第 8 行）。

**工具**：`tools/second_reference_differential.py`（差分 + 归因）、`tools/fetch_second_reference.sh`（取参照、记录版本与许可）。
参照自己声明的口径必须**逐条对齐**，否则比的是口径：

| 参照 | 本库默认 | 对齐 |
|---|---|---|
| 截面 `rank` = **0..n−1** | `[0,1]`（官方） | 切 `ordinal` 后 **减 1**（实测：不改 alpha56 全列不匹配；改后 2138 → 26） |
| 滚动 `stddev` **ddof=1** | `ddof=0`（官方） | 切 `ddof=1` |
| `decay_linear` 满窗 | 稀疏（官方） | 切 `dense=True` |
| `argmax` 自窗口起点 | `days_ago`（官方） | 切 `basis="window_start"` |
| `^` 保号 | `power`（官方丢符号） | `^`→`signedpower` |
| `adv{N}` = `volume*close` | 真成交额 | 面板 `amount := volume*close` |
| 小数窗口**四舍五入** | `floor`（论文 §3） | ⚠️ **见下：实测不是主因** |

**已证明的机制（都有最小复现，不是猜）**

1. **并列取号不同**：参照按**行序递增**取号，本库取 `average`。
   复现：构造全并列面板（close 只有 3 个取值）⇒ 参照 `alpha56` 输出 −k² 序列（0,−1,−4,−9,…），本库 `ordinal` 出现 .5 名次；
2. **窗口不足/退化时 0 vs NaN**：参照走 SQL ⇒ 给 **0**，本库按官方给 **NaN**。
   复现：常价格面板上参照 `alpha56` 有有限值、本库全 NaN；真实面板上体现为 1.3~1.6 万个 NaN 差异。

**已被证伪的归因（重要教训）**：曾把「公式里有 round≠floor 的小数窗口」直接判为**已归因** ✗。
把参照的 `alpha58` 公式改成 floor 后重比：不匹配比例 **98.9% → 100%**（更差）
⇒ **小数窗口不是主因**。工具里该判定已降级为「待查（含小数窗口候选，未证伪）」，
并用测试钉死（`tests/test_second_reference.py::test_window_verdict_is_not_an_attribution`）。
**教训**：归因必须做**证伪实验**（改参照再比），不能靠「公式里有这个特征」。

**19 个因子的现状（真实面板 60 只 × 359 日，按 4 个一批跑）**：**没有任何一个达到逐点一致**；
差异主要由上面两类「参照侧口径偏离」加上**尚未定论的第三类**（`indneutralize` 语义：抽到的 L2 行业组只有 1 只 ⇒ 判定退化，
需用更粗的分组重测）共同造成。⇒ **19 个状态一律保持 `partial`**，不升级、不豁免（与设计文档 §6.4 同一条纪律）。
结果表：`reports/second_reference_diff.csv`。

**工程坑（都写进工具了）**：参照默认的自动分块/内存探测在沙箱里会**挂死**
（`/tmp` 是受限 tmpfs，DuckDB 落盘失败又不报错）⇒ 必须显式 `chunked='never' + memory_limit='1GB' + temp_dir=<工作区>`（>400s → 1.3s）；
公式数一多（19 个）仍会挂 ⇒ 按 4 个一批跑。

**下一步（收口这 19 个的唯一正路）**：逐因子做证伪实验——把参照改成与本库同口径
（组内去均值替代 z-score、空窗口给 NaN、并列取 average），若某因子差异随之塌缩到 0，
该因子的差异就被**证明**为参照侧口径偏离，届时再按既有标准评估是否升级。

## 2. 六层协议状态

| 层 | 判据 | 状态 | 说明 |
|---|---|---|---|
| **L1 算子层** | 20/20 | ✅ **通过** | 见 §1 |
| **L2 规范对照** | 101 行偏差清单 | ✅ **101/101 等价** | `tools/conformance_report.py` 已交付；对照粒度为算子级（见 §1.4 与工具文档的能力边界） |
| **L3 双实现差分** | 82 个可比因子 `allclose(rtol=1e-8)` | ✅ **算子层 + 因子层均已做**：算子层 24 项（18 一致 + 6 归因）；因子层 82 个可比因子 **0 待查**（64 一致 + 18 已归因，§1.5） | 19 个因子（18 IndNeutralize + alpha56）无第三方参照，结构上无法差分 |
| **L4 不变量与元测试** | 截断/缩放/未来扰动/入参不可变/变异 | ✅ **算子层 + 因子层均已做** | 算子层见 §3；因子层：101 个因子的「可算不产 ±inf / 入参不可变 / 时间截断一致性」（`tests/test_factors_all.py` 306 项）；8/8 变异注入被抓 |
| **L5 golden 快照** | 快照入库 | ✅ **已入库**（2026-10-11） | `tests/golden/`：5×320 定种子面板 + 101 个因子输出（npz）+ sha256 清单 + 环境版本；`tests/test_golden.py`（5 项）与 `tools/golden_snapshot.py --check` 已接进 CI，见 §1.7 |
| **L6 统计合理性** | IC 符号/衰减/暴露 | 🟡 **已跑（辅助，非门槛）** | `tools/l6_statistics.py` + `reports/l6_summary.md`；**明文：统计不参与 `verified` 判定**，A 股 ≠ 美股只作弱参考（§1.8） |
| **状态终态** | §6.8 六条门槛 | ✅ **`verified` 82/101、`partial` 19/101、`ambiguous` 0** | 19 个缺门槛 3（无第三方参照，见 `ambiguities.md` U5）；设计文档 §6.8 曾预估 60~80，实测 82 |

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
| 1 | 因子的正确性（`verified` 仍为 0/101） | **L2 结构对照 ✅**、**L3 因子级差分 ✅（82 个可比因子 0 待查）**、L4 不变量 ✅；缺 **L5 golden 快照（M5）** | M5 |
| 2 | 与论文公式的结构一致性（L2） | **基准文本已入库并通过 101/101 括号平衡校验**（§1.1）；缺的是「实现 AST ↔ 论文算子树」的逐节点比对工具（`tools/conformance_report.py`）与因子本身 | M3 |
| 3 | 与 vnpy 的**因子级**差分一致性（L3） | ✅ **已完成（M4）**：82 个可比因子 0 待查；19 个无参照的缺口由 L2 + L4 覆盖 | — |
| 4 | 19 个缺口因子（18 个 `IndNeutralize` + `alpha56`） | **无法差分**，只能靠 L2 规范对照 + L4 不变量 | M3/M4，结论须标注「无第三方对拍」 |
| 5 | golden 快照防回归（L5） | 无因子可冻结 | M5 |
| 6 | BRAIN 官方算子文档（L-B 级规范） | 未获取（设计文档 §2.3 待办） | 取到后复核 `days_ago` 等口径 |
| 7 | A 股落地口径（复权/PIT 行业/真换手率/单位） | 🟡 **部分完成**（§1.3）：PIT 行业、单位口径、市值已接上并验证；**复权未做** ⇒ `returns` 在除权日有假跳空 | M3 补复权（`stock_xdxr`）或改用已复权源 |
| 8 | 中性化算子在大面板上的性能 | M1 只承诺正确性 | M2 起基准测试 |

---

## 5. 复现与 CI

```bash
PY=/home/yinxiuqu/anaconda3/envs/qa/bin/python

$PY -m pytest -q                                   # 全量 682 项（真实数据 35 项在无库时自动跳过）
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
| **v0.10** | 2026-10-12 | 新增 §1.11（**美股验证**：tushare 三条硬约束 —— 无行业字段、`us_daily` 1 次/小时、复权接口无权限 ⇒ 本轮未完成且不假装完成；交付一条命令的完整链路 + 拆股后复权逻辑（含方向写反的回归测试）+ `--panel-file` 差分能力 + **美股数据删除审计**）；另新增 `docs/usage.md` 使用指南与 `examples/` 两个可跑示例 |
| v0.9 | 2026-10-11 | 新增 §1.8（**L6 辅助统计**：101 个因子在 60 只 × 359 日 A 股上跑完，平均 IC 约 +0.011~+0.015、两两相关 0.164 对照论文 15.9%，并写明「不参与判定」的三条纪律）、§1.9（**BRAIN 行为对齐**：工具已交付、平台侧因会话过期未完成，差一步的说明）、§1.10（**L-B 文档语料**：算子/教程/数据集/字段目录 + PDF，本地 gitignored）；门槛表 L6 行更新；测试数 671 |
| v0.8 | 2026-10-11 | **M5 终态**：新增 §1.7（L5 golden 快照 + 对 §6.6 示例的有意偏离 + 状态终态）；门槛表 L4 更正为「算子层 + 因子层均已做」、L5 置为已入库、新增「状态终态」行；测试数 655；状态 `verified` 82/101、`partial` 19/101 |
| v0.7 | 2026-10-10 | **三处官方口径落地**（§1.6）：`rank`/`ts_rank` 归一化 `[0,1]`、`ddof=0`、`decay_linear` 稀疏 NaN→0；官方四个算例进测试；新增「`rank` 可取 0 ⇒ 比值型因子除零 ⇒ 输出边界把 ±inf 降级为 NaN」的处置；差分 D2 消失、新增 D7/D7b/D8 |
| v0.6 | 2026-10-10 | 追加 **API 级完整文档**：65 个算子正文入库；新定案 3 处默认口径差异（归一化区间 / ddof / 稀疏 decay）并记为待办；测试数 648 |
| v0.5 | 2026-10-10 | **L-B 官方算子文档入库**：新增 §1.6（三处歧义定案 + 与本库既有决策的相互印证 + 文档未展开项）；§1.4 的「27 个 ambiguous」更新为已定案清零；argmax 默认翻转与 `elemwise.power` 新增（alpha48 修复） |
| v0.3 | 2026-10-09 | 新增 §1.2 **算子层差分对拍**（24 项：18 一致 + 6 归因 + 0 待查）；更新 §2 的 L3 行为「算子层已做」、§4 第 3 项、测试总数 219→277（新增 `test_elemwise`/`test_factors`/`test_differential`） |
| **v0.4** | 2026-10-09 | 新增 §1.3 **真实 A 股端到端**（359 交易日 × 120 只：契约通过、vwap 自洽 99.86%、行业覆盖 98.0%、5 因子零 inf、PIT 中性化残差和 3.4e-15）与 3 条数据口径限制（**未复权**、0.14% vwap 越界、市值口径待定）；测试总数 277→297；§4 第 7 项改为「部分完成」 |
| v0.2 | 2026-10-09 | 新增 §1.1 规范入库校验（论文 101/101 公式、0 条括号不平衡、与设计文档 §3.2 依赖表 5/5 一致）；更新 §4 第 2 项（L2 基准文本已就位） |
