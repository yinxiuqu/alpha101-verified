"""alpha101v.adapters — 数据适配层（可选，**不属于运行时依赖**）。

设计文档 §7.1 硬约束：本包**运行时**只依赖 ``numpy / pandas / scipy``。
适配器因此遵循两条纪律：

1. **延迟导入**：第三方驱动（如 ``pymongo``）只在函数体内 import，且本模块**不被
   ``alpha101v/__init__.py`` 导入** ⇒ ``import alpha101v`` 永远不会拉进它们
   （由 ``tests/test_provenance.py::test_runtime_import_is_minimal`` 机械守门）；
2. **不做隐式插值**：缺数据就是 NaN，需要前向填充必须由调用方显式开关并写清理由。

子模块
------
* :mod:`alpha101v.adapters.mongo` —— 本地 MongoDB（``quantaxis``）→ §7.4 面板契约；
* :mod:`alpha101v.adapters.industry` —— 申万 as-of 成员 → **PIT 行业标签面板**
  （DataFrame 形态，正是 :func:`alpha101v.neutralize.ind_neutralize` 支持的逐日口径）。
"""

__all__: list[str] = []
