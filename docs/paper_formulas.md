# 论文公式入库：101 Formulaic Alphas 规范文本（paper_formulas.md）

| 项 | 内容 |
|---|---|
| 文档版本 | **v0.1**（2026-10-09，M2 前置：规范入库） |
| 定位 | **L-A 级规范文本**（设计文档 §2.4 的规范权威度排序：论文公式表 = 因子结构的唯一权威） |
| 用途 | ① L2 规范对照的基准 ② clean-room 留痕（每个因子记录「来源＝论文公式 Y」，§4.5 纪律 2）③ 算子口径的论文级依据 |
| 上游 | Kakushadze, *101 Formulaic Alphas*, arXiv:1601.00991 **v3**（2016-03-18），Wilmott Magazine 2016(84):72–80 |
| 范围 | 只摘录**规范性内容**（101 条公式、算子与函数定义、输入数据定义），不含论文正文与附录 B 免责声明 |

## 1. 来源、获取方法与可复现性

```bash
curl -sS -o paper.pdf https://arxiv.org/pdf/1601.00991      # arXiv v3，244,416 bytes
pdftotext -layout paper.pdf paper.txt                       # 861 行
```

| 项 | 值 |
|---|---|
| 抓取日期 | 2026-10-09 |
| PDF SHA256 | `1f9c21afe32dcb3ee77b31548acdaea00451fbfa1c0ee10c907867bcc736fce9` |
| 抽取文本行数 | 861 |
| 许可 | arXiv non-exclusive distribution license（**非** GPL/CC） |
| PDF 是否进仓库 | **否**。只收录数学公式与算子定义（事实性规范内容）；PDF 与正文抽取文本均不入库 |

获取路径说明：`web_fetch` 不支持 `application/pdf`（返回 `unsupported content type`），
`ar5iv` HTML 版实测重定向回 `arxiv.org` 且无可用正文，因此采用「curl 下载 PDF + 本地 `pdftotext -layout` 抽取」。

## 2. 保真校验（机械可复验）

| 校验项 | 结果 |
|---|---|
| `Alpha#k` 条数 | **101**（编号 1–101 连续，无缺失） |
| **每式括号平衡** | **101/101 全部平衡，0 条不平衡** ← 转写保真的主证据 |
| 跨行公式条数 | **69** 条（页面换行所致，按「续行直到括号平衡」合并） |
| 页码残留 | 已按 `^\s*\d{1,3}\s*$` 过滤（例如第 15 页的孤立 `15`） |
| 非整数窗口 | 共 **229 次**，涉及 **40 个因子**（见 §7.1） |

**已知抽取注意点**（不影响公式，但影响引用）：

1. **论文自身子节编号前后不一致**：引言称「公式在 A.1、算子定义在 A.2、输入数据在 A.3」，
   而正文标题实际是 `A.1. Formulaic Expressions for Alphas` → `A.1. Functions and Operators` → `A.2. Input Data`。
   **引用时请用标题名而非编号**（本文件与 `docs/operators.md` 均按标题引用）。
2. 论文声明表达式**大小写不敏感**（"All expressions are case insensitive"）：`Ts_Rank` ≡ `ts_rank`。
3. 论文用 `^` 表示幂（如 `(high * low)^0.5`），不是位运算。

## 3. 算子与函数定义（论文原文，逐字）

> 出处：Appendix A，子节「Functions and Operators」（论文正文误编为 A.1，引言称 A.2）。

```
(Below “{ }” stands for a placeholder. All expressions are case insensitive.)

abs(x), log(x), sign(x) = standard definitions; same for the operators “+”, “-”, “*”, “/”, “>”, “<”,
“==”, “||”, “x ? y : z”

rank(x) = cross-sectional rank

delay(x, d) = value of x d days ago

correlation(x, y, d) = time-serial correlation of x and y for the past d days

covariance(x, y, d) = time-serial covariance of x and y for the past d days

scale(x, a) = rescaled x such that sum(abs(x)) = a (the default is a = 1)

delta(x, d) = today’s value of x minus the value of x d days ago

signedpower(x, a) = x^a

decay_linear(x, d) = weighted moving average over the past d days with linearly decaying
weights d, d – 1, …, 1 (rescaled to sum up to 1)

indneutralize(x, g) = x cross-sectionally neutralized against groups g (subindustries, industries,
sectors, etc.), i.e., x is cross-sectionally demeaned within each group g

ts_{O}(x, d) = operator O applied across the time-series for the past d days; non-integer number
of days d is converted to floor(d)

ts_min(x, d) = time-series min over the past d days


ts_max(x, d) = time-series max over the past d days

ts_argmax(x, d) = which day ts_max(x, d) occurred on

ts_argmin(x, d) = which day ts_min(x, d) occurred on

ts_rank(x, d) = time-series rank in the past d days

min(x, d) = ts_min(x, d)

max(x, d) = ts_max(x, d)

sum(x, d) = time-series sum over the past d days

product(x, d) = time-series product over the past d days

stddev(x, d) = moving time-series standard deviation over the past d days
```

