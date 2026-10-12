#!/usr/bin/env bash
# 取第二独立参照 `alpha101-pipeline`（MIT）到仓库内的独立 venv（gitignored，仅供测试期对拍）。
#
# 为什么独立 venv：它依赖 duckdb，本项目的**运行时依赖只有 numpy/pandas/scipy**
# （由 tests/test_provenance.py 机械守着）。参照只在对拍时用，不能污染运行时依赖。
#
# 合规：只用宽松许可（MIT）；作者/版本/许可分类器记录在下方与
# `tools/second_reference_differential.py` 的 REFERENCE 常量里；GPL 实现一律不用。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.refs/venv-ref"
PY="${PYTHON:-/home/yinxiuqu/anaconda3/envs/qa/bin/python}"
VERSION="0.6.2"

echo "==> 建独立 venv：$VENV"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --disable-pip-version-check "duckdb>=1.0" "alpha101-pipeline==$VERSION"
"$VENV/bin/python" - <<'PY'
import importlib.metadata as md, duckdb
meta = md.metadata("alpha101-pipeline")
lic = [c for c in meta.get_all("Classifier") or [] if "License" in c]
print(f"参照就绪：alpha101-pipeline {md.version('alpha101-pipeline')} | duckdb {duckdb.__version__}")
print(f"许可：{lic}")
print(f"来源：https://pypi.org/project/alpha101-pipeline/")
PY
echo "==> 完成（该目录在 .gitignore 内，不入库）"
