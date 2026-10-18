# 使用指南：用这个项目算 101 个 Alpha 因子

面向**第一次拿到这个仓库、想用它算因子**的人。验证方法论与证据链不在这里，
在 [`verification.md`](verification.md) 与 [README 的一页复现](../README.md)。

---

## 0. 30 秒版

```bash
python -m pip install "numpy>=1.26" "pandas>=2.1" "scipy>=1.11"     # 运行时只依赖这三个
git clone <this-repo> && cd alpha101-verified && python -m pip install -e .
python examples/hello_alpha101.py        # 合成面板：不需要数据库、不需要网络，直接出结果表
```

**Python ≥ 3.11**（实测 3.11.16 / pandas 2.3.3 / numpy 1.26.4 / scipy 1.17.1）。
运行时依赖被 `tests/test_provenance.py` 机械守着：只有 numpy / pandas / scipy
（vnpy 只在**测试期**用于差分对拍，polars/talib 都不是必需品）。

---

## 0.5 ⚠️ 两个环境硬事实（踩过坑，写在这里省你时间）

1. **默认 `python3` 不是本项目的解释器**：本机默认 `python3` 是 **3.8.8**（`/home/yinxiuqu/anaconda3/bin/python3`），
   而本项目声明并实测在 **3.11.16**（`pyproject.toml` 的 `requires-python = ">=3.11"`）。
   包**只装在 qa 环境**里，用默认解释器会 `ModuleNotFoundError`。请显式指定：

   ```bash
   /home/yinxiuqu/anaconda3/envs/qa/bin/python -m pytest -q     # 697 项
   ```
   ⚠️ **测试项数也依赖解释器**：同一份代码，用 3.8.8 收集会少很多（缺依赖/跳过），
   所以「收集到 662 还是 697」不是代码变了，而是用错了解释器。
2. **`requires-python` 只是元数据声明**：实测 3.8 也能 `import` 包（**但没有测试覆盖，不承诺可用**）——
   声明为 ≥3.11 是「我们测过并承诺的范围」，不是「语法上跑不了」。

## 1. 五分钟上手（合成数据，可直接复制）

```python
import numpy as np, pandas as pd
from alpha101v import ALL_FACTOR_NAMES, registry

rng = np.random.default_rng(0)
index = pd.date_range("2021-01-04", periods=120, freq="B")   # 必须是 DatetimeIndex，升序唯一
columns = [f"S{i}" for i in range(8)]                        # 列 = 标的代码

close = pd.DataFrame(30 * np.exp(np.cumsum(rng.normal(0, 0.02, (120, 8)), axis=0)), index=index, columns=columns)
open_ = close * (1 + rng.normal(0, 0.004, (120, 8)))
high = np.maximum(close, open_) * (1 + abs(rng.normal(0, 0.004, (120, 8))))
low = np.minimum(close, open_) * (1 - abs(rng.normal(0, 0.004, (120, 8))))
volume = pd.DataFrame(np.exp(rng.normal(np.log(2e5), 0.6, (120, 8))), index=index, columns=columns)
amount = volume * close
panel = {
    "close": close, "Open": open_, "high": high, "low": low, "volume": volume,
    "amount": amount, "vwap": amount / volume,
    "returns": close.pct_change(fill_method=None),           # 注意 fill_method=None
    "cap": pd.DataFrame(abs(rng.normal(1e6, 2e5, (120, 8))) + 1, index=index, columns=columns),
    "ind_sector": pd.Series(["A", "A", "A", "A", "B", "B", "B", "B"], index=columns),
    "ind_industry": pd.Series(["A1", "A1", "A2", "A2", "B1", "B1", "B2", "B2"], index=columns),
    "ind_subindustry": pd.Series([f"G{i % 4}" for i in range(8)], index=columns),
}

print(registry.run_factor("alpha101", panel))                # 单个因子
ok = 0
for name in ALL_FACTOR_NAMES:                                # 全部 101 个
    ok += registry.run_factor(name, panel) is not None
print(f"跑通 {ok}/101")
```

三条契约（违反会**明确报错**，不会静默算错）：

