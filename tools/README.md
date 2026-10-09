# tools/ — 报告与对拍工具（M3/M4 起）

按设计文档 §7.2 预留两个工具，**本轮（M0/M1）未实现**（没有因子可对照，写了也是假代码）：

| 文件 | 里程碑 | 职责 |
|---|---|---|
| `differential.py` | ✅ **算子层已交付**（2026-10-09） | 双实现差分对拍：本库 vs vnpy（MIT，polars DSL）逐点 `allclose(rtol=1e-8)`，并对差异做归因分类（一致 / 口径差异 / 不一致待查），**严禁简单判错**（§6.4）。24 项：18 一致 + 6 归因 + 0 待查 |
| `fetch_vnpy_reference.sh` | ✅ **已交付** | 下载 vnpy 的 `cs_function.py` / `ts_function.py` / `utility.py` / `datasets/alpha_101.py` 到 gitignored 的 `.vnpy-ref/`，逐文件校验 SHA256（**第三方代码不入库**） |
| `conformance_report.py` | M3 | 把论文附录公式逐条解析成算子树，与实现的 AST 逐节点比对，生成《与论文的偏差清单》（101 行：等价/近似/偏离三分类，§6.3） |

运行方式（本机 `qa` 环境已含 polars 1.44，无需新建环境）：

```bash
bash tools/fetch_vnpy_reference.sh          # 取参照（需网络，约 1 秒/文件）
/home/yinxiuqu/anaconda3/envs/qa/bin/python tools/differential.py   # 打印对拍表；有待查项则退出码 1
python -m pytest tests/test_differential.py -q                      # 测试包装（参照缺失时跳过）
```

⚠️ **因子级差分（M4）还有两件前置**（见 `docs/operators.md` §6.3 L3）：
① 需要 `math_function.py`（`less/greater/log/abs/sign/pow1/pow2/quesval…`）；
② `calculate_by_expression` 会 import `ta_function`，而它依赖 **talib**（本机未装 ta-lib）
——需补一个只用于未调用路径的 shim，或在差分时绕过该入口直接调用算子函数。

对拍范围提醒（§4.3.1）：vnpy 只覆盖 **82/101**（缺 alpha56 与 18 个含
``IndNeutralize`` 的行业中性因子），且那 18 个因子在它的测试里被静默摘掉了中性化。
因此差分对拍的范围**仅限这 82 个**，剩余 19 个只能靠「论文规范对照 + 不变量」验证——
这一点必须在 `docs/verification.md` 里如实标注。
