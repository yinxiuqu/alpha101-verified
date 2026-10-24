# Changelog

本项目遵循「结论可追溯、边界如实标注」的写法：每个版本都写清**改了什么口径、为什么**，以及**哪些仍未被验证**。

## [0.1.7] - 2026-10-24

### Changed — 因子出口统一 float32 + 三原则

- `run_factor` 默认返回 **float32**（此前 float64）；新增 `dtype` 参数可显式覆盖。
- 新增 `FACTOR_DTYPE` / `cast_factor_dtype()`：±inf → NaN（①/③）；float32 范围内的
  huge finite 保留不裁剪（②）；超出 float32 上限的有限值 → NaN，并在
  `result.attrs["overflow_to_nan"]` 记录数量。
- `run_factor_raw` 默认行为不变（float64、可含 ±inf），仅新增可选 `dtype` 参数。
- golden 快照与 auto-wire 测试显式用 `dtype=np.float64`，继续守算法口径；
  新增 `tests/test_output_dtype.py` 守 float32 出口。

## [0.1.6] - 2026-10-19

### 🔴 修复：顶层漏导出 `run_factor`（PyPI 安装测试抓到的真 bug）

在**全新 venv** 里从 PyPI 装 0.1.5 后，按文档调用 `alpha101v.run_factor(...)` 报
`AttributeError: module 'alpha101v' has no attribute 'run_factor'` ——
前几轮只把 `run_factor_raw` / `research_mode` 追加到顶层，**`run_factor` 本身漏了**
（它只存在于 `alpha101v.registry`）。此前所有测试都从 `registry` 或 `src` 路径导入，所以没暴露；
**独立安装测试才抓到**（这正是「安装试用归另一个会话」的价值）。

现在顶层可用：`run_factor` / `run_factor_raw` / `research_mode` 三者都在 `__all__`。

### ✅ 顺带验证：pandas 3.x 兼容性

仓库 CI 只覆盖 pandas 2.1–2.3；本次在全新 venv（**pandas 3.0.6 + numpy 2.4.6 + scipy**）里用源码跑
全部 101 个因子：**全部通过**（补齐 `ind_*` 字段后无失败）。

## [0.1.5] - 2026-10-19

修 0.1.4 引入的问题 + 补齐 B4 + 接入 lint 关卡 + **更正 0.1.4 的性能声明**。

### 🔴 N1 重复定义（真缺陷）

`run_factor_raw` 在 `registry.py` 里被定义了两次（补丁重复粘贴），第二份覆盖第一份、签名还不一致
（`panel: Mapping` vs `panels: dict`），pyflakes 会报 F811 ⇒ 删除重复定义、签名统一；
新增 `test_no_duplicate_top_level_definitions`（AST 扫描，禁止同模块重复定义）。

### 🟠 N2 B3 之前只修了一半

`run_factor_raw` 存在但**不可发现**（不在 `__all__`、也没顶层导出）⇒ 用户仍会去碰 `meta.func`。
现在**顶层导出并加入 `__all__`**，并新增 `test_run_factor_raw_is_discoverable`。

### ✅ lint 关卡（用户建议）

`pyproject` 增加 `[tool.ruff]`（只选能抓真 bug 的规则：`E9/F63/F7/F82/F811/F821`，不做风格限制），
CI 增加 `ruff check src tools tests`。
**接入当天就抓到一个真 bug**：`tools/second_reference_differential.py:209` 引用了从未定义的
`ROUNDING_CONFLICTS`（F821；一个未被调用的死函数）⇒ 已删除。ruff 现已 0 error。

### ✅ B4：研究口径的正规入口（方案 A）

`factors.py` 里 **62 处** `decay_linear(...)` 都不传 `dense`（忠实官方 sparse 默认），而 `run_factor` 没有口径参数
⇒ 想用严格口径只能 monkeypatch `alpha101v.factors.decay_linear`（且必须打 `factors.` 前缀，改 `operators.` 无效）。

现在提供上下文开关（**默认行为完全不变** ⇒ golden/差分/平台对拍口径不动）：

```python
with alpha101v.research_mode():
    factor = run_factor("alpha31", panel)     # 窗口必须完整，缺数据 ⇒ NaN
```

* `decay_linear(..., dense: bool | None = None)`：`None` 时读 `ContextVar`（线程/协程安全）；
* **显式传参优先**；默认值恒为 `None` ⇒ 行为与 0.1.4 逐位一致（golden 无需重生成）。

### 🟡 N3 性能声明更正（见上 0.1.4 条目）

