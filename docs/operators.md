# Alpha101 算子层口径规范（operators.md）

| 项 | 内容 |
|---|---|
| 文档版本 | **v0.3**（2026-10-09；v0.3 加入 **vnpy 差分实测**结论） |
| 状态 | 16 个时序/截面算子 + 1 个构件 + 3 个中性化算子，**全部有测试**，M1 判据 20/20 通过 |
| 上游依据 | `docs/Alpha101_修复发布决策与验证协议_v0.1.md`（内容版本 **v0.2**）§6.2、§7.3、§8 |
| **规范来源（L-A）** | `docs/paper_formulas.md`——论文 arXiv:1601.00991v3 的 **101/101 条公式与算子定义逐字入库**（括号平衡校验 0 条不平衡） |
| 代码 | `src/alpha101v/operators.py`、`src/alpha101v/neutralize.py` |
| 测试 | `tests/test_operators.py`（§8 全部用例）、`tests/test_invariants.py`、`tests/test_mutation.py` |
| **第三方对拍（L3）** | `tools/differential.py` + `tests/test_differential.py`：与 vnpy（MIT）算子层逐点对拍，24 项中 18 项对齐后逐点一致、6 项为**已归因口径差异**（§6） |

> **本文档是算子口径的唯一权威。** 代码与测试都是它的实现与执行：
> 任何口径变更必须**先改本文档**，再改代码，再改测试。三处不一致即为缺陷。

---

## 1. 范围

**做**：20 个算子的语义、口径、边界与歧义点决策，以及锁定它们的具体测试。
**不做**：因子实现（M2/M3）、回测、因子挖掘、数据采集（见设计文档 §7.1「非目标」）。

算子面恰好 20 个（设计文档 §7.3 的 17 个 API + §8.1 要求对拍的构件 + §8.3 的两个中性化变体）：

| 组 | 算子 | 来源 |
|---|---|---|
| A 组·时序（16 个中的 14 个） | `ts_sum` `sma` `stddev` `correlation` `covariance` `ts_rank` `product` `ts_min` `ts_max` `delta` `delay` `decay_linear` `ts_argmax` `ts_argmin` | §7.3 |
| B 组·截面（2 个） | `rank` `scale` | §7.3 |
| 构件（1 个） | `rolling_rank` | §8.1「被 ts_rank 使用」 |
| 中性化（3 个） | `ind_neutralize` `neu_industry` `neutral` | §7.3 + §8.3 |

`alpha101v.OPERATORS` 导出这份清单，`tests/test_operators.py::test_api_surface_is_exactly_twenty` 守着它。

📌 澄清（非勘误）：§7.3 的代码块只有 17 个 `def`，而 §10.4 的 DoD 要求「20 个算子」。
差额正是 §8.1 的 `rolling_rank` 与 §8.3 的 `neu_industry`、`neutral`。本实现按 20 个交付。

📌 **论文原文核对后的补充（2026-10-09）**：20 个算子是**算子层**的正确边界。
论文另用 4 个**一元逐元素函数**（`abs` 5 个因子、`log` 3 个、`sign` 6 个、`signedpower` 2 个，合计影响 **15 个因子**），
它们不属于算子层，必须在**因子层**补一个 `elemwise` 层（M2 交付；见 `docs/paper_formulas.md` §7.6）。

---

## 2. 统一契约

### 2.1 面板与轴向（设计文档 §7.4、附录 B）

* **面板 = `DataFrame`**，`index` = 交易日（**升序、唯一、`DatetimeIndex`**），`columns` = 股票代码（唯一）。
* **时序算子沿 `axis=0`**（逐股票一条序列滚动）；**截面算子沿 `axis=1`**（每日算一次）。
* 所有算子返回 `DataFrame`，`index`/`columns` 与入参一致。
* 严格模式：index/columns 有重复 → `ValueError`（重复会让 `stack/unstack`、分组语义不明）。

### 2.2 纯函数与输入不可变性（设计文档 §6.5）

算子**绝不原地修改入参**。这条不是风格偏好，而是针对原始实现真实事故的修复：
`alpha1` 里 `x = close; x[returns < 0] = ...` 因别名而非拷贝，**污染了整个 close 面板**
（设计文档 §3.3 缺陷 2）。

* 锁定测试：`tests/test_invariants.py::test_inputs_are_not_modified`（22 个调用点逐一断言 `assert_frame_equal`）。
* 变异测试 `m6_delta_mutates_input` 注入原地写入，断言该测试**必然失败**。
* 因子层另有一道防线：`registry.run_factor` 默认对入参做深拷贝（设计文档 §7.5 前提①）。

另有一条**依赖纪律**：算子不得触发 pandas 弃用警告（`test_no_deprecated_pandas_api_warnings`
把 `FutureWarning`/`DeprecationWarning` 转成异常）。原始实现正是死于 `as_matrix()`
（pandas ≥1.0 已删除，§3.3 缺陷 1）与 `fillna(method=)`（2.x 废弃）：把「用了将被删除的 API」
变成一条立刻失败的测试，比等它某天崩掉便宜得多。

### 2.3 预热期策略：`min_periods = window`（★ 设计决策）

**决策**：所有滚动算子的 `min_periods` 一律等于 `window`，即**前 `window-1` 行必为 NaN**，
窗口内出现任何一个 NaN 该点即为 NaN（不做部分窗口近似）。

**理由**：
1. 幂等可信：NaN 只代表「信息不足」，不会被一个用 1 个样本算出来的伪值掩盖；
2. 原始实现与多数实现放任默认值，导致「前 3 行到底该不该有值」无人能答（设计文档 §6.2 要求钉死）；
3. 与 `delta`/`delay` 的 NaN 语义（无过去数据即 NaN）保持一致。

**被否决的替代口径**：`min_periods=1`（预热期填值）。它不引入前视，但会让
`ts_rank`/`stddev` 在样本不足时给出**不可比**的数值，且与 `warmup` 相关的回归测试失去意义。
（若未来确有需要，应做成显式参数并同时改本文档，而不是偷偷放宽默认值。）

**锁定测试**：`test_a25_min_periods_strict_warmup_for_every_rolling_operator`（12 个滚动算子逐一断言预热期 NaN 且之后有值）、
`test_a26_nan_inside_window_propagates`。变异 `m7_ts_sum_min_periods_loosened` 必须被抓住。

### 2.4 `Series` 语法糖

传入 `Series` 视为「单列面板」的语法糖（便于按单只股票逐条对拍），但**返回值一律是 `DataFrame`**：
全库只有一种返回类型，避免 M2 的因子代码出现多态分支。

* 二元算子（`correlation`/`covariance`）要求两块面板 `(index, columns)` **完全一致**；
  两个 `Series` 语法糖因此要求列名相同，否则显式报错并提示用 `.to_frame(name=...)` 统一列名。

### 2.5 NaN / Inf 语义汇总

| 情形 | 结果 | 说明 |
|---|---|---|
| 预热期（样本 < window） | NaN | §2.3 |
| 窗口内含 NaN | NaN | 不做部分窗口 |
| 截面除零（`Σ\|x\| = 0`） | NaN | 0/0 未定义，**不是 0、不是 inf** |
| 相关系数零方差 | NaN | §3.5 |
| `vwap` 遇 `volume = 0` | NaN | `panel.vwap_from_amount` |
| `returns` 遇价格 ≤ 0 | NaN | 脏数据，不制造 inf |
| `neu_industry` 遇行业均值 0 | NaN | 比例未定义 |
| 行业标签 NaN | 残差 NaN | 无法定义所属组 |
| 输入 ±inf | 不承诺 | 面板契约把 ±inf 判为脏数据（`panel.validate_panel` 报错） |

