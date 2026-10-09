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
| 测试总数 | **219**（6 个测试文件，含变异测试） |
| 结果 | **219 passed / 0 failed**（约 2~3 分钟，其中变异测试约 2 分钟） |
| 数值容差 | 与权威实现对拍 `rtol = 1e-10`（statsmodels 残差、pandas rolling、scipy `rankdata`） |
| 失败即停 | 本层未 100% 通过前不得进入因子实现（§10.4 第 6 条） |

各文件规模与职责：

| 文件 | 收集用例数 | 覆盖 |
|---|---|---|
| `tests/test_operators.py` | 54 | §8 全部用例：A 组 28 项、B 组 8 项、中性化组 15 项 + API 面/契约 |
| `tests/test_invariants.py` | 129 | §6.5：输入不可变性（22 个调用点）、截断一致性（19 算子）、未来扰动（19 算子）、缩放不变性、脏数据 |
| `tests/test_panel.py` | 13 | §7.4 面板契约、单位口径（含设计文档 §10.2 的实测样本） |
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

## 2. 六层协议状态

| 层 | 判据 | 状态 | 说明 |
|---|---|---|---|
| **L1 算子层** | 20/20 | ✅ **通过** | 见 §1 |
| **L2 规范对照** | 101 行偏差清单 | ⛔ **0/101** | 无因子；`tools/conformance_report.py` 待 M3 |
| **L3 双实现差分** | 82 个可比因子 `allclose(rtol=1e-8)` | ⛔ **未开始** | 需 vnpy 4.x + polars（**不得污染 `qa` 环境**）；19 个缺口无法差分 |
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
| 1 | 任何因子的正确性（0/101） | 因子层未实现（M2/M3） | M2 试点 5 个 → M3 全量 |
| 2 | 与论文公式的结构一致性（L2） | 同上；且需论文 PDF 逐条文字核对（设计文档「待办」第二项仍未完成） | M3 |
| 3 | 与 vnpy 的差分一致性（L3） | 需 vnpy 4.x + polars 独立环境 | M4（范围仅 82/101） |
| 4 | 19 个缺口因子（18 个 `IndNeutralize` + `alpha56`） | **无法差分**，只能靠 L2 规范对照 + L4 不变量 | M3/M4，结论须标注「无第三方对拍」 |
| 5 | golden 快照防回归（L5） | 无因子可冻结 | M5 |
| 6 | BRAIN 官方算子文档（L-B 级规范） | 未获取（设计文档 §2.3 待办） | 取到后复核 `days_ago` 等口径 |
| 7 | A 股落地口径（复权/PIT 行业/真换手率/单位） | 需数据；MongoDB 与申万 as-of 成员已就位（设计文档 §10.2） | M2 起逐步接 |
| 8 | 中性化算子在大面板上的性能 | M1 只承诺正确性 | M2 起基准测试 |

---

## 5. 复现与 CI

```bash
PY=/home/yinxiuqu/anaconda3/envs/qa/bin/python

$PY -m pytest -q                                   # 全量 219 项
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
