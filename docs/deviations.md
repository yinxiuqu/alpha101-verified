# 偏差清单（deviations.md）

| 项 | 内容 |
|---|---|
| 文档版本 | v0.1（2026-10-09，M0/M1） |
| 依据 | 设计文档 §6.3（三分类）、§6.8（门槛 2）、§7.2 |
| 状态 | **《与论文的偏差清单》（101 行）尚未生成 → M3 交付**；本文件现在记录已可判定的算子层偏差、设计文档勘误、以及待办模板 |

> 设计文档 §6.3 要求：把论文附录每个 alpha 的公式解析成算子树，与实现的 AST 逐节点比对，
> 输出**等价 / 近似 / 偏离**三分类，产出 101 行的《与论文的偏差清单》。
> **本轮（M0/M1）没有因子**，因此那份清单为 **0/101**——这不是遗漏，是里程碑顺序。

---

## 1. 算子层偏差（与 GPL 原实现、与论文原文）

### 1.1 与「被分析的 GPL 实现」（依据设计文档 §3.3，不需要读它的代码）

下表依据设计文档 §3.3 的缺陷清单（该清单来自只读静态分析，本仓库**从未打开其代码文件**）。
它记录的是「本库在算子层与那个实现的做法不同，且本库有测试证明自己更接近规范」。

| # | GPL 原实现的做法（设计文档 §3.3） | 本库做法 | 判据来源 | 锁定测试 |
|---|---|---|---|---|
| 1 | `decay_linear` 用 `df.as_matrix()`（pandas ≥1.0 已删除）→ 22 个因子必崩 | 用 `np.arange(1..d)` 权重 + 逐窗口点积 | L-C 数学定义；与 `np.average(weights=1..d)` 对拍 | `test_a17`、`test_a18`；变异 `m3` |
| 2 | `alpha1` 内 `x = close; x[returns<0] = ...` 原地污染入参 | 全部算子**纯函数**，绝不写入入参 | 设计文档 §6.5「输入不可变性」 | `test_inputs_are_not_modified`（22 个调用点）；变异 `m6` |
| 3 | `scale` 用 `df.div(df.abs().sum())` → 按**列**求和（轴向错） | `axis=1`，每日 `Σ\|x\| = k` | L-A 论文定义（每日截面） | `test_b05`–`test_b07`；变异 `m1` |
| 4 | `IndNeutralize` 逐日 `la.inv`，遇空行业/奇异矩阵 → `LinAlgError` | `ind_neutralize` 向量化分组（`bincount`，无求逆）；`neutral` 用 `lstsq`(SVD) | L-C；与 `statsmodels.OLS` 对拍 `rtol=1e-10` | `test_c02`、`test_c03`、`test_c10`、`test_c12` |
| 5 | `ts_rank` 返回窗口末值**序号**，与截面 `rank` 的 pct 量纲混用 | `ts_rank` 默认 `pct=True`（名次/window），与 `rank` 同量纲 | 设计文档 §3.3 缺陷 6 | `test_a10`、`test_a11`；变异 `m2`（`rank` 侧） |
| 6 | 101 个因子几乎全部 `.fillna(0)` 收尾，缺失与真值 0 不可区分 | NaN 传播；需填充时必须显式（如 `returns_from_close(fill_first=True)`） | 设计文档 §3.3 缺陷 7 | `test_a25`、`test_a26`、`test_panel.py::test_returns_from_close_leaves_first_row_nan_by_default` |
| 7 | 零测试、零基准值 | 219 个测试 + 7 个变异注入 + 权威实现逐点对拍 | §6.2/§8.4 | 全量 `pytest` |

📌 第 4 条是生态级的差异点：vnpy（MIT）**整个算子缺失**、QAFactor **会崩**，
两个主流实现都栽在 `IndNeutralize`（设计文档 §4.3.1、§10.3）。

### 1.2 与论文原文（L-A 级，2026-10-09 逐字核对后新增）

论文正文已逐字入库（`docs/paper_formulas.md`，101/101 条公式、括号平衡校验 0 条不平衡）。
下表是核对后发现的**算子层**差异与覆盖缺口；因子层的 101 行清单仍待 M3。