---

## 3. 六个歧义点的显式决策

设计文档 §6.2 / §7.3 / §10.4 要求把以下歧义点「做成显式参数或显式文档决策」。
下表是决策摘要，随后逐条给理由与被否决的替代口径。

| # | 歧义点 | **本库决策** | 显式化方式 | 锁定测试 |
|---|---|---|---|---|
| 3.1 | `stddev`/`covariance` 的 ddof | ✅ **L-B 定案：默认 0**（总体口径，官方 `ts_std_dev` 算例除以 n），`ddof=1` 可选 | 参数 `ddof` | `test_a03` `test_a04` `test_a05` `test_a22` `test_a23` |
| 3.2 | `ts_rank`/`rank` 的归一化区间 | ✅ **L-B 定案：默认 `zero_to_one`** = `(名次−1)/(n−1)` ∈ **[0,1]**（官方算例 `(4,3,6,10,2)→(0.5,0.25,0.75,1,0)`、`ts_rank` `3/(5−1)=0.75`）；`one_over_n`（`名次/n`，vnpy 口径）与 `ordinal`（序号）可选 | 参数 `normalization` | `test_a10` `test_a11` `test_b01` `test_b03` |
| 3.3 | `ts_argmax`/`ts_argmin` 基准与方向 | ✅ **L-B 定案**：**默认 `days_ago`**（BRAIN 口径：今天=0 ∈ [0, window-1]）；`basis="window_start"`（自窗口起点 1-based）保留为 vnpy 对齐选项 | 参数 `basis` | `test_a12`–`test_a16` |
| 3.4 | `scale` 轴向 | **`axis=1`**（每日 `Σ\|x\| = k`） | 无参数（口径固定），断言逐日 `Σ\|x\| = k` | `test_b05`–`test_b07` |
| 3.5 | `correlation` 遇常数序列 | **NaN**（不是 0、不是 ±inf） | 无参数（口径固定） | `test_a20` |
| 3.6 | `rank` 并列策略 | **`method="average"`**（pandas/scipy 默认） | 参数 `method` | `test_b02` `test_a24` |

### 3.1 ddof：默认 `0`（总体口径，L-B 定案）

* **决策（2026-10-10 由 BRAIN 官方文档定案）**：`stddev(df, window, ddof=0)`、`covariance(x, y, window, ddof=0)`；
  `ddof=1`（样本口径）仍可选，其他值显式报错。
* **一手依据（L-B，官方算例）**：``ts_std_dev`` 文档的算例把平方偏差之和除以 **5**（不是 5−1）：
  > Compute the mean: (0.01 + 0.02 + −0.01 + 0.00 + 0.03) / 5 = 0.01 …
  > **Average the squared deviations: (0 + 0.0001 + 0.0004 + 0.0001 + 0.0004) / 5 = 0.0002**
  > Take the square root: sqrt(0.0002) ≈ 0.0141

  ⇒ 官方是**总体标准差**（`ddof=0`）。本库原先默认 `ddof=1`（当时以 pandas/polars 默认 + 「与 vnpy 对齐」为由），
  现已按官方口径翻转，并在 `test_a03` 用官方算例钉死（`sqrt(2/3)`）。
* **M3 时被否决、现被推翻的理由记录**：当时认为「金融收益是样本视角」且「pandas/polars 默认 1」；
  但本项目的第一判据是**平台规范（L-B）**，统计哲学不能凌驾于规范之上。
* **`covariance` 的 ddof=1 实现**：`cov_pop × window/(window-1)`（严格预热 ⇒ 窗口内有效样本数恒为 `window`）。
* **对拍影响**：vnpy 的 ``ts_std`` 本来就用 ``ddof=0`` ⇒ 本库默认现在与它**逐点一致**，
  `tools/differential.py` 里原先记录的差异项 **D2（ddof）已消失**（该工具现以「对齐」项断言它）。
  注意 vnpy 自身不一致：``cs_std``（截面）走 polars 默认 ``ddof=1``。

### 3.2 归一化区间：默认 `zero_to_one` = `(名次−1)/(n−1)` ∈ [0,1]（L-B 定案）

* **决策（2026-10-10 由 BRAIN 完整文档定案）**：
  * `ts_rank(df, window, normalization="zero_to_one")` → 窗口**末值**的平均名次 `k` ⇒ `(k−1)/(window−1)` ∈ **[0,1]**；
  * `rank(df, normalization="zero_to_one", method="average")` → 当日截面平均名次 `k` ⇒ `(k−1)/(n−1)` ∈ **[0,1]**；
  * 另两档可选：`one_over_n` = `名次/n` ∈ (0,1]（**vnpy 口径**，差分对拍用它对齐）、`ordinal` = 序号 `1..n`。
* **一手依据（L-B，官方算例）**：
  > `rank`：「assigns a rank to each value … **mapping the lowest value to 0.0 and the highest to 1.0**」
  > 例：`x = (4, 3, 6, 10, 2)` ⇒ `rank(x) = (0.5, 0.25, 0.75, 1, 0)`
  > `ts_rank`：「13 is the 4th value out of 5 (0-based index: 3) ⇒ **Normalized rank: 3 / (5 − 1) = 0.75**」

  两例都指向 `(名次−1)/(n−1)`；本库原先的 `名次/n`（值域 (0,1]，依 vnpy 的 `/count()`）**被官方口径取代**。
* **边界（显式声明）**：`n = 1`（当日只有一个有效标的）时 `(名次−1)/(n−1)` 分母为 0 ⇒ **NaN**（不伪装成 0 或 1）；
  `one_over_n` 在该情形给 1.0，`ordinal` 给 1。
* **影响面**：`rank` 在 101 个因子里出现 167 处、`ts_rank` 62 处 ⇒ **全部 101 个因子的取值都受影响**
  （L2 结构对照与 L4 不变量不受影响；因子级差分在按 `one_over_n` 对齐后仍为 0 待查，见 `docs/verification.md` §1.5）。
* **对拍影响**：新增两条已归因差异 **D7（`rank`）/D7b（`ts_rank`）**：本库默认 vs vnpy 的 `one_over_n`。
* **历史记录**：本库在 M1/M2 曾明确写下「若参照实现用 `(rank-1)/(n-1)` 或 ordinal，需要在差分层做归一化」——
  现在官方文档裁定 `(rank-1)/(n-1)` 才是主口径，因此不是「差分层归一化」，而是**本库默认口径的更正**。
* **vnpy 差分实测（2026-10-09）**：
  * ``cs_rank`` 源码自述 *"WorldQuant cross-sectional rank (method=min, pct=True)"* →
    与「无并列时」的本库默认 **逐点一致**（实测），**并列时**它用 `min`、本库用 `average`（§3.6）；
  * ``ts_rank`` 用 ``scipy.stats.percentileofscore(w, w[-1])/100``，与「窗口末值的 `rankdata` 平均名次 / n」
    **数学等价（含并列）**，实测 **逐点一致**——即本库 ``ts_rank(pct=True)`` 与参照完全吻合，
    无需归一化；``pct=False``（序号口径）才是参照没有的分支。

### 3.3 `ts_argmax`/`ts_argmin` 基准、方向与并列

