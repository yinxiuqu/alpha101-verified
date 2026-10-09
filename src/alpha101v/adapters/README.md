# alpha101v.adapters — 数据适配层（M2 起）

按设计文档 §7.2 预留：``mongo / parquet / 通用 DataFrame`` 适配器。
**当前为空**：本轮（M0/M1）只交付算子层，不接数据源。

硬约束（设计文档 §7.1「非目标」）：本包**运行时**只依赖 ``numpy / pandas / scipy``。
pymongo / QUANTAXIS / ClickHouse 等一律不得进入运行时依赖；真需要时做成可选 extra，
并在适配器内部延迟导入。