| # | 论文（L-A）规定 | 本库现状 | 性质 | 影响面 | 处置 |
|---|---|---|---|---|---|
| P1 | 非整数天数 `d` **取下整 `floor(d)`**（§3 通式明写） | `_check_window` 对非整数抛 `TypeError` | ❗**偏离**（已判定，待改码） | **40 个因子**（58–99 号，共 229 处非整数窗口） | 改为 `floor(d)`；floor 后 `<1` 仍报错；同步改 `operators.md` §3.8/§4.4 与 `test_a27` |
| P2 | `adv{d}` = 平均每日**美元成交额**（dollar volume） | 库内尚无 `adv` 派生（属因子层）；若用股数 `volume` 替代 | ⚠️**近似**（若替代） | **45 个因子** | A 股取 `amount`（元）：`adv20 = sma(amount, 20)`；M3 逐因子登记 |
| P3 | 使用 `abs`/`log`/`sign`/`signedpower` 四个一元函数 | 20 算子内**不含**（属层设计边界） | ⚠️**覆盖缺口** | **15 个因子** | M2 交付 `elemwise.py`（`operators.md` §1、`paper_formulas.md` §7.6） |
| P4 | `signedpower(x, a) = x^a` | 未实现 | ⚠️**歧义**（名字暗示保号幂） | 2 个因子（Alpha#1/#84，a=2 无差异） | 待 BRAIN 文档或 vnpy 实现定案 |
| P5 | `decay_linear` 权重 `d, d–1, …, 1`（**枚举方向未写死**） | 取「末值权重最大」（权重 `1..d` 归一） | ⚠️**论文歧义**（非偏离） | **22 个因子** | M4 专项核对 vnpy `ts_decay_linear` 方向；差分脚本预留开关 |
| P6 | `ts_argmax`/`ts_argmin` = "which day … occurred on"（**基准与方向未定义**） | 默认自窗口起点 1-based（可切 `days_ago`） | ⚠️**论文歧义**（非偏离）；两读法为**序反转**，Alpha#1 会变号 | **6 个因子** | 待 L-B（BRAIN 文档，需登录）或 vnpy 差分定案 |
| P7 | `scale(x, a)`：`sum(abs(x)) = a`（**轴向未写**） | `axis=1`（每日截面） | ⚠️**论文歧义**（非偏离） | 6 个因子 / 9 处调用 | 待 L-B 复核（BRAIN `scale` 带 booksize 语义） |
| P8 | `rank`/`ts_rank` 是否 pct、`stddev`/`covariance` 的 ddof、零方差相关系数行为 | 均已显式决策（pct=True / ddof=1 / NaN） | ✅**论文未规定**，属 L-C 决策，不算偏差 | — | 已记于 `operators.md` §3；M4 差分时按 §6 清单归一化 |

**结论**：论文级核对后，算子层的差距只剩 **P1 一处需要改码**（且规则明确、无歧义）；
P2/P3 是因子层的前置工作；P5/P6/P7 是**论文自身的歧义**，必须靠 L-B 或差分定案，**不得靠猜**。

---

## 2. 设计文档（v0.2）勘误：4 条

这些是**设计依据自身**的内部不一致。本实现以「文档中更权威的那条判据」为准，
并保留另一条数值为可复现的备选口径；推导与测试见 `docs/operators.md` §5。

| # | 位置 | 文档写法 | 实测/推导 | 本库处置 |
|---|---|---|---|---|
| 1 | §8.2 `rank` 并列行 | `[10,10,30]` → `[1/3, 1/3, 1.0]`（标注 average 法） | `average` 法给 `[0.5, 0.5, 1.0]`；`[1/3,1/3,1]` 是 **min** 法 | 取 average（与同段「与 rankdata(row,'average')/n 逐点相等」一致）；`method="min"` 可复现文档字面值 |
| 2 | §8.1 `covariance` 行 | `[NaN,NaN,1,1,1]`（ddof=1） | `4/(3-1) = 2`；`1` 是 `x=[1,2,3]` 的方差（疑似串行） | 断言 2，并与 pandas `rolling().cov()` 逐点对拍 |
| 3 | §8.4 最后一行 | `min_periods` 放宽 → 必须让「时间截断一致性」失败 | 放宽 min_periods **不引入前视**，截断一致性照样通过；真正的抓取者是「预热期必须 NaN」断言 | 变异 `m7` 由 `test_a01_ts_sum` 抓住；另设专门测试同时证明 `test_a25` 抓得住、`-k truncation` 抓不住 |
| 4 | §8.4 行数 vs 移交提示词 | 表格 7 行，提示词写「6 个注入」 | 逐行数得 7 | 以表格为准，**7/7 全覆盖** |

---

## 3. 与参照实现（vnpy, MIT）的差异：**算子层已实地复核**（2026-10-09）

实现路径：``tools/fetch_vnpy_reference.sh`` 取 vnpy（MIT）的 ``cs_function.py`` / ``ts_function.py``
到 gitignored 的 ``.vnpy-ref/``（含 SHA256 校验，**不入库**），再由 ``tools/differential.py``
在本机 ``qa`` 环境（已有 polars 1.44）逐点对拍——**polars 是参照侧依赖，不污染本库运行时**。
结果：**24 项对拍中 18 项对齐后逐点一致、6 项为已归因口径差异、0 项待查**
（明细见 `docs/operators.md` §6；测试包装见 `tests/test_differential.py`）。