### 3.1 与本库 20 个算子的映射（M2/M3 转写依据）

| 论文记号 | 本库算子 | 论文定义要点 | 与本库口径的关系 |
|---|---|---|---|
| `rank(x)` | `rank` | cross-sectional rank | ✅ 截面一致（axis=1）；**pct vs 序号论文未规定**（本库默认 pct） |
| `delay(x, d)` | `delay` | d 天前的值 | ✅ 一致 |
| `delta(x, d)` | `delta` | 今日值减 d 天前 | ✅ 一致 |
| `correlation(x, y, d)` | `correlation` | 过去 d 天**时序**相关 | ✅ 一致；零方差行为论文未规定（本库 NaN） |
| `covariance(x, y, d)` | `covariance` | 过去 d 天时序协方差 | ✅ 一致；ddof 论文未规定（本库默认 1） |
| `scale(x, a)` | `scale` | `sum(abs(x)) = a`，默认 a=1 | ⚠️ **轴向论文未写**（本库 axis=1 每日）→ §7.4 |
| `decay_linear(x, d)` | `decay_linear` | 线性衰减权重 `d, d–1, …, 1`，归一 | ⚠️ **列举顺序未明确**（本库取末值权重最大）→ §7.3 |
| `indneutralize(x, g)` | `ind_neutralize` | **组内截面去均值** | ✅ **L-A 级确认** → §7.5 |
| `ts_min` / `ts_max` | `ts_min` / `ts_max` | 过去 d 天时序最小/最大 | ✅ 一致 |
| `min(x, d)` / `max(x, d)` | `ts_min` / `ts_max` | = ts_min / ts_max | ✅ 别名（论文中两种写法都出现） |
| `ts_argmax` / `ts_argmin` | `ts_argmax` / `ts_argmin` | "which day … occurred on" | ⚠️ **基准与方向未定义** → §7.2 |
| `ts_rank(x, d)` | `ts_rank` | 过去 d 天时序 rank | ⚠️ 归一化论文未规定（本库默认 pct=True） |
| `sum(x, d)` | `ts_sum` | 过去 d 天求和 | ✅ 别名 |
| `product(x, d)` | `product` | 过去 d 天连乘 | ✅ 一致 |
| `stddev(x, d)` | `stddev` | 过去 d 天滚动标准差 | ✅ 一致；ddof 论文未规定（本库默认 1） |
| `ts_{O}(x, d)` | — | 时序算子通式；**非整数 d 取下整 floor(d)** | ❗ **本库当前报错** → §7.1（40 个因子吃紧） |
| `abs(x)` `log(x)` `sign(x)` | — | 标准定义 | ❗ 不在 20 算子内 → §7.6（需逐元素层） |
| `signedpower(x, a)` | — | `x^a` | ❗ 不在 20 算子内；语义有歧义 → §7.6 |
| `adv{d}` | 字段（非算子） | **平均每日「美元成交额」** | ❗ 数据口径决策 → §7.7（45 个因子） |

## 4. 输入数据定义（论文原文，逐字）

```
returns = daily close-to-close returns

open, close, high, low, volume = standard definitions for daily price and volume data

vwap = daily volume-weighted average price

cap = market cap

adv{d} = average daily dollar volume for the past d days

IndClass = a generic placeholder for a binary industry classification such as GICS, BICS, NAICS,
SIC, etc., in indneutralize(x, IndClass.level), where level = sector, industry, subindustry, etc.
Multiple IndClass in the same alpha need not correspond to the same industry classification.
```

📌 对 A 股落地的两个直接推论（M2 起用，属**数据口径**而非算子口径）：

* `adv{d}` = **美元成交额**（dollar volume）→ A 股对应 `amount`（元），即 `adv20 = sma(amount, 20)`。
  **用 `volume`（手/股）替代属于「近似」**（设计文档 §6.3 的分类），会在 45 个因子上造成系统性差异，必须逐条登记。
* `returns` = daily close-to-close returns → 与 `panel.returns_from_close`（前复权口径）一致。

## 5. 101 条公式（逐字；本清单即 L2 规范对照基准）

> 大小写不敏感；`.001` 即 `0.001`；跨行公式已合并为单行；括号平衡校验见 §2。
> `IndClass.subindustry` / `IndClass.industry` 等是行业分类层级占位符。

