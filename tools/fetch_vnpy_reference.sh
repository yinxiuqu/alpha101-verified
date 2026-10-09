#!/usr/bin/env bash
# 抓取 vnpy（MIT）算子层源码作为**测试期差分对拍参照**。
#
# 设计文档 §5.3 / §6.4：vnpy 是 MIT 许可，可自由参照/对拍。本脚本**只下载**，
# 不把第三方代码提交进仓库（目标目录 .vnpy-ref/ 已 gitignore）。
#
# 用法：bash tools/fetch_vnpy_reference.sh   （需要网络；GitHub raw 实测约 1 秒/文件）
# 校验：下载后逐文件比对 SHA256，任一不符即失败退出。
set -euo pipefail

DEST="${1:-.vnpy-ref}"
BASE="https://raw.githubusercontent.com/vnpy/vnpy/master/vnpy/alpha/dataset"

mkdir -p "$DEST/vnpy/alpha/dataset/datasets"
: > "$DEST/vnpy/__init__.py"
: > "$DEST/vnpy/alpha/__init__.py"
: > "$DEST/vnpy/alpha/dataset/__init__.py"
: > "$DEST/vnpy/alpha/dataset/datasets/__init__.py"

# 逐行：相对路径 期望 SHA256（2026-10-09 抓取时记录）
FILES="
cs_function.py 7cb7781ef5eac2e11c7abc632b139a13d5807c24b8093ad0e8f5fca22496a112
ts_function.py 88443ae16d4065406cdc7b6e034d72eceb1d06736ab97508d3c82a50d43ad18f
utility.py 49369cf93bd9eec0cb7f8f64df73a68d0161c5a7a569d6dda16b31ddab3be3e5
datasets/alpha_101.py cfca4ab7d5450b71a1c5af3639675948f0a6393a5ff6903dcee46480b942999d
"

echo "$FILES" | while read -r rel expected; do
  [ -z "${rel:-}" ] && continue
  url="$BASE/$rel"
  out="$DEST/vnpy/alpha/dataset/$rel"
  curl -sSf --max-time 60 -o "$out" "$url"
  actual="$(sha256sum "$out" | cut -d' ' -f1)"
  if [ "$actual" != "$expected" ]; then
    echo "SHA256 不符：$rel（期望 $expected，实得 $actual）—— 上游已改动，请复核差分结论" >&2
    exit 1
  fi
  echo "ok $rel"
done

cat <<'NOTE'

参照已就绪（未入库，见 .gitignore）。
注意：vnpy 的 ta_function.py 依赖 talib（本机未装），因此差分只覆盖
cs_function / ts_function；ta_* 算子不属于论文 101 因子的算子集合，不影响结论。
另：math_function.py（less/greater/log/abs/sign/pow1/pow2/quesval…）为 M4 因子级差分
（走 calculate_by_expression）所需，本轮算子层差分用不到。
NOTE
