# 101 个因子在说什么：机械事实 + 经济解读

本文回答「这 101 条公式各自是什么意思」。**两类内容严格分开**：

* **机械事实**：字段、算子、窗口、结构形态 —— 由 `tools/factor_meaning.py` 从公式**逐条提取**，
  可用 `--check` 校验与代码一致（防文档漂移）；
* **经济解读**：我给的**推断**，一律标注「推断」。它可能对也可能错，**不影响任何因子状态** ——
  `verified/partial` 只看六层证据链，不看故事讲得好不好（设计文档 §6.7）。

> ⚠️ 论文（Kakushadze 2016）本身对多数因子**只给公式、不给经济解释**；arXiv 版明确说这些是
> 在 WorldQuant 内部挖掘出来的表达式。所以任何「经济含义」都是**复原性推测**，不是原作者的说法。

## 一、怎么读这 101 条（结构框架）

先看**输入字段**，就能把 101 条粗分成几族：

| 族 | 依赖 | 在算什么 | 典型因子 |
|---|---|---|---|
| **纯价格路径** | 只要 `close`/`open`/`high`/`low` | 位置、极值时点、跳空、趋势与反转的切换 | alpha4/9/10/19/20/101 |
| **量价关系** | 价格 + `volume`（+`adv{d}`） | 价格与成交量的相关/协方差（同向 or 背离） | alpha2/3/6/13/15/16 |
| **波动与形态** | `stddev`、日内区间 | 波动率水平、日内振幅与收盘位置 | alpha1/18/31/37 |
| **成交额/流动性** | `amount`（本库用真成交额）、`adv{d}` | 放量/缩量、相对成交量 | alpha7/11/17/21/25/… |
| **行业中性** | `ind_*`（PIT as-of） | 先做行业中性再排序 | alpha48/56/58/59/…（19 个 `partial`） |

再看**结构形态**（机械事实表里的「结构形态」列）：`截面排序`（rank）决定它是**选股型**信号；
`量价相关`/`波动率`/`线性衰减加权`说明它用什么统计量；`取负`说明它是**反向**信号（反转类居多）。
**一个粗结论**：101 条里绝大多数是**短期反转 + 量价关系**的组合，少数是趋势跟随（如 alpha9/10），
极少数用到财务或行业结构（只有 19 个含 `IndNeutralize`、1 个用市值）。

## 二、机械事实表

<!-- MECH_TABLE:BEGIN（由 tools/factor_meaning.py 生成，勿手改）-->
#### 机械事实表（101 个因子；由 `tools/factor_meaning.py` 从公式逐条提取）