* **决策（2026-10-10 由 L-B 定案）**：**默认 `basis="days_ago"`** —— 官方 BRAIN 口径
  「距今几天」，**今天最大返回 0**、昨天返回 1，∈ [0, window-1]。
  另一口径 `basis="window_start"`（自窗口起点 1-based ∈ [1, window]）保留可选，
  **vnpy 用的就是它**，因子级差分对拍时用它对齐。换算关系 `days_ago = window − window_start`。
* **一手依据（L-B，原文）**：
  > `ts_arg_max(x, d)` — Returns the number of days since the maximum value occurred in the last d
  > days of a time series. **If today's value is the maximum, returns 0**; if it was yesterday,
  > returns 1, and so on.（`ts_arg_min` 同构；`refs/WorldQuant_BRAIN.pdf`，2026-10-10）

  即 BRAIN 明确采用 `days_ago`，本库原先的默认（自窗口起点 1-based，依据「原实现 `np.argmax+1`」
  这一 L-D 证据）**与官方口径相反**，故 M3 后翻转默认。
* **影响面（6 个因子）**：`days_ago = window − window_start_1based` 是**序反转**而非平移，
  因此对 `rank(Ts_ArgMax(...))`（Alpha#1）这类用法会得到镜像排序。受影响的 6 个因子：
  `ts_argmax` 用于 1、57、60、96，`ts_argmin` 用于 98、100。翻转默认后它们的取值随之改变
  （L2 结构对照与 L4 不变量不受影响，见 `docs/verification.md` §1.6）。
* **并列细节**：取**最早出现**（与 `np.argmax`/`np.argmin` 一致）⇒ 在 `days_ago` 基准下是「距今最远」。
  `[2, 2, 1]` 的 argmax：`days_ago = 2`、`window_start = 1`。**BRAIN 文档未规定并列**，本库显式钉死。
* **vnpy 差分实测（2026-10-09）**：vnpy 的 ``_reduce_argmax_slice`` 就是 ``series.arg_max() + 1``，
  即 1-based 自窗口起点 ⇒ **vnpy 与 BRAIN 官方口径不一致**（记入 `docs/deviations.md` §3.2 V16）；
  因子级差分因此新增 `basis="window_start"` 对齐开关（`tools/factor_differential.py`）。

### 3.4 `scale` 轴向：`axis=1`

* **决策**：`scale(df, k=1)` 沿 **`axis=1`** 缩放，使**每日** `Σ|x| = k`；`k` 必须是有限正数。
* **理由**：论文定义为**每日截面**缩放。原始实现 `df.div(df.abs().sum())` 是**按列（axis=0）**求和，
  既错又与「每日可比」的经济含义相悖（设计文档 §3.3 缺陷 3）。
* **边界**：某日 `Σ|x| = 0`（全 0 或全 NaN 行）→ 该日结果为 NaN（0/0 未定义），不返回 0、不抛异常。
  行内个别 NaN 不参与求和、不参与缩放，保持 NaN。
* **锁定方式**：断言不是「结果等于某个数组」而已，而是**逐日 `out.abs().sum(axis=1) == k`**——
  这样即使换数据、换 k，轴向一错就必失败（变异 `m1_scale_axis_flip` 即由此被抓住）。

⚠️ **论文原文核对（2026-10-09）**：论文只写 `scale(x, a) = rescaled x such that sum(abs(x)) = a`，
**没有写轴向**。本库取「每日截面」的三条理由（同算子系统内 `rank` 明写 cross-sectional；
「每日 Σ|x| = a」是唯一与面板长度无关的读法；设计文档 §8.2 也按逐日断言）依然成立，
但这条决策**保留为 L-A 歧义**（影响 6 个因子 / 9 处调用），待 BRAIN 文档复核（其 `scale` 带 booksize 语义）。
* **vnpy 差分实测（2026-10-09）**：vnpy ``cs_scale`` 也按 **每日截面** 除以 ``Σ|x|``（源码 `.over("datetime")`），
  与本库 `axis=1` **逐点一致**（实测）；唯一差异是**零和行**：vnpy 给 `0`，本库给 `NaN`（§6 D5）。

### 3.5 `correlation` 遇常数序列（零方差）：NaN

* **决策**：窗口内任一侧方差为 0（常数序列、全 0 序列）→ 结果 `NaN`。**不得返回 0，不得返回 ±inf。**
* **理由**：相关系数是 `cov/σxσy`，零方差时是 0/0 —— 数学上**未定义**。
  返回 0 会被下游因子解读为「无相关性」这一**具体结论**，从而把一个缺失值伪装成观测值。
* **实现依据**：pandas `rolling().corr()` 的实测行为即为 NaN（`tests/test_operators.py::test_a20` 断言），
  本库显式依赖并测试该行为，而不是依赖「碰巧如此」。
* **锁定测试**：`test_a20` 不仅断言 `isnan`，还额外断言 `not isinf` 且 `!= 0`。

### 3.6 并列 rank 策略：`average`；以及平移不变性的边界

* **决策**：`rank` 与 `rolling_rank` 的并列一律按 **`average`** 处理（scipy `rankdata` 默认、
  pandas `rank` 默认）。`method` 可显式切换为 `min`/`max`/`first`/`dense`。
* **理由**：设计文档 §8.2 的文字判据是「与 `scipy.stats.rankdata(row,'average')/n` 逐点相等」，
  且该判据在不含并列的样例上与文档数值一致；`average` 是生态默认，最不易产生意外。
  `method="min"` 可复现文档中并列那一行的字面数值（见 §5 勘误 1）。
* **NaN**：不参与排序且保持 NaN；`pct` 分母是**当日有效（非 NaN）股票数**。整行全 NaN → 全 NaN。
* **平移不变性（补充决策）**：价格整体 `+c` 时，`rank` 不变（单调平移）；但 `ts_rank` 之外的水平型算子
  （`ts_sum`/`stddev`/`decay_linear`…）会变。设计文档 §6.5 的「平移不变性」只在**因子排序层**有意义，
  算子层不作承诺——避免把「多数因子应该不变」误读成「算子应该不变」。
  锁定测试：`test_translation_is_not_guaranteed_but_documented_rank_behaviour`。

---

### 3.7 `decay_linear` 的权重列举顺序（L-A 歧义，影响 **22 个因子**）

论文（§3 定义，逐字）：*"decay_linear(x, d) = weighted moving average over the past d days with
linearly decaying weights **d, d – 1, …, 1** (rescaled to sum up to 1)"*。

**歧义所在**：「过去 d 天」的**枚举方向**没有写死。按时间正序（最早→最新）读 ⇒ 最早权重最大；
按由近及远读 ⇒ 最新权重最大。**两种读法互为反序，是系统性差异**，而 `decay_linear` 被 **22 个因子**使用
（编号与设计文档 §3.2 完全一致）——是本项目**影响面最大的口径风险**。

**本库决策**：末值（最新）权重最大，权重 `1..d` 归一。理由三条：

1. 算子名 `decay` 的语义是「权重随年龄衰减」；反序读法会给出「越老权重越大」，与命名自相矛盾；
2. 与设计文档 §8.1 的期望值 `decay_linear([1,2,3],3) = 14/6` 一致；
3. 把权重列表读作「由近及远」是时间序算子的常规书写方式。

