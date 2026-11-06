# Windows 快速启动与常见问题

> 适用于 **Smart Money AI Trader 源码体验版（v1.0 F4成本研究检查点）**。本版本主要面向 Windows 11，本地历史模拟可以不配置交易 API。**尚未完成真实资金交易的完整验收，不建议使用真实资金体验。**

## 1. 下载项目

**普通用户（不用安装 Git）**：在 [GitHub 项目首页](https://github.com/cuihanzhe955-commits/SmartMoneyAITrader) 点击 **Code → Download ZIP**，解压后进入包含 **start.bat** 和 **README.md** 的文件夹。

**开发者（已有 Git）**：在 PowerShell 执行：

~~~powershell
git clone https://github.com/cuihanzhe955-commits/SmartMoneyAITrader.git
cd SmartMoneyAITrader
~~~

如果 Git 命令无法识别，意味着 Git 未安装或未配置 PATH；只想体验软件的用户**无需安装 Git**，直接使用 ZIP 即可。

## 2. 运行前准备

- **系统**：Windows 11；本轮已验证Python **3.12（64位）**，其他 3.11 以上版本需满足项目锁定依赖的兼容性。
- **Python**：从 [python.org 官方下载页](https://www.python.org/downloads/windows/) 安装。安装时启用 **Add python.exe to PATH**，或使用 Windows Python Launcher（py）。安装完重新打开命令行。
- **Node.js**：普通运行不需要；只有重新开发/构建 React 前端时才需要。
- **依赖**：不用逐个安装 FastAPI、CCXT 等；启动器自动检查 requirements.txt 并在项目的 .venv 内安装缺失的依赖。首次安装需要网络。

## 3. 一键启动

双击项目根目录的 **start.bat**。启动器会依次：

1. 优先检测项目内已有的 .venv；否则查找 py -3.11 等可用解释器和 PATH 中的 Python。
2. 检查 127.0.0.1:8785：如果同类工作台已在运行，打开现有页面；如果是其他程序占用，停止启动并提示检查，不强制关闭别人的进程。
3. 为当前项目创建独立的 .venv，检查固定版本依赖；缺少时自动安装，已齐全则跳过。
4. 启动原有后端并在本机浏览器打开 **http://127.0.0.1:8785**。

运行中请保持黑色命令行窗口打开。首次体验在「配置普通交易」中选择 **内置历史归档 + 规则引擎 + 本地模拟**，并手动创建、开始会话。**启动器不会自动创建交易会话或授予实盘权限。**

只想提前准备依赖、不启动服务时，可以双击 **install.bat**，它现在使用同一套环境检查。

## 4. 常见报错

| 显示现象 | 建议操作 |
|---|---|
| Git 不是命令 | 改用 **Download ZIP**；如需 Git，请自行安装 [Git for Windows](https://git-scm.com/downloads/win) |
| 未检测到可用的 Python 3.11 | 安装 Python 3.11，重新打开 PowerShell；运行 py -3.11 --version 或 python --version 验证 |
| 已安装 Python，却仍提示找不到 | 检查 PATH 和 Windows 的「应用执行别名」是否拦截 python.exe；优先确认 py -3.11 --version 正常 |
| .venv 文件夹不完整 | 不要直接删除有用文件；先备份或重命名 .venv，再重新启动以创建新环境 |
| 依赖安装失败 | 查看窗口中 pip 的具体错误；检查网络、磁盘空间、Python 版本，解决后再次双击 start.bat |
| 端口 8785 已被其他服务占用 | 先确认占用该端口的程序；可以用 netstat -ano 查看，不要直接终止未知进程 |
| 打开页面后刷新无法连接 | 检查启动时的黑色窗口是否已关闭；若服务已停止，重新运行 start.bat |
| 页面打开但显示异常或数据无法载入 | 先查看黑色窗口的报错、访问 http://127.0.0.1:8785/api/health，再反馈错误信息 |

## 5. 安全退出

使用项目根目录的 **stop.bat** 请求正常退出。若存在未核对的真实订单或持仓，程序可能拒绝直接退出或要求人工核对。**关闭浏览器标签不等于停止后台服务；结束进程也不等于卖出持仓。** 不要为消除提示而强制结束可能关联真实交易的进程。

## 6. 当前交付边界

这是**源码版智能启动器（第一级）**，不是免 Python 的便携 EXE 或正式安装程序。启动流程自动化不代表真实交易功能已通过验证。当前事件研究操作见[Polymarket研究说明](POLYMARKET_RESEARCH.md)，最新检查点见[F1–F3记录](PHASE_F_READONLY_RESULTS.md)，资金边界见[实盘状态](LIVE_TRADING_VERIFICATION.md)。