```
Alpha#1: (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)
Alpha#2: (-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))
Alpha#3: (-1 * correlation(rank(open), rank(volume), 10))
Alpha#4: (-1 * Ts_Rank(rank(low), 9))
Alpha#5: (rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))
Alpha#6: (-1 * correlation(open, volume, 10))
Alpha#7: ((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))
Alpha#8: (-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10))))
Alpha#9: ((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : (-1 * delta(close, 1))))
Alpha#10: rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close, 1) : (-1 * delta(close, 1)))))
Alpha#11: ((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))
Alpha#12: (sign(delta(volume, 1)) * (-1 * delta(close, 1)))
Alpha#13: (-1 * rank(covariance(rank(close), rank(volume), 5)))
Alpha#14: ((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))
Alpha#15: (-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))
Alpha#16: (-1 * rank(covariance(rank(high), rank(volume), 5)))
Alpha#17: (((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))
Alpha#18: (-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open, 10))))
Alpha#19: ((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250)))))
Alpha#20: (((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open - delay(low, 1))))
Alpha#21: ((((sum(close, 8) / 8) + stddev(close, 8)) < (sum(close, 2) / 2)) ? (-1 * 1) : (((sum(close, 2) / 2) < ((sum(close, 8) / 8) - stddev(close, 8))) ? 1 : (((1 < (volume / adv20)) || ((volume / adv20) == 1)) ? 1 : (-1 * 1))))
Alpha#22: (-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))
Alpha#23: (((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)
Alpha#24: ((((delta((sum(close, 100) / 100), 100) / delay(close, 100)) < 0.05) || ((delta((sum(close, 100) / 100), 100) / delay(close, 100)) == 0.05)) ? (-1 * (close - ts_min(close, 100))) : (-1 * delta(close, 3)))
Alpha#25: rank(((((-1 * returns) * adv20) * vwap) * (high - close)))
Alpha#26: (-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))
Alpha#27: ((0.5 < rank((sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0))) ? (-1 * 1) : 1)
Alpha#28: scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))
Alpha#29: (min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1), 5))))), 2), 1))))), 1), 5) + ts_rank(delay((-1 * returns), 6), 5))
Alpha#30: (((1.0 - rank(((sign((close - delay(close, 1))) + sign((delay(close, 1) - delay(close, 2)))) + sign((delay(close, 2) - delay(close, 3)))))) * sum(volume, 5)) / sum(volume, 20))
Alpha#31: ((rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10)))) + rank((-1 * delta(close, 3)))) + sign(scale(correlation(adv20, low, 12))))
Alpha#32: (scale(((sum(close, 7) / 7) - close)) + (20 * scale(correlation(vwap, delay(close, 5), 230))))
Alpha#33: rank((-1 * ((1 - (open / close))^1)))
Alpha#34: rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + (1 - rank(delta(close, 1)))))
Alpha#35: ((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * (1 - Ts_Rank(returns, 32)))
Alpha#36: (((((2.21 * rank(correlation((close - open), delay(volume, 1), 15))) + (0.7 * rank((open - close)))) + (0.73 * rank(Ts_Rank(delay((-1 * returns), 6), 5)))) + rank(abs(correlation(vwap, adv20, 6)))) + (0.6 * rank((((sum(close, 200) / 200) - open) * (close - open)))))
Alpha#37: (rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))
Alpha#38: ((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))
Alpha#39: ((-1 * rank((delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))))) * (1 + rank(sum(returns, 250))))
Alpha#40: ((-1 * rank(stddev(high, 10))) * correlation(high, volume, 10))
Alpha#41: (((high * low)^0.5) - vwap)
Alpha#42: (rank((vwap - close)) / rank((vwap + close)))
Alpha#43: (ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, 7)), 8))
Alpha#44: (-1 * correlation(high, rank(volume), 5))
Alpha#45: (-1 * ((rank((sum(delay(close, 5), 20) / 20)) * correlation(close, volume, 2)) * rank(correlation(sum(close, 5), sum(close, 20), 2))))
Alpha#46: ((0.25 < (((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10))) ? (-1 * 1) : (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < 0) ? 1 : ((-1 * 1) * (close - delay(close, 1)))))
Alpha#47: ((((rank((1 / close)) * volume) / adv20) * ((high * rank((high - close))) / (sum(high, 5) / 5))) - rank((vwap - delay(vwap, 5))))
Alpha#48: (indneutralize(((correlation(delta(close, 1), delta(delay(close, 1), 1), 250) * delta(close, 1)) / close), IndClass.subindustry) / sum(((delta(close, 1) / delay(close, 1))^2), 250))
Alpha#49: (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.1)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))
Alpha#50: (-1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)), 5))
Alpha#51: (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.05)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))
Alpha#52: ((((-1 * ts_min(low, 5)) + delay(ts_min(low, 5), 5)) * rank(((sum(returns, 240) - sum(returns, 20)) / 220))) * ts_rank(volume, 5))
Alpha#53: (-1 * delta((((close - low) - (high - close)) / (close - low)), 9))
Alpha#54: ((-1 * ((low - close) * (open^5))) / ((low - high) * (close^5)))
Alpha#55: (-1 * correlation(rank(((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12)))), rank(volume), 6))
Alpha#56: (0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))
Alpha#57: (0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2))))
Alpha#58: (-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.sector), volume, 3.92795), 7.89291), 5.50322))
Alpha#59: (-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(((vwap * 0.728317) + (vwap * (1 - 0.728317))), IndClass.industry), volume, 4.25197), 16.2289), 8.19648))
Alpha#60: (0 - (1 * ((2 * scale(rank(((((close - low) - (high - close)) / (high - low)) * volume)))) - scale(rank(ts_argmax(close, 10))))))
Alpha#61: (rank((vwap - ts_min(vwap, 16.1219))) < rank(correlation(vwap, adv180, 17.9282)))
Alpha#62: ((rank(correlation(vwap, sum(adv20, 22.4101), 9.91009)) < rank(((rank(open) + rank(open)) < (rank(((high + low) / 2)) + rank(high))))) * -1)
Alpha#63: ((rank(decay_linear(delta(IndNeutralize(close, IndClass.industry), 2.25164), 8.22237)) - rank(decay_linear(correlation(((vwap * 0.318108) + (open * (1 - 0.318108))), sum(adv180, 37.2467), 13.557), 12.2883))) * -1)
Alpha#64: ((rank(correlation(sum(((open * 0.178404) + (low * (1 - 0.178404))), 12.7054), sum(adv120, 12.7054), 16.6208)) < rank(delta(((((high + low) / 2) * 0.178404) + (vwap * (1 - 0.178404))), 3.69741))) * -1)
Alpha#65: ((rank(correlation(((open * 0.00817205) + (vwap * (1 - 0.00817205))), sum(adv60, 8.6911), 6.40374)) < rank((open - ts_min(open, 13.635)))) * -1)
Alpha#66: ((rank(decay_linear(delta(vwap, 3.51013), 7.23052)) + Ts_Rank(decay_linear(((((low * 0.96633) + (low * (1 - 0.96633))) - vwap) / (open - ((high + low) / 2))), 11.4157), 6.72611)) * -1)
Alpha#67: ((rank((high - ts_min(high, 2.14593)))^rank(correlation(IndNeutralize(vwap, IndClass.sector), IndNeutralize(adv20, IndClass.subindustry), 6.02936))) * -1)
Alpha#68: ((Ts_Rank(correlation(rank(high), rank(adv15), 8.91644), 13.9333) < rank(delta(((close * 0.518371) + (low * (1 - 0.518371))), 1.06157))) * -1)
Alpha#69: ((rank(ts_max(delta(IndNeutralize(vwap, IndClass.industry), 2.72412), 4.79344))^Ts_Rank(correlation(((close * 0.490655) + (vwap * (1 - 0.490655))), adv20, 4.92416), 9.0615)) * -1)
Alpha#70: ((rank(delta(vwap, 1.29456))^Ts_Rank(correlation(IndNeutralize(close, IndClass.industry), adv50, 17.8256), 17.9171)) * -1)
Alpha#71: max(Ts_Rank(decay_linear(correlation(Ts_Rank(close, 3.43976), Ts_Rank(adv180, 12.0647), 18.0175), 4.20501), 15.6948), Ts_Rank(decay_linear((rank(((low + open) - (vwap + vwap)))^2), 16.4662), 4.4388))
Alpha#72: (rank(decay_linear(correlation(((high + low) / 2), adv40, 8.93345), 10.1519)) / rank(decay_linear(correlation(Ts_Rank(vwap, 3.72469), Ts_Rank(volume, 18.5188), 6.86671), 2.95011)))
Alpha#73: (max(rank(decay_linear(delta(vwap, 4.72775), 2.91864)), Ts_Rank(decay_linear(((delta(((open * 0.147155) + (low * (1 - 0.147155))), 2.03608) / ((open * 0.147155) + (low * (1 - 0.147155)))) * -1), 3.33829), 16.7411)) * -1)
Alpha#74: ((rank(correlation(close, sum(adv30, 37.4843), 15.1365)) < rank(correlation(rank(((high * 0.0261661) + (vwap * (1 - 0.0261661)))), rank(volume), 11.4791))) * -1)
Alpha#75: (rank(correlation(vwap, volume, 4.24304)) < rank(correlation(rank(low), rank(adv50), 12.4413)))
Alpha#76: (max(rank(decay_linear(delta(vwap, 1.24383), 11.8259)), Ts_Rank(decay_linear(Ts_Rank(correlation(IndNeutralize(low, IndClass.sector), adv81, 8.14941), 19.569), 17.1543), 19.383)) * -1)
Alpha#77: min(rank(decay_linear(((((high + low) / 2) + high) - (vwap + high)), 20.0451)), rank(decay_linear(correlation(((high + low) / 2), adv40, 3.1614), 5.64125)))
Alpha#78: (rank(correlation(sum(((low * 0.352233) + (vwap * (1 - 0.352233))), 19.7428), sum(adv40, 19.7428), 6.83313))^rank(correlation(rank(vwap), rank(volume), 5.77492)))
Alpha#79: (rank(delta(IndNeutralize(((close * 0.60733) + (open * (1 - 0.60733))), IndClass.sector), 1.23438)) < rank(correlation(Ts_Rank(vwap, 3.60973), Ts_Rank(adv150, 9.18637), 14.6644)))
Alpha#80: ((rank(Sign(delta(IndNeutralize(((open * 0.868128) + (high * (1 - 0.868128))), IndClass.industry), 4.04545)))^Ts_Rank(correlation(high, adv10, 5.11456), 5.53756)) * -1)
Alpha#81: ((rank(Log(product(rank((rank(correlation(vwap, sum(adv10, 49.6054), 8.47743))^4)), 14.9655))) < rank(correlation(rank(vwap), rank(volume), 5.07914))) * -1)
Alpha#82: (min(rank(decay_linear(delta(open, 1.46063), 14.8717)), Ts_Rank(decay_linear(correlation(IndNeutralize(volume, IndClass.sector), ((open * 0.634196) + (open * (1 - 0.634196))), 17.4842), 6.92131), 13.4283)) * -1)
Alpha#83: ((rank(delay(((high - low) / (sum(close, 5) / 5)), 2)) * rank(rank(volume))) / (((high - low) / (sum(close, 5) / 5)) / (vwap - close)))
Alpha#84: SignedPower(Ts_Rank((vwap - ts_max(vwap, 15.3217)), 20.7127), delta(close, 4.96796))
Alpha#85: (rank(correlation(((high * 0.876703) + (close * (1 - 0.876703))), adv30, 9.61331))^rank(correlation(Ts_Rank(((high + low) / 2), 3.70596), Ts_Rank(volume, 10.1595), 7.11408)))
Alpha#86: ((Ts_Rank(correlation(close, sum(adv20, 14.7444), 6.00049), 20.4195) < rank(((open + close) - (vwap + open)))) * -1)
Alpha#87: (max(rank(decay_linear(delta(((close * 0.369701) + (vwap * (1 - 0.369701))), 1.91233), 2.65461)), Ts_Rank(decay_linear(abs(correlation(IndNeutralize(adv81, IndClass.industry), close, 13.4132)), 4.89768), 14.4535)) * -1)
Alpha#88: min(rank(decay_linear(((rank(open) + rank(low)) - (rank(high) + rank(close))), 8.06882)), Ts_Rank(decay_linear(correlation(Ts_Rank(close, 8.44728), Ts_Rank(adv60, 20.6966), 8.01266), 6.65053), 2.61957))
Alpha#89: (Ts_Rank(decay_linear(correlation(((low * 0.967285) + (low * (1 - 0.967285))), adv10, 6.94279), 5.51607), 3.79744) - Ts_Rank(decay_linear(delta(IndNeutralize(vwap, IndClass.industry), 3.48158), 10.1466), 15.3012))
Alpha#90: ((rank((close - ts_max(close, 4.66719)))^Ts_Rank(correlation(IndNeutralize(adv40, IndClass.subindustry), low, 5.38375), 3.21856)) * -1)
Alpha#91: ((Ts_Rank(decay_linear(decay_linear(correlation(IndNeutralize(close, IndClass.industry), volume, 9.74928), 16.398), 3.83219), 4.8667) - rank(decay_linear(correlation(vwap, adv30, 4.01303), 2.6809))) * -1)
Alpha#92: min(Ts_Rank(decay_linear(((((high + low) / 2) + close) < (low + open)), 14.7221), 18.8683), Ts_Rank(decay_linear(correlation(rank(low), rank(adv30), 7.58555), 6.94024), 6.80584))
Alpha#93: (Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.industry), adv81, 17.4193), 19.848), 7.54455) / rank(decay_linear(delta(((close * 0.524434) + (vwap * (1 - 0.524434))), 2.77377), 16.2664)))
Alpha#94: ((rank((vwap - ts_min(vwap, 11.5783)))^Ts_Rank(correlation(Ts_Rank(vwap, 19.6462), Ts_Rank(adv60, 4.02992), 18.0926), 2.70756)) * -1)
Alpha#95: (rank((open - ts_min(open, 12.4105))) < Ts_Rank((rank(correlation(sum(((high + low) / 2), 19.1351), sum(adv40, 19.1351), 12.8742))^5), 11.7584))
Alpha#96: (max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume), 3.83878), 4.16783), 8.38151), Ts_Rank(decay_linear(Ts_ArgMax(correlation(Ts_Rank(close, 7.45404), Ts_Rank(adv60, 4.13242), 3.65459), 12.6556), 14.0365), 13.4143)) * -1)
Alpha#97: ((rank(decay_linear(delta(IndNeutralize(((low * 0.721001) + (vwap * (1 - 0.721001))), IndClass.industry), 3.3705), 20.4523)) - Ts_Rank(decay_linear(Ts_Rank(correlation(Ts_Rank(low, 7.87871), Ts_Rank(adv60, 17.255), 4.97547), 18.5925), 15.7152), 6.71659)) * -1)
Alpha#98: (rank(decay_linear(correlation(vwap, sum(adv5, 26.4719), 4.58418), 7.18088)) - rank(decay_linear(Ts_Rank(Ts_ArgMin(correlation(rank(open), rank(adv15), 20.8187), 8.62571), 6.95668), 8.07206)))
Alpha#99: ((rank(correlation(sum(((high + low) / 2), 19.8975), sum(adv60, 19.8975), 8.8136)) < rank(correlation(low, volume, 6.28259))) * -1)
Alpha#100: (0 - (1 * (((1.5 * scale(indneutralize(indneutralize(rank(((((close - low) - (high - close)) / (high - low)) * volume)), IndClass.subindustry), IndClass.subindustry))) - scale(indneutralize((correlation(close, rank(adv20), 5) - rank(ts_argmin(close, 30))), IndClass.subindustry))) * (volume / adv20))))
Alpha#101: ((close - open) / ((high - low) + .001))
```