| # | 因子 | 状态 | 输入字段 | 算子 | 窗口(≥2) | 结构形态 | 公式 |
|---|---|---|---|---|---|---|---|
| 1 | `alpha1` | verified | close,returns | ts_argmax,stddev,rank | 2,5,20 | 截面排序、波动率 | `(rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)` |
| 2 | `alpha2` | verified | open,close,volume | delta,correlation,rank | 2,6 | 量价相关、截面排序、日内开收盘差、取负（反向信号） | `(-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))` |
| 3 | `alpha3` | verified | open,volume | correlation,rank | 3,10 | 量价相关、截面排序、取负（反向信号） | `(-1 * correlation(rank(open), rank(volume), 10))` |
| 4 | `alpha4` | verified | low | ts_rank,rank | 4,9 | 截面排序、取负（反向信号） | `(-1 * Ts_Rank(rank(low), 9))` |
| 5 | `alpha5` | verified | open,close,vwap | sum,rank | 5,10 | 截面排序、取负（反向信号） | `(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))` |
| 6 | `alpha6` | verified | open,volume | correlation | 6,10 | 量价相关、取负（反向信号） | `(-1 * correlation(open, volume, 10))` |
| 7 | `alpha7` | verified | close,volume | ts_rank,delta | 7,20,60 | 截面排序、成交额均值、取负（反向信号） | `((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))` |
| 8 | `alpha8` | verified | open,returns | delay,sum,rank | 5,8,10 | 截面排序、取负（反向信号） | `(-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10))))` |
| 9 | `alpha9` | verified | close | ts_min,ts_max,delta | 5,9 | 取负（反向信号） | `((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : (-1 * delta(close, 1))))` |
| 10 | `alpha10` | verified | close | ts_min,ts_max,delta,rank | 4,10 | 截面排序、取负（反向信号） | `rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close, 1) : (-1 * delta(close, 1)))))` |
| 11 | `alpha11` | verified | close,vwap,volume | ts_min,ts_max,delta,rank | 3,11 | 截面排序 | `((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))` |
| 12 | `alpha12` | verified | close,volume | delta | 12 | 取负（反向信号） | `(sign(delta(volume, 1)) * (-1 * delta(close, 1)))` |
| 13 | `alpha13` | verified | close,volume | covariance,rank | 5,13 | 截面排序、取负（反向信号） | `(-1 * rank(covariance(rank(close), rank(volume), 5)))` |
| 14 | `alpha14` | verified | open,volume,returns | delta,correlation,rank | 3,10,14 | 量价相关、截面排序、取负（反向信号） | `((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))` |
| 15 | `alpha15` | verified | high,volume | correlation,sum,rank | 3,15 | 量价相关、截面排序、取负（反向信号） | `(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))` |
| 16 | `alpha16` | verified | high,volume | covariance,rank | 5,16 | 截面排序、取负（反向信号） | `(-1 * rank(covariance(rank(high), rank(volume), 5)))` |
| 17 | `alpha17` | verified | close,volume | ts_rank,delta,rank | 5,10,17,20 | 截面排序、成交额均值、取负（反向信号） | `(((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))` |
| 18 | `alpha18` | verified | open,close | correlation,stddev,rank | 5,10,18 | 量价相关、截面排序、波动率、日内开收盘差、取负（反向信号） | `(-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open, 10))))` |
| 19 | `alpha19` | verified | close,returns | delta,delay,sum,rank | 7,19,250 | 截面排序、取负（反向信号） | `((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250)))))` |
| 20 | `alpha20` | verified | open,high,low,close | delay,rank | 20 | 截面排序、取负（反向信号） | `(((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open - delay(low, 1))))` |
| 21 | `alpha21` | verified | close,volume | sum,stddev | 2,8,20,21 | 波动率、成交额均值、取负（反向信号） | `((((sum(close, 8) / 8) + stddev(close, 8)) < (sum(close, 2) / 2)) ? (-1 * 1) : (((sum(close, 2) / 2) < ((sum(close, 8) / 8) - stddev(close, 8))) ? 1 : (((1 < (volume / adv20)) \|\| ((volume / adv20) == 1)) ? 1 : (-1 * 1))))` |
| 22 | `alpha22` | verified | high,close,volume | delta,correlation,stddev,rank | 5,20,22 | 量价相关、截面排序、波动率、取负（反向信号） | `(-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))` |
| 23 | `alpha23` | verified | high | delta,sum | 2,20,23 | 取负（反向信号） | `(((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)` |
| 24 | `alpha24` | verified | close | ts_min,delta,delay,sum | 3,24,100 | 取负（反向信号） | `((((delta((sum(close, 100) / 100), 100) / delay(close, 100)) < 0.05) \|\| ((delta((sum(close, 100) / 100), 100) / delay(close, 100)) == 0.05)) ? (-1 * (close - ts_min(close, 100))) : (-1 * delta(close, 3)))` |
| 25 | `alpha25` | verified | high,close,vwap,returns | rank | 20,25 | 截面排序、成交额均值、取负（反向信号） | `rank(((((-1 * returns) * adv20) * vwap) * (high - close)))` |
| 26 | `alpha26` | verified | high,volume | ts_max,ts_rank,correlation | 3,5,26 | 量价相关、截面排序、取负（反向信号） | `(-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))` |
| 27 | `alpha27` | verified | vwap,volume | correlation,sum,rank | 2,6,27 | 量价相关、截面排序、取负（反向信号） | `((0.5 < rank((sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0))) ? (-1 * 1) : 1)` |
| 28 | `alpha28` | verified | high,low,close | correlation,scale | 2,5,20,28 | 量价相关、截面缩放、成交额均值 | `scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))` |
| 29 | `alpha29` | verified | close,returns | ts_min,ts_rank,delta,delay,sum,product,min,rank,scale | 2,5,6,29 | 截面排序、截面缩放、取负（反向信号） | `(min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1), 5))))), 2), 1))))), 1), 5) + ts_rank(delay((-1 * returns), 6), 5))` |
| 30 | `alpha30` | verified | close,volume | delay,sum,rank | 2,3,5,20,30 | 截面排序 | `(((1.0 - rank(((sign((close - delay(close, 1))) + sign((delay(close, 1) - delay(close, 2)))) + sign((delay(close, 2) - delay(close, 3)))))) * sum(volume, 5)) / sum(volume, 20))` |
| 31 | `alpha31` | verified | low,close | decay_linear,delta,correlation,rank,scale | 3,10,12,20,31 | 量价相关、线性衰减加权、截面排序、截面缩放、成交额均值、取负（反向信号） | `((rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10)))) + rank((-1 * delta(close, 3)))) + sign(scale(correlation(adv20, low, 12))))` |
| 32 | `alpha32` | verified | close,vwap | delay,correlation,sum,scale | 5,7,20,32,230 | 量价相关、截面缩放 | `(scale(((sum(close, 7) / 7) - close)) + (20 * scale(correlation(vwap, delay(close, 5), 230))))` |
| 33 | `alpha33` | verified | open,close | rank | 33 | 截面排序、取负（反向信号） | `rank((-1 * ((1 - (open / close))^1)))` |
| 34 | `alpha34` | verified | close,returns | delta,stddev,rank | 2,5,34 | 截面排序、波动率 | `rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + (1 - rank(delta(close, 1)))))` |
| 35 | `alpha35` | verified | high,low,close,volume,returns | ts_rank | 16,32,35 | 截面排序 | `((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * (1 - Ts_Rank(returns, 32)))` |
| 36 | `alpha36` | verified | open,close,vwap,volume,returns | ts_rank,delay,correlation,sum,rank | 2.21,5,6,15,20,36,200 | 量价相关、截面排序、日内开收盘差、成交额均值、取负（反向信号） | `(((((2.21 * rank(correlation((close - open), delay(volume, 1), 15))) + (0.7 * rank((open - close)))) + (0.73 * rank(Ts_Rank(delay((-1 * returns), 6), 5)))) + rank(abs(correlation(vwap, adv20, 6)))) + (0.6 * rank((((sum(close, 200) / 200) - open) * (close - open)))))` |
| 37 | `alpha37` | verified | open,close | delay,correlation,rank | 37,200 | 量价相关、截面排序 | `(rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))` |
| 38 | `alpha38` | verified | open,close | ts_rank,rank | 10,38 | 截面排序、取负（反向信号） | `((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))` |
| 39 | `alpha39` | verified | close,volume,returns | decay_linear,delta,sum,rank | 7,9,20,39,250 | 线性衰减加权、截面排序、成交额均值、取负（反向信号） | `((-1 * rank((delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))))) * (1 + rank(sum(returns, 250))))` |
| 40 | `alpha40` | verified | high,volume | correlation,stddev,rank | 10,40 | 量价相关、截面排序、波动率、取负（反向信号） | `((-1 * rank(stddev(high, 10))) * correlation(high, volume, 10))` |
| 41 | `alpha41` | verified | high,low,vwap | — | 41 | — | `(((high * low)^0.5) - vwap)` |
| 42 | `alpha42` | verified | close,vwap | rank | 42 | 截面排序 | `(rank((vwap - close)) / rank((vwap + close)))` |
| 43 | `alpha43` | verified | close,volume | ts_rank,delta | 7,8,20,43 | 截面排序、成交额均值、取负（反向信号） | `(ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, 7)), 8))` |
| 44 | `alpha44` | verified | high,volume | correlation,rank | 5,44 | 量价相关、截面排序、取负（反向信号） | `(-1 * correlation(high, rank(volume), 5))` |
| 45 | `alpha45` | verified | close,volume | delay,correlation,sum,rank | 2,5,20,45 | 量价相关、截面排序、取负（反向信号） | `(-1 * ((rank((sum(delay(close, 5), 20) / 20)) * correlation(close, volume, 2)) * rank(correlation(sum(close, 5), sum(close, 20), 2))))` |
| 46 | `alpha46` | verified | close | delay | 10,20,46 | 取负（反向信号） | `((0.25 < (((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10))) ? (-1 * 1) : (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < 0) ? 1 : ((-1 * 1) * (close - delay(close, 1)))))` |
| 47 | `alpha47` | verified | high,close,vwap,volume | delay,sum,rank | 5,20,47 | 截面排序、成交额均值 | `((((rank((1 / close)) * volume) / adv20) * ((high * rank((high - close))) / (sum(high, 5) / 5))) - rank((vwap - delay(vwap, 5))))` |
| 48 | `alpha48` | partial | close | delta,delay,correlation,sum,indneutralize | 2,48,250 | 量价相关、行业中性 | `(indneutralize(((correlation(delta(close, 1), delta(delay(close, 1), 1), 250) * delta(close, 1)) / close), IndClass.subindustry) / sum(((delta(close, 1) / delay(close, 1))^2), 250))` |
| 49 | `alpha49` | verified | close | delay | 10,20,49 | 取负（反向信号） | `(((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.1)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))` |
| 50 | `alpha50` | verified | vwap,volume | ts_max,correlation,rank | 5,50 | 量价相关、截面排序、取负（反向信号） | `(-1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)), 5))` |
| 51 | `alpha51` | verified | close | delay | 10,20,51 | 取负（反向信号） | `(((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.05)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))` |
| 52 | `alpha52` | verified | low,volume,returns | ts_min,ts_rank,delay,sum,rank | 5,20,52,220,240 | 截面排序、取负（反向信号） | `((((-1 * ts_min(low, 5)) + delay(ts_min(low, 5), 5)) * rank(((sum(returns, 240) - sum(returns, 20)) / 220))) * ts_rank(volume, 5))` |
| 53 | `alpha53` | verified | high,low,close | delta | 9,53 | 取负（反向信号） | `(-1 * delta((((close - low) - (high - close)) / (close - low)), 9))` |
| 54 | `alpha54` | verified | open,high,low,close | — | 5,54 | 取负（反向信号） | `((-1 * ((low - close) * (open^5))) / ((low - high) * (close^5)))` |
| 55 | `alpha55` | verified | high,low,close,volume | ts_min,ts_max,correlation,rank | 6,12,55 | 量价相关、截面排序、取负（反向信号） | `(-1 * correlation(rank(((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12)))), rank(volume), 6))` |
| 56 | `alpha56` | partial | returns,cap | sum,rank | 2,3,10,56 | 截面排序 | `(0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))` |
| 57 | `alpha57` | verified | close,vwap | ts_argmax,decay_linear,rank | 2,30,57 | 线性衰减加权、截面排序 | `(0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2))))` |
| 58 | `alpha58` | partial | vwap,volume | ts_rank,decay_linear,correlation,indneutralize | 3.92795,5.50322,7.89291,58 | 量价相关、线性衰减加权、截面排序、行业中性、取负（反向信号） | `(-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.sector), volume, 3.92795), 7.89291), 5.50322))` |
| 59 | `alpha59` | partial | vwap,volume | ts_rank,decay_linear,correlation,indneutralize | 4.25197,8.19648,16.2289,59 | 量价相关、线性衰减加权、截面排序、行业中性、取负（反向信号） | `(-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(((vwap * 0.728317) + (vwap * (1 - 0.728317))), IndClass.industry), volume, 4.25197), 16.2289), 8.19648))` |
| 60 | `alpha60` | verified | high,low,close,volume | ts_argmax,rank,scale | 2,10,60 | 截面排序、截面缩放 | `(0 - (1 * ((2 * scale(rank(((((close - low) - (high - close)) / (high - low)) * volume)))) - scale(rank(ts_argmax(close, 10))))))` |
| 61 | `alpha61` | verified | vwap | ts_min,correlation,rank | 16.1219,17.9282,61,180 | 量价相关、截面排序、成交额均值 | `(rank((vwap - ts_min(vwap, 16.1219))) < rank(correlation(vwap, adv180, 17.9282)))` |
| 62 | `alpha62` | verified | open,high,low,vwap | correlation,sum,rank | 2,9.91009,20,22.4101,62 | 量价相关、截面排序、成交额均值 | `((rank(correlation(vwap, sum(adv20, 22.4101), 9.91009)) < rank(((rank(open) + rank(open)) < (rank(((high + low) / 2)) + rank(high))))) * -1)` |
| 63 | `alpha63` | partial | open,close,vwap | decay_linear,delta,correlation,sum,rank,indneutralize | 2.25164,8.22237,12.2883,13.557,37.2467,63,180 | 量价相关、线性衰减加权、截面排序、行业中性、成交额均值 | `((rank(decay_linear(delta(IndNeutralize(close, IndClass.industry), 2.25164), 8.22237)) - rank(decay_linear(correlation(((vwap * 0.318108) + (open * (1 - 0.318108))), sum(adv180, 37.2467), 13.557), 12.2883))) * -1)` |
| 64 | `alpha64` | verified | open,high,low,vwap | delta,correlation,sum,rank | 2,3.69741,12.7054,16.6208,64,120 | 量价相关、截面排序、成交额均值 | `((rank(correlation(sum(((open * 0.178404) + (low * (1 - 0.178404))), 12.7054), sum(adv120, 12.7054), 16.6208)) < rank(delta(((((high + low) / 2) * 0.178404) + (vwap * (1 - 0.178404))), 3.69741))) * -1)` |
| 65 | `alpha65` | verified | open,vwap | ts_min,correlation,sum,rank | 6.40374,8.6911,13.635,60,65 | 量价相关、截面排序、成交额均值 | `((rank(correlation(((open * 0.00817205) + (vwap * (1 - 0.00817205))), sum(adv60, 8.6911), 6.40374)) < rank((open - ts_min(open, 13.635)))) * -1)` |
| 66 | `alpha66` | verified | open,high,low,vwap | ts_rank,decay_linear,delta,rank | 2,3.51013,6.72611,7.23052,11.4157,66 | 线性衰减加权、截面排序 | `((rank(decay_linear(delta(vwap, 3.51013), 7.23052)) + Ts_Rank(decay_linear(((((low * 0.96633) + (low * (1 - 0.96633))) - vwap) / (open - ((high + low) / 2))), 11.4157), 6.72611)) * -1)` |
| 67 | `alpha67` | partial | high,vwap | ts_min,correlation,rank,indneutralize | 2.14593,6.02936,20,67 | 量价相关、截面排序、行业中性、成交额均值 | `((rank((high - ts_min(high, 2.14593)))^rank(correlation(IndNeutralize(vwap, IndClass.sector), IndNeutralize(adv20, IndClass.subindustry), 6.02936))) * -1)` |
| 68 | `alpha68` | verified | high,low,close | ts_rank,delta,correlation,rank | 8.91644,13.9333,15,68 | 量价相关、截面排序、成交额均值 | `((Ts_Rank(correlation(rank(high), rank(adv15), 8.91644), 13.9333) < rank(delta(((close * 0.518371) + (low * (1 - 0.518371))), 1.06157))) * -1)` |
| 69 | `alpha69` | partial | close,vwap | ts_max,ts_rank,delta,correlation,rank,indneutralize | 2.72412,4.79344,4.92416,9.0615,20,69 | 量价相关、截面排序、行业中性、成交额均值 | `((rank(ts_max(delta(IndNeutralize(vwap, IndClass.industry), 2.72412), 4.79344))^Ts_Rank(correlation(((close * 0.490655) + (vwap * (1 - 0.490655))), adv20, 4.92416), 9.0615)) * -1)` |
| 70 | `alpha70` | partial | close,vwap | ts_rank,delta,correlation,rank,indneutralize | 17.8256,17.9171,50,70 | 量价相关、截面排序、行业中性、成交额均值 | `((rank(delta(vwap, 1.29456))^Ts_Rank(correlation(IndNeutralize(close, IndClass.industry), adv50, 17.8256), 17.9171)) * -1)` |
| 71 | `alpha71` | verified | open,low,close,vwap | ts_rank,decay_linear,correlation,max,rank | 2,3.43976,4.20501,4.4388,12.0647,15.6948,16.4662,18.0175,71,180 | 量价相关、线性衰减加权、截面排序、成交额均值 | `max(Ts_Rank(decay_linear(correlation(Ts_Rank(close, 3.43976), Ts_Rank(adv180, 12.0647), 18.0175), 4.20501), 15.6948), Ts_Rank(decay_linear((rank(((low + open) - (vwap + vwap)))^2), 16.4662), 4.4388))` |
| 72 | `alpha72` | verified | high,low,vwap,volume | ts_rank,decay_linear,correlation,rank | 2,2.95011,3.72469,6.86671,8.93345,10.1519,18.5188,40,72 | 量价相关、线性衰减加权、截面排序、成交额均值 | `(rank(decay_linear(correlation(((high + low) / 2), adv40, 8.93345), 10.1519)) / rank(decay_linear(correlation(Ts_Rank(vwap, 3.72469), Ts_Rank(volume, 18.5188), 6.86671), 2.95011)))` |
| 73 | `alpha73` | verified | open,low,vwap | ts_rank,decay_linear,delta,max,rank | 2.03608,2.91864,3.33829,4.72775,16.7411,73 | 线性衰减加权、截面排序 | `(max(rank(decay_linear(delta(vwap, 4.72775), 2.91864)), Ts_Rank(decay_linear(((delta(((open * 0.147155) + (low * (1 - 0.147155))), 2.03608) / ((open * 0.147155) + (low * (1 - 0.147155)))) * -1), 3.33829), 16.7411)) * -1)` |
| 74 | `alpha74` | verified | high,close,vwap,volume | correlation,sum,rank | 11.4791,15.1365,30,37.4843,74 | 量价相关、截面排序、成交额均值 | `((rank(correlation(close, sum(adv30, 37.4843), 15.1365)) < rank(correlation(rank(((high * 0.0261661) + (vwap * (1 - 0.0261661)))), rank(volume), 11.4791))) * -1)` |
| 75 | `alpha75` | verified | low,vwap,volume | correlation,rank | 4.24304,12.4413,50,75 | 量价相关、截面排序、成交额均值 | `(rank(correlation(vwap, volume, 4.24304)) < rank(correlation(rank(low), rank(adv50), 12.4413)))` |
| 76 | `alpha76` | partial | low,vwap | ts_rank,decay_linear,delta,correlation,max,rank,indneutralize | 8.14941,11.8259,17.1543,19.383,19.569,76,81 | 量价相关、线性衰减加权、截面排序、行业中性、成交额均值 | `(max(rank(decay_linear(delta(vwap, 1.24383), 11.8259)), Ts_Rank(decay_linear(Ts_Rank(correlation(IndNeutralize(low, IndClass.sector), adv81, 8.14941), 19.569), 17.1543), 19.383)) * -1)` |
| 77 | `alpha77` | verified | high,low,vwap | decay_linear,correlation,min,rank | 2,3.1614,5.64125,20.0451,40,77 | 量价相关、线性衰减加权、截面排序、成交额均值 | `min(rank(decay_linear(((((high + low) / 2) + high) - (vwap + high)), 20.0451)), rank(decay_linear(correlation(((high + low) / 2), adv40, 3.1614), 5.64125)))` |
| 78 | `alpha78` | verified | low,vwap,volume | correlation,sum,rank | 5.77492,6.83313,19.7428,40,78 | 量价相关、截面排序、成交额均值 | `(rank(correlation(sum(((low * 0.352233) + (vwap * (1 - 0.352233))), 19.7428), sum(adv40, 19.7428), 6.83313))^rank(correlation(rank(vwap), rank(volume), 5.77492)))` |
| 79 | `alpha79` | partial | open,close,vwap | ts_rank,delta,correlation,rank,indneutralize | 3.60973,9.18637,14.6644,79,150 | 量价相关、截面排序、行业中性、成交额均值 | `(rank(delta(IndNeutralize(((close * 0.60733) + (open * (1 - 0.60733))), IndClass.sector), 1.23438)) < rank(correlation(Ts_Rank(vwap, 3.60973), Ts_Rank(adv150, 9.18637), 14.6644)))` |
| 80 | `alpha80` | partial | open,high | ts_rank,delta,correlation,rank,indneutralize | 4.04545,5.11456,5.53756,10,80 | 量价相关、截面排序、行业中性、成交额均值 | `((rank(Sign(delta(IndNeutralize(((open * 0.868128) + (high * (1 - 0.868128))), IndClass.industry), 4.04545)))^Ts_Rank(correlation(high, adv10, 5.11456), 5.53756)) * -1)` |
| 81 | `alpha81` | verified | vwap,volume | correlation,sum,product,rank | 4,5.07914,8.47743,10,14.9655,49.6054,81 | 量价相关、截面排序、成交额均值 | `((rank(Log(product(rank((rank(correlation(vwap, sum(adv10, 49.6054), 8.47743))^4)), 14.9655))) < rank(correlation(rank(vwap), rank(volume), 5.07914))) * -1)` |
| 82 | `alpha82` | partial | open,volume | ts_rank,decay_linear,delta,correlation,min,rank,indneutralize | 6.92131,13.4283,14.8717,17.4842,82 | 量价相关、线性衰减加权、截面排序、行业中性 | `(min(rank(decay_linear(delta(open, 1.46063), 14.8717)), Ts_Rank(decay_linear(correlation(IndNeutralize(volume, IndClass.sector), ((open * 0.634196) + (open * (1 - 0.634196))), 17.4842), 6.92131), 13.4283)) * -1)` |
| 83 | `alpha83` | verified | high,low,close,vwap,volume | delay,sum,rank | 2,5,83 | 截面排序 | `((rank(delay(((high - low) / (sum(close, 5) / 5)), 2)) * rank(rank(volume))) / (((high - low) / (sum(close, 5) / 5)) / (vwap - close)))` |
| 84 | `alpha84` | verified | close,vwap | ts_max,ts_rank,delta | 4.96796,15.3217,20.7127,84 | 截面排序 | `SignedPower(Ts_Rank((vwap - ts_max(vwap, 15.3217)), 20.7127), delta(close, 4.96796))` |
| 85 | `alpha85` | verified | high,low,close,volume | ts_rank,correlation,rank | 2,3.70596,7.11408,9.61331,10.1595,30,85 | 量价相关、截面排序、成交额均值 | `(rank(correlation(((high * 0.876703) + (close * (1 - 0.876703))), adv30, 9.61331))^rank(correlation(Ts_Rank(((high + low) / 2), 3.70596), Ts_Rank(volume, 10.1595), 7.11408)))` |
| 86 | `alpha86` | verified | open,close,vwap | ts_rank,correlation,sum,rank | 6.00049,14.7444,20,20.4195,86 | 量价相关、截面排序、成交额均值 | `((Ts_Rank(correlation(close, sum(adv20, 14.7444), 6.00049), 20.4195) < rank(((open + close) - (vwap + open)))) * -1)` |
| 87 | `alpha87` | partial | close,vwap | ts_rank,decay_linear,delta,correlation,max,rank,indneutralize | 2.65461,4.89768,13.4132,14.4535,81,87 | 量价相关、线性衰减加权、截面排序、行业中性、成交额均值 | `(max(rank(decay_linear(delta(((close * 0.369701) + (vwap * (1 - 0.369701))), 1.91233), 2.65461)), Ts_Rank(decay_linear(abs(correlation(IndNeutralize(adv81, IndClass.industry), close, 13.4132)), 4.89768), 14.4535)) * -1)` |
| 88 | `alpha88` | verified | open,high,low,close | ts_rank,decay_linear,correlation,min,rank | 2.61957,6.65053,8.01266,8.06882,8.44728,20.6966,60,88 | 量价相关、线性衰减加权、截面排序、成交额均值 | `min(rank(decay_linear(((rank(open) + rank(low)) - (rank(high) + rank(close))), 8.06882)), Ts_Rank(decay_linear(correlation(Ts_Rank(close, 8.44728), Ts_Rank(adv60, 20.6966), 8.01266), 6.65053), 2.61957))` |
| 89 | `alpha89` | partial | low,vwap | ts_rank,decay_linear,delta,correlation,indneutralize | 3.48158,3.79744,5.51607,6.94279,10,10.1466,15.3012,89 | 量价相关、线性衰减加权、截面排序、行业中性、成交额均值 | `(Ts_Rank(decay_linear(correlation(((low * 0.967285) + (low * (1 - 0.967285))), adv10, 6.94279), 5.51607), 3.79744) - Ts_Rank(decay_linear(delta(IndNeutralize(vwap, IndClass.industry), 3.48158), 10.1466), 15.3012))` |
| 90 | `alpha90` | partial | low,close | ts_max,ts_rank,correlation,rank,indneutralize | 3.21856,4.66719,5.38375,40,90 | 量价相关、截面排序、行业中性、成交额均值 | `((rank((close - ts_max(close, 4.66719)))^Ts_Rank(correlation(IndNeutralize(adv40, IndClass.subindustry), low, 5.38375), 3.21856)) * -1)` |
| 91 | `alpha91` | partial | close,vwap,volume | ts_rank,decay_linear,correlation,rank,indneutralize | 2.6809,3.83219,4.01303,4.8667,9.74928,16.398,30,91 | 量价相关、线性衰减加权、截面排序、行业中性、成交额均值 | `((Ts_Rank(decay_linear(decay_linear(correlation(IndNeutralize(close, IndClass.industry), volume, 9.74928), 16.398), 3.83219), 4.8667) - rank(decay_linear(correlation(vwap, adv30, 4.01303), 2.6809))) * -1)` |
| 92 | `alpha92` | verified | open,high,low,close | ts_rank,decay_linear,correlation,min,rank | 2,6.80584,6.94024,7.58555,14.7221,18.8683,30,92 | 量价相关、线性衰减加权、截面排序、成交额均值 | `min(Ts_Rank(decay_linear(((((high + low) / 2) + close) < (low + open)), 14.7221), 18.8683), Ts_Rank(decay_linear(correlation(rank(low), rank(adv30), 7.58555), 6.94024), 6.80584))` |
| 93 | `alpha93` | partial | close,vwap | ts_rank,decay_linear,delta,correlation,rank,indneutralize | 2.77377,7.54455,16.2664,17.4193,19.848,81,93 | 量价相关、线性衰减加权、截面排序、行业中性、成交额均值 | `(Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.industry), adv81, 17.4193), 19.848), 7.54455) / rank(decay_linear(delta(((close * 0.524434) + (vwap * (1 - 0.524434))), 2.77377), 16.2664)))` |
| 94 | `alpha94` | verified | vwap | ts_min,ts_rank,correlation,rank | 2.70756,4.02992,11.5783,18.0926,19.6462,60,94 | 量价相关、截面排序、成交额均值 | `((rank((vwap - ts_min(vwap, 11.5783)))^Ts_Rank(correlation(Ts_Rank(vwap, 19.6462), Ts_Rank(adv60, 4.02992), 18.0926), 2.70756)) * -1)` |
| 95 | `alpha95` | verified | open,high,low | ts_min,ts_rank,correlation,sum,rank | 2,5,11.7584,12.4105,12.8742,19.1351,40,95 | 量价相关、截面排序、成交额均值 | `(rank((open - ts_min(open, 12.4105))) < Ts_Rank((rank(correlation(sum(((high + low) / 2), 19.1351), sum(adv40, 19.1351), 12.8742))^5), 11.7584))` |
| 96 | `alpha96` | verified | close,vwap,volume | ts_argmax,ts_rank,decay_linear,correlation,max,rank | 3.65459,3.83878,4.13242,4.16783,7.45404,8.38151,12.6556,13.4143,14.0365,60,96 | 量价相关、线性衰减加权、截面排序、成交额均值 | `(max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume), 3.83878), 4.16783), 8.38151), Ts_Rank(decay_linear(Ts_ArgMax(correlation(Ts_Rank(close, 7.45404), Ts_Rank(adv60, 4.13242), 3.65459), 12.6556), 14.0365), 13.4143)) * -1)` |
| 97 | `alpha97` | partial | low,vwap | ts_rank,decay_linear,delta,correlation,rank,indneutralize | 3.3705,4.97547,6.71659,7.87871,15.7152,17.255,18.5925,20.4523,60,97 | 量价相关、线性衰减加权、截面排序、行业中性、成交额均值 | `((rank(decay_linear(delta(IndNeutralize(((low * 0.721001) + (vwap * (1 - 0.721001))), IndClass.industry), 3.3705), 20.4523)) - Ts_Rank(decay_linear(Ts_Rank(correlation(Ts_Rank(low, 7.87871), Ts_Rank(adv60, 17.255), 4.97547), 18.5925), 15.7152), 6.71659)) * -1)` |
| 98 | `alpha98` | verified | open,vwap | ts_argmin,ts_rank,decay_linear,correlation,sum,rank | 4.58418,5,6.95668,7.18088,8.07206,8.62571,15,20.8187,26.4719,98 | 量价相关、线性衰减加权、截面排序、成交额均值 | `(rank(decay_linear(correlation(vwap, sum(adv5, 26.4719), 4.58418), 7.18088)) - rank(decay_linear(Ts_Rank(Ts_ArgMin(correlation(rank(open), rank(adv15), 20.8187), 8.62571), 6.95668), 8.07206)))` |
| 99 | `alpha99` | verified | high,low,volume | correlation,sum,rank | 2,6.28259,8.8136,19.8975,60,99 | 量价相关、截面排序、成交额均值 | `((rank(correlation(sum(((high + low) / 2), 19.8975), sum(adv60, 19.8975), 8.8136)) < rank(correlation(low, volume, 6.28259))) * -1)` |
| 100 | `alpha100` | partial | high,low,close,volume | ts_argmin,correlation,rank,scale,indneutralize | 5,20,30,100 | 量价相关、截面排序、行业中性、截面缩放、成交额均值 | `(0 - (1 * (((1.5 * scale(indneutralize(indneutralize(rank(((((close - low) - (high - close)) / (high - low)) * volume)), IndClass.subindustry), IndClass.subindustry))) - scale(indneutralize((correlation(close, rank(adv20), 5) - rank(ts_argmin(close, 30))), IndClass.subindustry))) * (volume / adv20))))` |
| 101 | `alpha101` | verified | open,high,low,close | — | 101 | 日内开收盘差 | `((close - open) / ((high - low) + .001))` |
<!-- MECH_TABLE:END -->