**锁定方式**：`test_a17`（解析值）+ `test_a18`（逐窗口与 `np.average(weights=1..d)` 对拍），
变异 `m3_decay_linear_reversed_weights` 必须失败。
**vnpy 差分实测（2026-10-09，本项风险最高）**：参照实现 `ts_decay_linear` 把权重
`pl.Series(range(window, 0, -1))`（即 `d, d-1, …, 1`）直接套在**时间正序**的滚动窗口上，
于是**最老的一天权重最大**——与本库默认**方向完全相反**（实测最大差 0.788，非平移/缩放）。
这正是论文「枚举方向未写死」的另一半世界。

**本库处置**（三条，全部可复现）：

1. **默认不变**（`recent_first`，最新权重最大）：与设计文档 §8.1 的期望值 `14/6` 一致，
   与 `decay` 命名自洽，也符合线性加权均值的通行惯例（TA-Lib `WMA` 即最新权重最大）；
2. **新增显式参数 `order="oldest_first"`**：复现参照实现的口径，
   实测「本库 `order="oldest_first"` vs vnpy」**逐点一致**（见 §6 对拍表）——
   于是「差异」被转化为一个**可切换的口径参数**，而不是一个说不清的偏差；
3. **风险登记**：`decay_linear` 被 **22 个因子**使用，方向一错即系统性错误。
   在 BRAIN 官方文档（L-B，仍未取得）或论文其他佐证出现前，**这 22 个因子不得标 `verified`**，
   只能标 `partial`/`ambiguous`（设计文档 §9 R2 的硬要求）。

### 3.8 非整数窗口：论文规定 `floor(d)`（本库当前**偏离**，影响 **40 个因子**）

论文（§3 通式，逐字）：*"ts_{O}(x, d) = operator O applied across the time-series for the past d days;
**non-integer number of days d is converted to floor(d)**"*。

论文自身**大量使用非整数窗口**（58–99 号因子，共 229 次，最多 8 位小数），因此这条规则是**吃紧的**：
本库 `_check_window` 目前对非整数 `window` 抛 `TypeError`（由 `test_a27` 断言），
**会让 40 个因子（近 40% 的库）无法转写**。

**决策（L-A，明确无歧义）**：应改为 `window = floor(d)`。要点：

* 必须是 **floor 而不是四舍五入**：`3.65459` 取下整 3，取整会得 4，结果不同；
* floor 之后仍 `< 1`（如 `0.5`）继续报错；`bool` 仍拒绝；
* floor 规则在论文中挂在 `ts_{O}` 通式下，本库把它推广到所有「天数参数」
  （`correlation`/`covariance`/`delta`/`delay`/`decay_linear`/`sum`/`product`/`min`/`max`/`stddev`）——
  这是**合理推断**，已记录（`docs/paper_formulas.md` §7.1）；
* **落地状态**：本条属**已判定但尚未改码**（M1 冻结件；改动将同时更新 `§4.4`、`test_a27` 与 `docs/paper_formulas.md` §7.1）。

### 3.9 论文 `adv{d}` 的落地：取 `amount`（美元成交额），不是 `volume`

论文逐字：``adv{d} = average daily dollar volume for the past d days``。
A 股面板对应 **`amount`（元）** ⇒ ``_adv(amount, d) = sma(amount, d)``。
用股数 `volume` 替代属**近似**（设计文档 §6.3 举的正是这个例子），影响 **45 个因子**，
已记入 `docs/deviations.md` §1.2 P2。实现上 `adv{d}` 是**字段**（论文标识符的一部分），
不是算子——规范对照器把 ``_adv(amount, d)`` 映射回 `adv{d}` 再比对。

### 3.10 `min`/`max` 的两种语义（论文里同名不同义）

论文的算子表只定义了 ``min(x, d) = ts_min(x, d)``（第二参数是**天数**），
但 9 个因子写成 ``min/max(表达式, 表达式)``（两侧都是序列）。本库的消歧规则：

| 第二参数 | 语义 | 落地 | 用到的因子 |
|---|---|---|---|
| 数值（如 `min(x, 5)`） | 时序窗口最小/最大 | `ts_min` / `ts_max` | alpha29（`min(..., 5)`）等 |
| 表达式（序列） | **逐元素**最小/最大 | `elemwise.minimum` / `maximum` | 29/71/73/76/77/82/88/92/96 |

该规则在 101 条公式上无冲突（可机械核验：`tools/conformance_report.py` 的分类结果）。

### 3.11 论文中缀 `^` 的语义：取**保号幂**（`sign(x)·|x|^a`）

论文的算子表里没有独立的 `^` 算子，只有 ``signedpower(x, a) = x^a``；而公式里 16 处使用 `^`
（含负底数：alpha90 的 `(close − ts_max(close, d))`、alpha48 的负收益）。两种读法：

* **保号幂**（`sign(x)·|x|^a`，**本库默认**）：负底数也能出值，与算子名 *signed* power 自洽；
* 论文字面 `x^a`：负底数 + 分数指数 ⇒ **NaN**（会把 alpha90 整片打成 NaN）。

两种读法只在**底数为负**时不同，因此 **alpha48、alpha90 被标为 `ambiguous`**（见 §7）。
切换方式：把 `factors._pow` 改成 `signedpower(..., preserve_sign=False)`。

### 3.12 缺失值语义（论文未规定，本库显式决策）

| 场景 | 本库决策 | 理由 | 影响 |
|---|---|---|---|
| 比较（`<` `>` `==`），任一侧 NaN | **结果 NaN**（不是 C 语义的 False） | 把「未知」输出成 0 会让下游当成真实结论（§3.3 缺陷 7 的同类批评） | 所有条件型因子 |
| 逻辑 `\|\|` | **Kleene 三值**：True∨未知=True；False∨未知=未知 | 同上 | alpha21/24 |
| 三元 `cond ? a : b`，cond 为 NaN | 结果 NaN | 同上 | 16 处 |
| 逐元素 `min/max`，一侧 NaN | **返回另一侧**（`np.fmin/fmax`），两侧皆 NaN ⇒ NaN | 论文未定义；若取 NaN 传播，alpha96 这类 `max(分支A, 分支B)` 会在某分支系统性 NaN 时**整片退化**（实测教训） | 9 个因子 |
| `log(x)`，x ≤ 0 | NaN（不是 −inf） | §3.9 的 elemwise 层决策 | alpha2/29/81 |
| **`decay_linear` 窗口内 NaN** | **计 0（稀疏，官方默认 `dense=False`）**；`dense=True` 恢复严格（整窗有效否则 NaN） | BRAIN 原文「By default, it operates in **sparse mode** (`dense = false`), treating missing (NaN) values as zero」，分母恒为 `1+…+d` | 22 个 decay 因子 |

### 3.13 WorldQuant BRAIN 官方算子文档（L-B）入库与三处定案

**一手依据**：`refs/WorldQuant_BRAIN.pdf`（BRAIN 平台 `learn/operators` 页面打印件，11 页，
打印时间 2026-10-10 21:07，sha256 `8a20029d93d9ecd8…`）。该文件**不入库**（登录墙内的专有文档，
已 gitignore），仅作本地规范依据。

⚠️ **能力边界（如实声明）**：打印件里每个算子只展开了**首行描述**，细节在页面 `Show more` 里
**未被打印** ⇒ 本文档能定案的是「首行描述已说清的事」（方向、基准、两算子之分），
**不能**定案 `rank` 的 `rate=2`、`ts_decay_linear` 的 `dense`、`min/max` 的 NaN 口径等。

#### 3.13.1 三处定案（原先 27 个 `ambiguous` 因子的来源）