## 6. 五个试点因子（M2 计划）的核对结论

| 因子 | 论文原文（逐字） | 依赖算子 | 依赖字段 | 备注 |
|---|---|---|---|---|
| `alpha101` | `((close - open) / ((high - low) + .001))` | 无（纯算术） | `close, open, high, low` | 可手算，最适合打通 pipeline |
| `alpha4` | `(-1 * Ts_Rank(rank(low), 9))` | `rank` → `ts_rank` | `low` | `ts_rank` 输出直接就是因子值（见 §6.1） |
| `alpha5` | `(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))` | `rank`, `sum` | `open, vwap, close` | 压测 vwap 单位口径 `amount/(volume×100)` |
| `alpha41` | `(((high * low)^0.5) - vwap)` | 无（算术 + `^0.5`） | `high, low, vwap` | 纯截面；验证幂运算与单位 |
| `alpha56` | `(0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))` | `rank`, `sum` | `returns, cap` | **vnpy 唯一因缺 `cap` 未实现的因子**（设计文档 §4.3.1）→ 补齐缺口的第一块证据 |

📌 **落地状态（2026-10-09，M2 完成）**：上表 5 个试点因子**已全部实现**并通过验证
（`src/alpha101v/factors.py`，状态一律 `partial`）；其中 `alpha5` 依赖逐元素 `abs`，
是本项目 `elemwise` 层的首个消费者，`alpha56` 因 vnpy 缺 `cap` 而**无第三方可差分**。

