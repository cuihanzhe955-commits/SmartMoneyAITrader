# GitHub 仓库发布与使用说明

> **状态更新（2026-11-03）**：Smart Money AI Trader 已作为**公开可见仓库**发布。本文件保留原有 `GITHUB_UPLOAD.md` 路径，供历史阶段文档引用；此前要求“发布为 Private”的旧上传指引已不适用于当前仓库。

## 仓库定位

本仓库用于展示 **Smart Money AI Trader v1.0 · C1 开发检查点** 的源码、技术说明与阶段性测试证据。项目**尚非 Stable / 生产就绪版本**，也**没有完成真实资金交易闭环及托管保护单的完整验收**。

初次了解项目，请先阅读 [README](../README.md)；实际运行细节见 [使用说明](../使用说明.md)；已验证和未验证内容分别记录在 [C1 工程验收记录](PHASE_C1_RESULTS.md) 及 [实盘验证状态](LIVE_TRADING_VERIFICATION.md)。

## 获取与阅读源码

```powershell
git clone https://github.com/cuihanzhe955-commits/SmartMoneyAITrader.git
cd SmartMoneyAITrader
.\start.bat
```

建议在 Windows 11、Python 3.11+ 环境先运行**内置历史归档 + 本地模拟**，不需要交易账户。开发检查点并非可直接投入真实资金的发行版。

## 阶段记录与版本关系

- `SOURCE_MANIFEST.json` 是 C1 源码导出时生成的文件清单与哈希快照；仓库公开后的 README 等文档提交可能不再匹配当时清单的哈希。这不表示新的文档提交重新经过原 C1 测试与打包验收。
- [C1 工程验收记录](PHASE_C1_RESULTS.md)保留了当轮测试完成时的历史描述；其中“当时未上传/未公开”的文字不是仓库当前公开状态。
- 目前未发布开源许可证；公开可见仅供阅读与评估，不等于授予第三方自由复制、修改、分发或商业使用的许可。

## 反馈与交流

欢迎通过仓库 [Issues](https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/issues) 交流可以公开讨论的代码问题、测试复现及文档改进建议。项目开发与验证状态以对应提交和阶段性记录为准。