## 三、逐条解读（分批，第一批：alpha1–alpha20）

标注约定：**机械**＝从公式直接可读出；**推断**＝经济/统计含义的推测。

### alpha1
`rank(ts_argmax(signedpower(returns<0 ? stddev(returns,20) : close, 2), 5)) - 0.5`
* **机械**：昨日跌 → 用 20 日波动率的平方；昨日涨 → 用收盘价的平方；取近 5 日内最大值的**位置**，再截面排序。
* **推断**：一个「状态切换 + 路径」信号 —— 下跌日用波动率定位、上涨日用价格定位，
  本质上是在问「谁最近 5 天里最晚（或最早）进入极端状态」。属**路径依赖型反转**特征。

### alpha2
`-correlation(rank(delta(log(volume),2)), rank((close-open)/open), 6)`
* **机械**：成交量对数 2 日变化的秩 与 日内涨跌幅的秩，做 6 日滚动相关，取负。
* **推断**：**量增但日内不涨**（背离）时取正值 ⇒ 是「量价背离反转」。同类里属于较稳的日内量价结构。

### alpha3
`-correlation(rank(open), rank(volume), 10)`
* **机械**：开盘价秩与成交量秩的 10 日相关，取负。
* **推断**：**高开放量**是反向信号（人多的地方不去）。与 alpha2 同族，但用开盘价、窗口更长。

