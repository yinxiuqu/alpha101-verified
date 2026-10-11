# tools/ — 报告与对拍工具（M3/M4 起）

按设计文档 §7.2 预留两个工具，**本轮（M0/M1）未实现**（没有因子可对照，写了也是假代码）：

| 文件 | 里程碑 | 职责 |
|---|---|---|
| `differential.py` | ✅ **算子层已交付**（2026-10-09） | 双实现差分对拍：本库 vs vnpy（MIT，polars DSL）逐点 `allclose(rtol=1e-8)`，并对差异做归因分类（一致 / 口径差异 / 不一致待查），**严禁简单判错**（§6.4）。24 项：18 一致 + 6 归因 + 0 待查 |
| `fetch_vnpy_reference.sh` | ✅ **已交付** | 下载 vnpy 的 `cs_function.py` / `ts_function.py` / `utility.py` / `datasets/alpha_101.py` 到 gitignored 的 `.vnpy-ref/`，逐文件校验 SHA256（**第三方代码不入库**） |
| `fetch_brain_docs.py` | ✅ **已交付**（2026-10-11） | 一次性抓取 BRAIN 平台文档 → MD（+PDF）：算子 66 条（完整正文 + 官方算例）、Learn 教程 17 页、数据集 150 个、数据字段 4367 个（含描述/数据集）。落 `refs/`（gitignored）：**专有文档，不提交、不分发**；cookie 只走环境变量 |
| `brain_alignment.py` | ✅ **已交付**（2026-10-11） | **BRAIN 行为对齐抽样**（补充证据，不是 L3）：同表达式在本库与平台各出一条日度 PnL，比较**单调性**（Spearman）而非数值相等。两条取数路径都**零配额**（`--alpha-id` 读已有仿真 / `--platform-pnl` 读导出文件）；`--submit` 会拒绝执行（不代你消耗配额）。凭据只从 `BRAIN_COOKIE` 或文件读，**不接受命令行 cookie** |
| `l6_statistics.py` | ✅ **已交付**（2026-10-11） | **L6 辅助统计**（**不是门槛**）：横截面 Spearman IC（h=1/2/3/5/10）、IC 衰减形状、市值/行业暴露、因子两两 PnL 相关。⚠️ 明文：统计显著 ≠ 实现正确，不参与 `verified/partial` 判定；A 股 ≠ 美股 |
| `golden_snapshot.py` | ✅ **已交付**（2026-10-11，M5） | **L5 golden 快照**：固定种子面板（5×320）上冻结 101 个因子输出（npz + sha256 清单 + 面板哈希 + 环境版本），`--check` 即门禁。判据 = **NaN 模式一致 + allclose 紧容差**；哈希不一致但数值一致只算「漂移提示」。⚠️ 只防回归、不证明正确性 |
| `factor_differential.py` | ✅ **已交付**（2026-10-09，M4） | **因子级**差分：同一面板喂给本库 101 因子与 vnpy 的 82 条表达式，按 §6.4 做语义归一化后逐点比较，并把差异**自动归因**（一致 / 覆盖差异经截面算子传播 / 同值不同配 / 参照 quesval2 取反 / 待查）。附带发现：**vnpy 的 `quesval2` 与它自己的文档语义相反**（详见 `docs/verification.md` §1.5） |
| `conformance_report.py` | ✅ **已交付**（2026-10-09） | 把论文附录公式解析成表达式树（完整词法 + 递归下降），与实现 AST 做**算子／字段／字面量**三重对照，输出 101 行偏差清单（当前 **101/101 等价、0 偏离**）。能力边界：算子级对照，不是完整数据流同构证明 |

运行方式（本机 `qa` 环境已含 polars 1.44，无需新建环境）：

```bash
bash tools/fetch_vnpy_reference.sh          # 取参照（需网络，约 1 秒/文件）
/home/yinxiuqu/anaconda3/envs/qa/bin/python tools/differential.py   # 打印对拍表；有待查项则退出码 1
python -m pytest tests/test_differential.py -q                      # 测试包装（参照缺失时跳过）
```

### 抓取 BRAIN 平台文档（本地语料）

```bash
BRAIN_COOKIE='t=...' python tools/fetch_brain_docs.py            # 默认全抓 → refs/brain_docs/*.md
BRAIN_COOKIE='t=...' python tools/fetch_brain_docs.py --pdf      # 额外渲染 PDF（pandoc+xelatex，chromium 兜底）
BRAIN_COOKIE='t=...' python tools/fetch_brain_docs.py --only datafields
```

