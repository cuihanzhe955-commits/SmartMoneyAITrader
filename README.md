# Smart Money AI Trader

**面向数字资产现货与永续合约的 AI 辅助量化交易终端**

![Status](https://img.shields.io/badge/Status-Development%20Checkpoint-orange) ![Live Trading](https://img.shields.io/badge/Live%20Trading-Not%20Accepted-red) ![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white) ![React](https://img.shields.io/badge/React-TypeScript-087EA4?logo=react&logoColor=white)

> **当前版本：开发检查点，尚未达到 Stable。** 本页描述产品目标与当前可核验的代码状态，不把规划中的能力写成已完成能力。

## 项目目标

Smart Money AI Trader 是一个面向 Windows 本地运行的数字资产量化交易终端。产品重点是 **现货与永续合约**，并且最终必须同时具备模拟交易和真实交易能力。

模拟交易用于优先开发、验证策略、测试风险控制和观察实时表现；它不是产品终点。真实交易属于正式产品范围，但必须在交易所接口、订单生命周期、资金核对、保护措施和安全验收完成后才能启用。

项目不承诺盈利。策略是否有效，必须以扣除手续费、滑点和永续资金费后的结果，以及样本外和前向验证为依据。

## 产品核心能力

| 能力 | 产品要求 |
|---|---|
| 市场数据 | 实时与历史行情、盘口、成交量、资金费率、交易规则和数据质量检查 |
| 策略 | 趋势、动量、突破、均值回归、波动过滤及可复核的进出场条件 |
| AI 决策 | 分析市场、评估策略、提出买入/卖出/观望/跳过建议，并说明依据和风险 |
| 风险管理 | 仓位、单笔风险、账户风险、止损止盈、回撤限制、保证金和异常停机 |
| 交易执行 | 现货与永续；模拟与真实；订单、成交、撤单、部分成交、恢复和对账 |
| 回测与验证 | 费用后收益、滑点、资金费率、最大回撤、样本外和前向模拟 |
| 账户与绩效 | 余额、资产、持仓、订单、已实现/未实现盈亏和交易复盘 |
| 系统管理 | 通知、异常告警、运行状态、日志、配置、备份与恢复 |

这些能力是产品验收范围，不要求每一项都新建独立模块。优先复用仓库已有实现和经过评估的开源项目。

## 当前代码状态（GitHub main：`4dbda5fc797f87b45c258456ff16dcfad3ac126c`）

以下状态来自仓库源码和现有验收文档；本次文档整理没有重新运行代码测试。

| 范围 | 当前可确认情况 | 尚未证明或未完成 |
|---|---|---|
| 本地工作台 | Python、FastAPI、React、TypeScript 和 Windows 启动入口已有 | 干净环境安装、全站用户流程和正式发布仍需验收 |
| 行情与策略 | 有公开现货行情、历史数据、规则策略及动态模拟准入代码 | 多产品、多个平台的完整交易能力尚未验收 |
| AI | 已有 Provider、Coordinator、异步 Worker、结构化提案和 Brain 相关代码 | 默认模型名称为空；需配置有效模型和密钥；真实 Provider 的稳定性、决策价值和前向表现未证明 |
| 现货模拟 | 有历史回放、公开行情模拟、订单状态与风险检查 | 不能把模拟成交当作交易所真实成交 |
| 现货真实交易 | 源码包含受限的现货实盘执行和只读验收路径 | 平台 demo/真实账户完整成交、保护单生命周期和资金对账尚未验收 |
| 永续合约 | 有部分 swap 连接与历史兼容代码 | 当前新实盘会话明确拒绝非现货产品；永续完整模拟/实盘闭环尚未验收 |
| 通知 | 已有 Outbox、发送 Worker、Gateway 协议适配代码 | 生产 WebSocket 连接、认证、Runtime 生命周期、UI 配置及真实通道发送闭环尚未完成 |
| Brain 与实验 | 已有记忆、观察、复盘和研究相关代码 | 数据库忙异常、真实 AI 质量及长期有效性仍需验证 |
| 挑战功能 | G1 自动预测挑战及其历史测试记录保留 | 用户已批准移除“24小时翻倍挑战”；代码依赖核查和安全清理尚待执行 |

### 当前集成检查点与未关闭问题

main 已集成 G1、Windows 实例隔离修复和 G2 通知相关模块。集成记录报告 **938 项离线测试通过、0 失败、0 跳过**，前端 TypeScript/Vite 构建通过。该记录是已有测试证据，不代表本次重新执行。

集成报告仍列出以下问题：
1. 保护单浏览器验收等待第二条“核对完成 · 已释放”超时；
2. 86,401 点图表压力测试出现 Node 内存分配失败；
3. G1 工作线程遇到 Brain 数据库忙异常后退出；
4. 浏览器验收日志出现 ConnectionResetError，即使进程退出码为 0 也不能视为通过。

完整说明见 [2026-11-10 集成记录](docs/MAIN_INTEGRATION_20261110.md) 和 [当前进度](docs/PROGRESS_STATUS.md)。

## 交易路线与开发顺序

1. **现货基础闭环：** 行情、策略、AI/规则建议、风控、模拟订单、真实订单路径、持仓、止损止盈、成交核对和盈亏。
2. **永续合约闭环：** 多空、保证金、杠杆、强平风险、资金费率、模拟与真实订单、止损止盈和恢复。
3. **AI 可用性：** 先让一个 AI 决策流程稳定、及时、可解释；再评估是否需要多个角色。
4. **盈利验证：** 统一成本口径，完成回测、样本外、Walk-forward 和前向模拟，对比纯规则与 AI 增量价值。
5. **整合发布：** 简化界面、保留已有功能、完成通知、Windows 安装/恢复和安全验收。

Polymarket 事件市场研究暂缓至现货与永续主线稳定后再启动。

## 开源优先与复用原则

实现每项能力前，先检查仓库现有代码，再评估 GitHub 上成熟的开源项目。合适时优先采用成熟依赖、适配器、独立组件或经过隔离验证的代码，不要求所有功能都从头实现。

采用前必须核查：
- 许可证和分发义务；
- 上游维护状态、版本和安全公告；
- Windows、Python、Node 与现有架构兼容性；
- 与现有模块的功能重叠、数据格式和运行依赖；
- 性能、测试覆盖、供应链风险和回滚方案。

优先复用当前已集成的 CCXT 与 Lightweight Charts。Hummingbot、Jesse、Freqtrade 等仅作为待评估候选，不能因为开源就整套搬入。GPL/AGPL 等许可证在复制或链接代码前必须完成合规评估。详细记录见 [开源组件评估](docs/OPEN_SOURCE_AUDIT.md)。

## 快速开始

**系统要求：** Windows 11、Python 3.11 或以上。前端已包含构建产物，普通运行无需 Node.js。

下载仓库 ZIP 并解压，进入包含 `start.bat` 的项目根目录，双击启动。也可以使用 PowerShell：

```powershell
git clone https://github.com/cuihanzhe955-commits/SmartMoneyAITrader.git
cd SmartMoneyAITrader
.\start.bat
```

默认本地地址：**http://127.0.0.1:8785**。首次安装依赖需要网络；运行期间保持启动窗口打开。使用 `stop.bat` 安全退出。

当前版本是开发检查点。开始真实交易前，必须确认交易所、产品、账户权限、风险设置、保护方案和验收状态。当前源码不支持新建永续实盘会话，也没有通过完整真实账户验收。

更多操作见 [Windows 快速启动](docs/WINDOWS_QUICK_START.md) 和 [完整使用说明](使用说明.md)。

## 文档入口

- [项目当前状态与验收证据](docs/PROGRESS_STATUS.md)
- [产品范围与实施计划](docs/SmartMoney_Stable_Plan.md)
- [v1.0 产品路线图](docs/V1_ROADMAP.md)
- [产品决策池](docs/PRODUCT_DECISION_POOL.md)
- [开源组件评估与采用记录](docs/OPEN_SOURCE_AUDIT.md)
- [组件采用历史决定](docs/COMPONENT_DECISIONS.md)
- [现货实盘验证状态](docs/LIVE_TRADING_VERIFICATION.md)
- [G1/G2 集成记录](docs/MAIN_INTEGRATION_20261110.md)
- [通知系统检查点](docs/G2_OUTBOX_CHECKPOINT.md)
- [Brain 记忆设计](docs/BRAIN_MEMORY_DESIGN.md)
- [文档导航](docs/README.md)
- [用户使用说明](使用说明.md)
- [开发与交付规范](docs/AI_DEVELOPMENT_COLLABORATION.md)

## 代码结构

| 路径 | 职责 |
|---|---|
| `frontend/` | React + TypeScript 工作台 |
| `terminal/` | FastAPI、本地 API、WebSocket、配置与会话调度 |
| `market/` | 行情、市场规则和数据质量 |
| `strategy/` | 技术指标、规则和策略组合 |
| `ai/` | 模型服务、AI 提案和异步推理 |
| `risk/` | 仓位与风险约束 |
| `execution/` | 模拟/交易所执行、订单状态和恢复 |
| `events/` | 事件记录、Brain 与通知相关数据 |
| `tests/` | 自动化测试与验收工具 |

## 本地复验

```powershell
python -m pip install -r requirements.txt
python -X utf8 -B tests/run_offline.py
npm --prefix frontend ci
npm --prefix frontend run build
```

具体测试范围、环境、结果和未完成项必须以对应报告为准。Mock、历史数据、公开只读行情和模拟成交不能替代交易所 demo 或真实账户验收。

## ☕ 支持开发者

如果 Smart Money AI Trader 对你有所帮助，欢迎通过开发者个人提供的付费服务，支持项目后续维护与开发。支持完全自愿，不影响任何人阅读本仓库。

> [!NOTE]
> **ChatGPT 订阅代充协助服务 · ¥135 CNY**
>
> 该服务由开发者个人提供，**不是 OpenAI 官方服务或授权代理**，价格不代表官方订阅定价。购买前请确认具体套餐、期限、交付方式、退款规则和适用地区；请勿向他人提供账户密码或验证码。

**购买咨询 / 联系开发者**

以下二维码由开发者提供的联系方式重新生成，分别对应微信、QQ、Telegram 的添加入口。**扫码或点击二维码均可尝试联系**，不需要公开留言或提供账户密码。

| 微信 WeChat | QQ | Telegram |
| :---: | :---: | :---: |
| <a href="https://u.wechat.com/EHh0vOjHfvhUI2EZiIg_Ihs?s=4"><img src="assets/support/wechat.svg" alt="微信添加开发者二维码" width="180"></a> | <a href="https://qm.qq.com/q/xo6MxVkBMW"><img src="assets/support/qq.svg" alt="QQ 添加开发者二维码" width="180"></a> | <a href="https://t.me/LingYuChrisOedipus"><img src="assets/support/telegram.svg" alt="Telegram 添加开发者二维码" width="180"></a> |
| 微信号：`PuRP1E22` | QQ：`1632832719` | [@LingYuChrisOedipus](https://t.me/LingYuChrisOedipus) |

> 温馨提示：二维码跳转可能需要相应 App。请先通过上述渠道确认具体服务条款及金额，再决定是否购买。

**请先沟通确认，不要直接付款。** 本仓库不收款，不设置自动交易或自动充值功能；上述服务与 Smart Money AI Trader 的软件功能、运行安全及项目许可证相互独立。

## 风险与许可

**当前为研究与开发检查点，不建议直接使用真实资金运行。** 本地止损依赖服务、网络和行情持续可用，异常中断时交易所持仓不一定自动平仓。访问交易所时须遵守所在地法律与平台限制；本项目不提供投资建议或收益保证。

仓库目前**公开可见，但尚未发布开源许可证**，第三方依赖及公开发布许可仍待审计。公开浏览代码不表示授权复制、修改、分发或商业使用。

---

*文档补录日期：2026-11-06。F1–F3源码分别在370b6b2、0491e4c上传；本次补齐遗漏记录，不把文档同步计为功能实现。完整F、E外部门槛和真实资金验收仍未通过。*