### alpha4
`-ts_rank(rank(low), 9)`
* **机械**：最低价做截面秩，再取 9 日时序秩，取负。
* **推断**：**低位买入**（近 9 日越靠低位越买）——最纯粹的短期反转因子之一，只用价格、无成交量。

### alpha5
`rank(open - sum(vwap,10)/10) * (-1 * abs(rank(close - vwap)))`
* **机械**：开盘相对 10 日均价的偏离（正向） × 收盘相对均价的绝对偏离（负向）。
* **推断**：要求「**开盘低于均价（负偏离）** 且 **收盘贴近均价（偏离小）**」——即日内被压回均价的形态，
  典型的**均值回复**结构。注意 vwap 在本库是**真成交额加权**价（不是近似）。

### alpha6
`-correlation(open, volume, 10)`
* **机械**：原始开盘价与成交量的 10 日相关，取负。
* **推断**：与 alpha3 同义，但**不做 rank** ⇒ 对极端值更敏感（少数巨量日会主导）。

### alpha7
`(adv20 < volume) ? (-1*ts_rank(abs(delta(close,7)),60)*sign(delta(close,7))) : -1`
* **机械**：放量日（量 > 20 日均量）取 7 日价格变化的幅度在 60 日内的秩、乘以方向；缩量日恒为 −1。
* **推断**：**放量确认**型动量 —— 放量上涨给正、放量下跌给负（经秩缩放）；缩量日一律看空。
  这是少数**带条件分支**的因子，也是少数**顺势**（而非反转）的。