抓 `/operators`(+`/{name}`)、`/tutorials`(+`/tutorial-pages/{id}`)、`/data-sets`、`/data-fields/summary`
与 `/data-fields`（后者**必须带完整上下文**，否则 `Invalid query`）。
**不抓** `/research`（那是社区帖检索，不是文档）与运营内容。

### L6 辅助统计与 BRAIN 行为对齐（补充证据层）

```bash
python tools/l6_statistics.py --n-codes 120            # 真实 A 股上跑 101 个因子的 IC/暴露/两两相关
python tools/l6_statistics.py --factors 4,5,101        # 少数因子快速核查

python tools/brain_alignment.py --factor alpha5        # 只算本地基线（不需要任何凭据）
python tools/brain_alignment.py --factor alpha5 --platform-pnl pnl.csv   # 与平台导出的 PnL 对比（零配额）
BRAIN_COOKIE='t=...' python tools/brain_alignment.py --factor alpha5 --alpha-id <id>  # 读已有仿真（零配额）
```

⛔ **行为对齐目前被数据权限卡住**：该账号只有 USA 数据（`/data-sets?region=X`：USA 150，GLB/EUR/ASI/CHN 全 0），
而本库是 A 股 ⇒ 没有「同一市场」的可比结果。拿到 CHN 权限或同源美股数据后，用
`--alpha-id` / `--platform-pnl` 即可收口（详见 `docs/verification.md` §1.9）。

两者都**不进入 L1–L5 门禁、不改变任何因子状态**：
L6 的纪律写在设计文档 §6.7（统计显著 ≠ 实现正确）；行为对齐的边界写在本工具文档串
（平台只返回表现、不返回因子矩阵；且两侧必须**同一市场**，本库是 A 股 ⇒ 平台侧须选 CHN）。

### golden 快照（M5）

```bash
python tools/golden_snapshot.py --check    # 校验当前实现与冻结基线（CI 门禁，退出码即结论）
python tools/golden_snapshot.py --write    # 仅在**有意**改动算法/口径时重建，并在 PR 说明原因
```

基线内容与判据见 `tests/golden/README.md`；面板 5×320、种子 20261010
（对设计文档 §6.6「5×250」示例的有意偏离：250 日是最长窗口，会整片 NaN）。

### 因子级差分（M4）

```bash
bash tools/fetch_vnpy_reference.sh              # 抓取参照（含 math_function.py + talib 替身）
python tools/factor_differential.py             # 语义归一化后对拍 82 个可比因子（退出码即门禁）
python tools/factor_differential.py --no-align  # 看「默认口径」下的差距有多大（归因素材）
python tools/factor_differential.py --panel real --alphas 13,15,16   # 真实连续行情定点核查
```

对拍范围 82/101：vnpy 未实现的 **19 个**（18 个含 `IndNeutralize` + `alpha56`）**结构上无法差分**。
语义归一化开关（`docs/verification.md` §1.5 有实测依据）：rank 并列（vnpy=min）、decay 方向（vnpy=oldest_first，
**与 BRAIN 官方相反**）、`stddev` ddof（vnpy=0）、`adv{d}` 口径（把 `amount` 喂成 `volume`）、
非整数窗口（论文 floor vs vnpy 四舍五入）、**argmax 基准**（本库按 BRAIN 的 `days_ago`，对拍切回 vnpy 的 `window_start`）、
**中缀 `^` 口径**（本库按 BRAIN 的 `power`，对拍切回 vnpy 的保号幂）、预热期。

### 规范对照（M3）

```bash
python tools/conformance_report.py            # 分类统计 + 非等价明细（退出码即门禁）
python tools/conformance_report.py --table    # 输出 101 行偏差表（docs/deviations.md §4 由它生成）
python tools/conformance_report.py --alpha 48 # 单因子排查
```

⚠️ **因子级差分（M4）还有两件前置**（见 `docs/operators.md` §6.3 L3）：
① 需要 `math_function.py`（`less/greater/log/abs/sign/pow1/pow2/quesval…`）；
② `calculate_by_expression` 会 import `ta_function`，而它依赖 **talib**（本机未装 ta-lib）
——需补一个只用于未调用路径的 shim，或在差分时绕过该入口直接调用算子函数。

对拍范围提醒（§4.3.1）：vnpy 只覆盖 **82/101**（缺 alpha56 与 18 个含
``IndNeutralize`` 的行业中性因子），且那 18 个因子在它的测试里被静默摘掉了中性化。
因此差分对拍的范围**仅限这 82 个**，剩余 19 个只能靠「论文规范对照 + 不变量」验证——
这一点必须在 `docs/verification.md` 里如实标注。
