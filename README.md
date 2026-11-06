# Smart Money AI Trader

**面向策略研究的 AI 辅助量化交易与可视化工作台**

*AI-Assisted Quantitative Trading Research Workbench*

![Development](https://img.shields.io/badge/Status-F5%20Research%20Journal-blue) ![Live](https://img.shields.io/badge/Live%20Trading-Not%20Verified-orange) ![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white) ![React](https://img.shields.io/badge/React-TypeScript-087EA4?logo=react&logoColor=white)

> **当前开发检查点：v1.0-F5-research-journal（2026-11-06）。** F1–F3已接入Polymarket公开发现、盘口/基准费率和官方结算证据；F4新增受限v1费用曲线及逐档成本研究；F4.1补齐单位交叉核对与费用精度情景；F5.1新增事件研究记录的保存、去重和重启恢复。最新离线回归**765通过、0失败**，前端构建和浏览器检查通过。完整费用/资产执行验收、模拟账本、AI复盘与Brain仍未完成，当前不是Stable。见[F5.1记录](docs/PHASE_F5_OBSERVATIONS.md)、[F4记录](docs/PHASE_F4_COST_RESEARCH.md)、[F1–F3记录](docs/PHASE_F_READONLY_RESULTS.md)、[操作说明](docs/POLYMARKET_RESEARCH.md)。完整E与C资金门槛仍开放，需求以[主计划](docs/SmartMoney_Stable_Plan.md)为准。

## 项目概览

Smart Money AI Trader 是一个使用 **Python、FastAPI、React 和 TypeScript** 构建的本地量化交易研究平台，围绕行情数据、规则策略、可选 AI 提案、风控约束、订单状态管理和可视化分析，探索**可解释、可追溯、可测试**的智能决策软件架构。

本项目侧重软件工程实践与技术验证，而非收益宣传。仓库中的「24小时翻倍挑战」是策略实验模板及目标名称，**不代表真实收益、盈利保证或经过验证的胜率**。

## 技术亮点

| 方向 | 设计与实现重点 |
|---|---|
| **规则与 AI 分层决策** | 动量、EMA 趋势、RSI 均值回归、成交量异常、ATR 波动等信号；可选 AI 提案经 Schema 检查并受本地风控约束 |
| **风险约束与执行隔离** | 参数约束、仓位与资金校验；区分历史模拟、只读健康检查和需要单独授权的真实执行路径 |
| **订单状态与异常处理** | IOC 请求适配、部分成交/超时/未知订单处理及待核对状态阻断；相关链路已做测试替身验证，非真实成交认证 |
| **可追溯的历史实验** | 历史数据回放、模拟撮合、实验报告、SQLite 事件记录和自动化回归测试 |

## 系统架构

```mermaid
flowchart LR
    UI["React / TypeScript<br/>可视化工作台"] <--> API["FastAPI / WebSocket<br/>本地服务"]
    API --> DATA["行情 / 历史数据"]
    DATA --> STRATEGY["规则策略 / AI 提案"]
    STRATEGY --> RISK["风险约束"]
    RISK --> EXEC["模拟执行 / CCXT 适配"]
    EXEC --> DB["SQLite / 事件记录"]
    API <--> DB
```

此图为核心模块关系示意，不代表所有外部交易接口已完成实盘联调。

## 当前功能与验证状态

下表区分**已有代码/离线证据**与**尚未完成的外部验收**。测试替身、只读公开行情、历史回放和模拟成交都不能替代交易所 demo 或真实账户成交证明。

| 范围 | 当前可确认状态 | 边界与未完成项 |
|---|---|---|
| 前端与本地服务 | React / TypeScript 工作台、FastAPI / WebSocket 本地服务及 Windows 启动器已有代码和构建检查 | 全站最终体验、干净 Windows 安装包和发布迁移仍需 I 阶段验收 |
| 规则与 AI 决策 | 规则扫描与 AI 提案分层；AI 推理工作线程有超时、取消、过期结果检查及规则回退相关代码和离线测试 | AI Brain 长期记忆、模拟结算后自动复盘、跨模型记忆闭环尚未整体验收 |
| 市场研究与模拟 | 三平台公开现货研究适配；异步行情、动态模拟准入、独立持仓保护通道与单主平台隔离已通过本地验收 | Binance地区访问受限；Gate源时间不足导致动态拒绝、私有执行关闭；平台账户验收仍未通过 |
| 订单与保护 | 已有订单状态、部分成交、未知订单阻断、模拟保护生命周期、恢复和只读核对报告的实现及离线测试证据 | 相关 Mock / 模拟验证不代表平台 demo 真实回报；托管保护单的实际平台生命周期仍未通过联调 |
| 历史实验与回放 | 有历史行情模拟、SQLite 事件账本和只读图表回放；D 验收使用24小时历史会话及272笔模拟成交验证回放 | 模拟盈亏不是实盘成绩；回放不驱动真实交易 |
| D 组件与依赖审查 | D 阶段 POC / 条件采用评审完成；495 项隔离离线回归通过、0 失败，前端构建通过 | 这是 D 验收记录，不是495项平台或真实资金验收 |
| 平台与真实资金 | 已有部分 CCXT 协议 POC、公开行情检查和模拟执行基础 | 未完成平台 demo 账户成交闭环；未进行真实资金试单，真实资金验收仍是 Stable 门槛 |

### D 阶段已留存的验收证据

- **Python：** 隔离离线回归 495 通过、0 失败；报告记录执行时间 55.95 秒。
- **前端：** TypeScript / Vite 生产构建通过。
- **浏览器：** 回放、研究、市场发现和监控池回归通过；检查 1366×768、1920×1080 两种尺寸及深浅主题。
- **图表压力：** 100,000 个输入点；24小时回放显示 86,401 个点，首次渲染记录约 1.02–2.12 秒。
- **依赖：** 38 个生产 Python 包、2 个研究 Python 包和185个 npm 锁定节点完成目标环境审查；当次公开公告查询结果为0。
- **隔离边界：** 未访问用户真实账户、未读取真实密钥、未提交交易所订单。上述数字是 D 阶段历史证据；本轮 E 回归另行记录。

详见 [D 阶段最终验收记录](docs/PHASE_D_RESULTS.md)、[组件采用决定](docs/COMPONENT_DECISIONS.md) 和 [依赖审查](docs/OPEN_SOURCE_AUDIT.md)。

### E 阶段非资金验收

- 587项隔离离线回归通过，规则及Mock AI提案均经独立风控进入动态模拟委托/成交，覆盖原固定池之外的交易对。
- 发现、候选扫描、持仓保护使用独立有界通道；市场数据、交易规则、预算、费用、滑点和精度不满足时拒绝模拟成交。
- OKX / Binance / Gate模拟切换独立建立资金、订单、持仓和风控作用域；未知订单、保护单及任意远程环境待核对资产阻止切换。
- 前端设置、主平台能力状态、动态雷达与中文拒绝原因通过1366×768 / 1920×1080、深浅主题检查。
- 公开只读探测与模拟测试分开：OKX可读；Binance返回地区限制；Gate可读但缺少批量行情源时间。三所账户/资金验收均未完成。

详见 [E记录](docs/PHASE_E_RESULTS.md)、[机器可读测试摘要](docs/E_TEST_RESULTS.json)。这是非资金工程检查点，不是完整E外部平台验收或Stable。

### F1–F3事件研究

在策略实验室直接发现开放/已关闭的Polymarket市场，查看ID映射、选择结果查询盘口与基准费率、读取官方结算证据。只读路径不读取凭据，不提交订单。v1指数1费用曲线及成本研究可用；完整实际费用/资产执行验收和模拟闭环尚未开放；官方micro-USDC兑付单位不以现货USDT假设替代。详见[F记录](docs/PHASE_F_READONLY_RESULTS.md)。

## v1.0 阶段路线图

阶段状态以 [项目进度文档](docs/PROGRESS_STATUS.md) 和 [主计划书](docs/SmartMoney_Stable_Plan.md) 为准。当前不使用未经定义权重的单一百分比表示项目完成率。

| 阶段 | 目标 | 当前状态 |
|---|---|---|
| A · 基线审计 | 目录、备份、Git、运行数据和测试基线 | 已有审计记录；发布前仍需复核最新基线 |
| B · 可靠性 | AI 非阻塞、决策过期、订单幂等和异常恢复 | 已有代码与离线测试证据；后续持续回归 |
| C · 实盘核心 | 订单、资金、保护与恢复的端到端验收 | 本地实现持续推进；平台 demo 与真实资金验收未通过 |
| D · 开源组件 | 组件 POC、采用评审、依赖审查和图表回放 | **已完成本阶段组件验收** |
| E · 多交易所 | Gate / OKX / Binance 单主平台切换与隔离 | **非资金实现与本地验收通过；完整 E 的地区/数据源/私有执行与账户验收缺口仍开放** |
| F · Brain 与事件研究 | 模拟学习记忆、Polymarket事件研究 | F1–F3只读研究及F4受限费用/成本研究已实现；完整执行条件、模拟账本与Brain仍待完成；Gate事件禁用 |
| G · 挑战与通知 | 100轮 AI 预测挑战、OpenClaw 飞书/Telegram 异步通知 | 尚未整体验收 |
| H · UI 与迁移 | AI Intelligence Center、模型迁移、设置与工作台闭环 | 部分设置和保护界面已有实现；完整中心与迁移未完成 |
| I · Stable 发布 | 全量安装、迁移、平台和发布验收 | 未通过；不得标记 Stable |

**事件平台说明：** Polymarket已接入公开只读研究；官方API证据不等于链上兑付、完整模拟结算闭环或真实交易验收。Gate 事件接口保留为待验证适配目标并默认禁用；Gate / OKX / Binance 现货规划与事件市场适配相互独立。

**真实资金验证安排：** 用户已决定先完成非资金阶段和发布准备，再单独制定真实验收单。近期不要求用户提供实盘密钥，不开展真实资金测试。模拟、Mock 或只读公开行情不能关闭 C 阶段真实验收门槛。

## 快速开始（本地历史模拟）

**系统要求**：Windows 11，Python 3.11 或以上；本轮验证 Python 3.12。前端已编译，普通使用无需 Node.js。当前为F5研究记录检查点，**不是 Stable，完整平台与实盘验收未通过**。

**无需安装 Git 也能体验**：点击本仓库的 **Code → Download ZIP**，解压后进入包含 start.bat 的项目根目录，**双击 start.bat**。喜欢命令行的开发者可以通过 Git 克隆：

~~~powershell
git clone https://github.com/cuihanzhe955-commits/SmartMoneyAITrader.git
cd SmartMoneyAITrader
.\start.bat
~~~

智能启动器会检查 Python 版本、已有本机服务与端口、项目虚拟环境和 requirements.txt 的依赖；**缺少项目依赖时自动安装到 .venv**，已安装则跳过。首次安装需要网络；没有 Python 时，会提示前往官方页面安装，而不是静默修改系统环境。想只准备依赖、不启动服务，可使用 install.bat。

正常启动后访问 **http://127.0.0.1:8785**；运行期间保持命令行窗口打开。进入总览，选择「配置普通交易」→ **内置历史归档 + 规则引擎 + 本地模拟**，创建会话后再点击「开始运行」。结束时使用 stop.bat 安全退出。也可创建公开现货的动态模拟会话；地区或源时间不满足条件时显示拒绝原因，内置历史模拟仍可使用。

**遇到 Python 未识别、pip 安装失败、端口占用或刷新后打不开？** 请查看 [Windows 快速启动与常见问题](docs/WINDOWS_QUICK_START.md)。交易所接入、CSV 格式、风控细节及运行边界请阅读 [完整使用说明](使用说明.md)。

## 代码结构

| 路径 | 职责 |
|---|---|
| `frontend/` | React + TypeScript 前端与构建产物 |
| `terminal/` | FastAPI、WebSocket、配置与会话调度 |
| `ai/` | AI 提案协调、模型服务适配与校验 |
| `market/`、`strategy/`、`risk/` | 数据获取、信号组合、仓位与风险约束 |
| `execution/` | 模拟执行、CCXT 适配、订单状态与恢复 |
| `challenge/`、`events/` | 策略实验生命周期与事件记录 |
| `data/`、`tests/` | 历史行情、规则快照与自动化测试 |

运行数据库等本机状态不随公开源码提供；项目仍保留兼容旧终端的代码路径。详情见 [使用说明](使用说明.md)。

## 开发与复验

以下命令用于本地复验；运行环境、依赖版本和浏览器条件会影响结果。

~~~powershell
python -m pip install -r requirements.txt
python -X utf8 -B tests/run_offline.py
npm --prefix frontend ci
npm --prefix frontend run build
~~~

当前765项回归在Windows本地通过隔离运行器执行，不是 GitHub Actions CI 或平台资金验收。D阶段495项为历史证据；当前结果见[F测试摘要](docs/F_TEST_RESULTS.json)；E历史结果仍见[E测试摘要](docs/E_TEST_RESULTS.json)。事件浏览器复验见`tests/event_research_browser.py`。

## 项目文档

- [项目进度与验收口径](docs/PROGRESS_STATUS.md)：A–I 阶段状态、测试证据、未完成门槛和真实资金验证顺序
- [主实施计划书](docs/SmartMoney_Stable_Plan.md)：v1.0 冻结范围、平台优先级和后续执行依据
- [文档导航与仓库结构](docs/README.md)：按计划、使用、验收和未来候选分类查看项目资料
- [v1.0 公开开发路线图](docs/V1_ROADMAP.md)：A–I 阶段目标及验收边界
- [D 阶段最终验收](docs/PHASE_D_RESULTS.md)：组件 POC、495项离线回归、图表回放和依赖审查
- [组件采用决定](docs/COMPONENT_DECISIONS.md)：CCXT、TA-Lib、Pydantic AI、Lightweight Charts 等组件评审
- [依赖与开源组件审查](docs/OPEN_SOURCE_AUDIT.md)：目标环境依赖、许可证和公开公告检查
- [D3 市场发现](docs/PHASE_D3_DISCOVERY.md) / [D4 监控池隔离](docs/PHASE_D4_MONITOR_POOL.md)：只读市场研究和必须监控集合边界
- [C2 保护生命周期](docs/PHASE_C2_LIFECYCLE.md) / [C3 模拟联调准备](docs/PHASE_C3_READINESS.md)：本地模拟保护与只读预检证据
- [C1 历史工程验收](docs/PHASE_C1_RESULTS.md)：早期检查点的历史记录，不代表当前阶段
- [实盘验证状态](docs/LIVE_TRADING_VERIFICATION.md)：按平台/产品区分已测试和未验收项
- [Windows 快速启动与常见问题](docs/WINDOWS_QUICK_START.md)：安装、启动和排障
- [完整使用说明](使用说明.md)：安装运行、交易所配置、策略与回放、资金及风控边界
- [中文 Git 双端安全同步工具](tools/git_sync/README.md)：Windows 一键审计、备份和无冲突安全同步

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
