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
| 3.1 | `stddev`/`covariance` 的 ddof | **默认 1**（样本口径），只接受 0/1 | 参数 `ddof` | `test_a03` `test_a04` `test_a05` `test_a22` `test_a23` |
| 3.2 | `ts_rank` 是否归一化；`rank` 是否 pct | `ts_rank` **默认 `pct=True`**（`名次/window` ∈ (0,1]）；`rank` **默认 `pct=True`**（`名次/n` ∈ (0,1]） | 参数 `pct` | `test_a10` `test_a11` `test_b01` `test_b03` |
| 3.3 | `ts_argmax`/`ts_argmin` 基准与方向 | **默认自窗口起点 1-based** ∈ [1, window]；并提供 `basis="days_ago"`（BRAIN 口径：今天=0 ∈ [0, window-1]） | 参数 `basis` | `test_a12`–`test_a16` |
| 3.4 | `scale` 轴向 | **`axis=1`**（每日 `Σ\|x\| = k`） | 无参数（口径固定），断言逐日 `Σ\|x\| = k` | `test_b05`–`test_b07` |
| 3.5 | `correlation` 遇常数序列 | **NaN**（不是 0、不是 ±inf） | 无参数（口径固定） | `test_a20` |
| 3.6 | `rank` 并列策略 | **`method="average"`**（pandas/scipy 默认） | 参数 `method` | `test_b02` `test_a24` |

### 3.1 ddof：默认 `1`（样本口径）

* **决策**：`stddev(df, window, ddof=1)`、`covariance(x, y, window, ddof=1)`；`ddof` 只放行 `0` 与 `1`，其他值显式报错。
* **理由**：
  1. pandas `rolling().std()`/`.cov()` 的默认就是 `ddof=1`，本库直接的实现基础与对拍对象都是 pandas；
  2. 差分对拍参照 vnpy 走 polars，polars 的 `std`/`cov` 默认亦为 `ddof=1` → **默认口径天然与参照一致，M4 少一类差异**；
  3. 金融收益序列本就以「样本」视角估计波动率（只有一段历史，不是全集）；
  4. 只放行 0/1：这两个是唯一有明确统计含义的口径，禁止 `ddof=2` 之类的静默漂移。
* **被否决**：`ddof=0`。numpy 默认是 0，若跟随 numpy，则与 pandas 对拍、与 vnpy 对拍都要额外换算；
  `covariance` 的闭式换算 `(n-1)/n` 也只在 0/1 之间有明确形式。
* **`covariance` 的 ddof=0 实现**：`cov_sample × (window-1)/window`，因为严格预热 ⇒ 窗口内有效样本数恒为 `window`。
* **vnpy 差分实测（2026-10-09）**：vnpy 的 ``ts_std`` 用 **``ddof=0``**（源码里 `np.nanstd(..., ddof=0)`），
  **且它自己不一致**——``cs_std``（截面）走 polars `.std()` 默认 ``ddof=1``。
  本库默认维持 ``ddof=1``（pandas/polars 默认 + 设计文档 §7.3 签名），
  对齐方式：``stddev(..., ddof=0)`` / ``covariance(..., ddof=0)``（实测逐点一致，见 §6 D2）。

### 3.2 pct：`ts_rank` 与 `rank` 都默认 `True`

* **决策**：
  * `ts_rank(df, window, pct=True)` → 窗口末值的名次 `rankdata(w)[-1]` 除以 `window`，值域 **(0, 1]**；
    `pct=False` → 序号 `1..window`。
  * `rank(df, pct=True, method="average")` → `rankdata(row, method)/n`，值域 **(0, 1]**；`pct=False` → 序号 `1..n`。
* **理由**：
  1. 设计文档 §7.3 的签名默认就是 `pct=True`，§8.2 第一行样例 `[0.25, 0.5, 0.75, 1.0]` 也正是 `名次/n`；
  2. **量纲一致**：原始实现 `ts_rank` 返回窗口内末值**序号**（1..n），而 `rank` 返回**截面 pct**，
     两者相乘相除会得到量纲混乱的结果（设计文档 §3.3 缺陷 6 明确指出）；
  3. `pct=False` 保留序号口径，M4 差分对拍时若要贴合序号语义的实现，**改参数即可，不必改库**。