| 议题 | BRAIN 原文（逐字） | 定案 |
|---|---|---|
| A11 `ts_decay_linear` 方向 | *"Applies a linear decay to time-series data over a set number of days, smoothing the data by **averaging recent values** and **reducing the impact of older or missing data**."* | **近期权重更大** = 本库默认 `order="recent_first"` ✓（vnpy 的 `oldest_first` 与官方相反，见 V18） |
| A4 `ts_arg_max`/`ts_arg_min` 基准 | *"Returns the number of days since the maximum value occurred in the last d days of a time series. **If today's value is the maximum, returns 0**; if it was yesterday, returns 1, and so on."* | **`days_ago`（今天=0）** ⇒ 本库**翻转默认**（原默认 1-based 自窗口起点与官方相反），见 §3.3 |
| A20 中缀 `^` | *"`power(x, y)` Returns x raised to the power of y (x ^ y). Note: power(x, y) **can drop the sign of x when y is non-integer**; use `signed_power(x, y)` to preserve"* + *"`signed_power(x, y)` x raised to the power of y such that final result preserves sign of x"* | 论文 `^` → **`power`**（新增 `elemwise.power`）；论文显式 `SignedPower(...)`（Alpha#1、#84）→ `signed_power`。alpha48 的 `Σ((Δclose/delay)^2)` 因此得正 |

#### 3.13.2 与本库既有决策的**相互印证**（L-B 确认，无需改码）

| 本库决策 | BRAIN 原文 | 结论 |
|---|---|---|
| §3.4 `scale` 逐日截面 `Σ\|x\| = k` | *"`scale(x, scale=1, longscale=1, shortscale=1)` Scales the input so that the sum of absolute values **across all instruments** equals a specified book size."* | ✅ 一致；并确认 BRAIN 另有 `ts_scale`（时序 min-max 到 [0,1]）⇒ 论文的 `scale` 不是它 |
| §3.5 零方差相关 → NaN | *"`ts_corr(x, y, d)` Calculates the Pearson correlation between two variables, x and y, over the past d days"* | 定义一致；零方差口径官方未写，本库显式钉死（§3.12） |
| §3.12 比较/算术的 NaN | *"`add/multiply/subtract(..., filter=false)` Set filter=true to treat NaNs as 0 (1) before summing"* | ✅ 默认 `filter=false` ⇒ **算术不吞 NaN**，与本库一致 |
| §3.12 `log` 的定义域 | *"`log(x)` Calculates the natural logarithm of the input value. Commonly used to transform data that has positive values."* | ✅ 暗示 x ≤ 0 未定义 ⇒ 本库给 NaN（不给 −inf） |
| §3.11 的两种幂 | *"`signed_power(x, y)` = **sign(x) * (abs(x) ^ y)**"* | ✅ 与本库 `signedpower(preserve_sign=True)` **逐字一致**；`signed_power` 的正文还补了一句「For power of 2, `x^y` will be a parabola but `signed_power(x, y)` will be odd and one-to-one」——正是 alpha48 必须用 `power` 的理由 |
| §3.12 `sign` 的 NaN | *"`sign(x)` … If the input is NaN, returns NaN."* | ✅ 一致 |
| A24 行业中性化 | *"`group_neutralize(x, group)` Neutralizes Alpha values within each specified group by **subtracting the group mean** from each value."* | ✅ 与 `ind_neutralize` 的逐日组内去均值一致 |
| §3.10 `min`/`max` 两种语义 | *"`max(x, y, ..)` Maximum value of all inputs. **At least 2 inputs are required**."*（`min` 同） | ✅ BRAIN 的 `min/max` 就是逐元素多输入版本；论文 `min(x, d)`（第二参数是常数天数）对应 `ts_min/ts_max` |
| `ts_rank` 逐股时序口径 | *"`ts_rank(x, d, constant = 0)` Ranks the value of a variable **for each instrument** over a specified number of past days, returning the rank of the current value"* | ✅ 与本库 `ts_rank` 一致（归一化区间官方未写明，本库取 ∈ (0,1]，见 A2） |
| §3.9 `adv{d}` | 文档中**无** `adv` 算子（它是数据字段而非算子） | 论文的 `adv{d}` = 美元成交额 ⇒ 本库取 `amount` 的依据仍在 L-A + §3.9 |

#### 3.13.3 完整文档（API 级）揭示的 3 处默认口径差异（✅ **已落地**，2026-10-10）

打印件只给了首行描述；随后用会话凭据抓取了**完整文档**（`GET /operators/{name}`，66 个算子中 65 个可取，
本地语料 `refs/brain_operator_docs.md`，gitignored）。完整正文里的**官方算例**又定案了三处
**与本库/参照都不同**的口径 —— 三者都会**改变因子取值**，故单独作为下一里程碑落地：

| 议题 | BRAIN 完整文档原文/算例 | 本库处置 | 影响面 |
|---|---|---|---|
| `rank`/`ts_rank` 归一化 | 算例 `(4,3,6,10,2) → (0.5, 0.25, 0.75, 1, 0)`；「Normalized rank: 3 / (5 − 1) = **0.75**」⇒ **[0,1] 闭区间 `(名次−1)/(n−1)`** | ✅ **默认改为 `zero_to_one`**（§3.2 已改写；`one_over_n`/`ordinal` 保留），`test_b01`/`test_a10` 用官方算例钉死 | **全部 101 个因子** |
| `ts_std_dev` 的 ddof | 算例：`(0 + 0.0001 + 0.0004 + 0.0001 + 0.0004) / **5** = 0.0002` ⇒ **ddof=0（总体）** | ✅ **默认改为 0**（§3.1 已改写），`test_a03`/`test_a22` 钉死；vnpy 的 D2 差异随之消失 | 8 个因子 + `covariance` |
| `ts_decay_linear` 缺失值 | 「By default, it operates in **sparse mode** (`dense = false`), **treating missing (NaN) values as zero**」（分母仍 `1+…+d`） | ✅ **默认改为稀疏**（`dense=False`），`dense=True` 保留严格口径；§3.12 记录与「不 fillna」契约的关系 | 22 个 decay 因子 |

同时确认（无需改动）：`rank` 的 `rate=2` 只是**排序精度**开关（"set to 0 for exact sorting"）；
`ts_corr` 是标准 Pearson 且「first element is the latest」；`if_else(cond, a, b)` 与本库 `_if` 同义。

#### 3.13.4 文档也没给出的（本库显式决策）

`ts_decay_linear` 的 `dense=true` 分支细节、逐元素 `min/max` 的 NaN 口径、滚动算子的 `min_periods`（预热期）、
`if_else` 条件为 NULL 时的分支。均为库级约定，本库显式决策并测试（§3.12、A1、A2、A7、A8）。

`rank(x, rate=2)` 的 `rate` 语义、`ts_decay_linear` 的 `dense` 参数、逐元素 `min/max` 的 NaN 口径、
`ts_std_dev` 的 ddof、`ts_corr`/滚动算子的 `min_periods`。
这些**均为库级约定**（不改变公式含义），本库各自显式决策并测试（§3.12、A1、A2、A7、A8），
且在 `docs/deviations.md` §3.2 记录与 vnpy 的差异。

## 4. 逐算子定义

记窗口 `d = window`，`x_t` 为某只股票在 t 日的取值，滚动窗口覆盖 `t-d+1 … t`（含当日，不用未来数据）。

### 4.1 A 组 · 时序算子（`axis=0`）