### 6.1 `alpha4` 的一个有用推论（口径差异的影响面分析）

`alpha4 = -1 * ts_rank(rank(low), 9)`：`ts_rank` 的输出**直接就是因子值**。
本库 `pct=True` 给 `rankdata/d`，`pct=False` 给序号 `rankdata`，两者相差**全局常数 `1/d`**（此处 d=9）。
该缩放对当日所有股票相同 ⇒ **截面排序与 IC 完全不变**；只有进入多因子加权、
中性化或与量纲相关算子复合时才会分叉。
→ 结论：这类因子上 pct 口径差异**不必判错**，但必须记录（设计文档 §6.4「严禁简单判错」）。

## 7. 由论文原文新发现/确认的口径问题（附影响面计数）

> 全部计数由 §5 的公式文本机械统计得出，可用同一份文本复算。

### 7.1 ❗非整数窗口：`floor(d)` 规则吃紧 **40 个因子**

论文（§3 通式）：*"non-integer number of days d is converted to floor(d)"*。
而论文确实**大量使用非整数窗口**（最多 8 位小数，共 229 次），集中在 58–99 号（该段做了混淆处理）：

```
涉及因子（40 个）：[58, 59, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99]
示例 Alpha#63: Ts_Rank(decay_linear(correlation(Ts_Rank(close, 2.25164), ...), 8.22237), 37.2467)
```