* **注意（对拍归一化点）**：pct 归一化分母是 `window`（不是 `window-1`），即最小值得 `1/window` 而非 `0`。
  这与「与 `rankdata/n` 逐点相等」一致；若参照实现用 `(rank-1)/(n-1)`（值域 [0,1]）或 ordinal，需要在差分层做归一化
  （见 §6 清单）。
* **vnpy 差分实测（2026-10-09）**：
  * ``cs_rank`` 源码自述 *"WorldQuant cross-sectional rank (method=min, pct=True)"* →
    与「无并列时」的本库默认 **逐点一致**（实测），**并列时**它用 `min`、本库用 `average`（§3.6）；
  * ``ts_rank`` 用 ``scipy.stats.percentileofscore(w, w[-1])/100``，与「窗口末值的 `rankdata` 平均名次 / n」
    **数学等价（含并列）**，实测 **逐点一致**——即本库 ``ts_rank(pct=True)`` 与参照完全吻合，
    无需归一化；``pct=False``（序号口径）才是参照没有的分支。

### 3.3 `ts_argmax`/`ts_argmin` 基准、方向与并列

* **决策**：返回**自窗口起点 1-based 的位置** ∈ [1, window]，窗口最新值 = `window`，最旧值 = `1`。
  并列时取**最早出现**（与 `np.argmax`/`np.argmin` 一致）。另提供 `basis="days_ago"`：
  **官方 BRAIN 口径**「距今几天」，今天是 0 ∈ [0, window-1]；换算关系 `days_ago = window - window_start`。
* **理由**：
  1. 设计文档 §8.1 给出两条候选并注明「原实现 `np.argmax(...)+1` = 自窗口起点 1-based」，
     本库以该口径为默认（可与数值对拍、且它是有界的正整数序列，便于人工核验）；
  2. BRAIN 口径是**算子的官方第二规范来源**（设计文档 §2.3），不能视而不见。
     把两者都实现并同时测试，把「选哪个」这件事从隐含假设变成调用方的一次选择；
  3. 若只实现一种，M4 差分对拍时出现的差异会被误判为 bug——这正是设计文档 §6.4 强调的
     「先做语义归一化，严禁简单判错」。
* **并列细节**：`[2, 2, 1]` 的 argmax 为 `1`（最早的 2），不是 `2`。文档未规定，本库显式钉死。

⚠️ **论文原文核对（2026-10-09，见 `docs/paper_formulas.md` §7.2）**：论文只写
*"which day ts_max(x, d) occurred on"*，**同样没有定义基准与方向**——本库的默认值仍然是
「设计文档 §8.1 + 原实现」口径，**不是论文级结论**。这不是可以忽略的细节：
`days_ago = window − window_start_1based` 是**序反转**而非平移，故对 `rank(Ts_ArgMax(...))`
这类用法（Alpha#1 就是）会得到镜像排序、因子整体变号。共 **6 个因子**受影响
（`ts_argmax`：1、57、60、96；`ts_argmin`：98、100）。
* **vnpy 差分实测（2026-10-09）**：vnpy 的 ``_reduce_argmax_slice`` 就是 ``series.arg_max() + 1``，
  即 **1-based 自窗口起点**——与本库默认口径 **逐点一致**（实测）。因此本库默认值获得了
  第二实现的独立支持（L-D 级证据）；**BRAIN 官方文案（L-B）仍待复核**，但它已不再是「无证据的选择」。

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

### 6.2 已归因的口径差异（6 条，全部实测存在）