| 算子 | 签名 | 定义 | 预热 | 主要边界 |
|---|---|---|---|---|
| `ts_sum` | `(df, window)` | `Σ x_i` | `d-1` 行 NaN | 窗口含 NaN → NaN |
| `sma` | `(df, window)` | `(1/d)Σ x_i` | 同上 | 等权，**不是** EMA |
| `stddev` | `(df, window, ddof=1)` | `sqrt(Σ(x_i-m)²/(d-ddof))` | 同上 | `ddof ∈ {0,1}`，见 §3.1 |
| `correlation` | `(x, y, window)` | 窗口内 Pearson 相关 | 同上 | 零方差 → NaN（§3.5） |
| `covariance` | `(x, y, window, ddof=1)` | `Σ(x_i-mx)(y_i-my)/(d-ddof)` | 同上 | ddof=0 按 `(d-1)/d` 换算 |
| `ts_rank` | `(df, window, pct=True)` | `rankdata(w)[-1]`；pct 时 `/d` | 同上 | 见 §3.2；并列 average；论文未规定归一化 |
| `product` | `(df, window)` | `Π x_i` | 同上 | — |
| `ts_min` / `ts_max` | `(df, window)` | 窗口最小/最大值 | 同上 | — |
| `delta` | `(df, period=1)` | `x_t - x_{t-period}` | `period` 行 NaN | `period=0` → 全 0 |
| `delay` | `(df, period=1)` | `x_{t-period}` | `period` 行 NaN | — |
| `decay_linear` | `(df, period)` | `Σ w_i x_{t-d+1+i}`，`w_i=(i+1)/(d(d+1)/2)` | `d-1` 行 NaN | **末值权重最大**（论文列举顺序歧义见 §3.7）；`period=0` 报错 |
| `ts_argmax` | `(df, window, basis="window_start")` | 窗口内最大值的位置 | 同上 | 见 §3.3；并列取最早 |
| `ts_argmin` | `(df, window, basis="window_start")` | 窗口内最小值的位置 | 同上 | 同上 |
| `rolling_rank` | `(window_values)` | `rankdata(w)[-1]`（序号 1..n，并列 average） | — | `ts_rank` 的构件；对单窗口一维数组 |

`decay_linear` 的权重向量恰为 `1..d / (d(d+1)/2)`：`d=3` 时 `[1/6, 2/6, 3/6]`，
`decay_linear([1,2,3], 3) = (1·1 + 2·2 + 3·3)/6 = 14/6 ≈ 2.3333`。
测试除断言该解析值外，还在随机面板上逐窗口与 `np.average(w, weights=1..d)` 对拍
（`test_a18`）——因为「权重反序」是极易发生且肉眼难查的错误（变异 `m3` 即注入它）。

### 4.2 B 组 · 截面算子（`axis=1`，每日一次）

| 算子 | 签名 | 定义 | 值域 | 边界 |
|---|---|---|---|---|
| `rank` | `(df, pct=True, method="average")` | 当日截面名次；pct 时 `/n` | `pct=True` → (0, 1] | NaN 保持 NaN；`method` 见 §3.6 |
| `scale` | `(df, k=1.0)` | `x · k / Σ\|x\|`（当日截面） | `Σ\|x\| = k` | `Σ\|x\|=0` → NaN；`k` 必须 > 0 |

### 4.3 中性化算子（`neutralize.py`）

`industry` 可以有两种形态，二者都会按 `(交易日, 股票代码)` 对齐：

* `pd.Series`：**静态快照**，`index` = 股票代码，广播到所有交易日；
* `pd.DataFrame`：**PIT as-of 面板**（`index` = 交易日, `columns` = 股票代码），逐日行业口径可不同。

对不上的格子留 NaN → 残差 NaN（不静默填充）。

| 算子 | 签名 | 定义 | 边界策略 |
|---|---|---|---|
| `ind_neutralize` | `(df, industry)` | `y - mean(y \| 交易日, 行业)` | 行业标签 NaN → 残差 NaN；单成员行业 → 残差 0；空行业/全 NaN 行业 → NaN，**不抛 `LinAlgError`** |
| `neu_industry` | `(df, industry)` | `y / mean(y \| 交易日, 行业)` | 行业均值 0 → NaN（不产生 ±inf） |
| `neutral` | `(y, x)` | 逐日 `y - X·pinv(X)·y`（无隐式截距） | 共线/全 0 回归元 → SVD 最小范数解，投影仍唯一；`y` 或回归元非有限 → 该股当日残差 NaN |

#### 4.3.1 `ind_neutralize` 为什么等价于 OLS 残差

「仅有行业哑变量、**无截距**」的设计矩阵 `X` 的列空间，正是「在每个行业内取常值」的函数空间，
因此投影 `X(XᵀX)⁻¹Xᵀy` 就是**组内均值**，残差即**组内去均值**。可检验的推论（都在测试里）：

* 每个行业内残差求和 ≈ 0（`test_c01`）；
* 残差与行业哑变量的内积 ≈ 0（正交性，`test_c01`）；
* 逐点等于 `statsmodels.OLS(y, dummies).fit().resid`，`rtol=1e-10`（`test_c02`）；
* 等于 `neutral(y, 哑变量面板列表)`——两条独立实现互证（`test_c11`）。

#### 4.3.2 为什么不用矩阵求逆（这是本项目的技术差异化点）

原始实现逐日 `numpy.linalg.inv`，行业含 NaN/空行业时矩阵奇异 → `LinAlgError`（设计文档 §3.3 缺陷 4）。
两个主流实现都栽在这里：vnpy 直接缺这个算子，QAFactor 会崩（设计文档 §4.3.1）。

本库的做法：

1. **`ind_neutralize` 向量化**：把 (交易日, 行业) 编码成组合编号，用 `np.bincount`
   一次算完全面板的分组和/计数，**无逐日 Python 循环、无矩阵求逆**；
2. **`neutral` 用 `np.linalg.lstsq`（SVD）**：列共线时给出最小范数解，
   投影到列空间的结果**仍然唯一且正确**，因此不会抛 `LinAlgError`（`test_c12` 用重复列 + 全 0 列验证）；
3. 两条路径互相差分（`test_c06`、`test_c11`）+ 与 statsmodels 差分（`test_c02`、`test_c10`）。

### 4.4 输入校验契约

| 情形 | 异常 |
|---|---|
| 传入非 DataFrame/Series | `TypeError` |
| 面板含非数值列 | `TypeError` |
| `window` 为 0/负数 | `ValueError` |
| `window` 非整数（如 2.5） | `TypeError`（❗**与论文 `floor(d)` 规则冲突，待改**，见 §3.8） |
| `period` 为负 | `ValueError` |
| `ddof ∉ {0,1}` | `ValueError` |
| `k ≤ 0` 或非有限 | `ValueError` |
| `basis` 非法 | `ValueError` |
| `method` 非法 | `ValueError` |
| 二元算子两块面板不同形/不同轴 | `ValueError` |
| index 或 columns 重复 | `ValueError` |

---

## 5. 设计文档勘误（v0.2，实现期实测发现）

> 这些是**设计文档自身的**内部不一致，不是本实现的偏离。全部按「文档中更权威的那条判据」取值，
> 并把另一条数值保留为可复现的备选口径。任何人复算都能验证。

