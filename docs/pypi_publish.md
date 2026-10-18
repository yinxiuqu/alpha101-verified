# PyPI 发布步骤（Trusted Publishing，**不需要 token**）

本仓库已配好 [`.github/workflows/publish.yml`](../.github/workflows/publish.yml)：
**在 GitHub 上创建 Release 即自动发布**。唯一需要人工做的是在 PyPI 网页上登记**一次**。

> 这条路线是照 `alphalens-cna` 的既有做法复用的：密钥（OIDC 短期令牌）由 GitHub 与 PyPI
> 之间直接交换，**不经过任何人的手** —— 没有 token 需要保存、拷给谁、或写进任何文件。
> 环境变量里之所以找不到 PyPI token，是因为**从来就没用过 token**。

---

## 一、你需要做的（一次性，约 5 分钟）

1. **注册账号** → <https://pypi.org/account/register/>（免费，邮箱验证即可）。
2. **开启两步验证（2FA）** —— PyPI 强制要求，否则无法发布：
   <https://pypi.org/manage/account/totp-provisioning/>
3. **登记 Trusted Publisher**（项目还没建 ⇒ 用 "Add a **pending** publisher"）：
   <https://pypi.org/manage/account/publishing/>

   | 字段 | 填什么 |
   |---|---|
   | PyPI Project Name | `alpha101v` |
   | Owner | `yinxiuqu` |
   | Repository name | `alpha101-verified` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

   保存即生效。`alpha101v` 这个名字此前已确认在 PyPI 上**未被占用**（404）。

## 二、然后发布（每次发版）

```bash
# 1) 升版本：pyproject.toml 的 version + CHANGELOG.md 加条目 + 同步 __init__ 兜底
#    （tests/test_version.py 会替你核对「pyproject / dist / __version__」三方一致）
git commit -am "release: vX.Y.Z"
git push origin main

# 2) GitHub 网页 → Releases → Draft a new release → 选/建 tag vX.Y.Z → Publish release
#    那一刻 Actions 自动：build（sdist+wheel）→ twine check → 校验 tag 与 pyproject 版本一致 → 上传 PyPI
```

⚠️ **两条硬约束**（工作流里已有门禁）：

* **版本号不可覆盖**：PyPI 上一个版本只能发一次 ⇒ `twine check` 与「tag vs pyproject」自检放在上传**之前**；
* **README 就是 PyPI 长描述** ⇒ README 里的版本字样若改了，也要在**同一次发版**里改掉，
  否则 PyPI 页面要等下一版才刷新。

## 三、发布后自检

```bash
curl -s https://pypi.org/pypi/alpha101v/json | python -c "import json,sys; d=json.load(sys.stdin); print(d['info']['version'], sorted(d['releases']))"
# 或（新环境，装回来的必须是同一个版本）
python -m pip install alpha101v==X.Y.Z && python -c "import alpha101v; print(alpha101v.__version__)"
```

## 四、两个真实踩过的坑（2026-10-18 首次发布时）

1. **`release` 事件用的是「tag 所在提交」里的 workflow 文件** —— `v0.1.2` 的 tag 指向 `6f10899`，
   而 `publish.yml` 是在其后的 `a983acf` 才加入的 ⇒ **发布 Release 时没有触发任何运行** ✗
   （Actions 里该工作流 `total_count = 0`）。
   ⇒ 以后发版：**先确保 `publish.yml` 已在 tag 指的那个提交里**（先推工作流，再打 tag），
   或临时手动触发：Actions → Publish to PyPI → Run workflow（`workflow_dispatch`）。
2. **`workflow_dispatch` 下 `GITHUB_REF_NAME` 是分支名**（`main`），不是 tag ⇒
   若自检脚本无条件拿它当版本号，会以 `test "main" = "0.1.2"` 失败 ✗。
   ⇒ 自检现在**事件无关**：release 事件比 tag，手动触发比「pyproject 版本 vs dist 产物文件名」。