**影响**：本库 `_check_window` 当前对非整数 `window` 抛 `TypeError`
（`tests/test_operators.py::test_a27` 断言此行为），**这会让 40 个因子无法转写**。
**建议动作**：改为 `window = floor(d)`——必须用 **floor 而非四舍五入**（`3.65459` 取 3，取整会得 4，结果不同）；
floor 后仍 `< 1` 的报错；同步更新 `operators.md` §4.4 与 `test_a27`。
（严格说 floor 规则挂在 `ts_{O}` 通式下，本库把它推广到所有「天数参数」
——`correlation/covariance/delta/delay/decay_linear/sum/product/min/max/stddev`——属**合理推断**，一并记录。）

### 7.2 ❗`ts_argmax`/`ts_argmin` 的「which day」基准未定义：**6 个因子**

论文只写 *"which day ts_max(x, d) occurred on"*，**未定义基准与方向**。
两种主流读法本库均已实现（`basis` 参数），但二者**不是平移关系而是序反转**：

```
days_ago = window − window_start_1based
```

因此对 `rank(Ts_ArgMax(...))` 这类用法（**Alpha#1** 正是如此），两种口径给出**镜像排序**，
在 `- 0.5` 之后**因子整体变号**——这是会改变信号方向的量级，不是数值噪声。

