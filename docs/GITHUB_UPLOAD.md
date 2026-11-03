# GitHub 上传指引

请上传本轮生成的干净源码文件夹 SmartMoneyAITrader，不要上传正在运行的主工程文件夹或任何 backups 备份。压缩包是便携副本；要在 GitHub 浏览和继续开发代码，应上传解压后的源码文件。

## 推荐：GitHub Desktop

1. 安装并登录 [GitHub Desktop](https://desktop.github.com/download/)。
2. 将源码 ZIP 解压到一个新目录，例如 D:\GitHub\SmartMoneyAITrader。确认目录内直接有 README.md、terminal、frontend、SOURCE_MANIFEST.json 和 .gitignore。
3. 打开 Desktop，选择 File → Add Local Repository，选中这个源码目录。如果提示不是 Git 仓库，点击界面中的 create a repository here，在该目录创建本地仓库，不要重新选择主工程。若已经有目标 GitHub 仓库，先克隆到新的空目录，再把干净源码复制到克隆目录；不要删除 .git 或强制覆盖远程历史。
4. 在 Changes 栏核对文件。应有 Python、React 源码、数据档案和构建产物；不应出现 runtime、credentials.dpapi、.env、数据库、.venv、node_modules 或本机报告。
5. 填写提交说明，例如 Move 24h challenge into strategy templates。点击 Commit to main（界面分支名可能不同）。这是本地保存。
6. 点击 Publish repository，仓库名可用 SmartMoneyAITrader。保持勾选 **Keep this code private**，再点击发布。此操作才会上传至你的 GitHub 账户。
7. 在 GitHub 页面确认仓库有 Private 标识，根目录文件结构正确。当前版本写为 C1 template UI development，不能标记为 Stable。已有仓库请把本轮干净源码复制到本地克隆目录，保留 .git，核对 Changes 后 Commit 和 Push origin；不要重新建仓或强推覆盖历史。

完整流程见 [GitHub 官方说明](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop)。

## 本包已做的清理

白名单导出，排除整个 runtime、历史私人报告、备份、环境变量、依赖环境和缓存。对选中文件及 ZIP 内部再次扫描常见密钥、私钥、私人聊天 ID 和用户目录路径，并输出 SOURCE_MANIFEST.json 与 SHA-256。扫描未匹配不等于可数学证明没有秘密；上传前仍可用 Desktop 查看实际待提交文件。

不要把本机检查报告、凭据截图、个人交易账本作为 Issue 或附件上传。项目及依赖的公开发布许可证尚待后续 D 阶段审计，当前建议保留为私人仓库。

## 验证和使用

Windows 安装 Python 3.11+ 后双击 start.bat，缺失依赖会自动安装，已含编译前端，无需为了运行而安装 Node。设置页重新输入自己的凭据；本包没有携带原账户密钥或历史账户数据。

需要构建前端时，在 frontend 运行 npm ci 和 npm run build。离线测试使用 python -B tests/run_offline.py（需额外安装 pytest）。UI 测试需 playwright 与本机 Chrome。

只读验收不会启动实盘；创建和启动交易所会话仍使用独立授权。当前尚未完成真实资金及托管保护单验收。