| # | 项 | vnpy（L-D） | 本库（默认） | 影响面 | 归因与处置 |
|---|---|---|---|---|---|
| D1 | `decay_linear` 权重方向 | 最老权重最大（权重表套在时间正序窗口） | 最新权重最大 | **22 个因子** | 论文枚举方向未写死（§3.7）；本库用 `order` 参数对齐，**默认不动**，相关因子不得 `verified` |
| D2 | `ts_std` 的 ddof | `0`（且 `cs_std` 用 polars 默认 `1`，**自身不一致**） | `1` | 8 个因子 | pandas/polars 默认 + 设计文档签名；用 `ddof=0` 对齐 |
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
| 1 | **BRAIN 官方算子文档（L-B）**：`ts_arg_max`/`ts_arg_min` 基准、`ts_decay_linear` 权重方向、`ts_rank`/`rank` 归一化、`scale` 轴向 | **未获取**：2026-10-09 实测 `platform.worldquantbrain.com/learn/operators` 只返回登录态空壳（正文仅 `index`）。其中 **argmax 基准已获 vnpy 实测支持**（§3.3），`decay_linear` 方向仍是最硬的未决项 | **22 个因子**（decay） |
| 2 | 与 vnpy `{cs,ts}_function.py` 的逐项口径核对（§5.3、§6.4） | ✅ **算子层已完成**（2026-10-09：`tools/differential.py`，24 项，见 §6）；`ta_*` 与因子级差分待 M4（§6.3 L3） | 82 个因子（M4） |
| 3 | **非整数窗口 `floor(d)` 改码**（§3.8，论文 L-A 已明确） | 已判定、**未改码**（M1 冻结件；需同步改 `§4.4` + `test_a27`） | **40 个因子** |
| 4 | `elemwise` 层（`abs`/`log`/`sign`/`signedpower`） | M2 交付（`operators.md` §1；论文用它们覆盖 15 个因子） | 15 个因子 |
| 5 | `signedpower` 是否保号（`x^a` vs `sign(x)·\|x\|^a`） | 待 BRAIN 文档或 vnpy 实现；Alpha#1/#84 中 a=2 无差异 | 2 个因子 |
| 6 | `adv{d}` 落地口径（论文＝**美元成交额** → A 股取 `amount` 而非 `volume`） | 已判定（L-A）；需在 `deviations.md` 逐因子登记 | **45 个因子** |
| 7 | `ind_neutralize` 静态快照路径的 T×N 标签矩阵内存优化（one-hot 矩阵乘法） | 已记录于代码注释；当前优先正确性与单一路径 | 性能 |
| 8 | 中性化算子在大面板上的性能基准 | 未做（M1 只承诺正确性） | 性能 |

## 8. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-09 | 首版：20 算子口径、六个歧义点决策、边界策略、设计文档勘误 4 条、M4 归一化清单 |
| **v0.3** | 2026-10-09 | 加入 **vnpy 差分实测**：§3.1（vnpy `ts_std` 用 ddof=0 且与自身 `cs_std` 不一致）、§3.2（`cs_rank`=min+pct；`ts_rank` 与 `percentileofscore` 数学等价、实测逐点一致）、§3.3（vnpy `arg_max()+1` ⇒ 本库 1-based 默认获第二实现支持）、§3.4（`cs_scale` 同为每日截面）、§3.6（文档那组并列数字其实与参照 min 口径吻合）、**§3.7（vnpy 的 `decay_linear` 权重方向与本库默认相反 ⇒ 22 个因子的最高风险项，新增 `order` 参数对齐）**；§6 换成实测归一化清单（18 项一致 + 6 项归因 + 3 项参照能力边界）；§7 更新 1/2 项 |
| v0.2 | 2026-10-09 | 加入论文原文（arXiv:1601.00991v3，逐字入库于 `docs/paper_formulas.md`）核对结论：①`indneutralize` 语义获 **L-A 确认**（组内截面去均值）②新增 §3.7 `decay_linear` 权重列举顺序歧义（22 因子）③新增 §3.8 非整数窗口 `floor(d)` 规则（40 因子，本库当前偏离待改）④§3.3 补记 argmax 基准在论文中同样未定义（6 因子，两读法为序反转）⑤§3.4 补记 `scale` 轴向论文未写（6 因子）⑥§1 补记逐元素函数层缺口（15 因子）⑦§7 未决表按影响面重排 |