| # | 差异 | 性质 | 复核结论 / 处置 |
|---|---|---|---|
| V1 | `decay_linear` 权重方向：vnpy 把 `d, d–1, …, 1` 套在**时间正序**窗口上（最老权重最大） | ⚠️**口径相反**（论文枚举方向未写死） | **最高风险项**：影响 **22 个因子**。本库默认「最新权重最大」（设计文档 §8.1 + WMA 惯例），并新增 `order="oldest_first"` 与 vnpy 逐点对齐；未取得 BRAIN 文案前，这 22 个因子不得标 `verified` |
| V2 | `ts_std` 用 `ddof=0`（而它的 `cs_std` 用 polars 默认 `ddof=1`，**自身不一致**） | 口径差异（可接受） | 本库默认 `ddof=1`（pandas/polars 默认 + 设计文档签名），`stddev(ddof=0)` 对齐后逐点一致；影响 8 个因子 |
| V3 | vnpy 覆盖 **82/101**：缺 `alpha56`（无 `cap`）+ 18 个 `IndNeutralize` 因子 | 覆盖度缺口 | 这 19 个**无法差分**，只能靠 L2+L4（本库已交付 alpha56 试点） |
| V4 | 那 18 个因子在 vnpy 测试里被**静默摘掉中性化**（表达式里 `IndNeutralize` 消失，断言仍通过） | 「有测试 ≠ 有验证」的教科书案例 | 因子级对拍必须按**含中性化的原式**比对，否则对拍对象本身是错的 |
| V5 | vnpy 的 `ts_argmax`/`ts_argmin` 即 `arg_max()+1`（**1-based 自窗口起点**） | ✅ 与本库默认**一致** | 本库 §3.3 的默认口径获第二实现支持 |
| V6 | vnpy 的 `ts_rank` 用 `scipy.percentileofscore(w, w[-1])/100` | ✅ 与本库 `ts_rank(pct=True)` **数学等价** | 实测逐点一致（含并列）；`pct=False` 是参照没有的分支 |
| V7 | vnpy 的 `cs_rank` 用 `method="min"`；`cs_scale` 零和行给 `0`；预热期各算子不统一（多为 `min_samples=1` 填值） | 口径差异（可接受） | 均可用本库显式参数对齐或已文档化（`method=` / §3.4 / §2.3） |
| V8 | vnpy 的算子签名是 `window: int`，**不支持非整数窗口** | 参照能力缺口 | 论文 58–99 号共 **40 个因子**用非整数窗口 ⇒ 参照无法表达；本库按论文 `floor(d)` 实现 |
| V9 | vnpy 自述 alpha21 把 `>=1` 实现为 `>1`、alpha24 把 `<=0.05` 实现为 `<0.05` | 参照**主动标注**的边界偏差 | 因子级对拍时列为「已知差异」，**不得判为 bug**（§6.4）；留待 M4 |
| V10 | 因子级差分入口 `calculate_by_expression` 依赖 `math_function` 与 `ta_function`（后者需 **talib**） | 工具链缺口 | M4 需补 `math_function` 并处理 talib（本机未装 ta-lib）；本轮只做算子层 |

---

## 4. 待 M3 生成的《与论文的偏差清单》模板（101 行）

| 字段 | 取值 |
|---|---|
| `factor` | `alpha001` … `alpha101` |
| `paper_ref` | 论文附录公式编号（如 `Appendix A, eq. (1)`） |
| `implemented_expr` | 本库实现的算子树（由 AST 导出） |
| `paper_expr` | 论文公式解析出的算子树 |
| `classification` | `等价` / `近似` / `偏离` |
| `differences` | 近似/偏离时的具体差异（少一个 `rank`、`adv20` 用 volume 替代、常量不同…） |
| `impact` | 差异对数值的预期影响（含是否影响排序） |
| `status` | `verified` / `partial` / `ambiguous`（与 `registry` 元信息一致） |

生成工具：`tools/conformance_report.py`（**M3 待实现**，见 `tools/README.md`）。

## 5. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-09 | 首版：算子层 7 项与原 GPL 实现的偏差、设计文档勘误 4 条、vnpy 差异 5 项待复核、101 行清单模板 |
| **v0.3** | 2026-10-09 | §3 重写为**算子层已实地复核**：24 项对拍（18 一致 + 6 归因 + 0 待查），差异表 V1–V10（含 `decay_linear` 方向相反这一 22 因子最高风险项、`ts_argmax`/`ts_rank` 与本库一致、vnpy 不支持非整数窗口、因子级差分缺 talib/math_function） |
| v0.2 | 2026-10-09 | 新增 §1.2「与论文原文（L-A）的算子层偏差」：P1 非整数窗口 `floor(d)`（40 因子，**唯一需改码项**）、P2 `adv{d}`=美元成交额（45 因子）、P3 逐元素层缺口（15 因子）、P4 `signedpower`、P5 `decay_linear` 权重方向（22 因子）、P6 `ts_argmax` 基准（6 因子）、P7 `scale` 轴向（6 因子）；§1 拆为 1.1（GPL）/1.2（论文） |