1. **面板**：`pd.DataFrame`，`index` 是升序唯一的 `DatetimeIndex`，`columns` 是标的代码；
2. **不许用 0 填 NaN**：NaN 的含义是「信息不足」，本库的任何算子都不会悄悄填 0
   （唯一例外是 `decay_linear` 的官方默认「稀疏模式」，见 §5）；
3. **入参不会被改写**：`registry.run_factor(..., copy_inputs=True)` 默认深拷贝；
   直接调 `alpha101v.factors.alpha5(...)` 时也保证不写入参（有专门测试守着）。

---

## 2. 换成你自己的数据

### 2.1 字段清单（表 A / 表 B 由注册表自动生成）

<!-- FIELD_TABLES:BEGIN（由 tools/field_requirements.py 生成，勿手改）-->
#### 表 A：字段 → 需要它的因子

| 字段 | 含义 | 需要它的因子数 | 因子（编号） |
|---|---|---:|---|
| `close` | 收盘价（**必须复权**） | 62 | 1、2、5、7、9、10、11、12、13、17、18、19、20、21、22、24、25、28、29、30、31、32、33、34、35、36、37、38、39、42、43、45、46、47、48、49、51、53、54、55、57、60、63、68、69、70、71、74、79、83、84、85、86、87、88、90、91、92、93、96、100、101 |
| `amount` | 成交额（元）——**论文的 `adv{d}` 是美元成交额**，用 volume 替代属近似 | 45 | 7、17、21、25、28、31、36、39、43、47、61、62、63、64、65、67、68、69、70、71、72、74、75、76、77、78、79、80、81、85、86、87、88、89、90、91、92、93、94、95、96、97、98、99、100 |
| `vwap` | 成交均价（论文 vwap；无 vwap 时可用 `amount/volume` 近似） | 43 | 5、11、25、27、32、36、41、42、47、50、57、58、59、61、62、63、64、65、66、67、69、70、71、72、73、74、75、76、77、78、79、81、83、84、86、87、89、91、93、94、96、97、98 |
| `volume` | 成交量（**手**，与 `panel.py` 口径一致；1 手 = 100 股 ⇒ 换算成股数要 ×100） | 42 | 2、3、6、7、11、12、13、14、15、16、17、21、22、26、27、30、35、36、39、40、43、44、45、47、50、52、55、58、59、60、72、74、75、78、81、82、83、85、91、96、99、100 |
| `high` | 最高价（**必须复权**） | 34 | 15、16、20、22、23、25、26、28、35、40、41、44、47、53、54、55、60、62、64、66、67、68、72、74、77、80、83、85、88、92、95、99、100、101 |
| `low` | 最低价（**必须复权**） | 33 | 4、20、28、31、35、41、52、53、54、55、60、62、64、66、68、71、72、73、75、76、77、78、83、85、88、89、90、92、95、97、99、100、101 |
| `Open` | 开盘价（**必须复权**） | 29 | 2、3、5、6、8、14、18、20、33、36、37、38、54、62、63、64、65、66、71、73、79、80、82、86、88、92、95、98、101 |
| `returns` | 日收益率（`close.pct_change(fill_method=None)`，首行留 NaN） | 12 | 1、8、14、19、25、29、34、35、36、39、52、56 |
| `ind_industry` | 行业标签·论文 `IndClass.industry`（PIT/as-of） | 10 | 59、63、69、70、80、87、89、91、93、97 |
| `ind_sector` | 行业标签·论文 `IndClass.sector`（PIT/as-of，**不能用今天的快照**） | 5 | 58、67、76、79、82 |
| `ind_subindustry` | 行业标签·论文 `IndClass.subindustry`（PIT/as-of） | 4 | 48、67、90、100 |
| `cap` | 总市值（只被 alpha56 用；`rank` 型 ⇒ 总/流通市值等价） | 1 | 56 |

#### 表 B：你手上有什么 → 能跑多少因子

按**推荐获取顺序**累进（`close` 起，逐项补齐）：