0.1.4 只报了合成面板的 10–19×，与真实面板（4.5–4.7×、小面板 1.3×、端到端 1.03×）不符 ⇒ 已在本文件与
`docs/vectorization.md` 如实并列「合成 vs 真实」两组数字，并写明小面板可能变慢。

### 验证

`extreme + golden + operators` 72 项、`factors_all + usage` 314 项通过；ruff 0 error。

## [0.1.4] - 2026-10-19

**性能版本**：两项算子向量化。规矩是「**没等价性就是失败**」—— 每项都给出机器可验证的等价性断言
与同输入、预热后 3 次平均的速度数字（详见 `docs/vectorization.md`）。

### `decay_linear` 向量化（10–19×）

* 由 `rolling().apply` 改为 `window` 次整列 shift 乘加；
* **等价性：数学等价，末位 ≤1 ulp** —— `max|Δ| ≈ 4.26e-14`（因子值约 100 时约 3 ulp、相对 3e-16），
  **NaN 掩码逐位相同**。这是浮点求和顺序的物理下限：原实现用 numpy pairwise 求和，向量化只能按
  `Σ coef[k]·x[t−k]` 累加 ⇒ 末位可能不同（`ts_rank` 能做到逐位相等，是因为它本质是比较+整数计数）。
* 断言：`tests/test_decay_equivalence.py`（**96 用例**）要求 NaN 掩码逐位相同 + `max|Δ| ≤ 1e-13` + `rel ≤ 1e-15`；
* **golden 按此重新生成**（该 1 ulp 变化会触发位级守卫，属预期）；
* 速度 —— ⚠️ **0.1.4 原文只报了合成面板的数字（10–19×），这是误导，0.1.5 更正如下**：
  * **合成面板**（无 NaN；同输入、预热后 3 次平均）：60×300 w=20 **10.8×**、200×500 w=20 **18.9×**、w=10 **14.8×**、w=5 **14.0×**；
  * **真实 A 股面板实测**：359×60 **1.3×**、400×1000 **4.5×**、400×3000 **4.7×**（w=20）；
  * **101 因子端到端仅 1.03×**（37.0 s → 36.1 s），且 **8 个因子变慢**（小面板上按 window 次 `shift` 的分配开销超过 `rolling.apply`）。
  * 结论：**大面板受益明显、小面板基本持平** —— 别把合成面板的 10–19× 当通用预期。

### `ts_argmax` / `ts_argmin` 向量化（6.8–11.6×）

* 由 `rolling().apply(np.argmax/np.argmin)` 改为 `rolling.max/min` + 「自新到老扫、命中即覆盖」⇒
  最老命中者胜出，复刻 `np.argmax` 的**并列取最早**；
* **等价性：逐位精确相等**（整数索引，`np.array_equal`）—— 40 用例覆盖 max/min × basis × window × {并列, NaN}；
* **golden 与 101 因子全量无需重生成**（313 passed）⇒ 逐位不变的独立证据；
* 速度：60×300 w=20 **8.3×/6.8×**；200×500 w=20 **11.5×/10.7×**；w=5 **10.2×/11.6×**。

### `product` **有意不向量化**

`exp(Σlog)` 只对正数成立（0 ⇒ −inf、负数 ⇒ NaN），且上溢点与顺序不同 ⇒ 差异可能达**数量级**、
不是 1 ulp。按其使用面（少数因子）与风险，保持 apply 实现。

### 其他

* `docs/vectorization.md` 新增：做了什么、等价性到什么程度、速度多少、测量方法、边界（并行/状态属使用者）；
* 变异测试同步：`m3`（权重反序）与 `m4`（argmax 错位 1）的注入点改到新实现，
  两条注入仍被套件抓住（`tests/test_mutation.py` 8 项通过）；
* 记录一个真实教训：我第一版向量化把 `recent_first` 的系数方向写反（差异达 40），被等价性测试当场抓出。

## [0.1.3] - 2026-10-19

外部审计（9 条，均带可复现证据）修复版。**0.1.2 存在 P0-1 缺陷，请升级到 0.1.3。**

### 🔴 P0-1 `decay_linear` 零观测伪造 0.0（静默错误）

稀疏模式（官方默认）在 `fillna(0.0)` 之后 rolling，导致「窗口内一个有效值都没有」时 `min_periods` 仍被满足，
输出 **0.0** 而不是 NaN —— 新股「上市前全 NaN」的列因此会在截面 rank 里拿到名次、挤动全市场排名
（审计实测：180×30 面板新增一只全 NaN 股票，16/101 个因子被改变；切 dense 后只剩 2 个、差异 5.6e-17）。