### alpha8
`-rank(sum(open,5) * sum(returns,5))`
* **机械**：5 日开盘价之和 × 5 日收益之和，截面排序取负。
* **推断**：短期「价量同向」给反向：开盘持续走高且收益为正 ⇒ 卖出信号。属**短期反转**。

### alpha9
`(0 < ts_min(delta(close,1),5)) ? delta(close,1) : ((ts_max(delta(close,1),5) < 0) ? delta(close,1) : -delta(close,1))`
* **机械**：连续 5 日上涨 → 顺势（用当日涨跌）；连续 5 日下跌 → 也顺势；否则（震荡）→ 反向。
* **推断**：**趋势/震荡的自适应切换**：有明确趋势时跟随，无趋势时反转。论文里少见的状态机结构。

### alpha10
`rank((0 < ts_min(delta(close,1),4)) ? delta(close,1) : ((ts_max(delta(close,1),4) < 0) ? delta(close,1) : -delta(close,1)))`
* **机械**：alpha9 的 4 日版，外加截面排序。
* **推断**：同上；排序后变成「选股」用法（alpha9 是原始值，更适合做时序择时）。

### alpha11
`(rank(ts_max(vwap-close,3)) + rank(ts_min(vwap-close,3))) * rank(delta(volume,3))`
* **机械**：近 3 日 (vwap − close) 的最大值与最小值各自排序后相加，再乘 3 日成交量变化的秩。
* **推断**：**均价压力 + 放量**的组合：既能捕捉「均价高于收盘」（卖方压力）也能捕捉「均价低于收盘」（买方压力），
  相当于看**偏离的幅度而非方向**，再要求成交量变化配合。