| 已有的字段 | 可跑的因子数 | 新增 |
|---|---:|---|
| 截至 `close`（含以上） | **6** | +6 |
| 截至 `Open`（含以上） | **10** | +4 |
| 截至 `high`（含以上） | **11** | +1 |
| 截至 `low`（含以上） | **16** | +5 |
| 截至 `volume`（含以上） | **31** | +15 |
| 截至 `vwap`（含以上） | **43** | +12 |
| 截至 `returns`（含以上） | **51** | +8 |
| 截至 `amount`（含以上） | **82** | +31 |
| 截至 `cap`（含以上） | **83** | +1 |
| 截至 `ind_sector`（含以上） | **87** | +4 |
| 截至 `ind_industry`（含以上） | **97** | +10 |
| 截至 `ind_subindustry`（含以上） | **101** | +4 |

* **只有 OHLCV**（`close/Open/high/low/volume`）就能跑 **31** 个因子；
* 最省的因子只要**一个字段**：`alpha4`、`alpha9`、`alpha10`、`alpha23`、`alpha24`、`alpha46`、`alpha49`、`alpha51`；
* 缺字段时 `registry.run_factor` 会**明确报出缺哪个字段**——不要用 0 或均值去填，那会让因子变成另一个东西（见 §5 口径）。
<!-- FIELD_TABLES:END -->

### 2.2 从 CSV 接进来（长表 → 面板）

假设你的 CSV 是长表：`date,code,open,high,low,close,volume,amount`：

```python
import pandas as pd
from alpha101v import registry

long = pd.read_csv("my_prices.csv", parse_dates=["date"])
long = long.sort_values(["date", "code"])

def to_panel(long, field):
    return long.pivot(index="date", columns="code", values=field).sort_index()

panel = {name: to_panel(long, name) for name in ("open", "high", "low", "close", "volume", "amount")}
panel["Open"] = panel.pop("open")                       # 注意大小写：论文写 Open，其余小写
panel["vwap"] = panel["amount"] / panel["volume"]        # 没有 vwap 时的近似（见 §5）
panel["returns"] = panel["close"].pct_change(fill_method=None)
out = registry.run_factor("alpha5", panel)
```

完整可跑的模板见 [`examples/from_my_csv.py`](../examples/from_my_csv.py)（自带造一份假 CSV 并读回）。

### 2.3 用项目自带的适配器读本地数据（可选）

仓库里带了一套**本地 MongoDB** 的适配器（A 股）：

```python
from alpha101v.adapters.mongo import load_panel
from alpha101v.adapters.industry import load_sw_industry

panel = load_panel(codes, "2023-01-03", "2024-06-28", adjust="hfq")   # 默认 hfq（后复权、PIT 安全）
index, columns = panel["close"].index, panel["close"].columns
panel["ind_sector"] = load_sw_industry(index, columns, level="L1")    # 申万 L1/L2/L3 → sector/industry/subindustry
```

它只是**一个示例数据源**，不是必需组件；换成你自己的数据库/文件即可。

---

## 3. ⚠️ 两个必须注意的数据问题

| 问题 | 后果 | 怎么办 |
|---|---|---|
| **价格未复权** | 除权除息日出现**假跳空**，`returns`、`delta`、`stddev`、`decay_linear` 全被污染。实测某只 A 股在除权日「跌」−27.52%，复权后是 **+3.48%** | 用复权价（`load_panel(adjust="hfq")`，或你自己的复权源）。⚠️ **前复权（qfq）依赖未来事件 ⇒ 含前视**，做 PIT 回测请用后复权 |
| **行业/市值用了「今天的快照」** | 引入前视（未来信息），回测虚高 | 行业标签必须 **as-of/PIT**：每个交易日取当日已知的行业（`load_sw_industry` 已按 `in_date/out_date` 做 as-of 合并） |

### 2.4 常见数据源的列名与**单位**换算（中文数据源）