**勘误 1 · §8.2 `rank` 并列行：数值与标注的方法不符。**
文档写「`rank([10,10,30])` → `[0.3333, 0.3333, 1.0]`（average 法）」。
实测：`rankdata([10,10,30], 'average')/3 = [0.5, 0.5, 1.0]`；`[1/3, 1/3, 1]` 是 **`min` 法** `rankdata(...,'min')/3` 的结果。
文档同一行的文字判据「与 `scipy.stats.rankdata(row,'average')/n` 逐点相等」与 §8.2 第一行样例
（`[10,20,30,40] → [0.25,0.5,0.75,1.0]`，average 与 min 在该例上同值）**互相印证 average**。
**决策**：取 `average`（`test_b02`），并在同一测试中断言 `method="min"` 能复现文档字面数值。

* **vnpy 差分实测（2026-10-09）**：参照实现 ``cs_rank`` 用的是 **`method="min"`**，
  也就是说设计文档 §8.2 那组 `[1/3, 1/3, 1.0]` 数字其实**与参照口径吻合**，只是被标注成了 "average"。
  两种口径**仅在并列行**不同（实测：无并列面板逐点一致；并列面板最大差 0.25）。
  本库保留 `average` 默认（scipy/pandas 默认 + 文档文字判据），并提供 `method="min"` 对齐参照。

**勘误 2 · §8.1 `covariance` 期望值写成 1。**
文档：`covariance([1,2,3,4,5],[2,4,6,8,10],3)` → `[NaN,NaN,1,1,1]`（ddof=1）。
实测/推导：`cov = Σ(x-mx)(y-my)/(n-1) = 4/2 = 2`，即 `[NaN,NaN,2,2,2]`；`1` 既不等于 ddof=1 的 2，
也不等于 ddof=0 的 4/3（`1` 是 `x=[1,2,3]` 的**方差**，疑似串行）。
文档同时要求「与 pandas `rolling().cov()` 对拍」，而 pandas 给 2。
**决策**：断言 2 并与 pandas 逐点对拍（`test_a22`）。

**勘误 3 · §8.4 最后一行：`min_periods` 放宽的抓取者归因错误。**
文档要求「`ts_sum` 的 `min_periods` 放宽」必须让 §6.5「时间截断一致性」失败。
实测：放宽 `min_periods` 只影响**预热期是否填值**，不引入未来信息，
因此 `[0,T]` 与 `[0,t]` 在 t 处依然相等——**截断一致性对该变异天然无感**。
真正的抓取者是 §8.1 的「前 `window-1` 行必须为 NaN」断言。
**决策**：变异 `m7` 断言由 `test_a01_ts_sum` 抓住，另有专门测试
`test_errata_min_periods_is_caught_by_warmup_assertion_not_truncation` 同时证明
「`test_a25`（预热期断言）能抓住」且「`-k truncation` 抓不住」。

**勘误 4（计数，非数值）· §8.4 的表有 7 行，移交提示词里写「6 个注入」。**
本实现以**表格**为准，7 条全部覆盖（`tests/test_mutation.py::MUTATIONS`）。

---

## 6. M4 差分对拍的口径归一化清单（给 `tools/differential.py` 用）

设计文档 §6.4 强调「先做语义归一化，再逐点对拍，严禁简单判错」。
**2026-10-09 已用 vnpy（MIT，polars DSL）完成算子层对拍**（`tools/differential.py`，
24 项：18 项逐点一致 + 6 项已归因差异，无「待查」项）。以下是**实测**而非推测的归一化清单。

### 6.1 对齐后逐点一致（`rtol=1e-8`，NaN 位置亦一致）

| 算子 | 对齐方式 | 实测最大差 |
|---|---|---|
| `ts_sum` / `delta` / `delay` / `ts_min` / `ts_max` / `product` / `scale` | 默认即一致（`scale` 需面板无零和行） | ≤ 6e-17 |
| `sma` / `stddev` | `stddev` 需 `ddof=0`；`sma` 默认 | ≤ 2e-13 |
| `ts_argmax` / `ts_argmin` | 默认即一致（两边都是**自窗口起点 1-based**） | 精确 0 |
| `ts_rank` | 默认即一致（`pct=True`；vnpy 用 `percentileofscore`，与本库数学等价） | 精确 0 |
| `correlation` / `covariance` | `covariance` 需 `ddof=0` | ≤ 4e-12 |
| `decay_linear` | **必须显式** `order="oldest_first"` | ≤ 7e-15 |
| `rank` | 无并列：默认即一致；有并列：`method="min"` | 精确 0 |

### 6.2 已归因的口径差异（8 条，全部实测存在；原 D2 已因官方口径落地而消失）

| # | 项 | vnpy（L-D） | 本库（默认） | 影响面 | 归因与处置 |
|---|---|---|---|---|---|
| D1 | `decay_linear` 权重方向 | 最老权重最大（权重表套在时间正序窗口） | 最新权重最大 | **22 个因子** | 论文枚举方向未写死（§3.7）；本库用 `order` 参数对齐，**默认不动**，相关因子不得 `verified` |
| ~~D2~~ | ~~`ts_std` 的 ddof~~ | — | — | — | ✅ **已消失**（2026-10-10）：本库默认改为 `ddof=0`（BRAIN 官方算例，§3.1）⇒ 与 vnpy 逐点一致，该差异不复存在 |
| D7 | `rank` 的归一化区间 | `名次/n ∈ (0,1]`（`one_over_n`） | `(名次−1)/(n−1) ∈ [0,1]`（**官方** `zero_to_one`） | **全部 101 个因子** | BRAIN 完整文档算例（§3.2）；对拍时切 `normalization="one_over_n"` 对齐 |
| D7b | `ts_rank` 的归一化区间 | 同 D7 | 同 D7 | 62 处调用 | 同上（官方算例 `3/(5−1)=0.75`） |
| D8 | `decay_linear` 的缺失值 | 另有其 NaN 处理 | **稀疏：窗口内 NaN 计 0**（官方默认 `dense=False`） | 22 个 decay 因子 | BRAIN 完整文档（§3.12）；对拍时切 `dense=True` 避免与 vnpy 各异的 NaN 处理混淆 |
| D3 | 预热期 | 各算子不统一（`ts_sum` 严格；`ts_min/max/mean/std/corr` 用 `min_samples=1` 填值） | 统一严格 NaN（§2.3） | 全部时序算子 | 本库要「NaN 只代表信息不足」；实测预热期外逐点一致 |
| D4 | `rank` 并列策略 | `method="min"` | `method="average"` | 并列行 | 仅并列时不同（实测无并列逐点一致）；`method` 可切 |
| D5 | `scale` 零和行 | `0` | `NaN` | 罕见（全 0/全 NaN 日） | 本库拒绝把「无数据」伪装成 0（§3.3 缺陷 7 的同类问题） |
| D6 | 窗口含 NaN 的 `sma`/`ts_std` | nan 归约 + `min_samples=1` ⇒ **跨 NaN 出值** | 窗口含 NaN 即 NaN | NaN 脏数据 | 本库视为「信息不足」；`ts_sum` 两边都严格（实测一致） |

### 6.3 参照实现的能力边界（不是差异，是缺口）

| # | 项 | 实测 | 含义 |
|---|---|---|---|
| L1 | 非整数窗口 `floor(d)` | vnpy 直接 `TypeError: 'float' object cannot be interpreted as an integer` | 论文 58–99 号共 **40 个因子**用非整数窗口 ⇒ 参照实现**无法表达**这些因子；本库已实现（§3.8） |
| L2 | 覆盖度 | 82/101（缺 `alpha56` 与 18 个 `IndNeutralize` 因子） | 其余 19 个**无法差分**，只能靠规范对照 + 不变量 |
| L3 | 因子级差分入口 | `calculate_by_expression` 还需要 `math_function` 与 `ta_function`（后者依赖 **talib**） | M4 做因子级差分时需补 `math_function` 并处理 talib 依赖（本机未装 ta-lib） |