### alpha12
`sign(delta(volume,1)) * (-1 * delta(close,1))`
* **机械**：量增取正、量减取负；乘上「当日涨跌的反向」。
* **推断**：最简版的**量价配合反转**：放量上涨 → 看跌；缩量上涨 → 看涨。无窗口、对噪声最敏感。

### alpha13
`-rank(covariance(rank(close), rank(volume), 5))`
* **机械**：收盘秩与量秩的 5 日协方差，截面排序取负。
* **推断**：与 alpha3/6 同族（量价关系），但用**协方差**且先做截面秩 ⇒ 更强调「同步性」而非水平。

### alpha14
`(-rank(delta(returns,3))) * correlation(open, volume, 10)`
* **机械**：3 日收益变化的反向排序 × 开盘-量相关。
* **推断**：把「收益减速」与「高开放量」两个反向信号相乘，放大两者的共同表现（乘积型因子会放大极端值）。

### alpha15
`-sum(rank(correlation(rank(high), rank(volume), 3)), 3)`
* **机械**：高价秩与量秩的 3 日相关，排序后在 3 日上求和，取负。
* **推断**：**高位放量看空**。用 `high` 而非 `close` ⇒ 更贴「冲高」的语义。

### alpha16
`-rank(covariance(rank(high), rank(volume), 5))`
* **机械**：alpha15 的协方差版 + 截面排序。
* **推断**：同族；协方差对方向更敏感，秩排序再做一次截面标准化。