* 使用者：`ts_argmax` → [1, 57, 60, 96]；`ts_argmin` → [98, 100]
* 本库现状：默认 `basis="window_start"`（自窗口起点 1-based），可选 `"days_ago"`（今天=0）
* **未取到的决定性证据**：BRAIN 官方算子文档（L-B，设计文档 §2.3 待办 #1）。
  本次实测 `https://platform.worldquantbrain.com/learn/operators` **只返回登录态空壳**（正文仅一个词 `index`）。
* **建议动作**：M3 转写这 6 个因子前必须定案。最便宜的定案途径：① 可登录者在 BRAIN 文档页
  取 `ts_arg_max` / `ts_arg_min` 定义原文；② 提前做 vnpy 差分（M4 任务提前）。

### 7.3 ⚠️`decay_linear` 权重列举顺序未明确：**22 个因子**

论文：*"weighted moving average over the past d days with linearly decaying weights d, d – 1, …, 1 (rescaled to sum up to 1)"*。
「过去 d 天」的**枚举方向**未写死：按时间正序（最早→最新）读则最早权重最大；按由近及远读则最新权重最大。

* 本库取「**末值（最新）权重最大**」，权重 `1..d` 归一（`operators.md` §4.1）。依据：
  ①算子名 `decay` 的语义是「权重随年龄衰减」；②与设计文档 §8.1 的期望值 `14/6` 一致；
  ③反向读法会得到「越老权重越大」，与 `decay` 命名自相矛盾。
* **影响面最大的一条**：22 个因子使用 `decay_linear`（编号与设计文档 §3.2 完全一致）。
  若读法有误即为**系统性**错误。
* **建议动作**：M4 差分时**专门核对权重方向**（vnpy `ts_decay_linear`），差分脚本预留方向开关。
  本库已用 `test_a17`（解析值）与 `test_a18`（逐窗口 vs `np.average`）钉死当前方向。

### 7.4 ⚠️`scale` 轴向论文未写：**6 个因子（9 处调用）**

论文只写 `sum(abs(x)) = a`，未说沿哪一维、是否逐日。本库取 **axis=1（每日截面）**，依据：
①`rank` 明确写 cross-sectional，同一算子系统内截面语义应自洽；②「每日 Σ|x| = a」是唯一与面板长度无关的读法；
③设计文档 §8.2 亦按逐日断言（并以此抓出原始实现按列求和的缺陷 3）。
**保留为已决策的 L-A 歧义**：取到 BRAIN 文档后复核（其 `scale` 带 booksize 语义）。

### 7.5 ✅`indneutralize` 语义获得 L-A 级确认（口径升级）

论文逐字：*"x cross-sectionally neutralized against groups g …, i.e., **x is cross-sectionally demeaned within each group g**"*。

这**直接确认**本库 `ind_neutralize` 的实现（逐日组内去均值 ≡ 仅含行业哑变量、无截距的 OLS 残差），
把 `docs/operators.md` §4.3.1 的推导从「数学等价（L-C）」升级为「**论文明确定义（L-A）**」。
使用者编号见 §8，与设计文档 §3.2 完全一致。
残余的因子层歧义只剩「用哪个 IndClass 层级」——论文明确说同一 alpha 里的多个 IndClass
**不必属于同一套分类体系**，故必须按因子逐个确定（M3）。