| 数据源 | 原始列 | 本项目字段 | ⚠️ 单位/口径注意 |
|---|---|---|---|
| tushare `daily` | `trade_date, ts_code, open, high, low, close, vol, amount` | `date, code, Open, high, low, close, volume, amount` | `vol` 单位是**手**（1 手=100 股）⇒ `volume = vol * 100`；`amount` 单位是**千元** ⇒ `amount = amount * 1000` |
| akshare `stock_zh_a_hist` | `日期, 开盘, 最高, 最低, 收盘, 成交量, 成交额` | 同上 | 成交量单位**手**；成交额单位**元** |
| 聚宽 `get_price` | 宽表（列是多级索引） | 改名即可 | **已经是复权价**（取决于 `fq` 参数）⇒ 务必记下用的是哪种复权 |
| 本仓库的 MongoDB 适配器 | `stock_day` 的 `vol`（手）/ `amount`（元） | `volume`, `amount` | 适配器内部已做 ×100 换算（见 `src/alpha101v/adapters/mongo.py`） |

**为什么反复强调单位**：`adv{d}` 用的是 `amount`（论文定义是**美元成交额**），**45 个因子**依赖它；
而 `volume` 的「手 / 股」混用会让 `volume / adv20` 这类比值整体差 100 倍——因子值全错，
**却不会报任何错**，这是最难查的一类问题。

**一分钟自查**（建议接完数据先跑）：成交均价应落在当日价格区间内

```python
vwap = panel["amount"] / panel["volume"]                       # 单位对了才有意义
inside = (vwap >= panel["low"]) & (vwap <= panel["high"])
print("vwap ∈ [low, high] 的自洽率", float(inside.to_numpy().mean()))   # 单位错会明显偏低
```

（本仓库在真实 A 股面板上实测 **99.86%**；明显低于这个数就回头查单位。）

另外两个高频坑：

* `pct_change()` 在新版 pandas 会默认前向填充并改变含义 ⇒ 一律写 `pct_change(fill_method=None)`；
* 面板列顺序/集合不一致时，因子内部会校验并报错（这是有意的：静默外连接会产出 NaN 而不是报错）。

---

## 3.5 如果你要在 A 股用这些因子：T+1 与执行约束

本仓库的因子是**日频信号**，不含任何「当日买卖」假设（详见 [`t1_audit.md`](t1_audit.md)），但你自己接回测时必须补三道工序：

1. **信号后移一天**：因子值在 t 日收盘后才算得出 ⇒ 严格做法是 t+1 开盘/收盘成交（本仓库评估工具假设「t 日收盘信号 → t+h 收盘收益」，等价于能在收盘竞价成交）；
2. **剔除涨跌停与停牌**：一字板买不进、跌停卖不出、停牌不能交易 —— 本仓库不建模，需自行处理；
3. **T+1 持仓约束**：当日买入当日不可卖出 ⇒ 任何「日内平仓」型策略在 A 股不成立。

## 4. 字段不够时怎么办

见表 B：**只有 OHLCV 就能跑 31 个**（`alpha4/9/10/23/24/46/49/51` 这类甚至只要一个字段）。
三条实用建议：

1. **先跑得起来的，再补数据**：缺 `amount` 会少 45 个因子（`adv{d}` 依赖它）；
2. **不要用 0 / 均值 / 前值填缺失字段**：`adv20` 用 `volume` 代替是**近似**（论文是美元成交额），
   若你这么做，请在下游把它记成已知偏差（本库在 `docs/deviations.md` §1.2 就是这么记的）；
3. 缺 `ind_*` 只会影响 18 个含 `IndNeutralize` 的因子（48/58/59/63/67/69/70/76/79/80/82/87/89/90/91/93/97/100）
   —— `run_factor` 会告诉你缺哪个。

---

## 4.5 ⚠️ `decay_linear` 的 sparse 默认在研究场景下的坑（实测反馈）

官方默认是 sparse（窗口内 NaN 当 0 计入加权）——**本库忠实实现官方口径**，这一点没变。
但用于**实证研究**时它有个隐蔽后果：一只 2020 年才上市的股票，其 2020 年前 `close` 全 NaN，
sparse 会把这些 NaN 当 0 算进加权平均，产出一个**「看起来正常、实则无意义」**的因子值（而不是 NaN）。