修法**只堵「零观测」**（保留官方 sparse 语义，故 golden 口径不变）：公开 `decay_linear` 外包一层，
`valid_count == 0` 位置置 NaN；内核保留为 `_decay_linear_core`。
⇒ golden 基线已重新生成（该位置 0.0 → NaN 属预期行为修正）。

### 🔴 P0-2 `volume` 单位文档自相矛盾（照文档做静默差 100 倍）

`panel.py` 口径：`volume` 单位为**手**、`vwap = amount/(volume*100)`；而 `usage.md` 写 `volume = vol*100`（变股）
且 `vwap = amount/volume`（漏 ×100）。已按 `panel.py`（真实数据裁决：`amount×10/vol` 落在 [low,high] 100%）统一：
**`volume = vol`（手，不再 ×100）**、**`vwap = amount/(volume*100)`**，字段表由生成器产出并附警告。

### 🟠 P1

* **B3** 新增公开 `run_factor_raw`（不做出出口卫生，可能含 ±inf）；`run_factor`/`raw` 共用内部 `_invoke`。
* **B4** `usage.md` §4.5 如实写明限制：22 个因子内部写死 sparse，`run_factor` 无 `dense` 透传；
  给出两条绕法（直接用 `operators.decay_linear(dense=True)`；替换 `factors.` 前缀符号，改 `operators.` 无效）。
* **B5** `adapters/industry.py` 不再硬编码作者本机绝对路径：**存在才作为默认值**，否则要求显式传参或
  `ALPHA101V_SW_CLASSIFY` / `ALPHA101V_SW_MEMBERS`，缺失时抛明确错误。

### 🟡 P2 文档

* **B6** `registry.py` 头部过期说明（「M2 试点 / M3 工作」）→ 101 个全部注册（82 verified / 19 partial）。
* **B7** `usage.md` 耗时「≈8 分钟、ts_rank 是瓶颈」→ 实测 **≈37 秒**，**decay_linear 才是最大瓶颈**（4 个 apply 算子约 59%）。
* **B8** `count_extremes` 的 `huge` 默认改为**尺度感知**（`None` ⇒ 面板 4σ），不再用与量纲脱节的 `1e12`。

### 🟢 审计其余结论

* B9（4 个 apply 算子占 58.9%、端到端向量化上限约 2.4×）已记录为后续优化预期基线；
* 审计方核查「非 bug」清单（时间截断不变性 101/101、rank/ts_argmax/ind_neutralize/scale 的 NaN 处理、
  0/0 自然 NaN、`_sanitize` 不漏 inf、101/101 齐备）与本仓库自身测试一致。

### 本轮自查（发版前）

* **全量套件 714 项通过**（0 失败 / 0 错误）；
* **通用探针**：所有窗口算子在「全 NaN 输入」下**无伪造值**；**101 因子在「整列全 NaN 的股票」上
  无异常、无伪造值**；
* 静态扫描：`min_periods` 误配 0 处、`except: pass` 0 处、TODO 0 处、`src/` 下无本机绝对路径。

## [0.1.2] - 2026-10-18

### 修复（正确性）

* **复权 bug A**：`cumulative_factors` 取前收原本用 `series.iloc[position-1]`，若中间有停牌（NaN）
  会把除权事件**静默当 1.0**，导致同一股票「单独请求 vs 批量请求」结果不同（实测 000651：
  56.2956 / 51.9021）。改为**事件日之前最后一个非 NaN 收盘**。
* **复权 bug B**：新增 `anchor_date` 参数 —— 给定时该日期因子归一为 1，结果**与请求窗口/批次无关**；
  未给时保留历史语义（hfq 锚面板首行，依赖窗口）并在 docstring 写明。
  分工明确：库只保证「给定锚，算得对」；锚从哪来、变没变属调用方（数据仓库）职责。
* **字段表口径矛盾**：`volume` 单位为**手**（1 手 = 100 股），字段表由生成器
  `tools/field_requirements.py` 产出，改生成器而非手改产物。
* **仓库卫生**：删除误提交的 0 字节 `=1.26`（`pip install "numpy>=1.26"` 忘加引号产生）；
  新增守卫：`__version__` 必须等于 pyproject、dist 元数据一致、禁止跟踪/出现 `=` 开头的重定向事故文件。

### 新增

* **L7 调用方式不变性测试**（`tests/test_adjust_invariance.py`，纯合成数据、不需 MongoDB）：
  单股 vs 多股、同锚下长窗口 vs 短窗口，结果必须**逐位相同**；并复现停牌期除权事件。
