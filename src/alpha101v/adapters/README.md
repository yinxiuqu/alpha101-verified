# alpha101v.adapters — 数据适配层（可选，不属于运行时依赖）

设计文档 §7.1 硬约束：本包**运行时**只依赖 ``numpy / pandas / scipy``。
因此适配器遵循两条纪律：**延迟导入**第三方驱动（pymongo 只在函数体内 import，且本目录
**不被包根导入**），以及**不做隐式插值**（缺数据即 NaN，前向填充必须由调用方显式开启）。

| 文件 | 职责 |
|---|---|
| `mongo.py` | 本地 MongoDB（库 `quantaxis`）：`stock_day`(`vol`→`volume`，手；`amount`，元) + `stock_daily_basic`(`total_mv`, 万元) → §7.4 面板（含 `vwap = amount/(vol*100)`、`returns`） |
| `industry.py` | 申万 as-of 成员 parquet → **PIT 行业标签面板**（逐日 ``in_date/out_date`` 判定，非固定快照） |

用法：

```bash
pip install 'alpha101v[mongo]'        # 或 pip install pymongo
python tools/real_panel_smoke.py      # 真实 A 股端到端冒烟（退出码即证据）
python -m pytest tests/test_adapters_real_data.py -q
```

实测（2026-10-09）：359 交易日 × 120 只，面板契约通过、`vwap ∈ [low,high]` 自洽率 99.86%、
行业覆盖 98.0%、5 个试点因子零 ±inf、`ind_neutralize` 逐日行业内残差和 3.4e-15。
⚠️ 已知限制：**价格未复权**（复权信息在 `stock_xdxr`），见 `docs/verification.md` §1.3。