⚠️ 对拍范围仅限 **82/101**：vnpy 缺 `alpha56`（无 `cap`）与 18 个含 `IndNeutralize` 的行业中性因子
（且那 18 个在它的测试里被静默摘掉中性化），见设计文档 §4.3.1。
其余 19 个**无法做差分**，只能靠「论文规范对照 + 不变量」，必须在 `docs/verification.md` 如实标注。

---

## 7. 未决事项 / 待办（不假装已完成）

| # | 事项 | 状态 | 影响面 |
|---|---|---|---|
| 1 | **BRAIN 官方算子文档（L-B）** | ✅ **已获取**（2026-10-10，`refs/WorldQuant_BRAIN.pdf`，sha256 `8a20029d…`）：三处歧义全部定案 —— `ts_arg_max/min` 基准（§3.3）、`ts_decay_linear` 权重方向（§3.13）、中缀 `^` 的 `power`/`signed_power` 之分（§3.11）；`scale` 轴向、`ts_rank`/`rank`、`group_neutralize`、`sign`/`log`、`add/multiply/subtract` 的 `filter` 语义也获原文确认（§3.13） | 27 个因子的 ambiguous 标签清零 |
| 1b | BRAIN **完整文档（API 级）**已入库（`refs/brain_operator_docs.md`，65 个算子正文 + 算例） | ✅ **已定案并落地**（§3.2 归一化 `zero_to_one`、§3.1 ddof=0、§3.12 稀疏 decay）；官方算例全部逐字复核 | **101 个因子**（归一化）+ 8（ddof）+ 22（decay） |
| 1c | 完整文档**也未给出**：`dense=true` 分支、`min/max` 的 NaN 口径、滚动算子 `min_periods`、`if_else` 条件为 NULL 的分支 | 未定（文档确实没写） | 本库显式决策（§3.12） |
| 2 | 与 vnpy `{cs,ts}_function.py` 的逐项口径核对（§5.3、§6.4） | ✅ **算子层已完成**（2026-10-09：`tools/differential.py`，24 项，见 §6）；`ta_*` 与因子级差分待 M4（§6.3 L3） | 82 个因子（M4） |
| 3 | **非整数窗口 `floor(d)` 改码**（§3.8，论文 L-A 已明确） | 已判定、**未改码**（M1 冻结件；需同步改 `§4.4` + `test_a27`） | **40 个因子** |
| 4 | `elemwise` 层（`abs`/`log`/`sign`/`signedpower`） | M2 交付（`operators.md` §1；论文用它们覆盖 15 个因子） | 15 个因子 |
| 5 | `signedpower` 是否保号 | ✅ **已定案**（§3.11 + §3.13）：BRAIN 把 `power`（负底数 + 非整数指数丢符号）与 `signed_power`（保号）分为两个算子；论文中缀 `^` → `power`，显式 `SignedPower(...)` → `signed_power`。alpha48 的负收益平方因此得正；alpha90 的底数 `rank(...) ≥ 0` 两种读法同值 | 2 个因子（48、90） |
| 6 | `adv{d}` 落地口径（论文＝**美元成交额** → A 股取 `amount` 而非 `volume`） | 已判定（L-A）；需在 `deviations.md` 逐因子登记 | **45 个因子** |
| 7 | `ind_neutralize` 静态快照路径的 T×N 标签矩阵内存优化（one-hot 矩阵乘法） | 已记录于代码注释；当前优先正确性与单一路径 | 性能 |
| 8 | 中性化算子在大面板上的性能基准 | 未做（M1 只承诺正确性） | 性能 |

## 8. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-09 | 首版：20 算子口径、六个歧义点决策、边界策略、设计文档勘误 4 条、M4 归一化清单 |
| **v0.7** | 2026-10-10 | **三处 BRAIN 官方口径落地**：§3.2 归一化改为 `zero_to_one`（`(名次−1)/(n−1) ∈ [0,1]`，官方算例钉死）、§3.1 ddof 改为 0（官方算例除以 n）、§3.12 新增 `decay_linear` 稀疏模式（官方默认 `dense=False`，NaN 计 0）；§3.13.3 标记为已落地；差分新增 D7/D7b/D8、D2 消失 |
| v0.6 | 2026-10-10 | 追加 §3.13.3/§3.13.4：API 级**完整文档**（含官方算例）又定案三处默认口径差异（`rank`/`ts_rank` 归一化 `[0,1]`、`ts_std_dev` ddof=0、`ts_decay_linear` 稀疏 NaN→0），均**待落地**；§7 待办按影响面重排 |
| v0.5 | 2026-10-10 | **BRAIN 官方算子文档（L-B）入库**：新增 §3.13（原文引文 + 三处定案 + 与本库既有决策的相互印证 + 文档未展开项）；§3.3 默认基准翻转为 `days_ago`（BRAIN：今天最大返回 0）、§3.11 中缀 `^` 定案为 `power`（新增 `elemwise.power`，alpha48 负收益平方得正）、§3.13.1 确认 `ts_decay_linear` 近期权重大（本库默认）；§7 待办项 1/5 结案（27 个因子的 `ambiguous` 清零） |
| v0.4 | 2026-10-09 | M3 新增：§3.9 `adv{d}` 取 `amount`（影响 45 因子）、§3.10 `min/max` 两种语义的消歧规则、§3.11 中缀 `^` 取保号幂（alpha48/90 因此标 ambiguous）、§3.12 **缺失值语义总表**（比较/逻辑/三元/逐元素 min-max/log）；并追加一条由全量因子跑暴露并修掉的算子边界：`correlation`/`covariance` 在近乎零方差窗口中的 ±inf 一律掩为 NaN |
| v0.3 | 2026-10-09 | 加入 **vnpy 差分实测**：§3.1（vnpy `ts_std` 用 ddof=0 且与自身 `cs_std` 不一致）、§3.2（`cs_rank`=min+pct；`ts_rank` 与 `percentileofscore` 数学等价、实测逐点一致）、§3.3（vnpy `arg_max()+1` ⇒ 本库 1-based 默认获第二实现支持）、§3.4（`cs_scale` 同为每日截面）、§3.6（文档那组并列数字其实与参照 min 口径吻合）、**§3.7（vnpy 的 `decay_linear` 权重方向与本库默认相反 ⇒ 22 个因子的最高风险项，新增 `order` 参数对齐）**；§6 换成实测归一化清单（18 项一致 + 6 项归因 + 3 项参照能力边界）；§7 更新 1/2 项 |
| v0.2 | 2026-10-09 | 加入论文原文（arXiv:1601.00991v3，逐字入库于 `docs/paper_formulas.md`）核对结论：①`indneutralize` 语义获 **L-A 确认**（组内截面去均值）②新增 §3.7 `decay_linear` 权重列举顺序歧义（22 因子）③新增 §3.8 非整数窗口 `floor(d)` 规则（40 因子，本库当前偏离待改）④§3.3 补记 argmax 基准在论文中同样未定义（6 因子，两读法为序反转）⑤§3.4 补记 `scale` 轴向论文未写（6 因子）⑥§1 补记逐元素函数层缺口（15 因子）⑦§7 未决表按影响面重排 |