### alpha17
`(-1*rank(ts_rank(close,10))) * rank(delta(delta(close,1),1)) * rank(ts_rank(volume/adv20,5))`
* **机械**：收盘的 10 日时序秩（反向） × 价格的**二阶差分**（加速度） × 相对成交量的 5 日时序秩。
* **推断**：**三因子乘积**：低位（反转）+ 加速（动量）+ 放量（确认）。乘积结构让它只在三者同时满足时才显著。

### alpha18
`-rank(((stddev(abs(close-open),5) + (close-open)) + correlation(close,open,10)))`
* **机械**：日内绝对振幅的 5 日波动 + 日内涨跌 + 收盘-开盘 10 日相关，三者相加后取负并排序。
* **推断**：**复合反转**：日内振幅大、日内收阳、开收同向 ⇒ 看跌。属于「形态越强越反向」。

### alpha19
`(-1*sign((close - delay(close,7)) + delta(close,7))) * (1 + rank((1 + sum(returns,250))))`
* **机械**：7 日价格变化方向取负 × （1 + 250 日累计收益的截面秩）。
* **推断**：**中期反转 + 长期动量**的乘积：长期赢家（250 日收益高）里挑近期回调的。
  这是少数用到 **250 日**（约一年）长窗口的因子；也是本库需要「足够长历史」的因子之一。

### alpha20
`(-1*rank(open - delay(high,1))) * rank(open - delay(close,1)) * rank(open - delay(low,1))`
* **机械**：今日开盘相对**昨日高/收/低**的三个跳空幅度，各自排序后相乘，整体取负。
* **推断**：**跳空缺口反转**：高开越多（相对昨日高点）越看跌。三个排序相乘 ⇒ 要求三个缺口方向一致才显著。

---

---

### alpha21
`((sum(close,8)/8 + stddev(close,8)) < sum(close,2)/2) ? -1 : (((sum(close,2)/2) < (sum(close,8)/8 - stddev(close,8))) ? 1 : …)`
* **机械**：把「8 日均价 ± 8 日波动」当作通道上下轨，与「2 日均价」比较后输出 −1 / +1 / 其他。
* **推断**：**布林带式的突破状态机** —— 短均线冲出长期通道上轨给一个方向、跌出下轨给另一个方向。属趋势跟随。

### alpha22
`-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20)))`
* **机械**：最高价与成交量的 5 日相关，取它的 5 日**变化量**；乘以 20 日波动率的截面秩；整体取负。
* **推断**：看的是量价关系的**边际恶化**（相关性的动量），且只在波动大的股票上放大 ⇒「量价背离 + 高波动」看空。

### alpha23
`((sum(high,20)/20) < high) ? (-1 * delta(high, 2)) : 0`
* **机械**：今日最高价高于 20 日均高时，取 2 日高点变化的**反向**；否则输出 0。
* **推断**：**创 20 日新高后的反转**（冲高回落看空），且只在创新高时触发 ⇒ 稀疏信号。

### alpha24
`((delta(sum(close,100)/100, 100) / delay(close,100)) < 0.05) || (… == 0.05) ? … : …`
* **机械**：100 日均价的 100 日变化率（相对 100 日前收盘）与 0.05 比较后分支。
* **推断**：**长期趋势平坦**（百日均线一年涨幅不足 5%）时的专门处理 —— 少数需要 ≥200 天历史的因子之一。

### alpha25
`rank((((-1 * returns) * adv20) * vwap) * (high - close))`
* **机械**：负收益 × 20 日均成交额 × 成交均价 × (最高价 − 收盘) 的截面排序。
* **推断**：四个因子相乘，只有「**下跌 + 成交活跃 + 收盘离当日高点远**」同时成立才高分 ⇒ 超跌反弹，
  且用成交额加权强调「有真实资金参与」。本库的 `adv20` 用**真成交额**（不是 volume×close 近似）。

