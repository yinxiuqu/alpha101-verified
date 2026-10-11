# L5 golden 快照基线（M5 已建成）

本目录存放 **golden 快照**：固定随机种子的确定性面板上，101 个因子输出的**冻结基线**。
它在 CI 里的作用是**防回归**——pandas/numpy 升级、一次无意的重构、算子默认值被误改，
都会立刻暴露（设计文档 §6.6 / §7.2 的 L5 门槛）。

> ⚠️ **golden 只防回归，不证明正确性**。它回答的是「今天和昨天算得一样吗」；
> 「算得对不对」由 L1（解析期望值 + 权威实现对拍）、L2（规范对照）、L3（vnpy 差分）、L4（不变量）负责。

## 基线内容

| 文件 | 内容 |
|---|---|
| `panel.npz` | 确定性面板（9 个数值字段 + 3 个行业层级标签），供第三方独立复算 |
| `factor_values.npz` | 101 个因子的输出矩阵（float64，NaN 原样保留） |
| `manifest.json` | 面板与逐因子的 sha256、面板参数与种子、**环境版本**（python/numpy/pandas/scipy）、生成命令、判据说明 |

**面板参数**：5 只股票 × **320** 交易日，种子 `20261010`。

> 📌 **对设计文档 §6.6 示例的有意偏离**：§6.6 举例「如 5 只股票 × 250 天」，
> 但 **250 日正是 A101 的最长窗口**（`alpha19`/`alpha39` 的 `Σ returns, 250`、`alpha48` 的 250 日相关），
> 5×250 会让这些因子在基线上**整片 NaN**，等于没冻结。改用 320 天后它们各有 300+ 个有效格
> （`tests/test_golden.py::test_golden_panel_exercises_the_longest_windows` 守着这一点）。

## 判据（`tools/golden_snapshot.py` 与 `tests/test_golden.py` 共用）

1. **NaN 模式必须完全一致**（哪一格有值、哪一格没有，都不许变）——这比数值容差更重要；
2. 数值 `allclose(rtol=1e-9, atol=1e-12)`；
3. 逐因子 sha256 不一致但数值一致 ⇒ 只算「**漂移提示**」（跨 pandas 版本的末位差属正常；
   CI 还跑 pandas 2.1/2.2/2.3 的依赖矩阵，见 `.github/workflows/ci.yml`）。

## 命令

```bash
python tools/golden_snapshot.py --check     # 校验（CI 用；失败即退出码非 0）
python tools/golden_snapshot.py --write     # 重新生成（**只在有意改动算法/口径时**，且必须在 PR 里说明原因）
python -m pytest tests/test_golden.py -q    # 同样的门禁，含覆盖度/确定性/清单完整性检查
```

重新生成基线时，`manifest.json` 里的 `environment` 会更新为当前依赖版本——这正是排查
「数值漂移是依赖升级引起还是实现改动引起」的线索。