* **做研究**：建议对 `decay_linear` 显式传 `dense=True`（窗口需完整，缺数据就给 NaN）；
* **与平台算例对拍**：保持默认 sparse，因为那才是官方口径。

同一个道理适用于所有「窗口内缺数据怎么处理」的分歧：**先问它是研究口径还是平台口径**，
再决定传哪个参数（不要改源码默认值，见 §5）。

## 5. 口径：默认值不是随便定的（读这一节省你三天）

这些默认值**都有一手依据**（WorldQuant BRAIN 官方文档 + 论文），逐条对照见
[`lb_evidence.md`](lb_evidence.md)（结论 ↔ 官方短引文 + 出处页码）。

| 项 | 本库默认 | 为什么 | 例子 |
|---|---|---|---|
| `rank` / `ts_rank` 归一化 | 参数 `normalization="zero_to_one"`（默认）= **`(名次−1)/(n−1) ∈ [0,1]`**（官方） | 官方算例：`rank((4,3,6,10,2)) = (0.5,0.25,0.75,1,0)`；`ts_rank` 的 `3/(5−1)=0.75` | 最低位是 **0.0**（不是 1/n）⇒ `rank(a)/rank(b)` 型因子可能除零 |
| 除零结果 | **NaN**（不是 inf，也不加 epsilon） | 官方 `divide` 文档说除零是错误、建议加 epsilon；本库不偷改数值，把 ±inf 在输出边界降级为 NaN | `alpha42/57/72/93` 在部分日子无值 |
| `stddev` / `covariance` | **`ddof=0`**（总体） | 官方 `ts_std_dev` 算例把平方偏差之和除以 n | 想用样本口径就显式传 `ddof=1` |
| `decay_linear` | 权重**近期最大**；默认**稀疏**（窗口内 NaN 当 0） | 官方原文「averaging recent values…」「sparse mode (dense=false), treating missing values as zero」 | 严格口径传 `dense=True` |
| `ts_argmax/argmin` | **`days_ago`（今天=0）** | 官方原文「If today's value is the maximum, returns 0」 | 旧实现常给 `argmax+1`（1-based），本库用 `basis="window_start"` 可切 |
| 预热期 | **严格**：窗口不满就是 NaN | 「NaN 只代表信息不足」 | 想宽松就自己 `min_periods`，但要知道那已经不是论文口径 |
| 零方差相关 | **NaN** | 0/0 无定义，不伪装成观测 | 常数序列、单点窗口 |
| `min/max` 遇到 NaN | **返回另一侧**（`fmin/fmax`） | 否则 `max(分支A,分支B)` 型因子会整片退化 | `alpha96` 曾因此全 NaN |
| 比较/三元遇 NaN | **NaN 传播**（不是 C 的 False） | 把「未知」输出成 0 会被下游当成真结论 | 条件型因子 |
| 非整数天数 | **`floor(d)`** | 论文 §3 明写 | 40 个因子用到（如 `Ts_Rank(close, 7.45404)`） |

与参照实现（vnpy，MIT）的 **8 条口径差异**用 `python tools/differential.py` 可复现，
逐条归因在 `docs/deviations.md` §3。

---

## 6. 在你自己的数据上做质检（强烈建议，5 分钟）

```python
import pandas as pd, numpy as np
from alpha101v import registry

factor = registry.run_factor("alpha5", panel)

# 1) 覆盖率：几乎全 NaN 通常是字段缺失或窗口不够长
print("覆盖率", float(np.isfinite(factor.to_numpy()).mean()))

# 2) 时间截断一致性（PIT 金标准）：截断面板再算，必须逐点相等
cut = 200
truncated = registry.run_factor("alpha5", {k: (v.iloc[:cut] if hasattr(v, "iloc") else v) for k, v in panel.items()})
pd.testing.assert_frame_equal(truncated, factor.iloc[:cut])     # 不等 ⇒ 有前视或用了未来信息

# 3) 别把 NaN 当 0：下游 fillna(0) 会把「不知道」变成「确定是 0」
```