### alpha26
`-1 * ts_max(correlation(ts_rank(volume,5), ts_rank(high,5), 5), 3)`
* **机械**：量的 5 日时序秩与最高价的 5 日时序秩，做 5 日相关；取近 3 日的最大值；整体取负。
* **推断**：**放量冲高**这种极值状态看空（取最大值 ⇒ 只看最极端的那一天）。

### alpha27
`(0.5 < rank(sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0)) ? -1 : 1`
* **机械**：量秩与 vwap 秩的 6 日相关在 2 日上累加取均值，截面排序是否过半 ⇒ 输出 −1 或 +1。
* **推断**：**量价同向（放量且均价上行）看空**，反之看多。输出只有 ±1 ⇒ 信号粒度极粗，属于「方向性押注」。

### alpha28
`scale(correlation(adv20, low, 5) + (high + low)/2 - close)`
* **机械**：20 日均成交额与最低价的 5 日相关，加上「日内中点 − 收盘」，再截面缩放。
* **推断**：**尾盘走弱（收盘低于日内中点）+ 成交额与低位同向** ⇒ 均值回复买点。用真成交额 ✓。

### alpha29
`min(product(rank(rank(scale(log(sum(ts_min(rank(rank(-1 * rank(delta(close - 1, 5))))), 2), 1))))), 1), 5) + ts_rank(delay(-1 * returns, …), …)`
* **机械**：多层嵌套（rank→rank→scale→log→sum→ts_min→product→min）+ 一个滞后收益的时序秩。
* **推断**：全库**嵌套最深**的因子之一，本质是「价格变化的低阶统计」再叠加短期反转；
  层层单调变换不改变**排序**（rank/scale 单调），所以经济含义仍落在「反转 + 极端值抑制」上。
  ⚠️ 我不对每一层做硬解 —— 那会变成编故事。

### alpha30
`(1 - rank(sign(delta(close,1)) + sign(delay(close,1) - delay(close,2)) + sign(delay(close,2) - delay(close,3)))) …`
* **机械**：近 3 个「日涨跌符号」求和后取秩，再用 1 减去它。
* **推断**：**连涨天数越多分越低** ⇒ 连续同向后的反转（三天全涨 ⇒ 值最小）。

### alpha31
`rank(rank(rank(decay_linear(-1 * rank(rank(delta(close, 10))), 10)))) + rank(-1 * delta(close, 3)) + sign(scale(correlation(adv20, low, …)))`
* **机械**：三段相加 —— ①10 日价格变化反向的「三层秩 + 线性衰减」；②3 日变化反向的秩；③成交额-最低价相关的符号。
* **推断**：**多信号投票**（中期反转 + 短期反转 + 量价方向），三段量纲被 rank/scale 统一后才可相加。

### alpha32
`scale(sum(close,7)/7 - close) + 20 * scale(correlation(vwap, delay(close,5), 230))`
* **机械**：7 日均价与收盘之差（截面缩放）+ 20 倍(vwap 与 5 日前收盘的 **230 日**相关，截面缩放)。
* **推断**：**短期均值回复 + 长期量价同步**的加权组合；230 日是全库最长窗口之一，
  20 倍权重说明它把长期量价关系当主项。

### alpha33
`rank(-1 * ((1 - (open / close))^1))`
* **机械**：`1 − open/close` 取负后截面排序。
* **推断**：等价于**按 open/close 排序** ⇒ **日内收阳（收 > 开）看空**。全库最短视的一条：只看一天。

### alpha34
`rank((1 - rank(stddev(returns, 2) / stddev(returns, 5))) + (1 - rank(delta(close, 1))))`
* **机械**：「2 日波动 / 5 日波动」的反向秩 + 「当日涨跌」的反向秩，两者相加再排序。
* **推断**：**波动收缩 + 短期反转** —— 短波相对长波下降（波动被压缩）是看多信号，
  这是波动率类里金融直觉最清楚的一个（与低波动异象同源）。

### alpha35
`Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16)) * (1 - Ts_Rank(returns, 32))`
* **机械**：量的 32 日时序秩 × (1 − 日内「上影/振幅」的 16 日时序秩) × (1 − 收益的 32 日时序秩)。
* **推断**：**放量 + 日内没冲高 + 近期没涨** 三者同时满足才得高分；乘积结构 ⇒ 只在三者一致时输出显著。

### alpha36
`2.21 * rank(correlation((close - open), delay(volume, 1), 15)) + 0.7 * rank(open - close) + 0.73 * rank(Ts_Rank(delay(-1 * returns, …)))`
* **机械**：至少三项**带非平凡系数**（2.21 / 0.7 / 0.73）的加权合成：量价（滞后成交量）、日内反转、滞后收益。
* **推断**：全库**唯一带小数权重**的因子之一 —— 权重是原作者的拟合结果，经济上可读作
  「**日内涨跌 与 昨日成交量** 的关系」为主项、另两项为辅。

### alpha37
`rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close))`
* **机械**：**前一日**日内涨跌与收盘的 200 日相关（排序）+ 当日日内涨跌（排序）。
* **推断**：**长期量价结构 + 当日反转**。用 200 日窗口 ⇒ 接近「这只股票的日内涨跌是否长期被收盘价跟随」的刻画。

### alpha38
`-1 * rank(Ts_Rank(close, 10)) * rank((close / open))`
* **机械**：收盘的 10 日时序秩（负向）× 当日收开比的秩。
* **推断**：**低位 + 日内下跌** 双条件看多 ⇒ 双重反转，结构简洁（与 alpha33/4 同族）。

### alpha39
`-1 * rank(delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))) * (1 + rank(sum(returns, 250)))`
* **机械**：7 日价格变化 × (1 − 相对成交量的 9 日线性衰减秩)，取负并排序，再乘 (1 + 250 日累计收益秩)。
* **推断**：**中期反转 × 长期动量**（与 alpha19 同族结构），但用「相对成交量」来调制反转的强度。

### alpha40
`-1 * rank(stddev(high, 10)) * correlation(high, volume, 10)`
* **机械**：最高价 10 日波动率的秩（负向）× 最高价与成交量的 10 日相关。
* **推断**：**高波动看空 × 高位放量看空**，乘积 ⇒ 只在两者同向时显著（避免噪声相乘）。

---

### 待续（分批）

已完成 **alpha1–alpha40**（两批）。后续按每批 ~20 个继续（41–60、61–80、81–101），
保持同样的标注纪律：**机械可读的归机械，推断的标推断，绝不把故事写成事实**；
对于嵌套很深的因子（如 alpha29）只给结构判断，不逐层硬解。