### 7.6 ❗缺一个逐元素函数层：影响 **15 个因子**

论文使用、而本库 20 算子未覆盖的调用：

| 函数 | 论文定义 | 使用因子 | 说明 |
|---|---|---|---|
| `abs` | 标准定义 | [5, 7, 18, 36, 87] | 无歧义 |
| `log` | 标准定义 | [2, 29, 81] | 自然对数；负值/零的输入行为需显式规定 |
| `sign` | 标准定义 | [7, 12, 19, 30, 31, 80] | `sign(0)` 取 0 |
| `signedpower` | **`x^a`** | [1, 84] | ⚠️ 名字暗示「保号幂」`sign(x)·abs(x)^a`，论文只写 `x^a`；负底数 + 非整数指数时二者不同（Alpha#1/#84 中 a=2，无差异），保留为歧义 |

**结论**：设计文档 §7.3 的「20 个算子」是**算子层**的正确清单（一元函数不属于算子层），
但因子层（M2）**必须**同时交付逐元素层（`abs/log/sign/signedpower`，以及逐元素 `min/max`），
否则这 15 个因子无法转写。建议落在 `src/alpha101v/elemwise.py`，并在 `operators.md` 登记为「因子层依赖」。

### 7.7 ❗`adv{d}` = 平均每日**美元成交额**：影响 **45 个因子**

论文逐字：*"adv{d} = average daily **dollar volume** for the past d days"*。
45 个因子使用 `adv5 / adv15 / adv20 / adv30 / adv60 / adv120 / adv180` 等。
→ A 股面板应取 `amount`（元）：`adv20 = sma(amount, 20)`。
用 `volume`（手/股）替代是**近似**（设计文档 §6.3 举的正是这个例子），必须在 `deviations.md` 逐因子登记。

## 8. 与设计文档 §3.2 依赖表的交叉验证（独立确认）

用 §5 的文本机械统计「使用某依赖项的因子个数」，与设计文档 §3.2 对照：

| 依赖项 | 论文实测因子数 | 设计文档 §3.2 | 因子编号是否逐一相同 | 结论 |
|---|---|---|---|---|
| `indneutralize`（需 `ind`） | 18 | 18 | **完全相同** | ✅ 一致 |
| `decay_linear` | 22 | 22 | **完全相同** | ✅ 一致 |
| `returns` | 12 | 12 | **完全相同** | ✅ 一致 |
| `scale` | 6 | 6 | **完全相同** | ✅ 一致 |
| `cap` | 1 | 1（`alpha56`） | **完全相同** | ✅ 一致 |

**意义**：独立证实了设计文档的依赖面分析，从而支持其「vnpy 缺的 18 个中性化因子 = 本库最硬差异化」的判断
（设计文档 §4.3.1 的「巧合也是铁证」）。同时给出一个可复用方法：
**任何因子层面的返工风险，都可以先用这份文本预估影响面。**

## 9. 使用边界与待办

**使用边界**：本文件只收录论文的**规范性数学内容**（公式、算子定义、字段定义），不收录论文正文与附录 B。
论文按 arXiv non-exclusive 许可发布；公式与算法思想本身不受版权保护（与设计文档 §4.5 的 clean-room 逻辑一致）。
原始 PDF 与全文抽取文本**不入库**。

| # | 待办 | 阻塞什么 | 获取途径 |
|---|---|---|---|
| 1 | BRAIN 官方算子文档（L-B）：`ts_arg_max`/`ts_arg_min` 基准、`ts_decay_linear` 权重方向、`ts_rank`/`rank` 归一化、`scale` 轴向 | §7.2（6 因子）、§7.3（22 因子）、§7.4（6 因子） | `platform.worldquantbrain.com/learn/operators` **需登录**（本次只返回空壳） |
| 2 | `signedpower` 是否保号 | Alpha#1 / #84（a=2 时无差异；转写需显式决定） | BRAIN 文档或 vnpy 算子实现 |
| 3 | vnpy 4.x 的 `ts_decay_linear` 权重方向与 `ts_rank` 归一化 | M4 差分；提前做可同时解 §7.2/§7.3 | 独立环境安装 vnpy 4.x + polars |

## 10. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-09 | 首版：arXiv v3 的 101/101 条公式逐字入库（0 条括号不平衡）、算子与字段定义逐字、5 个试点公式核对、7 项口径问题（含影响面计数）、与设计文档 §3.2 的 5 项交叉验证全部一致 |