* **极端值三原则工具**（`alpha101v.extreme`）：
  ① 除以 0 ⇒ 默认 NaN（`_sanitize` 契约「永不输出 ±inf」）；
  ② 极小分母 ⇒ `mask_small_denominator` 按分母掩码 + `count_extremes` 的 `huge_finite` 让巨大有限值可见；
  ③ 分子溢出 ⇒ `bound_inf` 显式保留尾部（前提：已确认为溢出）。
  **不提供**「把 winsorize/inf 当默认流程」的开关 —— 那会把无意义的计算爆炸伪装成极端信号。

### 性能

* **`ts_rank` 向量化**：移除 `rolling().apply` 逐窗口回调，改为 `window` 次整列比较，
  `rank = 1 + #{< x} + (#{== x} − 1)/2`（= `rankdata(win)[-1]` 的 average 名次）。
  基准（60×40 面板、w=20）：**848.92 ms → 6.88 ms（≈123×）**；
  等价性：算子测试 57 项、**golden 位级比对 5 项（逐位相同）**、并列值场景位级一致。

### 文档

* `docs/audit_2026-10-18.md`：用户审计台账（N1–N5 / A–F 的核实结论、优先级与处置计划），
  并记录两条关键更正：**不要用 xdxr 自建复权**（送转偏 8–40%；应直接取供应商 `stock_adj`）、
  **锚必须每次重算、绝不跨运行持久化**（实测一夜 69 只新除权、锚偏 5.77%）。
* `docs/usage.md`：新增 §0.5 环境硬事实（默认 `python3` 是 3.8.8、必须用 qa 解释器；
  测试项数依赖解释器）、§4.5 `decay_linear` 的 sparse 默认在研究场景下的坑（建议 `dense=True`）、
  §3.5 A 股 T+1 与执行约束三道工序。
* `docs/verification.md`：新增 §1.13 许可澄清（GPL 同环境不传染、但绝不合并代码）。
* `docs/factor_meaning.md`：101 个因子的机械事实表（自动生成、可 `--check` 防漂移）+
  逐条经济解读（机械 / 推断分开标注）。
* README：路线图 M4/M5 状态更正为已完成、测试计数统一为实测值、耗时表述统一。

### 排障记录（更正：根因是陈旧 egg-info，不是 `.pyc`）

升到 0.1.2 后 `test_version.py` 一度仍报 `__version__ = 0.1.1`。我先怀疑 `__pycache__` 的陈旧字节码，
清掉后**仍然复现** ✗ —— 根因是 `src/alpha101v.egg-info/PKG-INFO` 里的 `Version: 0.1.1`：
`pip install -e .`（setuptools legacy）生成的 egg-info 也在 `sys.path` 上，
`importlib.metadata` 会把它当成该发行版的元数据源 ⇒ 插了 `src/` 的进程读到 0.1.1、没插的读到 dist-info 的 0.1.2。
删除陈旧 `src/alpha101v.egg-info`（本应 gitignored）后恢复正常。

## v0.1.1 — 2026-10-12

* **第二独立参照差分**（MIT 许可的 alpha101-pipeline）：专攻 19 个 partial 因子。逐条口径对齐
  （rank 取 0-based、stddev 用 ddof=1、decay_linear 用 dense、ts_argmax 用窗口起点、
  幂运算换成保号的 signedpower、adv 对齐为 volume×close）。证明了两处参照侧口径偏离
  （并列取号按行序、窗口不足给 0 而非 NaN），并**证伪**了「小数窗口是主因」这一归因
  （把参照改成 floor 后不匹配反而从 98.9% 升到 100%）⇒ 19 个状态**全部保持 partial**，不升级、不豁免。
* **使用指南** docs/usage.md 与两个可跑示例：字段依赖表（只有 OHLCV 时能跑 31 个因子）、
  中文数据源的单位换算、口径表、自查清单（时间截断一致性）。
* **美股真实数据验证**：新浪源 80 只 × 753 个交易日，82 个因子对拍参照：64 一致 + 18 已归因 + 0 待查；
  数据按用户要求用后即删并留审计。
* **依据清单** docs/lb_evidence.md：17 条官方文档结论对应短引文与 PDF 页码。

## v0.1.0 — 2026-10-11

* **M5 终态**：verified 82 / partial 19 / ambiguous 0；golden 快照入库；
  规范对照 101/101 等价；与 vnpy 的算子层 27 项 + 因子层 82 个可比因子差分 0 待查；
  不变量与 8 个变异注入全部被抓。
* 655 项测试；CI（pandas 2.1/2.2/2.3 矩阵 + golden 检查 + 规范对照）。