第 2 条是**最高性价比的自查**：任何前视（用了未来数据、非 PIT 行业、全样本拟合）都会让它失败。
本库里 101 个因子都通过这条（`tests/test_factors_all.py`），你自己的数据接进来后建议也跑一遍。

---

## 7. 性能与规模

实测（单核，本机）：**101 个因子 × 60 只 × 359 个交易日 ≈ 8 分钟**。

* 重型算子是 `decay_linear` / `ts_rank` / `product` / `ts_argmax` 这类**逐窗口 apply**（O(窗长)）；
* 提速手段：① 只算你需要的因子；② 把 `returns`/`vwap`/`amount` 预先算好复用；
  ③ 大面板按因子多进程切分（因子之间**无状态**，天然可并行）；
* 不需要 polars/talib；vnpy 只在**测试期**对拍用（`bash tools/fetch_vnpy_reference.sh`）。

---

## 8. 你会拿到什么、拿不到什么（诚实边界）

| | 情况 |
|---|---|
| ✅ 能拿 | 101 个因子的实现；**与论文公式结构一致**（L2 对照 101/101 等价）；算子层与因子层与第三方实现的差分证据；golden 快照防回归；每个因子的验证状态 |
| ⚠️ 状态不是全绿 | **`verified` 82 / `partial` 19**：那 19 个是含 `IndNeutralize` 或需要 `cap` 的因子，参照实现（vnpy）**没实现它们** ⇒ 「独立差分」这一必需门槛原理上无法满足，本库如实标注而不是豁免（`docs/verification.md` §1.7） |
| ❌ 不承诺 | **投资表现**（本项目不做回测/选股，见设计文档 §7.1 非目标）；与平台数值一致（平台不返回因子矩阵）；A 股上的有效性（`reports/l6_summary.md` 的统计**明文不参与判定**） |

---

## 9. 常见问题

**Q：为什么 `rank` 的结果里最低位是 0.0，而不是 `1/n`？**
A：因为官方就是 `[0,1]` 闭区间（§5 第一条，有官方算例）。默认档叫 `normalization="zero_to_one"`；
若你要旧口径（`名次/n`），传 `normalization="one_over_n"`；序号口径用 `normalization="ordinal"`。

**Q：为什么我的因子整片是 NaN？**
A：按顺序查：① 字段是否齐全（`run_factor` 会报缺字段）；② 历史长度是否够（最长窗口 **250 日**，
`alpha19/39/48` 需要 250 天以上）；③ 是否某列全常数（相关类算子在零方差时给 NaN）；
④ 是否出现了除零（比值型因子在 `rank` 取 0 时会给 NaN）。

**Q：能不能只装 pandas、不用 scipy？**
A：不行：`ts_rank`/`rolling_rank` 用 `scipy.stats.rankdata`，中性化对拍也用 scipy。运行时就是 numpy/pandas/scipy 三件套。

**Q：我想改成别的口径（比如 `ddof=1`、`decay_linear` 反向）怎么办？**
A：算子都留了显式参数：`stddev(..., ddof=1)`、`decay_linear(..., order="oldest_first", dense=True)`、
`rank(..., normalization="one_over_n")`、`ts_argmax(..., basis="window_start")`。
**改参数而不是改源码**，这样你的结果仍然可以对着文档解释。

**Q：这些因子在 A 股上有效吗？**
A：本项目**不回答**这个问题（非目标）。仓库里有一份辅助统计（`reports/l6_summary.md`：
平均 IC +0.011~+0.015、两两相关 0.164），但文档里写得很清楚：**统计显著 ≠ 实现正确**，
A 股 ≠ 美股，只作弱参考。

---

## 10. 想深入

* 每个算子的口径与理由：`docs/operators.md`
* 与论文的 101 行偏差清单：`docs/deviations.md` §4（`python tools/conformance_report.py --table`）
* 歧义与「无法判定」清单：`docs/ambiguities.md`
* 六层证据链与状态：`docs/verification.md`
* 官方文档结论 ↔ 原文出处：`docs/lb_evidence.md`
* 复现全部声明：README 的「一页复现」
